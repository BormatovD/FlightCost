"""Правки по сверке на сетях США (09.11.2026, research/verify-2026-11).

Аэронавигация: рейс с посадкой в США не платит FAA. Руление: подбор
t(вылет) + t(прилёт) по сети. Экипаж: множитель региона по аэропорту вылета.
"""
from __future__ import annotations

import unittest

from flightcostapp import econ, fleet, taxi


class Taxi(unittest.TestCase):
    def test_fit_recovers_airports(self):
        segs = [("A", "B", 100, 20), ("B", "A", 100, 20), ("A", "C", 100, 30), ("C", "A", 100, 30),
                ("B", "C", 100, 26)]
        est = taxi.fit(segs, min_departures=0, us_only=False)
        self.assertAlmostEqual(est["A"][0], 12.0, places=1)
        self.assertAlmostEqual(est["B"][0], 8.0, places=1)
        self.assertAlmostEqual(est["C"][0], 18.0, places=1)

    def test_thin_airport_and_bad_rows_left_out(self):
        segs = [("A", "B", 1000, 20), ("B", "A", 1000, 20), ("A", "X", 10, 30), ("A", "B", 50, 400)]
        est = taxi.fit(segs, us_only=False)
        self.assertNotIn("X", est)
        self.assertAlmostEqual(est["A"][0] + est["B"][0], 20.0, places=1)


class T100Taxi(unittest.TestCase):
    def test_parser_emits_taxi_by_airport(self):
        from flightcostapp.parsers import t100
        head = "PASSENGERS,SEATS,DEPARTURES_PERFORMED,RAMP_TO_RAMP,AIR_TIME,ORIGIN,DEST,YEAR,MONTH,CLASS"
        rows = []
        for o, d, taxi_min in (("AAA", "BBB", 20), ("BBB", "AAA", 20), ("AAA", "CCC", 30),
                               ("CCC", "AAA", 30), ("BBB", "CCC", 26), ("CCC", "BBB", 26)):
            rows.append(f"15000,18000,200,{200 * (60 + taxi_min)},{200 * 60},{o},{d},2025,7,F")

        class S:
            def icao_of_iata(self, as_of=None):
                return {c: "K" + c for c in ("AAA", "BBB", "CCC")}
        facts = t100.parse("\n".join([head] + rows).encode(), {"source_id": "t100", "store": S()})
        tx = {f.key: f.value for f in facts if f.domain == "taxi"}
        self.assertAlmostEqual(tx["KAAA"], 12.0, places=1)
        self.assertAlmostEqual(tx["KCCC"], 18.0, places=1)


class TaxiForeign(unittest.TestCase):
    def test_foreign_end_fitted_but_not_emitted(self):
        segs = [("KJFK", "EDDF", 500, 40), ("EDDF", "KJFK", 500, 40), ("KJFK", "KBOS", 2000, 30),
                ("KBOS", "KJFK", 2000, 30), ("KBOS", "KDCA", 2000, 22), ("KDCA", "KBOS", 2000, 22)]
        est = taxi.fit(segs, min_departures=0)
        self.assertNotIn("EDDF", est)
        self.assertIn("KJFK", est)

    def test_lookup_ignores_foreign_even_if_stored(self):
        class S:
            def value(self, *a):
                return 19.2
        self.assertIsNone(taxi.lookup(S(), "EDDF"))
        self.assertEqual(taxi.lookup(S(), "KDEN"), 19.2)


class Crew(unittest.TestCase):
    def test_us_by_departure_airport(self):
        self.assertEqual(fleet.crew_region("KDEN")[0], "north_america")
        self.assertEqual(fleet.crew_region("PHNL")[0], "north_america")
        self.assertIsNone(fleet.crew_region("EDDF")[0])


class NavZones(unittest.TestCase):
    def test_faa_transit_only(self):
        kk = econ._nav_formulas()["KK"]
        self.assertIn("US", kk["transit_only"])


if __name__ == "__main__":
    unittest.main()


class AirportFallback(unittest.TestCase):
    """Запись аэропорта сменила ключ ИАТА и пропала из выгрузки — расчёт
    находит её по ИКАО через указатель и называет это (09.11.2026, Палм-Бич)."""

    def setUp(self):
        import pathlib
        import tempfile
        from flightcostapp.store import Fact, Store
        self.st = Store(pathlib.Path(tempfile.mkdtemp()) / "a.db")
        f = lambda d, k, t: Fact(domain=d, key=k, valid_from="2026-08-01", value_text=t,  # noqa: E731
                                 unit="", source_id="t", extracted_by="t")
        self.st.commit_facts([f("airport", "DJT", "26.683201,-80.095596|KPBI|US|Palm Beach"),
                              f("airport_code", "IATA/PBI", "KPBI")])
        self.st.db.execute("UPDATE facts SET valid_to = '2026-09-29' WHERE domain = 'airport'")
        self.st.db.commit()

    def test_found_by_icao_and_named_stale(self):
        ap = econ._airport(self.st, "PBI", "2026-11-09")
        self.assertEqual(ap["icao"], "KPBI")
        self.assertIn("снятая 2026-09-29", ap["stale"])

    def test_unknown_still_raises(self):
        with self.assertRaises(KeyError):
            econ._airport(self.st, "QQQ", "2026-11-09")
