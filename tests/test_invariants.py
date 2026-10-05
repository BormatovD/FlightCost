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

    def test_library_type_is_tier1(self):
        self.assertEqual(self.fuel.trip_fuel("A320", 590, 148).tier, 1)

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
