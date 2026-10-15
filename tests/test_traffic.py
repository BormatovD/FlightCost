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
        self.assertIn("сводка по РФ", r["src"])


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


class DGCA(unittest.TestCase):
    """Индия: пары ГОРОДОВ DGCA -> пары аэропортов (вырезка настоящих данных)."""

    class S:
        def icao_of_iata(self, as_of=None):
            class D(dict):
                def get(self, k, d=None):
                    return ("Z" + k) if k else d
            return D()

    def run_(self, name):
        from flightcostapp.parsers import dgca
        ctx = {"source_id": "dgca", "today": "2026-10-15", "store": self.S()}
        return dgca.parse((FIX / name).read_bytes(), ctx), ctx

    def test_both_directions_and_both_orientations_are_summed(self):
        facts, _ = self.run_("dgca_domestic_excerpt.csv")
        m = months(facts)
        # 2025-12: DELHI→MUMBAI 304 512 + 275 378 и строка MUMBAI→DELHI 3 624 + 3 674
        self.assertEqual(m["DGCA/ZBOM-ZDEL/2025"]["12"][0], 304512 + 275378 + 3624 + 3674)

    def test_mumbai_splits_after_navi_mumbai_opens(self):
        facts, ctx = self.run_("dgca_domestic_excerpt.csv")
        keys = {f.key for f in facts}
        self.assertIn("DGCA/ZBOM-ZDEL/2026", keys)        # «MUMBAI (MUMBAI)»
        self.assertIn("DGCA/ZDEL-ZNMI/2026", keys)        # «MUMBAI (NAVI MUMBAI)»

    def test_goa_after_mopa_opened_is_mopa(self):
        from flightcostapp.parsers import dgca
        cities = dgca.load_cities()
        to = {"GOI": "VOGO", "GOX": "VOGA"}
        self.assertEqual(dgca.resolve("GOA", "2022-06", cities, to)[0], "VOGO")
        self.assertIsNone(dgca.resolve("GOA", "2023-03", cities, to)[0])   # переходный
        self.assertEqual(dgca.resolve("GOA", "2025-06", cities, to)[0], "VOGA")
        self.assertEqual(dgca.resolve("DABOLIM", "2025-06", cities, to)[0], "VOGO")

    def test_quarters_stay_quarters_and_city_is_flagged(self):
        facts, _ = self.run_("dgca_international_excerpt.csv")
        m = months(facts)
        self.assertEqual(m["DGCA/ZALA-ZDEL/2025"]["Q1"][0], 28212 + 29911)
        lon = next(f for f in facts if f.key == "DGCA/ZDEL-ZLHR/2025")
        self.assertIn("LONDON", lon.note)

    def test_reader_takes_a_third_of_the_quarter(self):
        st = Store(pathlib.Path(tempfile.mkdtemp()) / "d.db")
        st.commit_facts(self.run_("dgca_international_excerpt.csv")[0])
        r = traffic.published(st, "ZDEL", "ZALA", "2026-10-15")
        self.assertIn("квартальные", r["src"])
        q = [28212 + 29911, 21991 + 21225, 17672 + 19980, 16207 + 17388,
             14466 + 17736, 22747 + 22450]
        self.assertAlmostEqual(r["pax_month"], sum(q[-4:]) / 12, delta=1)


class RuPairs(unittest.TestCase):
    """Россия: годовая таблица пар городов без первоисточника (вырезка выгрузки за 2024 год)."""

    class S:
        def icao_of_iata(self, as_of=None):
            m = {"LED": "ULLI", "AER": "URSS", "KGD": "UMKK", "SVX": "USSS", "MRV": "URMM"}

            class D(dict):
                def get(self, k, d=None):
                    return m.get(k, "Z" + k) if k else d
            return D()

    def parsed(self):
        from flightcostapp.parsers import ru_pairs
        ctx = {"source_id": "ru_pairs", "today": "2026-10-15", "store": self.S()}
        return ru_pairs.parse((FIX / "ru_pairs_2024_excerpt.xlsx").read_bytes(), ctx), ctx

    def test_both_directions_summed_moscow_kept_as_city(self):
        facts, ctx = self.parsed()
        m = months(facts)
        self.assertEqual(m["RUPAIRS/@MOW-ULLI/2024"]["A"][0], 2325559 + 2314954)
        self.assertIn("ЯМБ", ctx["summary"][0])            # внутренний код — назван, не потерян

    def test_any_moscow_airport_gets_city_flow_flagged(self):
        st = Store(pathlib.Path(tempfile.mkdtemp()) / "r.db")
        st.commit_facts(self.parsed()[0])
        for ap in ("UUEE", "UUDD", "UUWW"):
            r = traffic.published(st, ap, "ULLI", "2026-10-15")
            self.assertTrue(r["city"])
            self.assertAlmostEqual(r["pax_month"], (2325559 + 2314954) / 12, delta=1)
            self.assertIn("весь город", r["src"])
            self.assertIn("годовые", r["src"])
            self.assertIn("первоисточник таблицы неизвестен", r["src"])


class Nearby(unittest.TestCase):
    """Второй аэропорт города: Дели–Нави-Мумбаи не должен читаться как весь Мумбаи."""

    def test_other_airport_of_the_city_is_named(self):
        import json
        from flightcostapp.store import Fact
        st = Store(pathlib.Path(tempfile.mkdtemp()) / "n.db")
        st.commit_facts([
            Fact(domain="airport", key=k, valid_from="2026-01-01", value_text=t,
                 source_id="t", confidence="exact")
            for k, t in (("DEL", "28.566,77.103|VIDP|IN|Delhi"),
                         ("BOM", "19.089,72.868|VABB|IN|Mumbai"),
                         ("NMI", "18.990,73.070|VANM|IN|Navi Mumbai"),
                         ("PNQ", "18.582,73.920|VAPO|IN|Pune"))] + [
            Fact(domain="traffic", key=f"DGCA/{p}/2026", valid_from="2026-08-01", value=v * 7,
                 value_text=json.dumps({f"{m:02d}": [v, None, None] for m in range(1, 8)}),
                 source_id="dgca_domestic", confidence="exact")
            for p, v in (("VABB-VIDP", 550000), ("VANM-VIDP", 52000), ("VAPO-VIDP", 300000))])
        near = traffic.nearby(st, "VIDP", "VANM", "2026-10-15")
        self.assertEqual([(n["with"], round(n["pax_month"])) for n in near], [("VABB", 550000)])
        self.assertLess(near[0]["km"], 80)                 # Пуна (~110 км) — не тот же город


class PublishedObservations(unittest.TestCase):
    """Аэропорты с наблюдениями видны и на сервере, где сырой таблицы нет:
    `fca publish` её вычищает, остаются агрегаты `observed/frequency/…`."""

    def test_airport_list_reads_aggregated_frequency(self):
        from flightcostapp.serve import Context
        from flightcostapp.store import Fact
        st = Store(pathlib.Path(tempfile.mkdtemp()) / "s.db")
        st.commit_facts([
            Fact(domain="airport", key=k, valid_from="2026-01-01", value_text=t,
                 source_id="t", confidence="exact")
            for k, t in (("SVO", "55.97,37.41|UUEE|RU|Sheremetyevo"),
                         ("LED", "59.80,30.26|ULLI|RU|Pulkovo"),
                         ("KZN", "55.61,49.28|UWKD|RU|Kazan"))] + [
            Fact(domain="observed", key=f"frequency/UUEE-ULLI/2026-09-0{d}", valid_from="2026-10-01",
                 value=12.0, unit="рейсов", source_id="observation", confidence="derived")
            for d in (1, 2)])
        c = object.__new__(Context)
        import threading
        c.store, c.lock, c._apts, c.ws = st, threading.Lock(), None, None
        apts = {a["icao"]: a for a in c.airports()}
        self.assertTrue(apts["UUEE"]["seen"])
        self.assertEqual(apts["ULLI"]["flights"], 24)
        self.assertNotIn("UWKD", apts)               # ни тарифа, ни наблюдений, ни перечня


if __name__ == "__main__":
    unittest.main(verbosity=2)
