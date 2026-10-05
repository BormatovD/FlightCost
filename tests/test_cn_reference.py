"""Эталон материкового Китая: один государственный документ на десять
аэропортов, ставки по классу аэропорта и по эксплуатанту.

Проверяется на Пекине Шоуду (класс 1-1) и Сямыне (класс 2): формула
«база + k × (T − нижняя граница полосы)», стоянка долями посадочного по
трём интервалам, пассажирский и безопасность за вылетающего, и то, что
международный рейс материкового перевозчика считается по ставкам
иностранных (民航发〔2013〕3号).

Запуск: python3 tests/test_cn_reference.py
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

MTOW, PAX = 78.0, 148.0


def rules(icao):
    doc = ROOT / "data" / "charges" / f"{icao}-2017.json"
    facts = airport_charges.parse(doc.read_bytes(), {
        "source_id": "test", "sha": "test", "extracted_by": "test",
        "as_of": "2026-09-18", "corpus": {}, "icao_seen": []})
    return [Rule.from_fact(asdict(f)) for f in facts
            if f.domain == "airport_charge" and f.value_text
            and not f.key.endswith(("/_next", "/_scope"))]


def total(icao, operator, flight, park_h, stand="pier"):
    c = {"mtow_t": MTOW, "pax": PAX, "cargo_kg": 0.0, "movements": 2, "landings": 1,
         "turnarounds": 1, "departures": 1, "flight": flight, "pax_type": "local",
         "dest": "intercontinental", "month": 7, "night": False, "noise_cat": None,
         "cargo": False, "stand": stand, "stand_group": None, "ac_group": None,
         "ac_class": None, "pax_per_mtow": PAX / MTOW, "park_h": park_h,
         "park_h_over_free": park_h > 0, "return_technical": False,
         "operator": operator, "terminal": None, "other": "ZSPD", "seats": 170.0}
    return {k: round(v, 2) for k, v in evaluate(rules(icao), c, fx=lambda cur: 1.0).items()
            if not k.startswith("_")}


class Beijing(unittest.TestCase):

    def test_domestic_two_hours(self):
        got = total("ZBAA", "national", "domestic", 2.0)
        self.assertEqual(got["landing"], 1200 + 24 * 28)        # 1 872
        self.assertEqual(got["passenger"], 34 * PAX)            # 5 032
        self.assertEqual(got["security"], 8 * PAX)              # 1 184
        self.assertEqual(got["pbb"], 100 + 100)                 # час + час сверх
        self.assertNotIn("parking", got)                        # до 2 часов бесплатно

    def test_parking_tiers(self):
        self.assertAlmostEqual(total("ZBAA", "national", "domestic", 5.0)["parking"], 0.20 * 1872, 2)
        self.assertAlmostEqual(total("ZBAA", "national", "domestic", 20.0)["parking"], 0.25 * 1872, 2)
        self.assertAlmostEqual(total("ZBAA", "national", "domestic", 30.0)["parking"], 0.25 * 1872 * 2, 2)

    def test_foreign_and_mainland_international_share_annex_4(self):
        fr = total("ZBAA", "foreign", "INTL", 2.0)
        self.assertEqual(fr["landing"], 2200 + 40 * 28)         # 3 320
        self.assertEqual(fr["passenger"], 70 * PAX)
        self.assertEqual(fr["security"], 12 * PAX)
        self.assertEqual(fr["pbb"], 200 + 200)
        self.assertEqual(total("ZBAA", "national", "INTL", 2.0), fr)
        self.assertAlmostEqual(total("ZBAA", "national", "EEA", 5.0)["parking"], 0.15 * 3320, 2)

    def test_remote_stand_has_no_bridge(self):
        self.assertNotIn("pbb", total("ZBAA", "national", "domestic", 2.0, stand="apron"))


class Xiamen(unittest.TestCase):

    def test_class_two_domestic(self):
        got = total("ZSAM", "national", "domestic", 2.0)
        self.assertEqual(got["landing"], 1300 + 26 * 28)        # 2 028
        self.assertEqual(got["passenger"], 42 * PAX)
        self.assertEqual(got["security"], 10 * PAX)

    def test_heavy_type_uses_the_next_band(self):
        c = total("ZSAM", "national", "domestic", 2.0)
        # 230 т (A330) — полоса 201+: 5 200 + 33 × (230 − 200)
        rs = rules("ZSAM")
        ctxd = {"mtow_t": 230.0, "pax": 0.0, "cargo_kg": 0.0, "movements": 2, "landings": 1,
                "turnarounds": 1, "departures": 1, "flight": "domestic", "pax_type": "local",
                "dest": "intercontinental", "month": 7, "night": False, "noise_cat": None,
                "cargo": False, "stand": "apron", "stand_group": None, "ac_group": None,
                "ac_class": None, "pax_per_mtow": 0.0, "park_h": 1.0, "park_h_over_free": True,
                "return_technical": False, "operator": "national", "terminal": None,
                "other": "ZSPD", "seats": 250.0}
        self.assertEqual(round(evaluate(rs, ctxd, fx=lambda cur: 1.0)["landing"], 2), 5200 + 33 * 30)


if __name__ == "__main__":
    unittest.main(verbosity=2)
