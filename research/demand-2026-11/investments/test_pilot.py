"""Tests run without third-party libraries or network access."""
import csv
from datetime import date
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pilot import SNAPSHOT, load_hotels, snapshot_as_of


class InvestmentSnapshotTests(unittest.TestCase):
    def test_values_and_scope(self):
        rows = load_hotels()
        self.assertEqual(10, len(rows))
        egypt = next(r for r in rows if r["country_iso3"] == "EGY")
        self.assertEqual(45984, egypt["rooms_pipeline"])
        self.assertEqual(23622, egypt["rooms_under_construction"])
        result = snapshot_as_of(date(2026, 11, 12), rows)
        self.assertEqual(10, result["country_count"])
        self.assertIsNone(result["effect_on_air_passengers"])
        self.assertFalse(result["airport_mapping_available"])
        self.assertLess(result["top10_rooms_pipeline"], 123846)

    def test_historic_cutoff_blocks_future_snapshot(self):
        rows = load_hotels()
        result = snapshot_as_of(date(2025, 12, 31), rows)
        self.assertEqual(0, result["country_count"])
        self.assertEqual(0, result["top10_rooms_pipeline"])
        self.assertEqual([], result["countries"])
        self.assertEqual(10, snapshot_as_of(date(2026, 3, 10), rows)["country_count"])

    def test_dedupes_and_physical_constraints(self):
        with SNAPSHOT.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        with tempfile.TemporaryDirectory() as root:
            data = Path(root) / "test.csv"
            def write(items):
                with data.open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(items)
            write(rows + [rows[0]])
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_hotels(data)
            bad = dict(rows[0]); bad["rooms_under_construction"] = "999999"
            write([bad])
            with self.assertRaisesRegex(ValueError, "exceeds pipeline"):
                load_hotels(data)


if __name__ == "__main__":
    unittest.main()
