#!/usr/bin/env python3
"""Dated, age-matched lease-reference corrections for the research article.

This deliberately does not fit a universal aircraft lease model or write to the
calculator. A current source appraisal supplies a reference level, not proof of
predictive accuracy. Historical sources and the old-model snapshot are inputs.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "out/lease_calibration.json"
AS_OF = "2026-11-11"
SELECTED = {
    "turboprop": ("AT46", "AT76"),
    "regional": ("E75L", "E295"),
    "narrowbody": ("A20N", "A21N"),
    "widebody": ("A359", "B789"),
}
ANCHORS = {
    "AT46": "history-truenoord-turboprop-2023-fig6.3(i)-at46-lease-0-2023",
    "AT76": "history-truenoord-turboprop-2023-fig6.3(ii)-at76-lease-0-2023",
    "E75L": "history-truenoord-regional-2025-fig6.3-e75l-lease-0-2024",
    "E295": "history-oriel-2026-e295-lease",
    "A20N": "history-iba-2026q1-a20n-a320-200n-lease",
    "A21N": "history-iba-2026q1-a21n-a321-200nx-lease",
    "A359": "history-iba-2026q1-a359-lease-new",
    "B789": "history-iba-2026q1-b789-lease-new",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def midpoint(row: dict) -> float:
    return (row["amount_low_usd"] + row["amount_high_usd"]) / 2


def period_span(period: str) -> list[float]:
    """The source period's resolution, never an invented appraisal date."""
    year = int(period[:4])
    if len(period) == 4:
        return [float(year), float(year + 1)]
    if "Q" in period:
        start = year + (int(period[-1]) - 1) / 4
        return [start, start + 0.25]
    start = year + (int(period[5:7]) - 1) / 12
    return [start, start + 1 / 12]


def compact_observation(row: dict) -> dict:
    names = (
        "id", "icao", "period", "period_precision", "age", "variant",
        "valuation_basis", "amount_low_usd", "amount_high_usd", "estimate_type",
        "source_id", "source_url", "source_family", "locator", "quality",
        "extraction_basis", "digitization_tolerance_usd", "notes", "series_key",
    )
    result = {key: row[key] for key in names if key in row}
    result["amount_mid_usd"] = midpoint(row)
    result["display_span_x"] = period_span(row["period"])
    result["range_is_confidence_interval"] = False
    return result


def metrics(rows: list[dict], field: str) -> dict:
    actual = sum(row["actual_usd_month"] for row in rows)
    errors = [row[field] - row["actual_usd_month"] for row in rows]
    return {
        "n": len(rows),
        "wape": sum(abs(error) for error in errors) / actual,
        "signed_bias": sum(errors) / actual,
        "mae_usd_month": sum(abs(error) for error in errors) / len(rows),
    }


def temporal_diagnostic(history: dict, models: dict[str, dict]) -> dict:
    """One year ahead within the same AVAC series, excluding target data.

    The latest 2026 anchors do not take part in this diagnostic. It examines the
    more general rule 'last year's anchor, with/without CPI'; it does not validate
    the current coefficients. CPI is the current annual series, so this is a
    retrospective diagnostic and not an operational real-time backtest.
    """
    groups = defaultdict(list)
    for row in history["observations"]:
        if (row["icao"] in {"A20N", "A21N", "A359", "B789"}
                and row["kind"] == "lease" and row["age"]["years"] == 0
                and row["source_family"] == "AVAC"):
            groups[row["series_key"]].append(row)
    rows = []
    for series_key, observations in sorted(groups.items()):
        observations.sort(key=lambda row: row["period"])
        for previous, actual in zip(observations, observations[1:]):
            origin, target = int(previous["period"][:4]), int(actual["period"][:4])
            if target != origin + 1:
                continue
            points = {p["year"]: p for p in models[actual["icao"]]["nominal_usd_points"]}
            cpi_ratio = points[target]["cpi"] / points[origin]["cpi"]
            rows.append({
                "icao": actual["icao"], "series_key": series_key,
                "origin_period": previous["period"], "target_period": actual["period"],
                "training_observation_id": previous["id"],
                "target_observation_id": actual["id"],
                "training_source_url": previous["source_url"],
                "target_source_url": actual["source_url"],
                "age_years": 0,
                "actual_usd_month": midpoint(actual),
                "old_model_usd_month": points[target]["lease_usd_month"],
                "last_anchor_cpi_usd_month": midpoint(previous) * cpi_ratio,
                "last_anchor_nominal_usd_month": midpoint(previous),
                "cpi_ratio": cpi_ratio,
            })
    rows.sort(key=lambda row: (row["target_period"], row["icao"]))
    fields = ("old_model_usd_month", "last_anchor_cpi_usd_month", "last_anchor_nominal_usd_month")
    cohorts = {
        "all_2017_2020": rows,
        "pre_pandemic_2017_2019": [r for r in rows if r["target_period"] < "2020"],
        "pandemic_2020": [r for r in rows if r["target_period"].startswith("2020")],
    }
    return {
        "status": "retrospective_diagnostic_not_operational_backtest",
        "current_coefficients_validated": False,
        "training_rule": "previous annual observation only, same aircraft/age/series_key",
        "source_family": "AVAC",
        "target_observation_used_for_prediction": False,
        "rows": rows,
        "metrics": {name: {field: metrics(cohort, field) for field in fields}
                    for name, cohort in cohorts.items()},
        "limitations": [
            "Only four new-aircraft types and sixteen one-year comparisons; correlated appraiser opinions, not deals.",
            "The 2026 production formula is a present-day comparator, not a formula known to a forecaster in 2016.",
            "Uses today's annual CPI series, including the target year's full-year CPI; not available at each October origin.",
            "The 2026 calibration observations are not holdout tests: they define the coefficients by construction.",
            "No out-of-source or multi-year validation; no evidence for a universal time-invariant correction.",
        ],
    }


def build() -> dict:
    history_path = HERE / "out/segments_history.json"
    model_path = HERE / "out/model_reference.json"
    history = json.loads(history_path.read_text(encoding="utf-8"))
    reference = json.loads(model_path.read_text(encoding="utf-8"))
    observations = {row["id"]: row for row in history["observations"]}
    models = {row["icao"]: row for row in reference["aircraft"]}
    source_registry = {row["id"]: row for row in history["sources"]}
    aircraft = []
    for segment, codes in SELECTED.items():
        for code in codes:
            model, anchor = models[code], observations[ANCHORS[code]]
            assert anchor["icao"] == code and anchor["kind"] == "lease"
            assert anchor["age"]["years"] == 0
            assert 0 < anchor["amount_low_usd"] <= anchor["amount_high_usd"]
            year = int(anchor["period"][:4])
            points = {row["year"]: row for row in model["nominal_usd_points"]}
            comparable = model["model_age_years"] == anchor["age"]["years"]
            before = points[year]["lease_usd_month"]
            lo, hi, mid = anchor["amount_low_usd"], anchor["amount_high_usd"], midpoint(anchor)
            calibration = {
                "status": "dated_age_matched_reference" if comparable else "unavailable_age_mismatch",
                "period": anchor["period"], "period_precision": anchor["period_precision"],
                "age_years": anchor["age"]["years"] if comparable else None,
                "model_before_year": year,
                "model_before_usd_month": before,
                "amount_low_usd": lo if comparable else None,
                "amount_high_usd": hi if comparable else None,
                "amount_mid_usd": mid if comparable else None,
                "multiplier_low": lo / before if comparable else None,
                "multiplier_high": hi / before if comparable else None,
                "multiplier_mid": mid / before if comparable else None,
                "change_pct": (mid / before - 1) * 100 if comparable else None,
                "calibrated_lease_eur_2026_month": mid / before * model["raw_parametric_lease_eur_month"] if comparable else None,
                "source_observation_id": anchor["id"], "source_id": anchor["source_id"],
                "source_url": anchor["source_url"],
                "display_span_x": period_span(anchor["period"]) if comparable else None,
                "display_span_meaning": "precision of appraisal period, not a guaranteed rent duration",
                "annual_points": [],
                "historical_backcast_allowed": False,
                "future_extrapolation_allowed": False,
                "range_is_confidence_interval": False,
                "fitted_to_anchor": comparable,
                "independently_validated": False,
                "production_changed": False,
                "reason": (
                    "Same type and new-aircraft age basis; source-level/condition/credit differences remain."
                    if comparable else
                    "Production basis is approximately 12 years; the available recent reference is new. No age-12 correction is inferred."
                ),
            }
            age_snapshot = []
            if code in {"AT46", "AT76"}:
                for obs in history["observations"]:
                    if (obs["icao"] == code and obs["kind"] == "lease"
                            and obs["source_id"] == anchor["source_id"]
                            and obs["period"] == anchor["period"]):
                        age_snapshot.append({
                            **compact_observation(obs),
                            "ratio_to_new_midpoint": midpoint(obs) / mid,
                        })
                age_snapshot.sort(key=lambda row: row["age"]["years"])
            new_rows = [obs for obs in history["observations"]
                        if obs["icao"] == code and obs["kind"] == "lease"
                        and obs["age"]["years"] == 0]
            latest_new = max(new_rows, key=lambda obs: (period_span(obs["period"])[0], obs["id"]))
            aircraft.append({
                "icao": code, "label": model["label"], "segment": segment,
                "mtow_t": model["mtow_t"],
                "raw_model_age_years": model["model_age_years"],
                "raw_model_age_is_approximate": model["model_age_is_approximate"],
                "raw_reference_eur_month": model["reference_lease_eur_month"],
                "raw_lease_eur_2026_month": model["raw_parametric_lease_eur_month"],
                "raw_lease_usd_2026_month": points[2026]["lease_usd_month"],
                "calibration": calibration,
                "anchor_observation": compact_observation(anchor),
                "latest_new_observation": compact_observation(latest_new),
                "new_observation_selection": (
                    "Q1 2026 credit range retained as the explicit comparable band; May 2026 approx. USD400k is a later same-provider check, not an independent range replacement."
                    if code == "A20N" else "Latest stored new-aircraft observation, retaining its original period precision."
                ),
                "anchor_source_published": source_registry[anchor["source_id"]].get("published"),
                "reference_age_calendar_years": 2026 - year,
                "old_anchor_is_not_2026_market": year < 2026,
                "same_period_age_snapshot": age_snapshot,
                "age_curve_fitted": False,
                "age_extrapolation_allowed": False,
            })
    return {
        "meta": {
            "schema_version": 1, "as_of": AS_OF,
            "scope": "research_only; five dated reference corrections, no production change",
            "inputs_sha256": {"out/segments_history.json": sha(history_path),
                              "out/model_reference.json": sha(model_path),
                              "lease_calibration.py": sha(Path(__file__))},
            "selected_aircraft_count": len(aircraft),
            "age_matched_calibration_count": sum(a["calibration"]["status"] == "dated_age_matched_reference" for a in aircraft),
            "age_mismatch_count": sum(a["calibration"]["status"] == "unavailable_age_mismatch" for a in aircraft),
            "formula_before": reference["meta"]["formula"],
            "formula_after": "L_refined(type,age,t0) = L_before(type,age,t0) * k(type,age,t0)",
            "formula_coefficient": "k = ((source_low + source_high) / 2) / L_before_at_same_year_and_age",
            "formula_range": "[k_low, k_high] = [source_low, source_high] / L_before_at_same_year_and_age",
            "midpoint_meaning": "arithmetic midpoint for a scenario, not an observed transaction mean",
            "cpi_and_fx_convention": reference["meta"]["historical_display"],
            "selection_reason": "Two readable examples per segment; retained types have dated new-aircraft history and explicit model metadata.",
            "current_model_age_is_not_changed_by_display": True,
            "publish_or_calculator_acceptance": "owner review; no accepted prices or production model written",
        },
        "segments": [{"id": segment, "types": list(codes)} for segment, codes in SELECTED.items()],
        "aircraft": aircraft,
        "temporal_diagnostic": temporal_diagnostic(history, models),
        "limitations": [
            "The after marker is anchored to an appraisal by construction, not evidence that the formula predicts market prices.",
            "No calibrated historical or future line is emitted; the horizontal marker shows only source-period precision.",
            "ATR and E175 new-aircraft history cannot calibrate the production model's approximately 12-year-old basis.",
            "ATR 2023 and E175 2024 appraisals are not relabelled as the 2026 market.",
            "Type-specific anchors are not transferred to unobserved aircraft, segments, variants or ages.",
            "CPI converts the display convention; it is not an aircraft-price index or a lease-contract escalator.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = build()
    encoded = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.check:
        if OUTPUT.read_text(encoding="utf-8") != encoded:
            raise SystemExit("lease_calibration.json differs; rebuild and review the input changes")
        print("lease_calibration.json: deterministic recomputation matches")
    else:
        OUTPUT.write_text(encoded, encoding="utf-8")
        print("Wrote out/lease_calibration.json: 8 types, 5 age-matched references, 3 unavailable corrections")


if __name__ == "__main__":
    main()
