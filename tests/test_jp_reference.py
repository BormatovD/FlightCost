"""Эталон Нариты: разбор RJAA-2026 воспроизводит пример самого NAA.

NAA публикует на странице сборов таблицу «Typical example of international
flight charges by aircraft type»: A320, 74 т, индекс шума B, терминал 2 —
посадка 122 100, стоянка 14 800, багажная система 68 400, телетрап 13 000
JPY. Это проверка того же класса, что счёт Франкфурта: издатель сам назвал
итог. Плюс стоянка «за каждые 24 часа сверх первых шести» и пассажирские
сборы по терминалам.

Запуск: python3 tests/test_jp_reference.py
"""

from __future__ import annotations

import pathlib
import sys
import unittest
from dataclasses import asdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flightcostapp.charges import Rule, evaluate  # noqa: E402
from flightcostapp.parsers import airport_charges  # noqa: E402


def rules():
    doc = ROOT / "data" / "charges" / "RJAA-2026.json"
    facts = airport_charges.parse(doc.read_bytes(), {
        "source_id": "test", "sha": "test", "extracted_by": "test",
        "as_of": "2026-09-18", "corpus": {}, "icao_seen": []})
    return [Rule.from_fact(asdict(f)) for f in facts
            if f.domain == "airport_charge" and f.value_text
            and not f.key.endswith(("/_next", "/_scope"))]


def ctx(**kw):
    c = {"mtow_t": 78.0, "pax": 148.0, "cargo_kg": 0.0, "movements": 2,
         "landings": 1, "turnarounds": 1, "departures": 1, "flight": "INTL",
         "pax_type": "local", "dest": "intercontinental", "month": 7,
         "night": False, "noise_cat": "B", "cargo": False, "stand": "pier",
         "stand_group": None, "ac_group": None, "ac_class": None,
         "pax_per_mtow": 148 / 78, "park_h": 2.0, "park_h_over_free": True,
         "return_technical": False, "operator": "national", "terminal": "2",
         "other": "EDDF", "seats": 170.0}
    c.update(kw)
    return c


def total(**kw):
    return {k: round(v, 2) for k, v in evaluate(rules(), ctx(**kw), fx=lambda cur: 1.0).items()
            if not k.startswith("_")}


class Narita(unittest.TestCase):

    def test_naa_own_example_a320_74t_noise_b(self):
        got = total(mtow_t=74.0, pax=0.0)
        self.assertEqual(got["landing"], 122_100.0)
        self.assertEqual(got["parking"], 14_800.0)
        self.assertEqual(got["bhs"], 68_400.0)
        self.assertEqual(got["pbb"], 13_000.0)

    def test_noise_category_changes_the_rate(self):
        self.assertEqual(total(pax=0.0, noise_cat="A")["landing"], 1550 * 78)
        self.assertEqual(total(pax=0.0, noise_cat="F")["landing"], 2000 * 78)

    def test_mtow_rounds_up_and_minimum_applies(self):
        self.assertEqual(total(pax=0.0, mtow_t=77.4)["landing"], 1650 * 78)
        self.assertEqual(total(pax=0.0, mtow_t=20.0)["landing"], 50_000.0)   # минимум

    def test_parking_per_day_above_six_hours(self):
        self.assertEqual(total(park_h=5.0)["parking"], 15_600.0)
        self.assertEqual(total(park_h=30.0)["parking"], 31_200.0)
        self.assertEqual(total(park_h=49.0)["parking"], 46_800.0)

    def test_passenger_charges_by_terminal(self):
        t2 = total()
        self.assertEqual(t2["passenger"], 2460 * 148)      # PSFC T1/T2, вылетающие
        self.assertEqual(t2["security"], 700 * 148)        # PSSC
        t3 = total(terminal="3")
        self.assertEqual(t3["passenger"], 1370 * 148)
        self.assertEqual(total(pax_type="transfer")["passenger"], 1230 * 148)

    def test_domestic_gets_only_psfc(self):
        got = total(flight="domestic")
        self.assertEqual(set(got), {"passenger"})
        self.assertEqual(got["passenger"], 450 * 148 * 2)  # на вылете и на прилёте

    def test_bhs_by_seats_and_terminal(self):
        self.assertEqual(total(seats=250.0)["bhs"], 76_950.0)
        self.assertNotIn("bhs", total(terminal="3"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
