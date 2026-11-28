import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from flightcostapp.admin_status import _airport_queue, _work


class AdminSnapshot(unittest.TestCase):
    def test_work_counts_current_rates_and_reports_last_import_separately(self):
        af = "airport_charge"
        ef = "enroute_rate"
        old, recent = "2026-10-01T08:30:00", "2026-11-19T10:30:00"
        with tempfile.TemporaryDirectory() as directory:
            master = Path(directory) / "master.db"
            with sqlite3.connect(master) as db:
                db.execute("""CREATE TABLE facts (
                    domain TEXT, key TEXT, value REAL, value_text TEXT, valid_from TEXT,
                    valid_to TEXT, source_id TEXT, created_at TEXT
                )""")
                db.executemany("INSERT INTO facts VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
                    (af, "KJFK/landing/r1", 1, "rule", "2026-01-01", None, "tier1", old),
                    (af, "KJFK/landing/r1", 2, "rule", "2026-10-01", None, "tier1", recent),
                    (af, "KJFK/parking/r2", 3, "rule", "2026-12-01", None, "tier1", recent),
                    (af, "KJFK/_info/s", 1, "metadata", "2026-10-01", None, "tier1", recent),
                    (ef, "UA/intl", 2, "", "2026-10-01", "2026-11-21", "fas_ans_rates", old),
                    (ef, "EU/intl", 3, "", "2026-10-01", None, "crco_enroute_rates", old),
                ])
            now = datetime(2026, 11, 23, tzinfo=timezone.utc)
            with patch("flightcostapp.admin_status._next_timer", return_value="2026-11-24T04:30:00+00:00"):
                work = _work(master, {"next": None}, {"observations": 23, "recent": [
                    {"route": "JFK-LHR", "at": "2026-11-21T10:00:00+00:00", "observations": 7},
                ]}, now)
        self.assertEqual(work["airports"], {"total": 1, "next_at": None, "last": {
            "at": recent + "+00:00", "label": "KJFK", "count": 2,
        }})
        self.assertEqual(work["enroute"]["total"], 1)
        self.assertEqual(work["enroute"]["last"]["count"], 2)
        self.assertEqual(work["terminal"], {"total": 0, "next_at": "2026-11-24T04:30:00+00:00", "last": None})
        self.assertEqual(work["tickets"]["total"], 23)
        self.assertEqual(work["tickets"]["last"]["kind"], "collection")
        self.assertEqual(work["tickets"]["last"]["count"], 7)

    def test_airport_queue_respects_deferred_manual_and_explicit_order(self):
        todo = {"airports": {"ZBAA": {"city": "Пекин"}}, "regions": {"china": {
            "name": "Китай", "prefixes": ["Z"], "min": 3,
            "candidates": [{"icao": code} for code in ("ZBAA", "ZSHC", "ZGGG")],
        }}}
        manual = [{"icao": "ZSPD", "city": "Шанхай", "added_at": "2026-11-20"}]
        with patch("flightcostapp.airport_queue.queue_airports", return_value=(manual, ["ZBAA"])):
            with patch.dict("os.environ", {"FCA_AGENT_CHARGES_ONLY": ""}):
                queued, stored, deferred = _airport_queue(todo, set(), {}, Path("."))
            with patch.dict("os.environ", {"FCA_AGENT_CHARGES_ONLY": "ZBAA,ZGGG,ZSHC"}):
                explicit, _, _ = _airport_queue(todo, set(), {}, Path("."))
        self.assertEqual([row["icao"] for row in queued], ["ZSPD", "ZSHC", "ZGGG"])
        self.assertEqual([row["icao"] for row in explicit], ["ZGGG", "ZSHC"])
        self.assertEqual(stored, [queued[0]])
        self.assertEqual(deferred, [{"icao": "ZBAA", "city": "Пекин", "region": "Китай", "origin": "deferred"}])
