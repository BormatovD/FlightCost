"""Решение 234: оценка сборов аэропорта без тарифа — по региону, и на каждом конце.

Регион определяется по префиксу ИКАО, уровень — медиана контрольного оборота
A320 по тарифам с документом (data/charges/_regional.yaml).
"""
from __future__ import annotations

import json
import pathlib
import unittest

import yaml

from flightcostapp import econ

ROOT = pathlib.Path(__file__).resolve().parents[1]


class RegionalCharges(unittest.TestCase):
    def test_regions_by_prefix(self):
        for icao, reg in (("EDDM", "europe"), ("GCRR", "europe"), ("HECA", "africa"), ("GMMN", "africa"),
                          ("VABB", "india"), ("VTBS", "asia_gulf"), ("ZBAA", "asia_gulf"), ("OMDB", "asia_gulf"),
                          ("UWWW", "russia_cis"), ("KJFK", "world"), ("SBGR", "world")):
            self.assertEqual(econ.regional_charge_k(icao)[1], reg, icao)

    def test_file_matches_turnarounds(self):
        """Медиана в файле = медиана оборотов исследования — файл не правится руками."""
        doc = yaml.safe_load((ROOT / "data/charges/_regional.yaml").read_text(encoding="utf-8"))
        turn = json.loads((ROOT / "research/charges-2026-10/turnaround.json").read_text(encoding="utf-8"))["airports"]
        base = doc["base_eur"]
        self.assertAlmostEqual(base, econ.APT_EST_MTOW * 78 + econ.APT_EST_PAX * 148)
        for code, r in doc["regions"].items():
            vals = sorted(turn[i]["eur"] for i in r["airports"])
            mid = len(vals) // 2
            med = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
            self.assertAlmostEqual(r["k"], round(med / base, 3), places=3, msg=code)
            self.assertEqual(r["n"], len(vals))

    def test_every_airport_with_tariff_is_in_a_region(self):
        """Регионы покрывают все аэропорты с тарифом, иначе медиана считает не то."""
        turn = json.loads((ROOT / "research/charges-2026-10/turnaround.json").read_text(encoding="utf-8"))["airports"]
        for icao in turn:
            self.assertNotEqual(econ.regional_charge_k(icao)[1], "world", icao)


if __name__ == "__main__":
    unittest.main()
