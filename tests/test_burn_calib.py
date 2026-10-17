"""Поправки к расходу openap (решение 225)."""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flightcostapp.parsers import burn_calib as P           # noqa: E402
from flightcostapp.store import Store                       # noqa: E402

CALIB = ROOT / "data" / "aircraft" / "burn_calib" / "calib.json"


def _openap():
    try:
        from flightcostapp.fuel import _flow
        _flow("A320")
        return True
    except Exception:                                         # noqa: BLE001
        return False


class Parser(unittest.TestCase):

    def test_file_parses(self):
        facts = P.parse(CALIB.read_bytes(), {"source_id": "burn_calib"})
        self.assertIn("A20N/burn_calib", {f.key for f in facts})

    def test_refuses_wild_or_unsourced(self):
        bad = {"types": {"A320": {"factor": 3.0, "basis": "x", "sources": ["u"]}}}
        with self.assertRaises(ValueError):
            P.parse(json.dumps(bad).encode(), {"source_id": "burn_calib"})
        bad = {"types": {"A320": {"factor": 1.1, "basis": "", "sources": []}}}
        with self.assertRaises(ValueError):
            P.parse(json.dumps(bad).encode(), {"source_id": "burn_calib"})


@unittest.skipUnless(_openap(), "openap не установлен")
class Applied(unittest.TestCase):

    def test_factor_scales_trip_and_is_traced(self):
        from flightcostapp.fuel import trip_fuel
        base = trip_fuel("A20N", 600, 130).trip_kg
        cal = trip_fuel("A20N", 600, 130, calib=1.37)
        # Множитель на фазы полёта; руление идёт по своей норме, поэтому на
        # коротком плече рейс растёт чуть меньше множителя.
        self.assertGreater(cal.trip_kg / base, 1.30)
        self.assertLess(cal.trip_kg / base, 1.45)
        self.assertIn("1.37", cal.tier_note)

    def test_load_aircraft_reads_factor(self):
        from flightcostapp.econ import _calib
        s = Store(pathlib.Path(tempfile.mkdtemp()) / "t.db")
        s.commit_facts(P.parse(CALIB.read_bytes(), {"source_id": "burn_calib"}))
        k, why, ref = _calib(s, "A20N", "2026-12-01")
        self.assertEqual((k, ref), (1.37, "aircraft/A20N/burn_calib"))
        self.assertIn("Aircraft Commerce", why)
        self.assertIsNone(_calib(s, "A320", "2026-12-01"))

    def test_factors_match_published_rows(self):
        """Поправка в файле совпадает с тем, что сейчас даёт сверка: при новой
        версии openap множители надо пересчитать, а не тащить старые."""
        from flightcostapp.burn_calib import ac_ratios
        ac = ac_ratios()
        for icao, t in json.loads(CALIB.read_text(encoding="utf-8"))["types"].items():
            with self.subTest(icao):
                self.assertAlmostEqual(ac[icao]["ratio"], t["factor"], delta=0.03)


if __name__ == "__main__":
    unittest.main(verbosity=2)
