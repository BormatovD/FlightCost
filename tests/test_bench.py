"""Бенчмарк флотской экономики: разбор Form 41 и IATA ACMG, полосы, структура.

ФИКСТУРЫ. Таблицы ACMG — настоящие файлы книги EUROCONTROL (CC BY 4.0,
`tests/fixtures/acmg_*.xlsx`). Form 41 — дважды: синтетика с заранее
известным ответом (заголовки в виде описания полей TranStats) и ВЫДЕРЖКА
ИЗ НАСТОЯЩЕЙ ВЫГРУЗКИ 2025 года (`form41_*_excerpt.csv`: семь перевозчиков,
пять кодов типа, данные правительства США). Синтетика проверяет
арифметику, выдержка — то, на чём синтетика однажды уже обманула: первая
версия была зелёной на выдуманных заголовках, а настоящий файл принёс
пустой итог амортизации, часы и дни в тысячах и код 699 с расшифровкой,
противоречащей данным.

Числа синтетики подобраны так, чтобы ответ был известен заранее: ТОиР
A321 у трёх перевозчиков на плечах 1,5 / 2,5 / 3,5 ч ровно 900 USD/ч +
1 500 USD/рейс, — подбор обязан вернуть именно это.
"""

from __future__ import annotations

import pathlib
import tempfile
import unittest

from flightcostapp import bench
from flightcostapp.parsers import acmg_cost, form41
from flightcostapp.store import Store

FIX = pathlib.Path(__file__).parent / "fixtures"

# перевозчик, код BTS, плечо ч, вылетов за квартал, бортов
FLEET = [("AA", "699", 1.5, 9000, 60), ("DL", "699", 2.5, 6000, 55),
         ("UA", "699", 3.5, 4000, 50), ("AA", "614", 2.0, 12000, 100),
         ("WN", "614", 1.8, 15000, 120)]
MAINT_H, MAINT_C = 900.0, 1500.0          # USD
PILOT_H, PILOT_C = 650.0, 300.0


def p52_camel() -> bytes:
    """Как выгрузка новой формы TranStats: имена полей из описания."""
    head = ["Year", "Quarter", "AirlineID", "UniqueCarrier", "UniqueCarrierName",
            "CarrierRegion", "AircraftConfig", "AircraftGroup", "AircraftType",
            "PilotFlyOps", "BenefitsFlyOps", "FuelFlyOps", "RentalFlyOps",
            "TotDirMaint", "ApMtBurden", "TotFltMaintMemo", "OthFltEquipDepGrpI",
            "FltEquipAExp", "TotAirOpExpenses", "TotalAirHours", "AirDaysAssign"]
    lines = [",".join(head)]
    for q in (1, 2, 3, 4):
        for car, typ, leg, dep, ac in FLEET:
            bh = dep * leg
            # Две строки на перевозчика — два региона (D и I): парсер обязан сложить.
            for share, reg in ((0.7, "D"), (0.3, "I")):
                d, h = dep * share, bh * share
                maint = (MAINT_H * h + MAINT_C * d) / 1000          # тыс. USD
                pilots = (PILOT_H * h + PILOT_C * d) / 1000 * 0.8
                benef = (PILOT_H * h + PILOT_C * d) / 1000 * 0.2
                own = 330.0 * ac * 91.3125 * share / 30.4375        # 330 тыс./мес на борт
                lines.append(",".join(map(str, [
                    2025, q, 19805, car, f'"{car} Airlines Inc."', reg, 1, 6, typ,
                    round(pilots, 3), round(benef, 3), 1000, round(own * 0.6, 3),
                    round(maint * 0.8, 3), round(maint * 0.2, 3), round(maint, 3),
                    round(own * 0.4, 3), 0, 9999, round(h * 0.88, 1),
                    round(ac * 91.3125 * share, 1)])))
    # Грузовой борт — мимо.
    lines.append(",".join(map(str, [2025, 1, 1, "FX", "Fedex", "D", 2, 6, "614",
                                    1, 1, 1, 1, 1, 1, 99999, 1, 0, 1, 1, 1])))
    return ("\n".join(lines) + "\n").encode()


def t2_snake() -> bytes:
    """Как предзаготовленный архив: верхний регистр и коды строк, классы обслуживания."""
    head = ["YEAR", "QUARTER", "AIRLINE_ID", "UNIQUE_CARRIER", "UNIQUE_CARRIER_NAME",
            "CARRIER_GROUP", "AIRCRAFT_TYPE", "AIRCRAFT_CONFIG", "SERVICE_CLASS",
            "AVL_SEAT_MILES_320", "REV_ACRFT_MILES_FLOWN_410", "REV_ACRFT_DEP_PERF_510",
            "ACRFT_HRS_RAMPTORAMP_630", "HOURS_AIRBORNE_650", "ACRFT_DAYS_ASSIGNED_810",
            "AIRCRAFT_FUELS_921"]
    lines = [",".join(head)]
    for q in (1, 2, 3, 4):
        for car, typ, leg, dep, ac in FLEET:
            bh = dep * leg
            miles = bh * 0.88 * 450
            row = lambda svc, k: [2025, q, 1, car, car, 3, typ, 1, svc, round(miles * 190 * k),
                                  round(miles * k), round(dep * k), round(bh * k, 1),
                                  round(bh * 0.88 * k, 1), round(ac * 91.3125 * k, 1),
                                  round(bh * 850 * k)]
            # Сводный Z и его слагаемые F и G: взять обязан только Z.
            for svc, k in (("F", 0.9), ("G", 0.1), ("Z", 1.0)):
                lines.append(",".join(map(str, row(svc, k))))
    return ("\n".join(lines) + "\n").encode()


TYPES = (b'Code,Description\n"614","Boeing 737-800"\n"699","Airbus Industrie A321/A321-200"\n'
         b'"838","Boeing 737 MAX 8"\n"999","Mystery Jet 9"\n')


class Form41Parse(unittest.TestCase):

    def ctx(self):
        return {"source_id": "form41", "today": "2026-10-14"}

    def test_files_are_recognised_by_header(self):
        for blob, prefix in ((p52_camel(), "F41/P52/"), (t2_snake(), "F41/T2/"),
                             (TYPES, "F41/TYPES/")):
            facts = form41.parse(blob, self.ctx())
            self.assertTrue(facts and all(f.key.startswith(prefix) for f in facts), prefix)

    def test_regions_are_summed_and_freighters_dropped(self):
        facts = form41.parse(p52_camel(), self.ctx())
        by = {f.key: f.value for f in facts}
        car, typ, leg, dep, _ = FLEET[0]
        want = (MAINT_H * dep * leg + MAINT_C * dep) / 1000
        self.assertAlmostEqual(by[f"F41/P52/2025Q1/{car}/{typ}/maint_total"], want, delta=0.01)
        self.assertFalse(any("/FX/" in k for k in by), "грузовая компоновка попала в выборку")

    def test_service_class_total_is_not_double_counted(self):
        facts = form41.parse(t2_snake(), self.ctx())
        by = {f.key: f.value for f in facts}
        car, typ, leg, dep, _ = FLEET[1]
        self.assertAlmostEqual(by[f"F41/T2/2025Q2/{car}/{typ}/departures"], dep, delta=1)

    def test_unknown_header_is_a_loud_refusal(self):
        with self.assertRaises(ValueError) as e:
            form41.parse(b"Foo,Bar,Baz\n1,2,3\n", self.ctx())
        self.assertIn("Foo", str(e.exception))

    def test_missing_required_column_names_the_headers(self):
        bad = p52_camel().replace(b"TotalAirHours", b"Something")
        with self.assertRaises(ValueError) as e:
            form41.parse(bad, self.ctx())
        self.assertIn("air_hours", str(e.exception))


class Bands(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.store = Store(pathlib.Path(cls.tmp.name) / "t.db")
        ctx = {"source_id": "form41", "today": "2026-10-14"}
        for blob in (p52_camel(), t2_snake(), TYPES):
            cls.store.commit_facts(form41.parse(blob, dict(ctx)))
        for f in ("acmg_aircraft_operating_costs.xlsx", "acmg_cost_structure.xlsx"):
            cls.store.commit_facts(acmg_cost.parse((FIX / f).read_bytes(),
                                                   {"source_id": "acmg_cost", "today": "2026-10-14"}))

    @classmethod
    def tearDownClass(cls):
        cls.store.db.close()
        cls.tmp.cleanup()

    def test_scale_of_thousands_is_detected_and_said(self):
        rows, meta = bench.carrier_rows(self.store)
        self.assertEqual(meta["scales"]["money"], 1000.0)
        self.assertEqual(meta["scales"]["hours"], 1.0)
        self.assertTrue(all(meta["scales"]["why"]))

    def test_rates_per_block_hour(self):
        b = bench.type_bench(self.store, "A321")
        self.assertEqual(b["year"], 2025)
        self.assertEqual(b["bands"]["maint_per_bh"].n, 3)
        aa = next(r for r in b["carriers"] if r["carrier"] == "AA")
        self.assertAlmostEqual(aa["maint_per_bh"], MAINT_H + MAINT_C / 1.5, delta=1)
        self.assertAlmostEqual(aa["util_h_month"], 9000 * 1.5 / (60 * 91.3125) * 30.4375, delta=0.5)
        self.assertAlmostEqual(aa["own_per_ac_month"], 330_000, delta=50)
        self.assertAlmostEqual(aa["seats"], 190, delta=0.5)

    def test_hour_and_cycle_parts_are_recovered_from_carriers_on_different_legs(self):
        b = bench.type_bench(self.store, "A321")
        s = b["split"]["maint"]
        self.assertEqual(s.structure, "measured")
        self.assertAlmostEqual(s.per_h, MAINT_H, delta=1)
        self.assertAlmostEqual(s.per_cycle, MAINT_C, delta=2)
        c = b["split"]["cockpit"]
        self.assertAlmostEqual(c.per_h, PILOT_H, delta=1)

    def test_two_carriers_do_not_pretend_to_measure_structure(self):
        b = bench.type_bench(self.store, "B738")
        self.assertIsNone(b["split"]["maint"])

    def test_unmapped_type_is_reported_not_dropped_silently(self):
        _, meta = bench.carrier_rows(self.store)
        self.assertEqual(meta["unmapped"], {})       # в выборке только A321 и B738
        self.assertIsNone(bench.icao_of("Mystery Jet 9"))
        self.assertEqual(bench.icao_of("Boeing 737 MAX 8"), "B38M")
        self.assertEqual(bench.icao_of("Airbus Industrie A321/A321-200"), "A321")
        self.assertEqual(bench.icao_of("Airbus A321-200n"), "A21N")
        self.assertEqual(bench.icao_of("Boeing 737-800"), "B738")

    def test_acmg_family_and_implied_leg(self):
        b = bench.type_bench(self.store, "A320")
        a = b["acmg"]
        self.assertEqual(a["family"], "A320_FAMILY")
        self.assertGreater(a["per_fh_usd"], 4000)
        self.assertAlmostEqual(a["leg_h"], 1.83, delta=0.05)
        self.assertGreater(bench.cabin_to_cockpit(self.store), 0.4)

    def test_band_verdict(self):
        bd = bench.type_bench(self.store, "A321")["bands"]["maint_per_bh"]
        self.assertEqual(bd.where(bd.p50), "в полосе p25–p75")
        self.assertEqual(bd.where(bd.lo * 0.5), "ниже всех перевозчиков")


class RealExcerpt(unittest.TestCase):
    """Выдержка из настоящих P-5.2 и T-2 за 2025 год — свойства, а не числа."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.store = Store(pathlib.Path(cls.tmp.name) / "r.db")
        for f in ("form41_p52_2025_excerpt.csv", "form41_t2_2025_excerpt.csv",
                  "form41_types_excerpt.csv"):
            cls.store.commit_facts(form41.parse((FIX / f).read_bytes(),
                                                {"source_id": "form41", "today": "2026-10-14"}))
        cls.rows, cls.meta = bench.carrier_rows(cls.store)

    @classmethod
    def tearDownClass(cls):
        cls.store.db.close()
        cls.tmp.cleanup()

    def test_p52_hours_and_money_are_in_thousands(self):
        """Описание полей не врёт хотя бы здесь: и часы, и деньги — в тысячах."""
        self.assertEqual(self.meta["scales"]["hours"], 1000.0)
        self.assertEqual(self.meta["scales"]["money"], 1000.0)

    def test_ownership_includes_depreciation_parts(self):
        """Итог амортизации пуст — владение без слагаемых было бы одной арендой."""
        wn = next(r for r in self.rows if r["carrier"] == "WN" and r["icao"] == "B737")
        self.assertGreater(wn["own_per_ac_month"], 50_000)

    def test_code_699_is_a321ceo_not_neo(self):
        icaos = {r["icao"] for r in self.rows if r["carrier"] == "AA"}
        self.assertIn("A321", icaos)
        self.assertIn("A21N", icaos)
        self.assertIn("699", self.meta.get("overrides", {}))

    def test_rates_are_in_plausible_corridors(self):
        """Коридоры широкие намеренно: ловят ошибку в тысячу раз, не уровень."""
        for r in self.rows:
            with self.subTest(f"{r['carrier']} {r['icao']}"):
                self.assertTrue(150 <= r["util_h_month"] <= 450, r["util_h_month"])
                self.assertTrue(200 <= r["maint_per_bh"] <= 5000, r["maint_per_bh"])
                self.assertTrue(300 <= r["cockpit_per_bh"] <= 4000, r["cockpit_per_bh"])
                self.assertTrue(1.0 <= r["block_per_dep"] <= 6.0, r["block_per_dep"])
                self.assertTrue(120 <= (r["seats"] or 0) <= 250, r["seats"])


class CarrierReports(unittest.TestCase):
    """Ставки на блок-час из годовой отчётности (data/benchmarks/*.yaml)."""

    @classmethod
    def setUpClass(cls):
        from flightcostapp.parsers import carrier_benchmark as C
        from flightcostapp.store import Fact
        cls.tmp = tempfile.TemporaryDirectory()
        cls.store = Store(pathlib.Path(cls.tmp.name) / "c.db")
        root = pathlib.Path(__file__).resolve().parents[1] / "data" / "benchmarks"
        for f in sorted(root.glob("*.yaml")):
            cls.store.commit_facts(C.parse(f.read_bytes(), {"source_id": "carrier_benchmark"}))
        cls.store.commit_facts([Fact(domain="fx", key=k, valid_from="2026-10-13", value=v,
                                     unit="per_EUR", source_id="fx_rates")
                                for k, v in (("USD", 1.16), ("GBP", 0.87), ("NOK", 11.6))])
        cls.rows = {r["carrier"]: r for r in bench.reports(cls.store)}

    @classmethod
    def tearDownClass(cls):
        cls.store.db.close()
        cls.tmp.cleanup()

    def test_norwegian_code_survives_yaml(self):
        """Голое NO в YAML 1.1 — false; Norwegian пропадал бы молча."""
        self.assertIn("NO", self.rows)

    def test_published_block_hours_are_not_estimates(self):
        self.assertFalse(self.rows["W6"]["bh_estimated"])
        self.assertAlmostEqual(self.rows["W6"]["staff_per_bh"], 564.9e6 / 812673, delta=1)

    def test_utilisation_gives_marked_estimate(self):
        u2 = self.rows["U2"]
        self.assertTrue(u2["bh_estimated"])
        self.assertAlmostEqual(u2["block_h"], 10.2 * (356 + 347) / 2 * 365, delta=1)
        self.assertEqual(u2["crew_basis"], "экипаж")

    def test_crew_from_cents_per_ask(self):
        bt = self.rows["BT"]
        self.assertAlmostEqual(bt["crew_per_bh"], 0.63 / 100 * 9121e6 / 107478, delta=1)
        self.assertIn("pilot_cost_c_per_ask", bt["unconfirmed"])

    def test_bool_carrier_is_a_loud_refusal(self):
        from flightcostapp.parsers import carrier_benchmark as C
        with self.assertRaises(ValueError) as e:
            C.parse(b"carrier: NO\nyear: 2025\nsource: x\nvalues: {}\n", {"source_id": "x"})
        self.assertIn("кавычки", str(e.exception))


class Generations(unittest.TestCase):
    """Решение 186: лизинг и ТОиР заготовки — одного поколения, сумма в полосе."""

    def test_ownership_plus_maintenance_lands_in_benchmark(self):
        from flightcostapp.fleet import parametric
        cur = parametric("A320", 78, 180)
        new = parametric("A20N", 79, 180)
        month = lambda f: f.lease_eur_month + f.effective_maint_per_h(2.5) * 300
        # Form 41 A320ceo ≈ 433 тыс. EUR, Wizz (A320/A321neo) ≈ 469 тыс.
        self.assertTrue(400_000 <= month(cur) <= 480_000, month(cur))
        self.assertTrue(430_000 <= month(new) <= 520_000, month(new))
        self.assertGreater(new.lease_eur_month, cur.lease_eur_month)
        self.assertLess(new.effective_maint_per_h(2.5), cur.effective_maint_per_h(2.5))

    def test_market_lease_maps_to_market_value(self):
        """400 тыс. в месяц ↔ новый A320neo за 55–58 млн (IBA, Ishka)."""
        from flightcostapp.solve import implied_aircraft_value
        v = implied_aircraft_value(400_000)["value"]
        self.assertTrue(53e6 <= v <= 59e6, v)


if __name__ == "__main__":
    unittest.main(verbosity=2)
