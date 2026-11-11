#!/usr/bin/env python3
"""Independent audit of the 0057 dated lease anchors and generated chart markup.

Does not import the calibration producer, model-card renderer, fleet calculator,
or its USD-display helper. Source rents below were rechecked in the two primary
publications on 2026-11-11. Aircraft masses are read from source cards/OpenAP.
"""
from __future__ import annotations

import argparse
import ast
from collections import defaultdict
import hashlib
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re

import yaml

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
ROOT = HERE.parents[2]
SELECTED = {
    "turboprop": ["AT46", "AT76"], "regional": ["E75L", "E295"],
    "narrowbody": ["A20N", "A21N"], "widebody": ["A359", "B789"],
}
IBA = "https://iclg.com/practice-areas/aviation-finance-and-leasing/02-the-aviation-finance-market-robust-demand-entrenched-supply-chain-challenges-and-strong-market-performance/"
ORIEL = "https://www.istat.org/ISTAT-Online/ISTAT-Online/Aircraft-Supporting-Assets/ArtMID/1205/ArticleID/1697/Appraisal-Embraer-E-Jet-E2"
RECHECKED = {
    "E295": (285000, 285000, "2026", "year", ORIEL, "market_monthly_lease"),
    "A20N": (395000, 424000, "2026-Q1", "quarter", IBA, "lessee_credit_range"),
    "A21N": (456000, 488000, "2026-Q1", "quarter", IBA, "lessee_credit_range"),
    "A359": (1190000, 1250000, "2026-Q1", "quarter", IBA, "market_monthly_lease"),
    "B789": (1070000, 1150000, "2026-Q1", "quarter", IBA, "market_monthly_lease"),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def constants(path, names):
    out = {}
    for node in ast.parse(path.read_text()).body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in names:
                out[target.id] = ast.literal_eval(node.value)
            elif isinstance(target, ast.Tuple):
                keys = [v.id for v in target.elts if isinstance(v, ast.Name)]
                if len(keys) == len(target.elts) and any(k in names for k in keys):
                    out.update({k: v for k, v in zip(keys, ast.literal_eval(node.value)) if k in names})
    return out


class Markup(HTMLParser):
    """Minimal element tree for auditable chart attributes, not browser layout."""
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root = {"tag": "root", "attrs": {}, "children": [], "text": ""}
        self.stack = [self.root]
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": dict(attrs), "children": [], "text": "", "parent": self.stack[-1]}
        self.stack[-1]["children"].append(node)
        if tag not in {"meta", "link", "br", "hr", "img", "input", "source", "wbr"}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = {"tag": tag, "attrs": dict(attrs), "children": [], "text": "", "parent": self.stack[-1]}
        self.stack[-1]["children"].append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        for node in self.stack:
            node["text"] += data


def elements(node, cls=None, tag=None):
    found = []
    for child in node["children"]:
        if (not cls or cls in child["attrs"].get("class", "").split()) and (not tag or child["tag"] == tag):
            found.append(child)
        found.extend(elements(child, cls, tag))
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--openap-root", type=Path, required=True)
    ap.add_argument("--html", action="store_true", help="Audit all three generated reports after rebuilding")
    args = ap.parse_args()
    d = json.loads((RESEARCH / "out/lease_calibration.json").read_text())
    ref = json.loads((RESEARCH / "out/model_reference.json").read_text())
    history = json.loads((RESEARCH / "out/segments_history.json").read_text())
    models = {a["icao"]: a for a in ref["aircraft"]}
    observations = {o["id"]: o for o in history["observations"]}
    fc = constants(ROOT / "flightcostapp/fleet.py", {"DEFAULTS", "GENERATIONS", "NEW_GENERATION"})
    sc = constants(ROOT / "flightcostapp/seo.py", {"PARAM_USD_PER_EUR", "PARAM_YEAR"})
    fx = json.loads((ROOT / "research/_fx.json").read_text())
    cpi = yaml.safe_load((ROOT / "data/macro/_us_cpi.yaml").read_text())["years"]
    last_cpi = max(cpi)
    cpi_growth = cpi[last_cpi] / cpi[last_cpi-1]
    ix = lambda year: cpi[year] if year in cpi else cpi[last_cpi] * cpi_growth ** (year-last_cpi)
    checks, failures, samples = [], [], []

    def eq(name, got, want, tol=1e-10):
        checks.append(name)
        numeric = isinstance(got, (int, float)) and not isinstance(got, bool) and isinstance(want, (int, float)) and not isinstance(want, bool)
        passed = math.isclose(got, want, rel_tol=tol, abs_tol=1e-7) if numeric else got == want
        if not passed:
            failures.append({"check": name, "observed": got, "expected": want})

    eq("production_fx", sc["PARAM_USD_PER_EUR"], 1.16)
    eq("production_base_year", sc["PARAM_YEAR"], 2026)
    eq("mass_reference", fc["DEFAULTS"]["lease_ref_mtow_t"], 78.0)
    eq("mass_exponent", fc["DEFAULTS"]["lease_mtow_exponent"], 1.1)
    eq("selected_types", {x["id"]: x["types"] for x in d["segments"]}, SELECTED)
    eq("five_eligible_types", sorted(a["icao"] for a in d["aircraft"] if a["calibration"]["multiplier_mid"] is not None), sorted(RECHECKED))
    for rel, expected in d["meta"]["inputs_sha256"].items():
        eq("producer_input_sha:"+rel, sha(RESEARCH/rel), expected)
    rents = {}
    for a in d["aircraft"]:
        code, c, anchor = a["icao"], a["calibration"], a["anchor_observation"]
        inp = models[code]["aircraft_input"]
        if inp["source"] == "aircraft_catalog":
            path = ROOT / inp["repository_path"]
            mass = json.loads(path.read_text())["fields"]["mtow_t"]
        else:
            path = args.openap_root / inp["package_path"]
            mass = yaml.safe_load(path.read_text())["mtow"] / 1000
        eq(code+":input_sha", sha(path), inp["sha256"])
        generation = "new" if code in fc["NEW_GENERATION"] else "current"
        age = 0 if generation == "new" else 12
        base = fc["GENERATIONS"][generation]["lease_ref_eur_month"]
        rent = base * math.exp(1.1 * math.log(mass/78.0))
        rents[code] = rent
        eq(code+":mass", a["mtow_t"], mass)
        eq(code+":model_age", a["raw_model_age_years"], age)
        eq(code+":eur_rent", a["raw_lease_eur_2026_month"], rent)
        eq(code+":usd_rent", a["raw_lease_usd_2026_month"], rent*1.16)
        source = observations[c["source_observation_id"]]
        eq(code+":stored_source_link", c["source_url"], source["source_url"])
        eq(code+":source_new", source["age"]["years"], 0)
        eq(code+":no_calibrated_history", c["annual_points"], [])
        for key in ("historical_backcast_allowed", "future_extrapolation_allowed", "independently_validated", "production_changed", "range_is_confidence_interval"):
            eq(code+":"+key, c[key], False)
        eq(code+":no_age_curve", a["age_curve_fitted"], False)
        eq(code+":no_age_extrapolation", a["age_extrapolation_allowed"], False)
        before = rent * 1.16 * ix(int(c["period"][:4])) / ix(2026)
        eq(code+":same_year_before", c["model_before_usd_month"], before)
        if code in RECHECKED:
            lo, hi, period, precision, url, basis = RECHECKED[code]
            for key, expected in {"amount_low_usd":lo, "amount_high_usd":hi, "period":period, "period_precision":precision, "source_url":url, "valuation_basis":basis}.items():
                eq(code+":primary_source:"+key, anchor[key], expected)
            eq(code+":comparable_age", age, 0)
            eq(code+":calibration_age", c["age_years"], age)
            mid = (lo+hi)/2
            for key, expected in {
                "amount_mid_usd":mid, "multiplier_low":lo/before, "multiplier_mid":mid/before,
                "multiplier_high":hi/before, "change_pct":100*(mid/before-1),
                "calibrated_lease_eur_2026_month":mid/1.16,
                "display_span_x":[2026., 2027.] if precision == "year" else [2026.,2026.25],
            }.items():
                eq(code+":calculation:"+key, c[key], expected)
            samples.append({"icao":code,"mass_t":mass,"age":age,"period":period,"before_usd_month":before,
                            "source_low_usd":lo,"source_high_usd":hi,"midpoint_usd":mid,"factor":mid/before,"change_pct":100*(mid/before-1)})
        else:
            eq(code+":mismatch_status", c["status"], "unavailable_age_mismatch")
            for key in ("amount_low_usd", "amount_high_usd", "amount_mid_usd", "multiplier_low", "multiplier_high", "multiplier_mid", "age_years", "calibrated_lease_eur_2026_month", "display_span_x"):
                eq(code+":no_false_correction:"+key, c[key], None)

    diagnostic = d["temporal_diagnostic"]
    eq("diagnostic_no_validation_claim", diagnostic["current_coefficients_validated"], False)
    eq("diagnostic_label", diagnostic["status"], "retrospective_diagnostic_not_operational_backtest")
    eq("diagnostic_rows", len(diagnostic["rows"]), 16)
    for row in diagnostic["rows"]:
        prev, actual = observations[row["training_observation_id"]], observations[row["target_observation_id"]]
        code = row["icao"]
        y0, y1 = int(prev["period"][:4]), int(actual["period"][:4])
        tag = code+":"+row["target_period"]
        eq(tag+":one_year", y1-y0, 1)
        eq(tag+":same_series", prev["series_key"], actual["series_key"])
        eq(tag+":new", (prev["age"]["years"],actual["age"]["years"]), (0,0))
        eq(tag+":past_anchor", y1 <= 2020, True)
        prev_mid = (prev["amount_low_usd"]+prev["amount_high_usd"])/2
        actual_mid = (actual["amount_low_usd"]+actual["amount_high_usd"])/2
        eq(tag+":actual", row["actual_usd_month"], actual_mid)
        eq(tag+":nominal", row["last_anchor_nominal_usd_month"], prev_mid)
        eq(tag+":cpi", row["last_anchor_cpi_usd_month"], prev_mid*ix(y1)/ix(y0))
        eq(tag+":old_model", row["old_model_usd_month"], rents[code]*1.16*ix(y1)/ix(2026))
    for cohort, stats in diagnostic["metrics"].items():
        rr = [x for x in diagnostic["rows"] if cohort == "all_2017_2020" or (cohort == "pandemic_2020") == x["target_period"].startswith("2020")]
        for field, result in stats.items():
            errors = [x[field]-x["actual_usd_month"] for x in rr]
            denom = sum(x["actual_usd_month"] for x in rr)
            for key, expected in {"n":len(rr), "wape":sum(map(abs,errors))/denom,
                                  "signed_bias":sum(errors)/denom,"mae_usd_month":sum(map(abs,errors))/len(rr)}.items():
                eq(cohort+":"+field+":"+key,result[key],expected)

    ex = json.loads((RESEARCH/"out/summary.json").read_text())["example"]
    eq("flight_fx_snapshot", ex["fx"]["usd_per_eur"], fx["rates"]["USD"])
    eq("separate_fx_in_metadata",d["meta"]["cpi_and_fx_convention"]["research_currency_widget_usd_per_eur"],1.113)
    q = ex["anchor"]["midpoint_usd_month"]
    ownership = q/fx["rates"]["USD"]*ex["inputs"]["block_hours"]/ex["inputs"]["monthly_hours"]
    eq("flight_example_midpoint", ex["research_ownership_eur_flight_midpoint"], ownership)
    fx_comparison = {"chart_usd_per_eur":1.16,"flight_example_usd_per_eur":fx["rates"]["USD"],
                     "a20n_chart_change_pct":100*(q/(rents["A20N"]*1.16)-1),
                     "a20n_flight_scenario_change_pct":100*(q/(rents["A20N"]*fx["rates"]["USD"])-1),
                     "same_market_midpoint_usd":q,"explanation":"Different declared FX scenarios; not two market-error estimates."}
    quote_words = defaultdict(int)
    for path in (RESEARCH/"trace").glob("*.jsonl"):
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if row.get("url") in (IBA,ORIEL):
                quote_words[row["url"]] += len(row.get("quote", "").split())
    for url, count in quote_words.items():
        eq("quote_budget:"+url, count <= 25, True)

    html_results = []
    if args.html:
        bycal = {a["icao"]:a["calibration"] for a in d["aircraft"]}
        for name in ("report.html", "report.en.html", "report.de.html"):
            path = RESEARCH/name
            dom = Markup(path.read_text()).root
            charts = elements(dom,"segment-history","svg")
            eq(name+":eight_charts",len(charts),8)
            for chart in charts:
                attrs = chart["attrs"]
                kind, segment = attrs["data-kind"],attrs["data-segment"]
                tag = name+":"+segment+":"+kind
                refs = elements(chart,"model-reference","polyline")
                cards = elements(chart,"model-card","g")
                corrections = elements(chart,"model-correction","g")
                expected_codes = SELECTED[segment] if kind == "lease" else []
                eq(tag+":model_types",[a["attrs"]["data-icao"] for a in refs],expected_codes)
                card_order = sorted(expected_codes, key=lambda code: models[code]["nominal_usd_points"][-1]["lease_usd_month"], reverse=True)
                eq(tag+":cards_follow_line_height",[a["attrs"]["data-icao"] for a in cards],card_order)
                eq(tag+":corrections",sorted(a["attrs"]["data-icao"] for a in corrections),sorted(c for c in expected_codes if c in RECHECKED))
                for curve in refs:
                    aa=curve["attrs"]; code=aa["data-icao"]
                    points=[tuple(map(float,x.split(','))) for x in aa["points"].split()]
                    eq(tag+":"+code+":eleven_original_points",len(points),11)
                    eq(tag+":"+code+":original_only",aa["data-reference-role"],"raw_parametric")
                    eq(tag+":"+code+":age",int(aa["data-model-age-years"]),models[code]["model_age_years"])
                    eq(tag+":"+code+":right_space",points[-1][0]<700,True)
                for mark in corrections:
                    aa=mark["attrs"]; code=aa["data-icao"]
                    eq(tag+":"+code+":mark_period",aa["data-period"],bycal[code]["period"])
                    eq(tag+":"+code+":mark_factor",float(aa["data-multiplier"]),bycal[code]["multiplier_mid"])
                    eq(tag+":"+code+":mark_not_validation",aa["data-independent-validation"],"false")
                    for node in elements(mark,tag="path"):
                        x1,_,x2=map(float,re.findall(r'-?\d+(?:\.\d+)?',node['attrs']['d']))
                        eq(tag+":"+code+":mark_not_historical",x1>=640,True)
                        eq(tag+":"+code+":source_period_only",x2-x1<=59,True)
                if kind == "value":
                    parent=chart.get("parent"); detail=None
                    while parent:
                        if parent["tag"]=="details" and "purchase-history" in parent["attrs"].get("class","").split():
                            detail=parent;break
                        parent=parent.get("parent")
                    eq(tag+":collapsed_purchase",detail is not None and "open" not in detail["attrs"],True)
            html_results.append({"file":name,"sha256":sha(path),"charts":len(charts),"model_cards":len(elements(dom,"model-card","g")),"source_correction_marks":len(elements(dom,"model-correction","g"))})

    result={"stage":"0057","status":"pass_with_limitations" if not failures else "fail","independent":True,
            "checked_at":"2026-11-11","input_sha256":{str(x.relative_to(ROOT)):sha(x) for x in (RESEARCH/'lease_calibration.py',RESEARCH/'out/lease_calibration.json',RESEARCH/'out/model_reference.json',RESEARCH/'model_cards.py',RESEARCH/'report_extensions.py')},
            "checks_count":len(checks),"samples":samples,"fx_scenarios":fx_comparison,
            "source_rechecks":[{"url":IBA,"checked":"Four new-aircraft ranges, Q1 context and credit-range basis; no new quotations added."},{"url":ORIEL,"checked":"E195-E2 new rent 285000 USD/month; year resolution retained, source dated 2026-03-12; no new quotations added."}],
            "trace_quote_word_counts":dict(quote_words),"html":html_results,"failures":failures,
            "method":"Direct source masses and production AST constants; independent exponential form, source-bound midpoint ratios and CPI arithmetic; primary pages reopened. No producer or renderer imported.",
            "limitations":["Matching a source by construction is not independent predictive validation.","ATR/E175 corrections deliberately unavailable because new-aircraft points differ from the approximately age-12 production basis.","Historical diagnostic uses current-vintage full-year CPI and a present-day model, so it is not a real-time out-of-sample backtest.","Prior AVAC historical source audits are inherited; this audit rechecks their diagnostic arithmetic, not every historical source PDF.","Markup audit is not browser layout/interaction verification.","The current public snapshot does not establish private/server/operator overrides."]}
    (HERE/'calibration_0057.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({"status":result["status"],"checks":len(checks),"samples":samples,"html":html_results,"failures":failures},ensure_ascii=False))
    raise SystemExit(bool(failures))


if __name__ == "__main__":
    main()
