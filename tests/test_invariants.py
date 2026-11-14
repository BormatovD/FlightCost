"""Инварианты последних заходов — без базы, без сети, для CI.

Каждый из этих дефектов прожил неделями, потому что проверки не было:
узел карты не доезжал до тарифов, неизвестный тип получал категорию по
остаточному принципу, OurAirports раздавал один код двум аэродромам, тип
без якоря получал число вместо «нельзя». Тест на каждый — та граница,
которую нельзя переступить молча.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from flightcostapp import categories as C
from flightcostapp.store import Fact, Store

FRA_STAND = {"named": {"A388": 9},
             "rules": [{"when": {"span_m": {"le": 30}, "length_m": {"le": 32}}, "value": 2},
                       {"when": {"span_m": {"le": 38}, "length_m": {"le": 47}}, "value": 3},
                       {"default": 9, "exact": True}]}
AENA = {"rules": [{"when": {"noise_margin_cum": {"gt": 15}}, "value": 4},
                  {"when": {"noise_margin_cum": {"ge": 10}}, "value": 3},
                  {"when": {"noise_margin_cum": {"ge": 5}}, "value": 2},
                  {"when": {"noise_margin_cum": {"lt": 5}}, "value": 1}]}


class Categories(unittest.TestCase):
    """Решения 132, 133."""

    def test_named_wins_over_rule_and_disagreement_is_named(self):
        r = C.resolve("stand_group", {"named": {"A320": 4}, "rules": FRA_STAND["rules"]},
                      {"icao": "A320", "span_m": 35.8, "length_m": 37.6})
        self.assertEqual((r.value, r.how), (4, "named"))
        self.assertIn("правила дают 3", r.disagree)

    def test_rule_then_exact_default(self):
        r = C.resolve("stand_group", FRA_STAND, {"icao": "A320", "span_m": 35.8, "length_m": 37.6})
        self.assertEqual((r.value, r.how), (3, "rule"))
        r = C.resolve("stand_group", FRA_STAND, {"icao": "B77W", "span_m": 64.8, "length_m": 73.9})
        self.assertEqual((r.value, r.how, r.certainty), (9, "rule", "exact"))

    def test_missing_data_does_not_fall_into_default(self):
        """Тип без записи EASA не получает категорию по остаточному принципу."""
        r = C.resolve("noise_cat", AENA, {"icao": "T214"})
        self.assertIsNone(r.value)
        self.assertIn("noise_margin_cum", r.note)

    def test_unlisted_type_is_not_guessed(self):
        r = C.resolve("ac_class", {"named": {"A320": 2}}, {"icao": "B739"})
        self.assertIsNone(r.value)
        self.assertIn("не назван документом", r.note)

    def test_explicit_boundaries(self):
        for cum, cat in ((4.9, 1), (5.0, 2), (9.9, 2), (10.0, 3), (15.0, 3), (15.1, 4)):
            self.assertEqual(C.resolve("noise_cat", AENA,
                                       {"icao": "X", "noise_margin_cum": cum}).value, cat, cum)

    def test_validation_refuses_in_words(self):
        dom = set(range(1, 10))
        for bad, why in (
                ({"rules": [{"when": {"wingspan": {"le": 3}}, "value": 1}]}, "вне словаря"),
                ({"rules": [{"when": {"span_m": [1, 2]}, "value": 1}]}, "явным сравнением"),
                ({"rules": [{"default": 1}, {"when": {"icao": ["A320"]}, "value": 2}]}, "недостижимо"),
                ({"rules": [{"when": {"icao": ["A320"]}, "value": 99}]}, "вне области")):
            with self.assertRaises(ValueError) as cm:
                C.validate("TEST", "stand_group", bad, dom)
            self.assertIn(why, str(cm.exception))

    def test_code_letter_by_span(self):
        for span, letter in ((14.9, "A"), (15.0, "B"), (35.8, "C"), (36.0, "D"),
                             (64.8, "E"), (79.8, "F"), (80.0, None)):
            self.assertEqual(C.code_letter(span), letter, span)


class StoreSameness(unittest.TestCase):
    """Решение 138: исправление узла доезжает, переформулировка — нет."""

    def test_node_correction_lands_wording_does_not(self):
        st = Store(Path(tempfile.mkdtemp()) / "t.db")
        f = dict(domain="airport_charge", key="EDDF/landing/ab12", valid_from="2026-01-01",
                 value=2.5, value_text='{"x":1}', unit="per_tonne_mtow", currency="EUR",
                 source_id="airport_charges_tier1")
        st.commit_facts([Fact(**f)])
        self.assertEqual(st.commit_facts([Fact(**f, node="src_airport_tariff")])["added"], 1)
        self.assertEqual(st.get("airport_charge", f["key"], "2026-06-01")["node"],
                         "src_airport_tariff")
        self.assertEqual(st.commit_facts([Fact(**f, node="src_airport_tariff",
                                               note="иначе сказано")])["added"], 0)

    def test_confirmation_of_reading_lands(self):
        st = Store(Path(tempfile.mkdtemp()) / "t.db")
        f = dict(domain="airport_charge", key="EGKK/demand/1", valid_from="2026-01-01",
                 value=10.0, unit="per_pax", currency="GBP", source_id="s")
        st.commit_facts([Fact(**f, certainty="reading_unconfirmed", error_cost=1574.0,
                              confirm_by="Gatwick")])
        self.assertEqual(st.commit_facts([Fact(**f)])["added"], 1,
                         "подтверждение прочтения при том же числе потерялось")


class OurAirportsIcao(unittest.TestCase):
    """Решение 141."""

    def test_owned_code_and_ambiguity(self):
        from flightcostapp.parsers.ourairports import assign_icao
        rows = [
            {"ident": "IN-0276", "gps_code": "VANM", "icao_code": ""},   # законный код
            {"ident": "BR-0333", "gps_code": "SWYU", "icao_code": ""},   # код чужой
            {"ident": "SWYU", "gps_code": "SWYU", "icao_code": ""},      # владелец
            {"ident": "BR-9001", "gps_code": "SXXA", "icao_code": ""},   # двое заявляют
            {"ident": "BR-9002", "gps_code": "SXXA", "icao_code": ""},
            {"ident": "00AA", "gps_code": "00AA", "icao_code": ""},      # не ИКАО
        ]
        codes, stats = assign_icao(rows)
        self.assertEqual(codes, ["VANM", "BR-0333", "SWYU", "BR-9001", "BR-9002", "00AA"])
        self.assertEqual(stats["ambiguous"], 2)
        icao4 = [c for c in codes if len(c) == 4 and c.isalpha()]
        self.assertEqual(len(icao4), len(set(icao4)), "один код у двух записей")


class FuelTiers(unittest.TestCase):
    """Решения 94, 106, 145: подмена допустима только объявленной."""

    @classmethod
    def setUpClass(cls):
        try:
            import openap  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("нет openap")
        from flightcostapp import fuel
        cls.fuel = fuel
        cls.t214 = fuel.Airframe(icao="T214", oew_kg=59000, mtow_kg=110750, mfc_kg=35700,
                            cruise_alt_ft=36000, cruise_tas_kt=460, source="store")

    def test_analog_without_anchor_is_infeasible(self):
        r = self.fuel.trip_fuel("T214", 590, 148, frame=self.t214, ref=self.fuel.BurnRef("B752"))
        self.assertEqual(r.tier, 4)
        self.assertFalse(r.feasible.ok)

    def test_trip_anchor_alone_is_enough(self):
        """Якорь рейсом (решение 224) — полноценная привязка: без часового якоря
        тип не должен отвечать «нет якоря», а множитель — сводить рейс к якорю."""
        ref = self.fuel.BurnRef("B752", anchor_trip_kg=9000, anchor_trip_nm=1000, anchor_trip_pax=150)
        r = self.fuel.trip_fuel("T214", 1000, 150, frame=self.t214, ref=ref)
        self.assertTrue(r.feasible.ok, r.feasible)
        from flightcostapp.fuel import payload_range
        self.assertNotIn("error", payload_range("T214", 176, points=3, frame=self.t214, ref=ref))

    def test_same_engine_variant_needs_no_anchor(self):
        fr = self.fuel.airframe_from_openap("A320")
        fr.mtow_kg = 73500.0
        r = self.fuel.trip_fuel("A320", 590, 148, frame=fr, ref=self.fuel.BurnRef("A320", same_engine=True))
        self.assertEqual(r.tier, 4)
        self.assertTrue(r.feasible.ok)

    def test_unknown_type_is_tier0_and_infeasible(self):
        r = self.fuel.trip_fuel("ZZ99", 590, 148, frame=self.t214)
        self.assertEqual(r.tier, 0, "параметрика обязана называть себя ярусом 0")
        self.assertFalse(r.feasible.ok)

    def test_type_without_polar_uses_synonym_not_flat_rate(self):
        """A21N и B39M есть в openap без поляры: прежде — плоская ставка 2 400 кг/ч
        без набора и снижения. Теперь поляра синонима (A20N, B38M) и свой планер."""
        for t in ("A21N", "B39M"):
            r = self.fuel.trip_fuel(t, 500, 150)
            self.assertNotEqual(r.method, "empirical", t)
            self.assertNotIn("плоская", r.note or "", t)

    def test_library_type_is_tier1(self):
        self.assertEqual(self.fuel.trip_fuel("A320", 590, 148).tier, 1)

    def test_b738_descent_interpolates_and_fits_short_routes(self):
        from flightcostapp.boeing_descent import b738_descent
        slope = self.fuel.CLIMB_TAS_KT / self.fuel.CLIMB_VS_FPM / 60
        self.assertEqual(b738_descent(35000, 60000, slope, 600), (35000, 24, 320, 113))
        self.assertEqual(b738_descent(41000, 70000, slope, 600), (41000, 26, 340, 137))
        self.assertEqual(b738_descent(36000, 55000, slope, 600), (36000, 24, 325, 110.25))
        short = b738_descent(36000, 55000, slope, 140)
        self.assertLess(short.altitude_ft, 36000)
        self.assertAlmostEqual(short.altitude_ft * slope + short.distance_nm, 140)
        for alt, mass, nm in [(1400, 60000, 600), (42000, 60000, 600),
                              (36000, 71000, 600), (36000, 39000, 600), (36000, 60000, 10)]:
            self.assertIsNone(b738_descent(alt, mass, slope, nm))

    def test_b738_cruise_table_nodes_interpolation_and_unpublished_cells(self):
        from flightcostapp.boeing_cruise import b738_cruise_reference
        self.assertEqual(b738_cruise_reference(35000, 60000), 2 * 1185)
        self.assertEqual(b738_cruise_reference(41000, 55000), 2 * 1064)
        self.assertEqual(b738_cruise_reference(25000, 85000), 2 * 1764)
        self.assertEqual(b738_cruise_reference(36500, 62500),
                         2 * (1161 + 1225 + 1149 + 1223) / 4)
        for alt, mass in [(24999, 50000), (42000, 50000), (35000, 39999),
                          (30000, 85001), (41000, 55001), (40500, 58000)]:
            self.assertIsNone(b738_cruise_reference(alt, mass))

    def test_b738_cruise_preserves_openap_speed_response(self):
        from openap import aero
        from flightcostapp.boeing_cruise import cruise_flow_kg_h
        flow = self.fuel._flow("B738")
        mass, alt = 60000, 37000
        def tas(mach):
            return aero.mach2tas(mach, alt * aero.ft) / aero.kts
        def openap(mach):
            return flow.enroute(mass=mass, tas=tas(mach), alt=alt) * 3600
        for mach in (0.79, 0.789):
            result, used = cruise_flow_kg_h(flow, True, mass, tas(mach), alt)
            self.assertTrue(used)
            self.assertAlmostEqual(result, 2 * 1149 * openap(mach) / openap(0.79))
        for enabled, mach in [(True, 0.76), (True, 0.80), (False, 0.79)]:
            self.assertEqual(cruise_flow_kg_h(flow, enabled, mass, tas(mach), alt),
                             (openap(mach), False))

    def test_b738_table_applies_to_profile_and_keeps_other_analogs_on_openap(self):
        from dataclasses import replace
        frame = replace(self.fuel.airframe_from_openap("B738"), cruise_alt_ft=35000)
        r = self.fuel.trip_fuel("B738", 600, 130, frame=frame)
        self.assertEqual(r.method, "openap")
        self.assertEqual(r.phases["Снижение"], 320)
        self.assertAlmostEqual(r.times["Снижение"] * 60, 24)
        self.assertAlmostEqual(r.trip_kg, sum(r.phases.values()))
        self.assertAlmostEqual(r.block_h, sum(r.times.values()))
        self.assertIn("PI.31.7", r.note)
        native = self.fuel.trip_fuel("B738", 600, 130)
        self.assertIn("FPPM 3.2.14", native.note)
        self.assertEqual(native.phase_sources,
                         "набор — OpenAP, крейсер — Boeing FPPM с поправкой OpenAP, снижение — Boeing FCOM")
        slow = self.fuel.trip_fuel("B738", 600, 130, frame=replace(frame, cruise_tas_kt=400))
        self.assertEqual(slow.phase_sources, "набор — OpenAP, крейсер — OpenAP, снижение — Boeing FCOM")
        heavy = self.fuel.trip_fuel("B738", 600, 130, frame=replace(frame, oew_kg=75000))
        self.assertEqual(heavy.phase_sources, "набор — OpenAP, крейсер — OpenAP, снижение — OpenAP")
        self.assertAlmostEqual(native.times["Набор"] * 60,
                               self.fuel.airframe_from_openap("B738").cruise_alt_ft / self.fuel.CLIMB_VS_FPM)
        other = self.fuel.trip_fuel("T214", 600, 130, frame=self.t214,
                                    ref=self.fuel.BurnRef("B738", same_engine=True))
        self.assertNotIn("PI.31.7", other.note)
        self.assertNotIn("FPPM", other.note)
        self.assertEqual(other.phase_sources, "")

    def test_payload_range_refuses_without_anchor(self):
        from flightcostapp.fuel import payload_range
        d = payload_range("T214", 176, points=3, frame=self.t214, ref=self.fuel.BurnRef("B752"))
        self.assertIn("error", d)
        self.assertNotIn("error", payload_range("A320", 170, points=3))


class GateKinds(unittest.TestCase):
    """Решение 139: узел пишется сразу, прочтение — на приёмку.

    Домен `aircraft`, а не тарифы: у тарифов гейт добавляет ссылочную
    проверку и корпус, а здесь проверяется только классификация изменений.
    """

    def _gate(self, st, f):
        from flightcostapp.validate import run_gate
        return run_gate([f], source={"domain": "aircraft", "gate": "review"}, store=st)

    def test_node_only_is_auto_reading_goes_to_review(self):
        st = Store(Path(tempfile.mkdtemp()) / "t.db")
        base = dict(domain="aircraft", key="A320/mtow_t", valid_from="2026-01-01",
                    value=78.0, unit="t", source_id="aircraft_openap")
        st.commit_facts([Fact(**base)])
        g = self._gate(st, Fact(**base, node="src_openap"))
        self.assertEqual(g.verdict, "auto")
        self.assertIn("diff.node", [x.code for x in g.findings])
        g = self._gate(st, Fact(**base, certainty="reading_unconfirmed",
                                error_cost=10.0, confirm_by="кто-то"))
        self.assertEqual(g.verdict, "review")
        g = self._gate(st, Fact(**base))
        self.assertIn("diff.empty", [x.code for x in g.findings])


class TkpPack(unittest.TestCase):
    """Упаковка реестра сообщества
    """

    def test_xlsx_and_pack_give_same_facts(self):
        import datetime as dt
        import io
        import json
        import openpyxl
        from flightcostapp.parsers import tkp_charges as T
        tmp = Path(tempfile.mkdtemp())
        (tmp / "charges").mkdir()
        (tmp / "charges" / "UUEE-2026.json").write_text("{}")
        (tmp / "codes.yaml").write_text(
            "codes:\n  ШРМ: {icao: UUEE}\n  ДМД: {icao: UUDD}\n  СОЧ: {icao: URSS}\n",
            encoding="utf-8")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Перечень услуг"
        ws.append(list(T.NEED))
        D = dt.date
        for r in (("ШРМ", "ВЗЛЕТ-ПОСАДКА", 768.5, "РУБ-Т", "", D(2025, 1, 1), D(2027, 12, 31), "АО", "1", ""),
                  ("ДМД", "ВЗЛЕТ-ПОСАДКА", 640.0, "РУБ-Т", "", D(2025, 3, 1), None, "АО", "1",
                   "В Т.Ч. ИНВЕСТИЦИОННАЯ СОСТАВЛЯЮЩАЯ 40,00"),
                  ("ДМД", "АЭРОВОКЗАЛ", 120.0, "РУБ-ПАСС", "", D(2025, 3, 1), None, "АО", "1", ""),
                  ("СОЧ", "СТОЯНКА", 5.0, "ПРОЦ-ЧАС", "", D(2025, 1, 1), None, "АО", "1", ""),
                  ("СОЧ", "КЕЙТЕРИНГ", 999.0, "РУБ", "", D(2025, 1, 1), None, "АО", "1", ""),
                  ("ЖЖЖ", "ВЗЛЕТ-ПОСАДКА", 1.0, "РУБ-Т", "", D(2025, 1, 1), None, "?", "1", "")):
            ws.append(list(r))
        buf = io.BytesIO()
        wb.save(buf)
        ctx = {"codes_path": str(tmp / "codes.yaml"), "charges_path": str(tmp / "charges"),
               "raw_dir": str(tmp / "raw"), "source_id": "tkp_charges"}
        packed = T.pack(buf.getvalue(), T._codes(ctx))
        self.assertEqual({r["svc"] for r in packed["records"]} - T.AERO, set(),
                         "в упаковку попало не только аэронавигационное")
        self.assertEqual(packed["unmapped_codes"], 1)
        key = lambda f: (f.domain, f.key, f.valid_from, f.valid_to, f.value)  # noqa: E731
        f_xlsx = T.parse(buf.getvalue(), dict(ctx))
        f_pack = T.parse(json.dumps(packed, ensure_ascii=False).encode(),
                         dict(ctx, codes_path=str(tmp / "нет.yaml")))
        self.assertEqual(sorted(map(key, f_xlsx)), sorted(map(key, f_pack)))
        self.assertTrue((tmp / "raw" / "_сверка.txt").exists(),
                        "сверка не записана, когда папки не было")


if __name__ == "__main__":
    unittest.main(verbosity=2)
