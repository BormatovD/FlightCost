"""Главная база на сервере: что едет, что остаётся дома, что возвращается.

Без ssh: проверяются функции по обе стороны провода — посев, предложение
с компьютера, приём на сервере, выгрузка домой.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from flightcostapp import master as M
from flightcostapp.store import Fact, Store


def home_db(path: Path) -> Path:
    st = Store(path)
    st.commit_facts([
        Fact(domain="aircraft", key="MYTYPE/mtow_t", valid_from="2026-01-01", value=70.0,
             source_id="aircraft_user", extracted_by="test"),
        Fact(domain="traffic", key="EDDF-LEBL/pax", valid_from="2024-01-01", value=1e6,
             source_id="eurostat_par", extracted_by="test"),
        Fact(domain="traffic", key="EDDF-LEPA/pax", valid_from="2024-01-01", value=5e5,
             source_id="eurostat_par", extracted_by="test"),
    ])
    st.db.execute("INSERT INTO observations (kind, key, value, unit, observed_at, source_id) "
                  "VALUES ('frequency', 'EDDF-LEBL/DLH', 1, 'flight', '2026-11-01T10:00', 'adsb_flights')")
    st.db.commit()
    st.db.close()
    return path


class Master(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = home_db(self.tmp / "home.db")
        self.master = self.tmp / "srv" / "master"
        self.drop = self.tmp / "srv" / "drop"
        (self.drop / "proposals").mkdir(parents=True)
        self.master.mkdir(parents=True)
        self.spool = self.tmp / "spool"

    def count(self, db, sql):
        con = sqlite3.connect(str(db))
        try:
            return con.execute(sql).fetchone()[0]
        finally:
            con.close()

    def test_seed_leaves_own_types_and_raw_tables_home(self):
        seed = self.drop / "seed.db"
        M.make_seed(self.home, seed)
        self.assertEqual(self.count(seed, "SELECT COUNT(*) FROM facts WHERE source_id='aircraft_user'"), 0)
        self.assertEqual(self.count(seed, "SELECT COUNT(*) FROM observations"), 0)
        self.assertEqual(self.count(seed, "SELECT COUNT(*) FROM facts WHERE source_id='eurostat_par'"), 2)

    def test_seed_import_then_send_lands_in_queue(self):
        M.make_seed(self.home, self.drop / "seed.db")
        M.cmd_import(None, master=self.master, drop=self.drop, spool=self.spool)
        db = self.master / "flightcost.db"
        self.assertTrue(db.exists())
        self.assertTrue((self.master / "out" / "flightcost.db.new").exists(), "витрине нет снимка")
        self.assertTrue((self.master / "export" / "flightcost.db").exists(), "домой нечего забрать")
        # Второй посев не затирает главную базу.
        M.make_seed(self.home, self.drop / "seed.db")
        M.cmd_import(None, master=self.master, drop=self.drop, spool=self.spool)
        self.assertTrue(any(self.drop.glob("seed.rejected-*")))
        # Предложение с компьютера — в очередь, не в факты.
        for i, p in enumerate(M.proposals_from(self.home, ["eurostat_par"])):
            (self.drop / "proposals" / f"{i}.json").write_text(json.dumps(p, default=str))
        M.cmd_import(None, master=self.master, drop=self.drop, spool=self.spool)
        pend = Store(db).pending_proposals()
        self.assertEqual([r["source_id"] for r in pend], ["eurostat_par"])
        self.assertEqual(list((self.drop / "proposals").glob("*.json")), [])
        # Приёмка (кнопка в боте) — тем же путём, что `fca review --accept`.
        facts = Store(db).resolve_proposal(pend[0]["id"], True, "test")
        self.assertEqual(len(facts), 2)

    def test_own_types_are_never_sent(self):
        p = M.proposals_from(self.home, ["aircraft_user"])
        (self.drop / "proposals" / "x.json").write_text(json.dumps(p[0], default=str))
        M.make_seed(self.home, self.drop / "seed.db")
        M.cmd_import(None, master=self.master, drop=self.drop, spool=self.spool)
        self.assertEqual(Store(self.master / "flightcost.db").pending_proposals(), [])

    def test_pull_keeps_home_observations(self):
        M.make_seed(self.home, self.drop / "seed.db")
        M.cmd_import(None, master=self.master, drop=self.drop, spool=self.spool)
        pulled = self.tmp / "pulled.db"
        pulled.write_bytes((self.master / "export" / "flightcost.db").read_bytes())
        kept = M.merge_home_tables(pulled, self.home)
        self.assertEqual(kept.get("observations"), 1)
        self.assertEqual(self.count(pulled, "SELECT COUNT(*) FROM observations"), 1)
        self.assertEqual(self.count(pulled, "SELECT COUNT(*) FROM facts WHERE source_id='aircraft_user'"), 1,
                         "свои типы ВС возвращаются из прежней домашней базы, без очереди приёмки")

    def test_pull_refuses_to_drop_unsent_home_facts(self):
        M.make_seed(self.home, self.drop / "seed.db")
        M.cmd_import(None, master=self.master, drop=self.drop, spool=self.spool)
        st = Store(self.home)
        st.commit_facts([Fact(domain="traffic", key="EDDF-LIRF/pax", valid_from="2024-01-01", value=7e5,
                              source_id="eurostat_par", extracted_by="test")])
        st.db.close()
        losses = M.home_only_losses(self.home, self.master / "export" / "flightcost.db")
        self.assertTrue(any("eurostat_par" in x for x in losses))

    def test_refresh_tree_links_repo_data_but_owns_raw(self):
        app = self.tmp / "app"
        (app / "data" / "charges").mkdir(parents=True)
        (app / "data" / "raw").mkdir()
        (app / "data" / "flightcost.db").write_text("")
        (app / "config").mkdir()
        M.ensure_tree(self.master, app)
        d = self.master / "data"
        self.assertTrue((d / "charges").is_symlink())
        self.assertFalse((d / "raw").is_symlink())
        self.assertFalse((d / "flightcost.db").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
