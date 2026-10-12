"""Слой гостя (решение 148) — без сети, на настоящем `Store` во временном файле.

Что проверяется: своё значение главнее общего по тому же ключу и не
протекает в справочник; ключ в базе не хранится; новая ссылка закрывает
старую; экспорт → импорт в другое место даёт то же; пределы и чистка
названы числами и срабатывают; запись в справочник из слоя закрыта.
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from flightcostapp import guest as G                      # noqa: E402
from flightcostapp.store import Fact, Store               # noqa: E402

TODAY = date.today().isoformat()


def fact(domain, key, value, **kw):
    kw.setdefault("source_id", "aircraft_user")
    kw.setdefault("extracted_by", "test")
    return Fact(domain=domain, key=key, valid_from=kw.pop("valid_from", "2026-01-01"),
                value=value, **kw)


class Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = pathlib.Path(self.tmp.name)
        self.base = Store(d / "flightcost.db")
        self.base.commit_facts([
            fact("aircraft", "A320/mtow_t", 78.0, source_id="aircraft_openap"),
            fact("aircraft", "A320/seats", 170, source_id="aircraft_openap"),
            fact("airport", "FRA", None, value_text="50.0,8.5|EDDF|DE|Frankfurt",
                 source_id="ourairports"),
        ])
        self.gdb = G.GuestDB(d / "user.db")
        self.key = self.gdb.create("203.0.113.1")
        self.ws = self.gdb.touch(self.key)

    def tearDown(self):
        self.base.db.close(); self.gdb.db.close(); self.tmp.cleanup()


class Keys(Base):

    def test_key_shape_and_hash_only_in_db(self):
        self.assertTrue(G.valid_key(self.key))
        self.assertEqual(len(self.key), 32)
        raw = self.gdb.db.execute("SELECT ws FROM workspaces").fetchone()[0]
        self.assertNotEqual(raw, self.key)
        self.assertEqual(raw, G.ws_id(self.key))
        self.assertIsNone(self.gdb.touch("deadbeef" * 4), "чужой ключ той же формы не открывает")
        self.assertIsNone(self.gdb.touch("не ключ"))

    def test_rotate_closes_old_link(self):
        self.gdb.put_doc(self.ws, "network", "ALA", {"a": 1})
        new = self.gdb.rotate(self.ws)
        self.assertIsNone(self.gdb.touch(self.key))
        w2 = self.gdb.touch(new)
        self.assertIsNotNone(w2)
        self.assertEqual(self.gdb.get_doc(w2, "network", "ALA"), {"a": 1})

    def test_creation_limit_per_network(self):
        for _ in range(G.MAX_NEW_PER_DAY - 1):
            self.gdb.create("203.0.113.1")
        with self.assertRaises(PermissionError):
            self.gdb.create("203.0.113.77")          # та же сеть /24 — предел общий
        self.gdb.create("203.0.114.2")               # другая сеть — можно

    def test_full_address_never_on_disk(self):
        """Политика: полный IP-адрес на диск не пишется. Здесь — маска
        журнала Caddy и короткая жизнь суточных счётчиков."""
        self.assertEqual(G.mask_ip("203.0.113.77"), "203.0.113.0")
        self.assertEqual(G.mask_ip("2001:db8:85a3:8d3:1319:8a2e:370:7348"), "2001:db8:85a3::")
        self.assertEqual(G.mask_ip("мусор"), "")
        self.gdb.create("2001:db8:85a3:8d3:1319:8a2e:370:7348")
        blob = " ".join(str(tuple(r)) for t in ("workspaces", "ws_created")
                        for r in self.gdb.db.execute(f"SELECT * FROM {t}"))
        self.assertNotIn("203.0.113.1", blob)
        self.assertNotIn("7348", blob)
        self.assertIn("203.0.113.0", blob)
        # счётчики суток: позавчерашний уходит, вчерашний и сегодняшний остаются
        y = (date.today() - timedelta(days=1)).isoformat()
        yy = (date.today() - timedelta(days=2)).isoformat()
        self.gdb.db.execute("INSERT INTO ws_created VALUES (?,?,1)", (y, "10.0.0.0"))
        self.gdb.db.execute("INSERT INTO ws_created VALUES (?,?,1)", (yy, "10.0.1.0"))
        self.gdb.db.commit()
        self.gdb.prune()
        days = {r[0] for r in self.gdb.db.execute("SELECT day FROM ws_created")}
        self.assertEqual(days, {date.today().isoformat(), y})

    def test_prune_removes_idle_only(self):
        other = self.gdb.touch(self.gdb.create("1.1.1.1"))
        old = (date.today() - timedelta(days=G.IDLE_DAYS + 1)).isoformat() + "T00:00:00Z"
        self.gdb.db.execute("UPDATE workspaces SET last_seen=? WHERE ws=?", (old, other))
        self.gdb.put_doc(other, "scenario", "x", {})
        self.gdb.db.commit()
        self.assertEqual(self.gdb.prune(), 1)
        self.assertFalse(self.gdb.info(other)["exists"])
        self.assertTrue(self.gdb.info(self.ws)["exists"])
        self.assertEqual(self.gdb.db.execute("SELECT COUNT(*) FROM gdocs").fetchone()[0], 0)


class Overlay(Base):

    def test_own_value_wins_and_base_untouched(self):
        self.gdb.replace_facts(self.ws, "aircraft", "USER:A21N-MY",
                               [fact("aircraft", "USER:A21N-MY/mtow_t", 97.0),
                                fact("aircraft", "USER:A21N-MY/seats", 220)])
        gs = G.GuestStore(self.base, self.gdb, self.ws)
        self.assertEqual(gs.value("aircraft", "USER:A21N-MY/mtow_t"), 97.0)
        self.assertEqual(gs.value("aircraft", "A320/mtow_t"), 78.0, "общее читается сквозь")
        self.assertIsNone(self.base.get("aircraft", "USER:A21N-MY/mtow_t"),
                          "в справочник ничего не попало")
        cur = gs.current("aircraft")
        self.assertIn("USER:A21N-MY/mtow_t", cur)
        self.assertIn("A320/seats", cur)
        self.assertEqual(gs.value_with_age("aircraft", "USER:A21N-MY/seats"), (220, 0))
        self.assertEqual(gs.own_types(), ["USER:A21N-MY"])

    def test_other_workspace_sees_nothing(self):
        self.gdb.replace_facts(self.ws, "aircraft", "USER:X",
                               [fact("aircraft", "USER:X/mtow_t", 1.0)])
        w2 = self.gdb.touch(self.gdb.create("9.9.9.9"))
        gs2 = G.GuestStore(self.base, self.gdb, w2)
        self.assertIsNone(gs2.get("aircraft", "USER:X/mtow_t"))

    def test_replace_closes_previous_and_history_stays(self):
        self.gdb.replace_facts(self.ws, "aircraft", "USER:X",
                               [fact("aircraft", "USER:X/mtow_t", 1.0, valid_from="2026-01-01")])
        st = self.gdb.replace_facts(self.ws, "aircraft", "USER:X",
                                    [fact("aircraft", "USER:X/mtow_t", 2.0, valid_from=TODAY)])
        self.assertEqual(st["closed"], 1)
        gs = G.GuestStore(self.base, self.gdb, self.ws)
        self.assertEqual(gs.value("aircraft", "USER:X/mtow_t"), 2.0)
        self.assertEqual(gs.value("aircraft", "USER:X/mtow_t", as_of="2026-02-01"), 1.0,
                         "прошлое воспроизводится — append-only")
        self.assertEqual(len(self.gdb.facts(self.ws, "aircraft", current_only=False)), 2)

    def test_writes_to_reference_are_closed(self):
        gs = G.GuestStore(self.base, self.gdb, self.ws)
        with self.assertRaises(AttributeError):
            gs.commit_facts([])
        with self.assertRaises(ValueError):
            self.gdb.replace_facts(self.ws, "enroute_rate", "ED",
                                   [fact("enroute_rate", "ED", 1.0)])
        self.assertIs(gs.db, self.base.db, "прямой SELECT — по справочнику")


class Docs(Base):

    def test_docs_roundtrip_and_limits(self):
        self.gdb.put_doc(self.ws, "settings", "default",
                         {"overrides": {"fleet_economics.A321.lease_eur_month": 380000}})
        self.assertEqual(self.gdb.get_doc(self.ws, "settings", "default")["overrides"]
                         ["fleet_economics.A321.lease_eur_month"], 380000)
        with self.assertRaises(ValueError):
            self.gdb.put_doc(self.ws, "diary", "x", {})
        with self.assertRaises(ValueError):
            self.gdb.put_doc(self.ws, "network", "big", {"blob": "x" * (G.MAX_BYTES + 1)})
        self.assertEqual([d["name"] for d in self.gdb.list_docs(self.ws, "settings")], ["default"])
        self.assertTrue(self.gdb.delete_doc(self.ws, "settings", "default"))
        self.assertFalse(self.gdb.delete_doc(self.ws, "settings", "default"))

    def test_export_import_into_another_workspace(self):
        self.gdb.replace_facts(self.ws, "aircraft", "USER:X",
                               [fact("aircraft", "USER:X/mtow_t", 97.0)])
        self.gdb.put_doc(self.ws, "network", "ALA", {"airports": ["ALA", "FRA"]})
        dump = self.gdb.export(self.ws)
        self.assertEqual(dump["schema"], "fca.workspace/1")
        w2 = self.gdb.touch(self.gdb.create("5.5.5.5"))
        st = self.gdb.import_(w2, dump)
        self.assertEqual((st["docs"], st["facts"]), (1, 1))
        gs2 = G.GuestStore(self.base, self.gdb, w2)
        self.assertEqual(gs2.value("aircraft", "USER:X/mtow_t"), 97.0)
        self.assertEqual(self.gdb.get_doc(w2, "network", "ALA")["airports"], ["ALA", "FRA"])
        with self.assertRaises(ValueError):
            self.gdb.import_(w2, {"schema": "other"})

    def test_info_counts(self):
        self.gdb.put_doc(self.ws, "network", "a", {})
        self.gdb.put_doc(self.ws, "scenario", "b", {})
        i = self.gdb.info(self.ws)
        self.assertEqual(i["docs"], {"network": 1, "scenario": 1})
        self.assertEqual(i["limits"]["idle_days"], G.IDLE_DAYS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
