"""Налёт из плеч сети и экипажи (план network-calc, 09.11.2026)."""

from __future__ import annotations

import unittest

from flightcostapp import netutil as N


class Window(unittest.TestCase):

    def test_peak_day_formula(self):
        # статья: окно 18 ч, оборот 25 мин, плечо 2,5 ч — шесть рейсов, 15 блок-часов
        self.assertEqual(N.flights_in_window(2.5), 6)
        self.assertAlmostEqual(N.peak_day(2.5), 15.0)
        # 1,9 ч: семь влезает, челнок — до чётного
        self.assertEqual(N.flights_in_window(1.93), 6)
        # от 3,5 ч — без чётности (трансконы, W-ротации); от 5 ч — сутки с долгим оборотом
        self.assertEqual(N.flights_in_window(4.5), 3)
        self.assertEqual(N.flights_in_window(8.1), 2)

    def test_wider_window_more_hours(self):
        self.assertGreater(N.peak_day(1.0, window_h=22), N.peak_day(1.0, window_h=18))


class HeldOut(unittest.TestCase):
    """Frontier и Southwest не входили в калибровку: модель против факта T-2 2025
    (блок-часы ÷ дни в парке; средняя длина плеча перевозчика на типе)."""

    FACT = {  # перевозчик/тип: (плечо, ч; факт, ч в сутки)
        "WN 737-700": (1.93, 9.8), "WN 737 MAX 8": (2.33, 10.8), "WN 737-800": (2.24, 10.5),
        "F9 A320neo": (2.54, 8.8),
    }

    def test_within_ten_percent(self):
        for name, (b, fact) in self.FACT.items():
            kind = "leisure" if name.startswith("F9") else "shuttle"
            u = N.network_util([(b, 1.0)], kind)
            err = u.h_month / N.DAYS_MONTH / fact - 1
            self.assertLess(abs(err), 0.11, f"{name}: модель {u.h_month / N.DAYS_MONTH:.1f} ч/сут, "
                                            f"факт {fact} ({err:+.0%})")


class Network(unittest.TestCase):

    def test_kind_by_sector_length(self):
        self.assertEqual(N.network_util([(2.0, 1)]).kind, "shuttle")
        self.assertEqual(N.network_util([(9.0, 1)]).kind, "longhaul")
        with self.assertRaises(ValueError):
            N.network_util([(2.0, 1)], "charter")

    def test_shares_multiply_back(self):
        u = N.network_util([(2.5, 1)], "hub")
        s = u.shares
        self.assertAlmostEqual((1 - s["reserve"]) * (1 - s["heavy_mx"]) * s["season_delay"], u.factor)
        self.assertIn("Form 41 T-2", u.note)

    def test_crews_and_duty(self):
        self.assertAlmostEqual(N.crews(312.5), 5.0)            # 3 750 ч в год ÷ 750
        self.assertEqual(N.max_sectors(1.0), 6)
        self.assertEqual(N.max_sectors(2.5), 3)               # четыре по 2,5 ч — уже 12,6 ч при пределе 12
        notes = N.duty_notes([("FRA→PMI", 2.5), ("FRA→JFK", 9.0)])
        self.assertTrue(any("FRA→PMI" in x and "2 смены" in x for x in notes))


if __name__ == "__main__":
    unittest.main()
