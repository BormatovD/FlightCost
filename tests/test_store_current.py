"""`Store.current` одним запросом — то же, что `get()` по каждому ключу.

Сборка сети зовёт `current` тысячи раз (тарифы, наблюдения), и раньше он
делал запрос на каждый ключ. Новый — один запрос и кэш до записи (решение
206). Тест сверяет его со старым определением на версиях с перекрытием,
закрытыми интервалами и префиксами, и проверяет, что запись сбрасывает кэш.
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from flightcostapp.store import Fact, Store  # noqa: E402


def F(key, value, vf, vt=None):
    return Fact(domain="airport_charge", key=key, valid_from=vf, valid_to=vt, value=value,
                source_id="t", extracted_by="t")


class Current(unittest.TestCase):

    def setUp(self):
        self.s = Store(pathlib.Path(tempfile.mkdtemp()) / "c.db")
        self.s.commit_facts([
            F("EDDF/land", 1.0, "2026-01-01", "2026-06-01"),
            F("EDDF/land", 2.0, "2026-06-01"),
            F("EDDF/pax", 10.0, "2026-01-01"),
            F("EDDF0/x", 5.0, "2026-01-01"),          # за границей префикса «EDDF/»
            F("LI/muni", 6.5, "2026-01-01"),
            F("LEBL/old", 3.0, "2025-01-01", "2025-12-31"),
        ])

    def old(self, as_of, prefixes=None):
        keys = [r["key"] for r in self.s.db.execute(
            "SELECT DISTINCT key FROM facts WHERE domain='airport_charge'")]
        out = {}
        for k in keys:
            if prefixes and not any(k.startswith(p) for p in prefixes):
                continue
            row = self.s.get("airport_charge", k, as_of)
            if row is not None:
                out[k] = row["value"]
        return out

    def test_same_as_get_per_key(self):
        for d in ("2025-06-01", "2026-03-01", "2026-07-01"):
            for pre in (None, ["EDDF/"], ["EDDF/", "LI/"]):
                got = {k: r["value"] for k, r in self.s.current("airport_charge", d, pre).items()}
                self.assertEqual(got, self.old(d, pre), (d, pre))

    def test_write_resets_cache_and_copy_is_returned(self):
        a = self.s.current("airport_charge", "2026-07-01")
        a["junk"] = None                                   # вызывающий дополняет копию
        self.assertNotIn("junk", self.s.current("airport_charge", "2026-07-01"))
        self.s.commit_facts([F("EDDF/new", 7.0, "2026-01-01")])
        self.assertIn("EDDF/new", self.s.current("airport_charge", "2026-07-01"))


if __name__ == "__main__":
    unittest.main()


class OnePendingProposal(unittest.TestCase):
    """Источник в статусе «ждёт приёмки» проверяется каждым прогоном; очередь
    не должна копить одинаковые предложения (jet_fuel_price, 3.11.2026)."""

    def test_same_facts_reuse_and_new_facts_supersede(self):
        import tempfile
        from pathlib import Path
        from flightcostapp.store import Store
        st = Store(Path(tempfile.mkdtemp()) / "x.db")
        a = {"facts": [{"key": "k", "value": 1}], "findings": [{"m": "x"}]}
        p1 = st.add_proposal("jet_fuel_price", a)
        self.assertEqual(st.add_proposal("jet_fuel_price", dict(a)), p1)
        p2 = st.add_proposal("jet_fuel_price", {"facts": [{"key": "k", "value": 2}]})
        self.assertEqual([r["id"] for r in st.pending_proposals()], [p2])
        self.assertEqual(st.db.execute("SELECT status FROM proposals WHERE id = ?", (p1,)).fetchone()[0],
                         "superseded")


class ProposalScope(unittest.TestCase):
    """Части одной большой отправки (разные префиксы) не заменяют друг друга;
    новая поставка той же области — заменяет."""

    def test_parts_coexist_same_scope_replaces(self):
        import tempfile
        from pathlib import Path as _P
        st = Store(_P(tempfile.mkdtemp()) / "x.db")

        def prop(pres, v):
            return {"facts": [{"key": f"{p}/m", "value": v} for p in pres],
                    "retire": {"domain": "fare_paid", "prefixes": pres}}
        a = st.add_proposal("db1c_market", prop(["AAA-BBB"], 1))
        b = st.add_proposal("db1c_market", prop(["CCC-DDD"], 1))
        pend = {r["id"] for r in st.pending_proposals()}
        self.assertEqual(pend, {a, b}, "части с разными префиксами ждут обе")
        c = st.add_proposal("db1c_market", prop(["AAA-BBB"], 2))
        pend = {r["id"] for r in st.pending_proposals()}
        self.assertEqual(pend, {b, c}, "новая поставка той же пары заменяет прежнюю")
