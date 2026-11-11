#!/usr/bin/env python3
"""Past-only rolling-origin baselines on the pinned PAS_CRD archive.

No network, fitting to target outcomes, production change, or fresh forecast.
This is a current-vintage retrospective experiment, not a real-time vintage test.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent
MODELS = ("last_year", "log_trend", "damped_log_trend")
PHI = 0.8  # Declared before evaluation, not chosen on the test scores.
MIN_HISTORY = 5
YEARS = range(2005, 2025)


def dump(path, value):
    content = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    path.write_bytes(content)


def percentile(values, probability):
    """Linear sample quantile, with its convention explicit for reproduction."""
    values = sorted(values)
    if not values:
        return None
    k = (len(values) - 1) * probability
    lo = int(k)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def annualize(panel):
    valid, counts, rejection = {}, {}, Counter()
    for pair, rows in sorted(panel["pairs"].items()):
        grouped = defaultdict(list)
        for row in rows:
            grouped[int(row[0][:4])].append(row)
        valid[pair], counts[pair] = {}, {}
        for year, months in grouped.items():
            counts[pair][year] = len(months)
            if len(months) != 12 or len({r[0] for r in months}) != 12:
                rejection["incomplete_year"] += 1
                continue
            if any(not isinstance(r[1], (int, float)) or not math.isfinite(r[1]) or r[1] < 0 for r in months):
                rejection["invalid_value"] += 1
                continue
            if any(r[3] is not None and r[3] > 0.1 for r in months):
                rejection["reporter_spread_above_10pct"] += 1
                continue
            if any(r[4] for r in months):
                rejection["source_flag"] += 1
                continue
            valid[pair][year] = sum(r[1] for r in months)
    return valid, counts, dict(rejection)


def predict(history, years_ahead):
    logs = [math.log1p(v) for v in history]
    # Five equally spaced years; centered x = -2,-1,0,1,2.
    slope = sum((i - 2) * y for i, y in enumerate(logs)) / 10.0
    level = logs[-1]
    damped_steps = sum(PHI ** k for k in range(1, years_ahead + 1))
    return {
        "last_year": history[-1],
        "log_trend": max(0.0, math.expm1(level + slope * years_ahead)),
        "damped_log_trend": max(0.0, math.expm1(level + slope * damped_steps)),
    }


def era(target_year):
    if target_year < 2020:
        return "pre2020"
    if target_year <= 2021:
        return "pandemic2020_2021"
    return "recovery2022_2024"


def metric(cases, model, interval_q=None):
    if not cases:
        return {"n": 0}
    actual = [x["actual"] for x in cases]
    predicted = [x["predictions"][model] for x in cases]
    error = [p - y for p, y in zip(predicted, actual)]
    denominator = sum(actual)
    factors = [math.exp(abs(math.log(p / y))) for p, y in zip(predicted, actual) if p > 0 and y > 0]
    out = {
        "n": len(cases), "unique_pairs": len({x["pair"] for x in cases}),
        "origin_years": sorted({x["origin"] for x in cases}),
        "target_years": sorted({x["target_year"] for x in cases}),
        "actual_passengers": denominator, "predicted_passengers": sum(predicted),
        "wape": sum(abs(v) for v in error) / denominator if denominator else None,
        "mae_passengers": sum(abs(v) for v in error) / len(cases),
        "signed_bias": sum(error) / denominator if denominator else None,
        "median_error_factor_positive": statistics.median(factors) if factors else None,
        "positive_factor_n": len(factors),
        "published_zero_targets": sum(y == 0 for y in actual),
        "zero_target_mae": statistics.mean(abs(p) for p, y in zip(predicted, actual) if y == 0)
        if any(y == 0 for y in actual) else None,
    }
    scored = []
    for c, p in zip(cases, predicted):
        q = (interval_q or {}).get((c["origin"], model))
        if q is None:
            continue
        low = max(0.0, math.expm1(math.log1p(p) - q))
        high = math.expm1(math.log1p(p) + q)
        scored.append((low <= c["actual"] <= high, high - low, c["actual"]))
    out["empirical_80pct_interval"] = {
        "n": len(scored),
        "coverage": sum(x[0] for x in scored) / len(scored) if scored else None,
        "mean_width_passengers": statistics.mean(x[1] for x in scored) if scored else None,
        "mean_width_over_mean_actual": sum(x[1] for x in scored) / sum(x[2] for x in scored)
        if scored and sum(x[2] for x in scored) else None,
    }
    return out


def experiment(annual, counts, horizon, lag):
    cases, folds = [], []
    # origin: end of decision calendar year. lag 1 uses data through origin-1.
    for origin in range(2009 + lag, 2025 - horizon):
        anchor = origin - lag
        training_years = list(range(anchor - 4, anchor + 1))
        target = origin + horizon
        eligible = [pair for pair, values in annual.items() if all(y in values for y in training_years)]
        fold = {"origin": origin, "anchor_year": anchor, "training_years": training_years,
                "target_year": target, "eligible_at_origin": len(eligible),
                "complete_clean_target": 0, "unscored_target": Counter()}
        for pair in eligible:
            values = annual[pair]
            predictions = predict([values[y] for y in training_years], horizon + lag)
            if target not in values:
                n = counts[pair].get(target, 0)
                reason = "absent" if n == 0 else "incomplete" if n < 12 else "quality_rejected"
                fold["unscored_target"][reason] += 1
                continue
            fold["complete_clean_target"] += 1
            cases.append({"pair": pair, "origin": origin, "anchor_year": anchor,
                          "target_year": target, "actual": values[target],
                          "predictions": predictions})
        fold["unscored_target"] = dict(fold["unscored_target"])
        folds.append(fold)
    # Calibrate intervals only with earlier forecasts whose outcomes are already
    # observable by the current anchor. The test target never contributes.
    interval_q, calibration = {}, []
    for fold in folds:
        past = [c for c in cases if c["target_year"] <= fold["anchor_year"]]
        past_origins = sorted({c["origin"] for c in past})
        sufficient = len(past_origins) >= 3 and len(past) >= 100
        row = {"origin": fold["origin"], "observed_through": fold["anchor_year"],
               "completed_prior_origins": past_origins, "past_cases": len(past),
               "status": "available" if sufficient else "insufficient_prior_outcomes", "q": {}}
        for model in MODELS:
            q = percentile([abs(math.log1p(c["actual"]) - math.log1p(c["predictions"][model]))
                            for c in past], 0.8) if sufficient else None
            row["q"][model] = q
            interval_q[(fold["origin"], model)] = q
        calibration.append(row)
    metrics = {}
    for group in ("all", "pre2020", "pandemic2020_2021", "recovery2022_2024"):
        selected = cases if group == "all" else [c for c in cases if era(c["target_year"]) == group]
        metrics[group] = {model: metric(selected, model, interval_q) for model in MODELS}
    return {"horizon_years_from_decision": horizon, "availability_lag_years": lag,
            "horizon_years_from_observation": horizon + lag,
            "eligible_origin_pair_cases": sum(f["eligible_at_origin"] for f in folds),
            "scored_cases": len(cases),
            "unscored_cases": sum(f["eligible_at_origin"] - f["complete_clean_target"] for f in folds),
            "folds": folds, "metrics": metrics,
            "interval_calibration": calibration,
            "metrics_by_origin": [{"origin": f["origin"], "target_year": f["target_year"],
                                    "models": {m: metric([c for c in cases if c["origin"] == f["origin"]], m, interval_q)
                                               for m in MODELS}} for f in folds]}, cases


def run(out):
    source = HERE / "out/eu_monthly_panel.json.gz"
    content = source.read_bytes()
    panel = json.loads(gzip.decompress(content))
    annual, counts, rejection = annualize(panel)
    results, rows = [], []
    for lag in (0, 1):
        for horizon in (3, 5, 10):
            result, cases = experiment(annual, counts, horizon, lag)
            results.append(result)
            for c in cases:
                rows.append([lag, horizon, c["origin"], c["pair"], c["actual"],
                             *[c["predictions"][m] for m in MODELS]])
    artifact = {
        "schema_version": 1, "as_of": "2026-11-11",
        "status": "retrospective_baselines_not_deployed_or_future_forecasts",
        "target": "annual PAS_CRD on-flight airport-pair passengers, both directions, all carriers",
        "input": {"path": "out/eu_monthly_panel.json.gz", "sha256": hashlib.sha256(content).hexdigest(),
                  "pairs": len(panel["pairs"]), "first_year": 2005, "last_year": 2024},
        "source_metadata": panel["source_metadata"],
        "policy": {
            "cohort": "Five complete clean consecutive training years; eligibility decided before inspecting target.",
            "annual_quality": "12 distinct months; finite nonnegative passengers; no source flag; relative reporter spread <= 10%.",
            "missing": "Absent, incomplete and quality-rejected targets are unscored, never zero or interpolated.",
            "primary_reporting_lag": 1,
            "time": "origin is end of decision year; lag=1 only uses annual data through origin-1; lag=0 is an optimistic sensitivity.",
            "vintage": "Archive with latest revisions; dates of actual historical publication are not reconstructed.",
            "selection_bias": "Scores are conditional on an observable complete target. Unobserved exits/entries are not evaluated.",
            "dependence": "Overlapping origin/horizon cases and repeated pairs are not independent samples.",
            "interval": "Empirical 80th percentile absolute log1p error from >=3 prior origins and >=100 cases whose targets <= current anchor. No distribution-free guarantee; same-pair and overlapping outcomes remain dependent.",
            "production_PTF": "Not tested: airport catchment and historical P/T/F inputs are not yet rebuilt within each fold.",
            "incremental_factors": "Income, tourism, business, diaspora and visas are not fitted in this baseline experiment.",
            "future_capacity": "Not used as predictor.",
        },
        "models": {
            "last_year": {"formula": "prediction = last complete annual passengers"},
            "log_trend": {"formula": "max(0, exp(log1p(P_anchor) + b * (h + lag)) - 1)",
                          "b": "OLS slope of log1p annual passengers on five equally spaced past years"},
            "damped_log_trend": {"formula": "max(0, exp(log1p(P_anchor) + b * sum(phi**k, k=1..h+lag)) - 1)",
                                 "phi": PHI, "selection": "fixed before scoring, not selected on final targets"},
        },
        "annual_input_quality": {"clean_pair_years": sum(len(v) for v in annual.values()),
                                 "rejected_pair_years_by_first_reason": rejection},
        "experiments": results,
    }
    out.mkdir(parents=True, exist_ok=True)
    case_payload = {"columns": ["availability_lag_years", "horizon_years", "origin_year", "pair", "actual",
                                *MODELS], "rows": rows}
    compressed = gzip.compress(json.dumps(case_payload, separators=(",", ":"), allow_nan=False).encode(), mtime=0)
    (out / "forecast_benchmark_cases.json.gz").write_bytes(compressed)
    artifact["case_file"] = {"path": "out/forecast_benchmark_cases.json.gz", "rows": len(rows),
                             "sha256": hashlib.sha256(compressed).hexdigest()}
    dump(out / "forecast_benchmark.json", artifact)
    for r in results:
        print("lag", r["availability_lag_years"], "h", r["horizon_years_from_decision"],
              "scored/eligible", r["scored_cases"], r["eligible_origin_pair_cases"],
              "WAPE", {m: round(r["metrics"]["all"][m]["wape"], 4) for m in MODELS})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "out")
    run(parser.parse_args().out)
