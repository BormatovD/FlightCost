"""Выбор типа (Ф1, решение 188): силуэт из чисел и участки подбора."""

from __future__ import annotations

import json
import pathlib
import unittest

from flightcostapp.parsers import aircraft_user, openap_aircraft
from flightcostapp.serve import Context

WEB = pathlib.Path(__file__).resolve().parents[1] / "flightcostapp" / "web"


class Geometry(unittest.TestCase):

    def test_openap_gives_silhouette_numbers(self):
        try:
            facts = openap_aircraft.parse(b"", {"source_id": "aircraft_openap", "today": "2026-10-14"})
        except ImportError:
            self.skipTest("openap не установлен")
        by = {f.key: f for f in facts}
        self.assertGreater(by["A320/sweep_deg"].value, 20)
        self.assertGreater(by["A388/fuselage_width_m"].value, 6)
        self.assertEqual(by["A320/engine_mount"].value_text, "wing")
        # Поправка к библиотеке: у CRJ900 двигатели на хвосте.
        self.assertEqual(by["CRJ9/engine_mount"].value_text, "rear")
        self.assertEqual(by["CRJ9/engine_mount"].confidence, "derived")

    def _doc(self, **kw):
        d = {"icao": "T214", "valid_from": "2026-10-14", "source": "s", "source_url": "u",
             "publisher": "p", "checked_at": "2026-10-14",
             "fields": {"mtow_t": 110.75, "oew_t": 59, "fuel_capacity_t": 35.7, "seats_max": 210,
                        "span_m": 41.8, "cruise_mach": 0.8, "cruise_alt_m": 11000, "sweep_deg": 28}}
        d.update(kw)
        return json.dumps(d).encode()

    def test_user_type_takes_mount_and_sweep(self):
        facts = aircraft_user.parse(self._doc(engine_mount="Wing"), {"source_id": "aircraft_user"})
        by = {f.key: f for f in facts}
        self.assertEqual(by["T214/engine_mount"].value_text, "wing")
        self.assertEqual(by["T214/sweep_deg"].value, 28)

    def test_user_type_rejects_unknown_mount(self):
        ctx = {"source_id": "aircraft_user"}
        with self.assertRaises(ValueError):
            aircraft_user.parse(self._doc(engine_mount="fuselage"), ctx)
        self.assertIn("engine_mount", ctx["rejected"][0])


class FleetRates(unittest.TestCase):
    """Ставки своего типа по полю (решение 190)."""

    class Res:
        def __init__(self, store=None, over=None):
            self.store, self.over, self.base = store or {}, over or {}, {}

        def value(self, dom, key):
            return self.over.get((dom, key), self.store.get((dom, key)))

        def has_override(self, dom, key):
            return (dom, key) in self.over

        def note_baseline(self, dom, key, was):
            self.base[(dom, key)] = was

    def test_author_rate_replaces_only_its_field(self):
        from flightcostapp import fleet
        res = self.Res({("aircraft", "USER:T214/fleet_lease_eur_month"): 250000.0,
                        ("aircraft", "USER:T214/fleet_maint_eur_per_fh"): 700.0})
        fe = fleet.load(res, "USER:T214", mtow_t=110.75, seats=176)
        base = fleet.parametric("USER:T214", 110.75, 176)
        self.assertEqual((fe.lease_eur_month, fe.maint_eur_per_fh), (250000.0, 700.0))
        self.assertEqual(fe.maint_eur_per_fc, base.maint_eur_per_fc)
        self.assertEqual((fe.prov("lease_eur_month"), fe.prov("maint_eur_per_fc")), ("store", "default"))
        self.assertEqual(fe.field_ref["lease_eur_month"], "aircraft/USER:T214/fleet_lease_eur_month")

    def test_override_beats_author_rate(self):
        from flightcostapp import fleet
        res = self.Res({("aircraft", "X/fleet_lease_eur_month"): 250000.0},
                       {("fleet_economics", "*/X/lease_eur_month"): 1.0})
        fe = fleet.load(res, "X", mtow_t=78, seats=170)
        self.assertEqual((fe.lease_eur_month, fe.prov("lease_eur_month")), (1.0, "override"))

    def test_parser_needs_source_for_rates(self):
        doc = json.loads(Geometry._doc(None))
        doc["fleet"] = {"maint_eur_per_fh": 800}
        ctx = {"source_id": "aircraft_user"}
        with self.assertRaises(ValueError):
            aircraft_user.parse(json.dumps(doc).encode(), ctx)
        doc["fleet_source"] = "моё допущение"
        by = {f.key: f for f in aircraft_user.parse(json.dumps(doc).encode(), {"source_id": "aircraft_user"})}
        self.assertEqual(by["T214/fleet_maint_eur_per_fh"].value, 800)


class Legs(unittest.TestCase):

    def setUp(self):
        self.c = object.__new__(Context)
        apts = [{"key": k, "icao": i} for k, i in (("FRA", "EDDF"), ("BCN", "LEBL"), ("LIS", "LPPT"))]
        self.c.airports = lambda: apts

    def test_single_route_without_legs(self):
        legs = self.c._legs({"origin": "EDDF", "destination": "BCN"}, 150)
        self.assertEqual(legs, [{"o": "FRA", "d": "BCN", "pax": 150}])

    def test_legs_with_and_without_pax(self):
        legs = self.c._legs({"legs": "FRA-BCN:120~EDDF LPPT"}, 150)
        self.assertEqual([(x["o"], x["d"], x["pax"]) for x in legs],
                         [("FRA", "BCN", 120), ("FRA", "LIS", 150)])

    def test_unknown_airport_is_one_error(self):
        with self.assertRaisesRegex(ValueError, "XXX"):
            self.c._legs({"legs": "FRA-XXX"}, 100)

    def test_leg_limit(self):
        with self.assertRaisesRegex(ValueError, "предел"):
            self.c._legs({"legs": "~".join(["FRA-BCN"] * 9)}, 100)


class NetCompare(unittest.TestCase):

    def test_summary_sums_pairs_and_counts_cuts(self):
        r = {"network": {"pairs": [
                {"key": "FRA-BCN", "freq_week": 14, "seats_month": 1000, "pax_month": 800,
                 "revenue_month": 9e4, "need_share": 0.4},
                {"key": "FRA-LIS", "freq_week": 7, "seats_month": 500, "pax_month": 400,
                 "revenue_month": 5e4, "need_share": 1.3}],
                "lease_eur_month": 2e5, "lease_prov": "default", "util_h_month": 300,
                "util_prov": "default", "hours_used": 500, "fleet": 2, "breakeven_lf": 0.7,
                "profit_at_ref": 1e4, "excluded": [], "warnings": []},
             "pairs": [{"a": "FRA", "b": "BCN", "status": "ok", "legs": [{"seats": 180}]},
                       {"a": "FRA", "b": "LIS", "status": "ok", "legs": [{"seats": 180}]},
                       {"a": "FRA", "b": "SVO", "status": "rights"}]}
        x = Context._net_summary("A320", r, own=True)
        self.assertEqual((x["freq_week"], x["seats_month"], x["pairs_in"], x["pairs_total"]), (21, 1500, 2, 3))
        self.assertEqual(x["cut"], {"rights": 1})
        self.assertEqual((x["need_max"], x["need_over"]), (1.3, 1))

    def test_failed_network_still_names_fleet_rates(self):
        x = Context._net_summary("E190", {"network": None, "error": "нет цены",
                                          "fleet": {"lease_eur_month": 1.2e5, "lease_prov": "default"}},
                                 own=False)
        self.assertEqual((x["status"], x["lease_eur_month"]), ("failed", 1.2e5))

    def test_type_limit(self):
        c = object.__new__(Context)
        self.assertIn("предел", c.net_compare({"types": "A,B,C,D,E,F"})["error"])


class Page(unittest.TestCase):

    def test_silhouette_is_drawn_not_stored(self):
        html = (WEB / "serve.html").read_text(encoding="utf-8")
        self.assertIn("function silhouette(", html)
        self.assertNotRegex(html, r"<img[^>]+(aircraft|silhouette)")
        self.assertIn('id="acgal"', html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
