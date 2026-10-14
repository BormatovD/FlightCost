"""Пассажиропоток по парам (M10, решение 195): разбор Eurostat и чтение.

Образцы синтетические, по описанию формата выгрузки; настоящая выгрузка
сверяется отдельно, когда появится.
"""

from __future__ import annotations

import pathlib
import tempfile
import unittest

from flightcostapp import traffic
from flightcostapp.parsers import eurostat_par
from flightcostapp.store import Store

FIX = pathlib.Path(__file__).resolve().parent / "fixtures"


def months(facts):
    import json
    return {f.key: json.loads(f.value_text) for f in facts}


def parse(name):
    ctx = {"source_id": "eurostat_par", "today": "2026-10-14", "url": f"file:{name}"}
    return eurostat_par.parse((FIX / name).read_bytes(), ctx), ctx


class Parser(unittest.TestCase):

    def test_tsv_takes_only_monthly_carried_passengers(self):
        facts, ctx = parse("eurostat_par_de.tsv")
        m = months(facts)
        self.assertEqual(m["EDDF/EDDF-LEBL/2025"]["01"][0], 100000)
        self.assertEqual(m["EDDF/EDDF-LEBL/2025"]["12"][0], 111000)
        self.assertEqual(len(facts), 2)                       # одна пара-год — один факт
        self.assertNotIn("04", m["EDDF/EDDF-LIRF/2025"])      # «:» — значения нет
        self.assertEqual(m["EDDF/EDDF-LIRF/2025"]["05"][0], 50000)  # знак «p» снят
        self.assertEqual(ctx["parsed_prefixes"], ["EDDF"])

    def test_sdmx_csv_and_pair_key_is_alphabetical(self):
        facts, ctx = parse("eurostat_par_es.csv")
        self.assertEqual(months(facts)["LEBL/EDDF-LEBL/2025"]["03"][0], 112000)
        self.assertEqual(ctx["parsed_prefixes"], ["LEBL"])

    def test_wrong_measure_is_refused_in_words(self):
        with self.assertRaisesRegex(ValueError, "PAS_CRD"):
            eurostat_par.parse(b"freq,unit,tra_meas,airp_pr\\TIME_PERIOD\t2025-01 \n"
                               b"M,PAS,PAS_BRD,DE_EDDF_ES_LEBL\t5 \n",
                               {"source_id": "x"})


class RealEurostat(unittest.TestCase):
    """Вырезка настоящей выгрузки avia_par_de (октябрь 2026)."""

    def test_months_sum_to_the_published_year(self):
        facts, ctx = parse("eurostat_par_de_real.tsv")
        y = {f.key: f.value for f in facts}
        self.assertEqual(y["EDDF/EDDF-LEBL/2024"], 804747)
        self.assertEqual(months(facts)["EDDF/EDDF-LEBL/2024"]["08"][0], 80411)

    def test_seats_and_flights_ride_along(self):
        facts, _ = parse("eurostat_par_de_real.tsv")
        self.assertEqual(months(facts)["EDDF/EDDF-LEBL/2024"]["08"][2], 481)

    def test_reader_gives_market_aircraft(self):
        st = Store(pathlib.Path(tempfile.mkdtemp()) / "r.db")
        st.commit_facts(parse("eurostat_par_de_real.tsv")[0])
        r = traffic.published(st, "EDDF", "LEBL", "2026-10-14")
        self.assertEqual(r["months"][-1], "2024-12")
        self.assertAlmostEqual(r["pax_month"], 804747 / 12, delta=1)
        self.assertGreater(r["market"]["pax_per_flight"], 100)


class T100(unittest.TestCase):

    def test_directions_and_carriers_are_summed(self):
        import csv
        from flightcostapp.parsers import t100
        rows = list(csv.DictReader(open(FIX / "t100_excerpt.csv", encoding="utf-8")))
        codes = {r["ORIGIN"] for r in rows} | {r["DEST"] for r in rows}

        class S:
            def icao_of_iata(self, as_of=None):
                return {c: "K" + c for c in codes if c != "LEX"}
        ctx = {"source_id": "t100", "today": "2026-10-14", "store": S()}
        facts = t100.parse((FIX / "t100_excerpt.csv").read_bytes(), ctx)
        want = sum(float(r["PASSENGERS"]) for r in rows if r["CLASS"] in ("F", "L")
                   and {r["ORIGIN"], r["DEST"]} == {"BOS", "JFK"}
                   and r["YEAR"] == "2025" and r["MONTH"] == "12")
        if want >= 1000:
            self.assertEqual(months(facts)["T100/KBOS-KJFK/2025"]["12"][0], want)
        self.assertIn("без ИКАО", ctx["summary"][0])      # LEX не переведён — назван
        self.assertEqual(ctx["parsed_prefixes"], ["T100"])


class Reader(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.store = Store(pathlib.Path(tempfile.mkdtemp()) / "t.db")
        for name in ("eurostat_par_de.tsv", "eurostat_par_es.csv"):
            cls.store.commit_facts(parse(name)[0])

    def test_two_reports_are_averaged_and_gap_named(self):
        r = traffic.published(self.store, "LEBL", "EDDF", "2026-10-14")
        # Германия 100…111 тыс., Испания 110…121 тыс. — среднее 110,5 тыс.
        self.assertAlmostEqual(r["pax_month"], 110500, delta=1)
        self.assertIn("расходятся", r["src"])
        self.assertEqual(r["months"][-1], "2025-12")

    def test_month_takes_that_calendar_month(self):
        r = traffic.published(self.store, "EDDF", "LEBL", "2026-10-14", month=8)
        self.assertAlmostEqual(r["pax_month"], (107000 + 117000) / 2, delta=1)

    def test_unknown_pair_falls_through_with_reason(self):
        r = traffic.pair_flow(self.store, "UUEE", "URSS", "2026-10-14")
        self.assertIsNone(r["pax_month"])
        self.assertIn("RU", r["src"])


class ObservedSeats(unittest.TestCase):
    """Кресла по типам наблюдённых бортов — для оценки RU/KZ (решение 198)."""

    def test_mix_of_types_gives_weighted_seats(self):
        from flightcostapp import observe
        from flightcostapp.store import Fact
        st = Store(pathlib.Path(tempfile.mkdtemp()) / "o.db")
        st.commit_facts([Fact(domain="aircraft", key=f"{t}/seats_typical", valid_from="2026-01-01",
                              value=v, unit="шт", source_id="t", confidence="exact")
                         for t, v in (("A320", 170.0), ("SU95", 98.0))])
        rows = [dict(kind="contact_time", key=f"{t}/UUEE-URSS", value=120.0, unit="мин",
                     observed_at=f"2026-09-{d:02d}T10:00:00", source_id="t", ref=f"{t}{d}", note=None)
                for t in ("A320", "SU95") for d in range(1, 6)]
        rows += [dict(kind="airborne_time", key="ZZZZ/URSS-UUEE", value=110.0, unit="мин",
                      observed_at="2026-09-01T12:00:00", source_id="t", ref="z", note=None)]
        st.add_observations(rows)
        facts, thin = observe.aggregate_seats(st, as_of="2026-10-14")
        st.commit_facts(facts)
        seats, why = traffic.obs_seats(st, "URSS", "UUEE", "2026-10-14")
        self.assertAlmostEqual(seats, (170 * 5 + 98 * 5) / 10)
        self.assertIn("A320", why)
        # Тип без кресел (ZZZZ) в среднее не входит, но назван.
        self.assertTrue(any("URSS-UUEE" in t for t in thin))


if __name__ == "__main__":
    unittest.main(verbosity=2)
