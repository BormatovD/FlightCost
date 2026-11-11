#!/usr/bin/env python3
"""Audit the existing-model overlay without importing its producer or fleet code.

Reads the pinned OpenAP YAML files and accepted aircraft cards directly. Formula
constants are independently checked in the production AST. USD display values
are recalculated from the CPI table, not by calling the production SEO helper.
"""
import argparse
import ast
import hashlib
import json
import math
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
INPUT = HERE.parent / "out/model_reference.json"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def literals(path, wanted):
    found = {}
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in wanted:
                    found[target.id] = ast.literal_eval(node.value)
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--openap-root", type=Path, required=True)
    args = parser.parse_args()
    d = json.loads(INPUT.read_text())
    constants = literals(ROOT / "flightcostapp/fleet.py", {"DEFAULTS", "GENERATIONS", "NEW_GENERATION"})
    defaults, generations, new_codes = (constants[k] for k in ("DEFAULTS", "GENERATIONS", "NEW_GENERATION"))
    cpi = yaml.safe_load((ROOT / "data/macro/_us_cpi.yaml").read_text())["years"]
    last = max(cpi)
    growth = cpi[last] / cpi[last - 1]
    ix = lambda y: cpi[y] if y in cpi else cpi[last] * growth ** (y - last)
    failures, checked = [], []

    def same(name, actual, expected):
        checked.append(name)
        ok = (math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-7)
              if isinstance(actual, (float, int)) and not isinstance(actual, bool)
              and isinstance(expected, (float, int)) and not isinstance(expected, bool)
              else actual == expected)
        if not ok:
            failures.append({"check": name, "independent": actual, "stored": expected})

    same("formula_reference_mass", defaults["lease_ref_mtow_t"], 78.0)
    same("formula_exponent", defaults["lease_mtow_exponent"], 1.10)
    same("current_reference", generations["current"]["lease_ref_eur_month"], 200000.)
    same("new_reference", generations["new"]["lease_ref_eur_month"], 345000.)
    for rel, recorded in d["meta"]["inputs_sha256"].items():
        same("repository_sha:" + rel, sha(ROOT / rel), recorded)
    for rel, recorded in d["meta"]["openap_package_inputs_sha256"].items():
        same("package_sha:" + rel, sha(args.openap_root / rel), recorded)
    for key in ("lease_uses_seats", "lease_uses_segment_coefficient", "lease_uses_continuous_age_curve", "purchase_price_model_available"):
        same("semantic_flag:" + key, False, d["meta"][key])
    hist = d["meta"]["historical_display"]
    same("display_fixed_fx", 1.16, hist["usd_per_eur"])
    same("display_base_year", 2026, hist["base_year"])
    same("display_last_cpi_year", last, hist["cpi_last_observed_year"])
    same("display_cpi_growth", growth, hist["cpi_last_annual_growth_factor"])
    same("display_cpi_base", ix(2026), hist["cpi_base_year_value"])
    same("display_base_cpi_extrapolated", 2026 not in cpi, hist["cpi_base_year_is_extrapolated"])
    fx = json.loads((ROOT / "research/_fx.json").read_text())
    same("separate_research_fx", fx["rates"]["USD"], hist["research_currency_widget_usd_per_eur"])
    same("separate_research_fx_date", fx["as_of"], hist["research_currency_widget_as_of"])
    history = json.loads((HERE.parent / "out/segments_history.json").read_text())
    same("same_selection", sorted(a["icao"] for a in history["aircraft"]), sorted(a["icao"] for a in d["aircraft"]))
    same("type_count", len(d["aircraft"]), 15)
    same("unique_types", len({a["icao"] for a in d["aircraft"]}), 15)
    same("segments", history["segments"], d["segments"])
    samples = []
    point_count = 0
    for row in d["aircraft"]:
        code = row["icao"]
        info = row["aircraft_input"]
        if info["source"] == "aircraft_openap":
            path = args.openap_root / info["package_path"]
            raw = yaml.safe_load(path.read_text())
            mass = raw["mtow"] / 1000
            seats = raw["pax"]["high"] or raw["pax"]["max"]
        elif info["source"] == "aircraft_catalog":
            path = ROOT / info["repository_path"]
            raw = json.loads(path.read_text())
            fields = raw["fields"]
            mass = fields["mtow_t"]
            seats = fields.get("seats_typical") or fields["seats_max"]
            same(code + ":no_card_lease_override", False, "fleet_lease_eur_month" in fields)
        else:
            failures.append({"check": code + ":known_input_source", "stored": info["source"]})
            continue
        same(code + ":source_sha", sha(path), info["sha256"])
        same(code + ":mtow", mass, row["mtow_t"])
        same(code + ":seats", seats, row["seats_for_public_default"])
        generation = "new" if code in new_codes else "current"
        age = 0 if generation == "new" else 12
        rent = generations[generation]["lease_ref_eur_month"] * math.exp(1.1 * math.log(mass / 78))
        for name, actual in {
            "generation": generation,
            "generation_label_ru": generations[generation]["label"],
            "model_age_years": age,
            "model_age_is_approximate": age != 0,
            "model_age_is_continuous_input": False,
            "comparable_with_new_aircraft": age == 0,
            "reference_lease_eur_month": generations[generation]["lease_ref_eur_month"],
            "raw_parametric_lease_eur_month": rent,
            "effective_public_default_lease_eur_month": rent,
            "effective_public_default_provenance": "default",
            "effective_public_default_source": None,
            "public_default_equals_raw_parametric": True,
            "purchase_price_reference": None,
            "market_observation_selected": False,
        }.items():
            same(code + ":" + name, actual, row[name])
        same(code + ":years", list(range(2016, 2027)), [p["year"] for p in row["nominal_usd_points"]])
        for p in row["nominal_usd_points"]:
            year = p["year"]
            usd = rent * 1.16 * ix(year) / ix(2026)
            for name, actual in {"x": year + .5, "lease_usd_month": usd, "lease_thousand_usd_month": usd / 1000,
                                 "cpi": ix(year), "cpi_extrapolated": year not in cpi}.items():
                same(f"{code}:{year}:{name}", actual, p[name])
            point_count += 1
        samples.append({"icao": code, "mtow_t": mass, "model_age_years": age,
                        "lease_eur_month_independent": rent, "lease_usd_2026_month_independent": rent * 1.16,
                        "new_aircraft_comparable": age == 0})
    same("new_age_count", sum(s["new_aircraft_comparable"] for s in samples), d["meta"]["new_aircraft_comparable_count"])
    result = {
        "stage": "0056-v2", "status": "pass" if not failures else "fail", "independent": True,
        "input_sha256": sha(INPUT), "check_count": len(checked), "aircraft_count": len(samples),
        "annual_points_checked": point_count, "checks": checked, "samples": samples, "failures": failures,
        "method": "Direct YAML/JSON input reading; AST constant check; independent logarithmic mass formula and explicit CPI ratios. No producer, fleet or SEO function imported.",
        "manual_code_review": [
            "ICAO selects a generation group; lease does not use a segment coefficient or passenger-seat count.",
            "The current generation uses an approximate age-12 basis. AT46/AT76 are current under the actual code despite the -600 name; no new-aircraft reinterpretation was made.",
            "fleet.load gives explicit scenario overrides priority, then fleet_economics values and aircraft-card values before the parametric fallback. Live server-only or operator-specific overrides are not established by this public snapshot.",
            "The age argument changes the maintenance layer, not a continuous lease age curve.",
            "serve.py can explicitly select a market observation midpoint; it must not become an independent model comparator for the same market data.",
            "The purchase price is not predicted by the production fleet formula; the article's hypothetical asset-NPV exercise is a separate research calculation.",
            "The 1.16 USD/EUR comparator convention differs from the separate research currency widget snapshot. CPI restatement is not a lease price index or a historical prediction."
        ],
        "limitations": [
            "Verification reproduces current public calculator input conventions, not an independent aircraft certificate audit or commercial rent appraisal.",
            "2026 CPI is extrapolated from the final 2025 annual growth rate, not a final observed annual CPI value.",
            "An age-12 contextual curve and new-aircraft observations do not support a like-for-like pricing-error claim.",
            "The benchmark has not been calibrated to the article's market observations."
        ]
    }
    (HERE / "model_reference_0056_v2.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(result["status"], len(checked), "checks;", point_count, "annual values; failures:", failures)


if __name__ == "__main__":
    main()
