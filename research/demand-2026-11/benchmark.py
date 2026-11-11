#!/usr/bin/env python3
"""Reproducible, deliberately limited benchmark of annual airport-pair traffic.

This is a research baseline, not a copy of the calculator's P/T/F models.
No network access; all inputs are pinned repository aggregates or a dated
World Bank covariate extract. Targets are carried passengers in both directions
per year, not unconstrained demand or true passenger origin/destination.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PAIRS = ROOT / "research/routes-2026-11/out/pairs_eu.json"
AIRPORTS = ROOT / "research/routes-2026-11/out/airports.json"
FOLDS = 5
SEED = "flightcost-demand-pairs-v1"


@dataclass(frozen=True)
class Row:
    pair: str
    a: str
    b: str
    country_a: str
    country_b: str
    km: float
    pax: float


def distance(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a[:2], *b[:2]))
    z = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * math.asin(min(1.0, math.sqrt(z)))


def load_rows(data, airports, year):
    rows, excluded = [], Counter()
    for pair, years in sorted(data["pairs"].items()):
        p = (years.get(str(year)) or {}).get("pax")
        if not isinstance(p, (int, float)) or p <= 0:
            excluded["no_positive_annual_observation"] += 1
            continue
        a, b = pair.split("-")
        if a not in airports or b not in airports:
            excluded["missing_coordinates"] += 1
            continue
        km = distance(airports[a], airports[b])
        if km < 100:
            excluded["distance_under_100_km"] += 1
            continue
        rows.append(Row(pair, a, b, airports[a][2], airports[b][2], km, float(p)))
    return rows, dict(excluded)


def fold_of(pair):
    # A pair has exactly one fold for every year and irrespective of file order.
    return int.from_bytes(hashlib.sha256(f"{SEED}/{pair}".encode()).digest()[:8], "big") % FOLDS


def node_totals(rows):
    totals = defaultdict(float)
    for r in rows:
        totals[r.a] += r.pax
        totals[r.b] += r.pax
    return dict(totals)


def features(row, totals, own_flow, income=None, covariate_scope="country"):
    # own_flow is known training/history traffic, never the held-out target.
    a, b = totals.get(row.a, 0.0) - own_flow, totals.get(row.b, 0.0) - own_flow
    if min(a, b) <= 0:
        return None
    ld = math.log(row.km / 1000.0)
    result = [1.0, math.log(a) + math.log(b), ld, ld * ld, float(row.country_a == row.country_b)]
    if income is not None:
        ka, kb = (row.a, row.b) if covariate_scope == "airport" else (row.country_a, row.country_b)
        ga, gb = income.get(ka), income.get(kb)
        if not ga or not gb or min(ga, gb) <= 0:
            return None
        result.append(math.log(ga) + math.log(gb))
    return result


def fit_model(rows, totals, *, income=None, distance_only=False, covariate_scope="country"):
    xs, ys = [], []
    for row in rows:
        x = features(row, totals, row.pax, income, covariate_scope)
        if x is not None:
            xs.append([x[0], *x[2:5]] if distance_only else x)
            ys.append(math.log(row.pax))
    if len(ys) < 20:
        raise ValueError("fewer than 20 training rows with independent endpoint masses")
    X, y = np.array(xs), np.array(ys)
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    # Duan's global retransformation factor, estimated exclusively on training rows.
    smear = float(np.exp(y - X @ coef).mean())
    return coef, len(ys), smear


def predict(coef, x, distance_only=False):
    if distance_only:
        x = [x[0], *x[2:5]]
    return float(math.exp(float(np.dot(coef, x))))


def metrics(records, model):
    values = [(r["actual"], r["predictions"][model]) for r in records if model in r["predictions"]]
    if not values:
        return {"n": 0}
    actual, pred = np.array(values).T
    return {
        "n": len(values),
        "median_factor": float(np.exp(np.median(np.abs(np.log(pred / actual))))),
        "wape_pct": float(np.abs(pred - actual).sum() / actual.sum() * 100),
        "mae_pax_year": float(np.abs(pred - actual).mean()),
        "bias_pct": float((pred - actual).sum() / actual.sum() * 100),
        "within_factor_2_pct": float((np.maximum(pred / actual, actual / pred) <= 2).mean() * 100),
    }


def package(records, models, **extra):
    example = next((r for r in records if r["pair"] == "EDDF-LEBL"), None)
    return {**extra, "n": len(records), "models": {m: metrics(records, m) for m in models}, "example": example}


def forecast(rows23, rows24, incomes=None, extra_name="income", covariate_scope="country"):
    totals = node_totals(rows23)
    history = {r.pair: r for r in rows23}
    inc22, inc23 = (incomes.get("2022", {}), incomes.get("2023", {})) if incomes else (None, None)
    eligible = [r for r in rows23 if features(r, totals, r.pax, inc22, covariate_scope) is not None]
    # When comparing income, refit the baseline on exactly the same training rows.
    models = {"distance": fit_model(eligible, totals, distance_only=True),
              "gravity": fit_model(eligible, totals)}
    if incomes:
        models[f"gravity_{extra_name}"] = fit_model(eligible, totals, income=inc22, covariate_scope=covariate_scope)
    else:
        models["gravity_smearing"] = models["gravity"]
    records, excluded = [], Counter()
    for row in rows24:
        prior = history.get(row.pair)
        if not prior:
            excluded["no_observation_in_2023"] += 1
            continue
        # Use 2023 endpoint totals, subtracting this pair's known 2023 flow.
        x = features(row, totals, prior.pax, inc23, covariate_scope)
        if x is None:
            excluded["no_independent_mass_or_covariate"] += 1
            continue
        preds = {"last_year": prior.pax}
        for model, (coef, _, smear) in models.items():
            mx = x if model == f"gravity_{extra_name}" and incomes else x[:5]
            preds[model] = predict(coef, mx, model == "distance") * (smear if model == "gravity_smearing" else 1)
        records.append({"experiment": f"{extra_name}_forecast" if incomes else "forecast",
                        "pair": row.pair, "year": 2024, "actual": row.pax, "predictions": preds})
    model_info = {k: {"training_n": n, "coefficients": c.tolist(),
                      "smearing_multiplier": smear if k == "gravity_smearing" else 1.0}
                  for k, (c, n, smear) in models.items()}
    return package(records, ["last_year", *models], excluded=dict(excluded), fit=model_info), records


def heldout(rows, income=None, extra_name="income", covariate_scope="country"):
    records, fold_info, excluded = [], [], Counter()
    for fold in range(FOLDS):
        train = [r for r in rows if fold_of(r.pair) != fold]
        test = [r for r in rows if fold_of(r.pair) == fold]
        assert not ({r.pair for r in train} & {r.pair for r in test})
        totals = node_totals(train)      # no held-out pair enters these sums
        eligible = [r for r in train if features(r, totals, r.pax, income, covariate_scope) is not None]
        models = {"distance": fit_model(eligible, totals, distance_only=True),
                  "gravity": fit_model(eligible, totals)}
        if income:
            models[f"gravity_{extra_name}"] = fit_model(eligible, totals, income=income, covariate_scope=covariate_scope)
        else:
            models["gravity_smearing"] = models["gravity"]
        fold_records = []
        for row in test:
            x = features(row, totals, 0.0, income, covariate_scope)  # no test flow subtraction or imputation
            if x is None:
                excluded["endpoint_without_training_mass_or_covariate"] += 1
                continue
            preds = {}
            for model, (coef, _, smear) in models.items():
                mx = x if model == f"gravity_{extra_name}" and income else x[:5]
                preds[model] = predict(coef, mx, model == "distance") * (smear if model == "gravity_smearing" else 1)
            fold_records.append({"experiment": f"{extra_name}_heldout" if income else "heldout",
                                 "pair": row.pair, "year": 2024, "fold": fold,
                                 "actual": row.pax, "predictions": preds})
        records.extend(fold_records)
        fold_info.append({"fold": fold, "training_pairs": len(train), "test_pairs": len(test),
                          "scored_pairs": len(fold_records), "fit_rows": {m: n for m, (_, n, _) in models.items()},
                          "smearing_multiplier": models["gravity"][2] if not income else None,
                          "metrics": {m: metrics(fold_records, m) for m in models}})
    records.sort(key=lambda r: r["pair"])
    return package(records, list(models), folds=FOLDS, excluded=dict(excluded), fold_results=fold_info), records


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def run(out_dir, income_path=None, tourism_path=None):
    pairs, airports = json.loads(PAIRS.read_text()), json.loads(AIRPORTS.read_text())
    r23, ex23 = load_rows(pairs, airports, 2023)
    r24, ex24 = load_rows(pairs, airports, 2024)
    fc, fc_records = forecast(r23, r24)
    ho, ho_records = heldout(r24)
    records = fc_records + ho_records
    inputs = [{"path": str(p.relative_to(ROOT)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
              for p in (PAIRS, AIRPORTS)]
    summary = {
        "schema_version": 1, "generated_on": "2026-11-11",
        "status": "first_research_benchmark_not_production_validation",
        "inputs": inputs, "target": "carried_passengers_both_directions_per_year",
        "coverage": {"pairs_in_source": len(pairs["pairs"]), "airports_in_reference": len(airports),
                     "last_source_month": pairs["last_month"], "eligible_2023": len(r23), "eligible_2024": len(r24),
                     "excluded_2023": ex23, "excluded_2024": ex24},
        "protocol": {"folds": FOLDS, "seed": SEED, "fold": "sha256(seed/pair), first 8 bytes unsigned big endian, modulo 5",
                     "features": ["intercept", "ln(training_mass_A * training_mass_B)", "ln(km/1000)",
                                  "ln(km/1000)^2", "same_country"],
                     "fit": "OLS on log annual passengers; base exp prediction and separate train-only Duan smearing diagnostic",
                     "minimum_distance_km": 100,
                     "forecast": "train 2023; score observed pairs in 2024 using only 2023 traffic masses",
                     "heldout": "hold out entire unordered pairs in 2024; recompute masses inside each training fold",
                     "scope": "simplified research gravity; not calculator P/T/F; no population catchments or airport effects"},
        "experiments": {"forecast_2023_2024": fc, "heldout_pairs_2024": ho},
        "macro": {"income": {"status": "not_available"}, "tourism": {"status": "not_in_benchmark"},
                  "business": {"status": "not_in_benchmark"}, "diasporas": {"status": "not_in_benchmark"},
                  "visas": {"status": "not_in_benchmark"}},
        "limitations": [
            "The source contains observed routes with 12 positive monthly values; absent pairs are not zeros.",
            "Eurostat PAS_CRD describes on-flight origin/destination airport pairs, not flight-stage PAS_BRD or true journey origin/destination; connecting journeys are not reconstructed.",
            "2024 is a retrospective check using the repository's published-data vintage, not a real-time backtest.",
            "Forecast scores cover surviving pairs with positive published annual observations in both years, not route openings or closures.",
            "Pair-held-out scores apply to observed airports with other training routes, not a new airport.",
            "Node masses are partial sums of the available route sample, not certified total airport traffic.",
            "The two tasks have different information sets; last year's flow is unavailable for a pair without history.",
            "Annual aggregates cannot validate monthly seasonality; no result for diaspora or visa effects is claimed.",
            "One fixed five-fold split is exploratory; no causal interpretation or uncertainty interval is claimed.",
        ],
        "next_data": ["monthly traffic panel with report provenance", "population catchments",
                      "regional GDP, accommodation nights and employment", "dated bilateral migration and visa indicators"],
    }
    if income_path and income_path.exists():
        cov = json.loads(income_path.read_text())
        incomes = cov["values"]
        fc_income, fc_extra = forecast(r23, r24, incomes)
        ho_income, ho_extra = heldout(r24, incomes.get("2023", {}))
        summary["macro"]["income"] = {"status": "exploratory_retrospective_comparison", "source": cov["source"],
            "indicator": cov["indicator"], "source_updated": cov["source_updated"], "unit": cov["unit"],
            "covariate_years": [2022, 2023], "countries_per_year": {y: len(v) for y, v in incomes.items()},
            "feature": "ln(GDP per capita PPP A * GDP per capita PPP B), observation year minus one",
            "vintage_caveat": "downloaded in 2026; publication/revision dates as known in 2023/2024 are not reconstructed",
            "comparison": "baseline and income model use identical training and scoring rows",
            "forecast_2023_2024": fc_income, "heldout_pairs_2024": ho_income}
        records += fc_extra + ho_extra
        inputs.append({"path": str(income_path.relative_to(ROOT)), "sha256": hashlib.sha256(income_path.read_bytes()).hexdigest()})
    if tourism_path and tourism_path.exists():
        cov = json.loads(tourism_path.read_text())
        values = cov["values"]
        fc_tourism, fc_extra = forecast(r23, r24, values, "tourism", "airport")
        ho_tourism, ho_extra = heldout(r24, values.get("2023", {}), "tourism", "airport")
        summary["macro"]["tourism"] = {"status": "exploratory_retrospective_comparison", "source": cov["source"],
            "geography_source": cov["geography_source"], "geography_version": cov["geography_version"],
            "source_updated": cov["source_updated"], "unit": cov["unit"],
            "covariate_years": [2022, 2023], "airports_per_year": {y: len(v) for y, v in values.items()},
            "feature": "ln(annual regional accommodation nights A * annual regional accommodation nights B), observation year minus one",
            "vintage_caveat": "2026 data vintage, 2024 region polygons, retrospective association; not historical publication-date availability",
            "comparison": "baseline and tourism model use identical training and scoring rows",
            "scope": "total nights including residents; annual tourism-activity proxy, not air arrivals or seasonal passenger demand",
            "forecast_2023_2024": fc_tourism, "heldout_pairs_2024": ho_tourism}
        records += fc_extra + ho_extra
        inputs.append({"path": str(tourism_path.relative_to(ROOT)), "sha256": hashlib.sha256(tourism_path.read_bytes()).hexdigest()})
    write_json(out_dir / "summary.json", summary)
    with (out_dir / "predictions.jsonl").open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=HERE / "out")
    p.add_argument("--income", type=Path, default=HERE / "out/income_covariates.json")
    p.add_argument("--tourism", type=Path, default=HERE / "out/tourism_covariates.json")
    args = p.parse_args()
    summary = run(args.out.resolve(), args.income.resolve(), args.tourism.resolve())
    for name, exp in summary["experiments"].items():
        print(name, exp["n"], {k: round(v["median_factor"], 3) for k, v in exp["models"].items()})
    inc = summary["macro"]["income"]
    if inc["status"] != "not_available":
        print("income_heldout", {k: round(v["median_factor"], 3) for k, v in inc["heldout_pairs_2024"]["models"].items()})


if __name__ == "__main__":
    main()
