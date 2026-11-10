"""ТОиР по типу, возрасту и году из статьи «ТОиР» (план toir-calc, 10.11.2026)."""

from __future__ import annotations

import unittest

from flightcostapp import toir

D = {"usd_year": 2025, "growth": 0.03, "cycle_share": 0.4, "sector_ref": {"narrow": 2.5},
     "shape": {"narrow": {0: 0.3, 6: 0.9, 12: 1.0, 20: 1.1}},
     "types": {"A320": {"cls": "narrow", "mature_usd_bh": 1000, "life_usd_bh": 900, "lo": 700, "hi": 1300,
                        "n": 70, "young_only": False}},
     "successors": {"A20N": {"base": "A320", "ratio": 0.7}, "AT72": {"base": "A320", "ratio": 1.0}}}


class Rate(unittest.TestCase):

    def test_life_average_without_age(self):
        r = toir.rate("A320", year=2025, usd_per_eur=1.0, d=D)
        self.assertAlmostEqual(r["per_bh_eur"], 900)
        # на опорном плече 2,5 ч сумма частей равна ставке, цикловая — 40 %
        self.assertAlmostEqual(r["per_fh"] + r["per_fc"] / 2.5, 900)
        self.assertAlmostEqual(r["per_fc"] / 2.5 / 900, 0.4)

    def test_age_interpolates_curve(self):
        self.assertAlmostEqual(toir.rate("A320", age=3, year=2025, usd_per_eur=1, d=D)["per_bh_eur"], 600)
        self.assertAlmostEqual(toir.rate("A320", age=30, year=2025, usd_per_eur=1, d=D)["per_bh_eur"], 1100)
        self.assertLess(toir.rate("A320", age=1, year=2025, usd_per_eur=1, d=D)["per_bh_eur"],
                        toir.rate("A320", age=12, year=2025, usd_per_eur=1, d=D)["per_bh_eur"])

    def test_growth_and_fx(self):
        r = toir.rate("A320", year=2027, usd_per_eur=1.2, d=D)
        self.assertAlmostEqual(r["per_bh_eur"], 900 * 1.03 ** 2 / 1.2)
        self.assertIn("индекс", r["note"])

    def test_successor_and_unknown(self):
        r = toir.rate("A20N", year=2025, usd_per_eur=1, d=D)
        self.assertAlmostEqual(r["per_bh_eur"], 630)
        self.assertIn("предшественнику A320 × 0.70", r["note"])
        self.assertAlmostEqual(toir.rate("AT72", year=2025, usd_per_eur=1, d=D)["per_bh_eur"], 900)
        self.assertIsNone(toir.rate("C919", d=D))

    def test_repo_table(self):
        d = toir.doc()
        self.assertGreaterEqual(len(d["types"]), 30)
        for icao, t in d["types"].items():
            self.assertGreaterEqual(t["n"], 8, icao)
            self.assertLessEqual(t["lo"], t["hi"], icao)
        for icao, s in d["successors"].items():
            self.assertIn(s["base"], d["types"], icao)
        # A320, борт 12 лет, 2025 год: 1 075 USD/блок-ч по статье
        self.assertAlmostEqual(toir.rate("A320", age=12, year=2025, usd_per_eur=1)["usd_bh"], 1075, delta=1)


if __name__ == "__main__":
    unittest.main()
