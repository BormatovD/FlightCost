"""Выбранная публикация лизинга: принятый ID → середина → EUR → владение.

Сценарий явный: историческая ставка не меняет дату расчёта или возраст,
не заменяет ручной ввод и не переносится на другой тип.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from flightcostapp import econ, fleet, fleetreport, network, prices, serve
from flightcostapp.overrides import Resolver
from flightcostapp.store import Fact, Store


OBS = {"icao": "CRJ9", "kind": "lease", "value_low": 100, "value_high": 115,
       "scale": "k", "currency": "USD", "month": "2022-07", "age": None,
       "source": "https://example.test/accepted-report.pdf",
       "quote": "Monthly lease rates as low as US$100-115,000.",
       "note": "Нижний диапазон ставок для находящихся на хранении бортов."}
DAY = "2026-11-11"
KEY = "fleet_economics.*/CRJ9/lease_eur_month"


class LeaseObservation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "calc.db")
        self.addCleanup(self.store.db.close)
        self.store.commit_facts([
            Fact(domain="fx", key="USD", value=1.25, unit="USD/EUR", valid_from="2026-11-09",
                 source_id="fx_rates", extracted_by="test"),
            Fact(domain="airport", key="FRA", value_text="50.026421,8.543125|EDDF|DE|Frankfurt",
                 valid_from="2020-01-01", source_id="test", extracted_by="test"),
            Fact(domain="airport", key="BCN", value_text="41.297078,2.078464|LEBL|ES|Barcelona",
                 valid_from="2020-01-01", source_id="test", extracted_by="test"),
        ])
        self.ctx = serve.Context(self.store, {"sources": {}})
        self.doc = {"observations": [dict(OBS)]}
        self.enterContext(mock.patch.object(prices, "load", return_value=self.doc))
        self.id = prices.observation_id(OBS)

    def query(self, **extra):
        return {"ac": "CRJ9", "lease_observation": self.id, "as_of": DAY, **extra}

    def test_midpoint_scale_current_fx_and_historical_metadata(self):
        kw = self.ctx._kwargs(self.query(age="12"))
        self.assertEqual(kw["overrides"][KEY], 86000)
        m = kw["lease_observation"]
        self.assertEqual((m["low"], m["high"], m["midpoint"]), (100000, 115000, 107500))
        self.assertEqual((m["month"], m["age"], kw["as_of"], kw["aircraft_age"]),
                         ("2022-07", None, DAY, 12))
        self.assertEqual((m["fx"]["rate"], m["fx"]["source"], m["fx"]["date"], m["fx"]["as_of"]),
                         (1.25, "fx_rates", "2026-11-09", DAY))
        self.assertTrue(m["applied"])
        self.assertEqual(m["note"], OBS["note"])
        # Выбор ничего не пишет в справочник ставок.
        self.assertIsNone(self.store.value("fleet_economics", "*/CRJ9/lease_eur_month", DAY))

    def test_no_selection_keeps_parametric_default(self):
        kw = self.ctx._kwargs({"ac": "CRJ9", "as_of": DAY})
        self.assertNotIn("lease_observation", kw)
        self.assertNotIn("overrides", kw)

    def accepted(self, *, icao="CRJ9", age=12, month="2026-10", value=125, **extra):
        obs = {"icao": icao, "kind": "lease", "value": value, "scale": "k",
               "currency": "USD", "month": month, "age": age,
               "source": "https://example.test/current-accepted.pdf",
               "quote": "Published monthly aircraft lease rate.", **extra}
        self.doc["observations"].append(obs)
        return obs

    def prepare_aircraft(self):
        from flightcostapp.parsers.openap_aircraft import parse
        self.store.commit_facts([f for f in parse(b"", {"source_id": "aircraft_openap", "today": "2026-11-01"})
                                 if f.key.split("/")[0] in ("CRJ9", "A20N")])

    def normal_route(self, **extra):
        return self.ctx.route({"ac": "CRJ9", "as_of": DAY, "age": "12",
                               "origin": "FRA", "destination": "BCN", **extra})

    def test_auto_age_freshness_category_and_incomplete_age(self):
        self.accepted(month="2025-12")
        self.accepted(age=None, month="2026-11")
        self.accepted(age=12, month="2026-12")
        self.accepted(age=11, month="2026-10")
        self.assertIsNone(prices.annual_lease("CRJ9", DAY, 12))
        self.assertIsNone(prices.annual_lease("CRJ9", DAY, 12.5))
        self.assertEqual(prices.annual_lease("CRJ9", DAY)["age"], 11)
        self.accepted(icao="A20N", age="new")
        self.accepted(icao="A20N", age=12, month="2026-11")
        self.assertEqual(prices.annual_lease("A20N", DAY)["age"], "new")
        self.assertEqual(prices.annual_lease("A20N", DAY, 0)["age"], "new")
        self.assertIsNone(prices.annual_lease("CRJ9", "2030-01-01", 12))

    def test_annual_mean_weights_sources_and_excludes_unpublished_or_duplicate_quotes(self):
        self.accepted(value=100, month="2026-Q1", source_family="IBA", published_on="2026-06-03")
        self.assertIsNone(prices.annual_lease("CRJ9", "2026-06-02", 12))
        self.accepted(value=100, month="2026-Q1", source_family="iba", published_on="2026-06-03",
                      source="https://example.test/reprint")
        self.accepted(value=120, month="2026-07", source_family="IBA")
        self.accepted(value=150, currency="EUR", source_family="OAG")
        m = prices.annual_lease("CRJ9", DAY, 12, self.store)
        self.assertEqual((m["source_count"], len(m["sources"])), (2, 3))
        self.assertEqual(m["midpoint"], (110000 + 150000 * 1.25) / 2)
        self.assertEqual(m["lease_eur_month"], m["midpoint"] / 1.25)

    def test_auto_default_current_window_and_incomplete_age(self):
        for age, eligible in ((7, False), (8, True), (14, True), (15, False),
                              (None, False), ({"from": 8, "to": 14}, False)):
            with self.subTest(age=age):
                self.doc["observations"] = []
                self.accepted(age=age)
                result = prices.annual_lease("CRJ9", DAY)
                self.assertEqual(result is not None, eligible)

    @unittest.skipUnless(importlib.util.find_spec("openap"), "openap не установлен")
    def test_auto_route_range_source_change_age_type_and_fallback(self):
        self.prepare_aircraft()
        interval = {**OBS, "month": "2026-10", "age": 12}
        self.doc["observations"].append(interval)
        result = self.normal_route()
        fl = result["inputs"]["fleet"]
        self.assertEqual(fl["lease_eur_month"], 86000)
        self.assertEqual(fl["lease_observation"]["id"], prices.observation_id(interval))
        self.assertTrue(fl["lease_observation"]["automatic"])
        self.assertEqual(fl["lease_observation"]["fx"]["date"], "2026-11-09")
        own = next(x["eur"] for x in result["cost"] if x["item"] == "ownership")
        self.assertAlmostEqual(own, 86000 * result["route"]["block_h"] / fl["monthly_hours"])
        revised = self.accepted(month="2026-11", value=150, source="https://example.test/revised.pdf")
        changed = self.normal_route()["inputs"]["fleet"]
        self.assertEqual(changed["lease_eur_month"], (107500 + 150000) / 2 / 1.25)
        self.assertIn(prices.observation_id(revised), [o["id"] for o in changed["lease_observation"]["sources"]])
        for changes in ({"age": "11"}, {"ac": "A20N", "age": "0"}):
            self.assertNotIn("lease_observation", self.normal_route(**changes)["inputs"]["fleet"])
        new = self.accepted(icao="A20N", age="new", value=500)
        for zero in (0, "0"):
            fl = self.normal_route(ac="A20N", age=zero)["inputs"]["fleet"]
            self.assertEqual(fl["lease_eur_month"], 400000)
            self.assertEqual(fl["lease_observation"]["id"], prices.observation_id(new))
        self.doc["observations"] = [dict(OBS)]
        fl = self.normal_route()["inputs"]["fleet"]
        mtow = self.store.value("aircraft", "CRJ9/mtow_t", DAY)
        self.assertEqual(fl["lease_eur_month"], fleet.parametric("CRJ9", mtow, 90).lease_eur_month)

    @unittest.skipUnless(importlib.util.find_spec("openap"), "openap не установлен")
    def test_auto_preserves_manual_workspace_card_and_operator_zero(self):
        self.prepare_aircraft()
        self.accepted()
        for value in (0, 42000):
            self.assertEqual(self.normal_route(set=f"fleet_economics.CRJ9.lease_eur_month={value}")
                             ["inputs"]["fleet"]["lease_eur_month"], value)
        with mock.patch.object(self.ctx, "_settings_overrides", return_value=[
                "fleet_economics.CRJ9.lease_eur_month=0"]):
            self.assertEqual(self.normal_route()["inputs"]["fleet"]["lease_eur_month"], 0)
        for domain, key, op in (("aircraft", "CRJ9/fleet_lease_eur_month", "*"),
                                ("fleet_economics", "LH/CRJ9/lease_eur_month", "LH"),
                                ("fleet_economics", "*/CRJ9/lease_eur_month", "*")):
            with self.subTest(key=key):
                self.store.commit_facts([Fact(domain=domain, key=key, value=0, valid_from="2026-01-01",
                                             source_id="test", extracted_by="test")])
                self.assertEqual(self.normal_route(operator=op)["inputs"]["fleet"]["lease_eur_month"], 0)
                self.store.db.execute("DELETE FROM facts WHERE domain=? AND key=?", (domain, key))

    @unittest.skipUnless(importlib.util.find_spec("openap"), "openap не установлен")
    def test_auto_without_fx_keeps_fallback_instead_of_guessing_conversion(self):
        self.prepare_aircraft()
        self.accepted()
        self.store.db.execute("DELETE FROM facts WHERE domain='fx' AND key='USD'")
        result = self.normal_route()
        fl = result["inputs"]["fleet"]
        self.assertNotIn("lease_observation", fl)
        self.assertEqual(fl["prov"]["lease_eur_month"], "default")
        self.assertTrue(any("ставки лизинга нет курса" in w for w in result["warnings"]))

    def test_manual_override_including_zero_and_workspace_wins(self):
        for value in (0, 42000):
            for key in ("fleet_economics.CRJ9.lease_eur_month", "fleet_economics.LH.CRJ9.lease_eur_month"):
                with self.subTest(value=value, key=key):
                    kw = self.ctx._kwargs(self.query(operator="LH", set=f"{key}={value}"))
                    fe = fleet.load(Resolver(self.store, DAY, kw["overrides"]), "CRJ9",
                                    operator="LH", mtow_t=37.4, seats=90)
                    self.assertEqual(fe.lease_eur_month, value)
                    self.assertFalse(kw["lease_observation"]["applied"])
        with mock.patch.object(self.ctx, "_settings_overrides", return_value=[
                "fleet_economics.CRJ9.lease_eur_month=0"]):
            kw = self.ctx._kwargs(self.query())
        self.assertEqual(kw["overrides"][KEY], 0)
        self.assertFalse(kw["lease_observation"]["applied"])

    def test_generic_override_beats_partial_and_complete_operator_store(self):
        fields = {"lease_eur_month": 200000, "monthly_hours": 300, "maint_eur_per_fh": 400,
                  "maint_eur_per_fc": 500, "crew_eur_per_fh": 200, "crew_eur_per_fc": 300}
        for complete in (False, True):
            self.store.commit_facts([
                Fact(domain="fleet_economics", key=f"LH/CRJ9/{f}", value=v,
                     valid_from="2026-01-01", source_id="test", extracted_by="test")
                for f, v in fields.items() if complete or f == "lease_eur_month"])
            with self.subTest(complete=complete):
                kw = self.ctx._kwargs(self.query(operator="LH"))
                fe = fleet.load(Resolver(self.store, DAY, kw["overrides"]), "CRJ9",
                                operator="LH", mtow_t=37.4, seats=90)
                self.assertEqual((fe.lease_eur_month, fe.prov("lease_eur_month")), (86000, "override"))
                manual = {**kw["overrides"], KEY: 0}
                self.assertEqual(fleet.load(Resolver(self.store, DAY, manual), "CRJ9",
                                           operator="LH", mtow_t=37.4, seats=90).lease_eur_month, 0)

    def test_invalid_id_type_kind_and_unaccepted_observation_fail_closed(self):
        unaccepted = {**OBS, "source": "https://example.test/draft.pdf"}
        for value in ("https://example.test/price?value=1", "100000", "0" * 64,
                      prices.observation_id(unaccepted)):
            with self.subTest(id=value), self.assertRaisesRegex(ValueError, "принятом справочнике"):
                self.ctx._kwargs(self.query(lease_observation=value))
        with self.assertRaisesRegex(ValueError, "для A320"):
            self.ctx._kwargs(self.query(ac="A320"))
        market = {**OBS, "kind": "market"}
        self.doc["observations"].append(market)
        with self.assertRaisesRegex(ValueError, "ставкой лизинга"):
            self.ctx._kwargs(self.query(lease_observation=prices.observation_id(market)))

    def test_missing_fx_is_error_unless_manual_rate_is_used(self):
        with self.assertRaisesRegex(ValueError, "нет курса USD/EUR"):
            self.ctx._kwargs(self.query(as_of="2020-01-01"))
        kw = self.ctx._kwargs(self.query(as_of="2020-01-01", set="fleet_economics.CRJ9.lease_eur_month=0"))
        self.assertEqual(kw["overrides"][KEY], 0)
        self.assertIsNone(kw["lease_observation"]["lease_eur_month"])
        eur = {**OBS, "currency": "EUR"}
        self.doc["observations"].append(eur)
        kw = self.ctx._kwargs(self.query(lease_observation=prices.observation_id(eur), as_of="2020-01-01"))
        self.assertEqual(kw["overrides"][KEY], 107500)
        self.assertEqual(kw["lease_observation"]["fx"]["kind"], "eur")

    @unittest.skipUnless(importlib.util.find_spec("openap"), "openap не установлен")
    def test_actual_route_midpoint_changes_ownership_and_zero_wins(self):
        from flightcostapp.parsers.openap_aircraft import parse
        self.store.commit_facts([f for f in parse(b"", {"source_id": "aircraft_openap", "today": "2026-11-01"})
                                 if f.key.startswith("CRJ9/")])
        q = self.query(origin="FRA", destination="BCN")
        base = self.ctx.route({k: v for k, v in q.items() if k != "lease_observation"})
        selected = self.ctx.route(q)
        fl = selected["inputs"]["fleet"]
        own = lambda r: next(x["eur"] for x in r["cost"] if x["item"] == "ownership")
        self.assertEqual(fl["lease_eur_month"], 86000)
        self.assertNotEqual(own(base), own(selected))
        self.assertAlmostEqual(own(selected), 86000 * selected["route"]["block_h"] / fl["monthly_hours"])
        trace = next(s for s in selected["trace"] if s["node"] == "d_fleet")
        self.assertIn("100,000 + 115,000", trace["subst"])
        self.assertIn("2022-07", trace["src"])
        self.assertIn("2026-11-09", trace["src"])
        self.assertIn(OBS["source"], trace["src"])
        self.assertEqual(trace["prov"], "override")
        zero = self.ctx.route({**q, "set": "fleet_economics.CRJ9.lease_eur_month=0"})
        self.assertEqual(own(zero), 0)
        self.assertFalse(zero["inputs"]["fleet"]["lease_observation"]["applied"])
        # Солвер наследует metadata, но меняет числовой override.
        kw = self.ctx._kwargs(q)
        kw["overrides"][KEY] = 1
        changed = econ.route_economics(self.store, "FRA", "BCN", **kw)
        self.assertFalse(changed.inputs["fleet"]["lease_observation"]["applied"])

    def network_result(self, *, automatic=False, **extra):
        def start(key, airports, base, kw, ov, as_of):
            if automatic:
                f = network.fleet_from_core(econ.route_economics, self.store, "FRA", "BCN",
                    aircraft=kw["aircraft"], as_of=as_of, month=kw.get("month"), overrides=ov,
                    operator=kw.get("operator", "*"), aircraft_age=kw.get("aircraft_age"))
            else:
                fe = fleet.load(Resolver(self.store, as_of, ov), kw["aircraft"], mtow_t=37.4, seats=90)
                f = network.Fleet("CRJ9", fe.lease_eur_month, fe.prov("lease_eur_month"), 300, "default")
            legs = [network.Leg(a, b, 2, 90, 90, 3000, 5, 1000, 1, .8, fare_eur=150,
                                market_fare_eur=150, market_fare_src="test")
                    for a, b in (("EDDF", "LEBL"), ("LEBL", "EDDF"))]
            pairs = [network.Pair("FRA", "BCN", "EDDF", "LEBL", "DE", "ES", dist_km=1100, legs=legs)]
            self.ctx._net_cache[key] = (pairs, f, 1)
            return {"done": True}
        with mock.patch.object(self.ctx, "_start_net_job", side_effect=start):
            q = self.query(airports="FRA,BCN", base="FRA", fleet="2", util_h="300",
                           freqs="FRA-BCN:14", **extra)
            if automatic:
                q.pop("lease_observation", None)
            return self.ctx.network(q)

    @unittest.skipUnless(importlib.util.find_spec("openap"), "openap не установлен")
    def test_auto_network_cache_age_source_zero_and_report(self):
        self.prepare_aircraft()
        obs = self.accepted()
        selected = self.network_result(automatic=True, age="12")
        self.assertIsNone(selected["error"])
        self.assertEqual(selected["network"]["lease_eur_month"], 100000)
        self.assertEqual(selected["network"]["lease_observation"]["id"], prices.observation_id(obs))
        revised = self.accepted(month="2026-11", value=150, source="https://example.test/network-revised.pdf")
        changed = self.network_result(automatic=True, age="12")
        self.assertEqual(changed["network"]["lease_eur_month"], 110000)
        self.assertIn(prices.observation_id(revised), [o["id"] for o in changed["network"]["lease_observation"]["sources"]])
        self.doc["observations"].remove(revised)
        same_amount = self.accepted(month="2026-11", value=150,
                                    source="https://example.test/same-amount-new-source.pdf")
        refreshed = self.network_result(automatic=True, age="12")
        self.assertEqual(refreshed["network"]["lease_eur_month"], 110000)
        self.assertIn(prices.observation_id(same_amount), [o["id"] for o in refreshed["network"]["lease_observation"]["sources"]])
        fallback = self.network_result(automatic=True, age="11")
        self.assertNotIn("lease_observation", fallback["network"])
        zero = self.network_result(automatic=True, age="12", lease="0")
        self.assertEqual(zero["network"]["lease_eur_month"], 0)
        self.assertFalse(zero["network"]["lease_observation"]["applied"])
        q = {"ac": "CRJ9", "types": "CRJ9", "airports": "FRA,BCN", "base": "FRA", "fleet": "2", "mode": "fleet"}
        with mock.patch.object(self.ctx, "_net_by_type", return_value=({"CRJ9": changed}, {"types_left": 0}, [])), \
                mock.patch.object(self.ctx, "aircraft", return_value=[{"icao": "CRJ9", "name": "CRJ900"}]):
            report, _ = self.ctx.fleet_report(q)
        self.assertIn(prices.observation_id(revised), [o["id"] for o in report["types"][0]["lease_observation"]["sources"]])
        self.assertEqual(report["types"][0]["lease_eur_month"], 110000)
        from flightcostapp.fleetreport_doc import render
        html = render(report)
        self.assertIn(revised["source"], html)
        self.assertIn("2026-11", html)
        self.assertIn("1 EUR = 1.25 USD", html)

    def test_network_midpoint_profit_manual_zero_and_cache_metadata(self):
        selected = self.network_result()
        self.assertIsNone(selected["error"])
        self.assertEqual(selected["network"]["lease_eur_month"], 86000)
        self.assertTrue(selected["network"]["lease_observation"]["applied"])
        self.assertEqual(serve.Context._net_summary("CRJ9", selected, True)["lease_observation"]["id"], self.id)
        zero = self.network_result(lease="0")
        self.assertEqual(zero["network"]["lease_eur_month"], 0)
        self.assertFalse(zero["network"]["lease_observation"]["applied"])
        self.assertEqual(fleetreport.TypePlan("CRJ9", zero).lease, 0)
        self.assertAlmostEqual(zero["network"]["profit_at_ref"] - selected["network"]["profit_at_ref"], 172000)
        other = {**OBS, "source": "https://example.test/another-accepted.pdf"}
        self.doc["observations"].append(other)
        oid = prices.observation_id(other)
        again = self.network_result(lease_observation=oid)
        self.assertEqual(again["fleet"]["lease_observation"]["id"], oid)
        self.assertEqual(selected["fleet"]["lease_observation"]["id"], self.id)
        self.assertTrue(all(not hasattr(value[1], "lease_observation") for value in self.ctx._net_cache.values()))
        # Числовой 0 тоже является ручным вводом; FX для него не нужен.
        no_fx = self.network_result(lease=0, as_of="2020-01-01")
        self.assertIsNone(no_fx["error"])
        self.assertEqual(no_fx["network"]["lease_eur_month"], 0)

    def test_fleet_report_keeps_midpoint_source_and_manual_zero(self):
        for manual, expected in ((None, 86000), ("0", 0)):
            result = self.network_result(**({"lease": manual} if manual is not None else {}))
            q = self.query(types="CRJ9", airports="FRA,BCN", base="FRA", fleet="2", mode="fleet")
            with mock.patch.object(self.ctx, "_net_by_type", return_value=({"CRJ9": result}, {"types_left": 0}, [])), \
                    mock.patch.object(self.ctx, "aircraft", return_value=[{"icao": "CRJ9", "name": "CRJ900"}]):
                rep, _ = self.ctx.fleet_report(q)
            with self.subTest(manual=manual):
                self.assertNotIn("error", rep)
                row = rep["types"][0]
                self.assertEqual(row["lease_eur_month"], expected)
                self.assertEqual(row["lease_observation"]["id"], self.id)
                self.assertEqual(row["lease_observation"]["applied"], manual is None)
                self.assertEqual(rep["context"]["inputs"]["lease_observation"]["id"], self.id)

    def test_network_comparison_clears_selection_for_foreign_type(self):
        with mock.patch.object(self.ctx, "network", return_value={}) as call:
            self.ctx._net_by_type(self.query(lease="0"), "CRJ9", ["CRJ9", "A320"])
        own, other = (x.args[0] for x in call.call_args_list)
        self.assertEqual(own["lease_observation"], self.id)
        self.assertEqual(own["lease"], "0")
        self.assertNotIn("lease_observation", other)
        self.assertNotIn("lease", other)

    def test_route_comparison_keeps_selection_override(self):
        with mock.patch.object(self.ctx, "_compare_type", return_value={"status": "ok"}) as compare:
            self.ctx.compare(self.query(origin="FRA", destination="BCN", types="CRJ9", pax="50",
                                        set="charge_context.EDDF.noise_cat=3"))
        kw = compare.call_args.args[2]
        self.assertEqual(kw["overrides"][KEY], 86000)
        self.assertNotIn("charge_context.EDDF.noise_cat", kw["overrides"])


@unittest.skipUnless(shutil.which("node"), "node не установлен")
class LeaseSelectionFrontend(unittest.TestCase):
    def test_real_frontend_functions_keep_id_and_clear_on_type_change(self):
        html = (Path(serve.WEB) / "serve.html").read_text("utf-8")
        def function(name):
            start = html.index(f"function {name}(")
            return html[start:html.index("\n}", start) + 2]
        funcs = "\n".join(function(n) for n in ("leaseObservationId", "setLeaseObservation",
            "leaseObservationNotice", "leaseOrigin", "setAircraftAge", "setAc", "params", "netParams", "netState"))
        self.assertIn('id="nage" type="number"', html)
        script = r'''
const assert = require("node:assert/strict");
const CHOSEN = {ac:"CRJ9", o:"FRA", d:"BCN", op:"*"};
const ACS = [{icao:"CRJ9",usable:true},{icao:"A320",usable:true}];
let LEASE_OBSERVATION = null, FBENCH = null;
const NET = {on:false,airports:["FRA","BCN"],base:"FRA",fares:{},market:{},freqs:{},tset:{},cmp:{types:[]},rep:{}};
const ctxVal = {}, CUR = {code:"EUR"};
const location = {href:"https://flightcost.app/ru/calc?ac=CRJ9&o=EDDF&mode=net"};
const history = {replaceState(a,b,url){location.href=String(url);}};
const nodes = {};
function $(key){
  return nodes[key] ||= {value:"",placeholder:"",options:[1],open:false,content:{},button:{},
    querySelector(selector){return selector === ".note" ? this.content : this.button;}};
}
const _t=x=>x, esc=x=>String(x??""), escA=esc, f0=x=>String(x), m0=x=>String(x), toEur=Number;
const seatsParam=()=>"", acLabel=t=>t.icao, acTier=()=>"", markClear=()=>{}, drawLayouts=()=>{}, benchLoad=()=>{}, netChips=()=>{}, pairsQ=()=>"";
let redraws=0; const draw=()=>{redraws++;}, netSoft=()=>{redraws++;};
'''
        script += funcs + "\nconst id = " + json.dumps(prices.observation_id(OBS)) + ";\n"
        script += r'''
$("#acage").value="12"; $("#month").value="5";
setLeaseObservation(id);
assert.equal(params().get("lease_observation"), id);
assert.equal(netParams().get("lease_observation"), id);
assert.equal(netState().lease_observation, id);
assert.equal($("#acage").value, "12"); assert.equal($("#month").value, "5");
$("#lease").value="0"; $("#nlease").value="0";
assert.match(params().get("set"), /lease_eur_month=0/);
assert.equal(netParams().get("lease"), "0");
assert.equal(params().get("lease_observation"), id);
leaseObservationNotice({id,icao:"CRJ9",month:"2022-07",age:null,low:100000,high:115000,midpoint:107500,currency:"USD",lease_eur_month:86000,applied:false,fx:{rate:1.25,date:"2026-11-09",source:"fx_rates"},source:"https://example.test/a.pdf",note:"stored aircraft"});
assert.equal($("#leaseobs").open, false);
$("#leaseobs").open = true;
leaseObservationNotice();
assert.equal($("#leaseobs").open, true);
assert.match($("#leaseobs").content.innerHTML, /2022-07/);
assert.match($("#leaseobs").content.innerHTML, /возраст не указан/);
assert.match($("#leaseobs").content.innerHTML, /Применяется ручная ставка/);
assert.match($("#leaseobs").content.innerHTML, /2026-11-09/);
assert.equal(leaseOrigin({lease_prov:"override",lease_observation:{applied:true}}), "из публикации");
assert.equal(leaseOrigin({lease_prov:"input",lease_observation:{applied:false}}), "задано");
setAc("CRJ9"); assert.equal(leaseObservationId(), id);
setAc("A320");
assert.equal(leaseObservationId(), "");
assert.equal(params().has("lease_observation"), false);
assert.equal(netParams().has("lease_observation"), false);
assert.equal(new URL(location.href).searchParams.has("lease_observation"), false);
assert.equal(new URL(location.href).searchParams.get("ac"), "A320");
assert.equal(new URL(location.href).searchParams.get("o"), "EDDF");
assert.equal(new URL(location.href).searchParams.get("mode"), "net");
assert.equal($("#leaseobs").hidden, true);
assert.equal($("#leaseobs").open, false);
setAc("CRJ9"); setLeaseObservation(id); $("#leaseobs").button.onclick();
assert.equal(leaseObservationId(), ""); assert.equal(redraws, 1);
$("#lease").value="";
leaseObservationNotice({id,icao:"CRJ9",automatic:true,applied:true,month:"2026-10",age:12,low:125000,high:125000,midpoint:125000,currency:"USD",lease_eur_month:100000,fx:{rate:1.25,date:"2026-11-09",source:"fx_rates"},source:"https://example.test/current.pdf",publisher:"Published Appraiser"});
assert.equal($("#leaseobs").hidden, false);
assert.match($("#leaseobs").content.innerHTML, /2026-10/);
assert.match($("#leaseobs").content.innerHTML, /1 EUR = 1.25 USD/);
assert.match($("#leaseobs").content.innerHTML, /current.pdf/);
assert.match($("#leaseobs").content.innerHTML, />Published Appraiser<\/a>/);
assert.doesNotMatch($("#leaseobs").content.innerHTML, /<button/);
assert.equal(leaseObservationId(), "");
assert.equal(params().has("lease_observation"), false);
assert.equal(netParams().get("age"), "12");
assert.equal(netState().age, "12");
setAircraftAge(0);
assert.equal($("#nage").value, "0"); assert.equal($("#acage").value, "0");
assert.equal(params().get("age"), "0"); assert.equal(netParams().get("age"), "0");
assert.equal(netState().age, "0");
setAircraftAge(null);
assert.equal($("#nage").value, ""); assert.equal($("#acage").value, "");
assert.equal(netParams().get("age"), "");
leaseObservationNotice(); assert.equal($("#leaseobs").hidden, true);
'''
        result = subprocess.run([shutil.which("node"), "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
