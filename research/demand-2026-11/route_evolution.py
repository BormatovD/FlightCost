#!/usr/bin/env python3
"""Matched-route descriptive decomposition; no aircraft-type inference.

The main cohort has complete clean reporter years in 2015, 2019 and 2024.
Both endpoint years use the same reporting airport(s), not a changing mix.
This retrospective balanced sample does not describe entries, exits or all Europe.
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
TARGET_YEARS = (2015, 2019, 2024)
PERIODS = ((2015, 2019), (2019, 2024))
EXAMPLE_PAIRS = ("EDDF-LEBL", "EDDL-LEPA", "EDDF-LIMC", "EDDF-VIDP", "EHAM-LFRN")


def load(path):
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw)), hashlib.sha256(raw).hexdigest()


def annual_reporter_rows(panel):
    annual, failures = {}, Counter()
    for pair, rows in sorted(panel["pairs"].items()):
        groups = defaultdict(list)
        for row in rows:
            y = int(row[0][:4])
            if y in TARGET_YEARS:
                groups[(y, row[1])].append(row)
        annual[pair] = {}
        for (y, reporter), months in groups.items():
            reason = None
            if len(months) != 12 or len({r[0] for r in months}) != 12:
                reason = "incomplete_months"
            elif any(any(v is None or not math.isfinite(v) or v < 0 for v in r[2:5]) for r in months):
                reason = "missing_or_invalid_triplet"
            elif any(r[5] for r in months):
                reason = "source_flag"
            elif any(r[2] > r[3] for r in months):
                reason = "passengers_exceed_seats"
            elif any((r[2] > 0 or r[3] > 0) and r[4] == 0 or r[2] > 0 and r[3] == 0 for r in months):
                reason = "positive_activity_zero_capacity_or_flights"
            totals = [sum(r[i] for r in months if r[i] is not None) for i in (2, 3, 4)]
            if reason is None and min(totals) <= 0:
                reason = "nonpositive_annual_total"
            if reason:
                failures[reason] += 1
                continue
            annual[pair].setdefault(y, {})[reporter] = totals
    return annual, dict(failures)


def disagreements(panel):
    result = set()
    for pair, rows in panel["pairs"].items():
        for row in rows:
            y = int(row[0][:4])
            if y in TARGET_YEARS and "reporter_disagreement_above_10pct" in (row[8] or ""):
                result.add((pair, y))
    return result


def quantities(totals):
    p, s, f = totals
    return {"passengers": p, "seats": s, "flights": f,
            "seats_per_flight": s / f, "load_factor": p / s}


def fixed_reporters(annual, years, disagreement=None):
    result, missing = {}, Counter()
    for pair, by_year in sorted(annual.items()):
        if not all(y in by_year for y in years):
            missing["no_complete_clean_reporter_in_every_year"] += 1
            continue
        reporters = sorted(set.intersection(*(set(by_year[y]) for y in years)))
        if not reporters:
            missing["no_same_reporter_across_years"] += 1
            continue
        if disagreement and any((pair, y) in disagreement for y in years):
            missing["reporter_disagreement_above_10pct"] += 1
            continue
        result[pair] = {"reporters": reporters, "years": {}}
        for y in years:
            means = [sum(by_year[y][reporter][i] for reporter in reporters) / len(reporters) for i in range(3)]
            result[pair]["years"][str(y)] = quantities(means)
    return result, dict(missing)


def decomposition(a, b):
    factors = {"flights": b["flights"] / a["flights"],
               "seats_per_flight": b["seats_per_flight"] / a["seats_per_flight"],
               "load_factor": b["load_factor"] / a["load_factor"]}
    ratio = b["passengers"] / a["passengers"]
    log_ratio = math.log(ratio)
    delta = b["passengers"] - a["passengers"]
    lm = delta / log_ratio if abs(log_ratio) > 1e-12 else a["passengers"]
    contributions = {k: lm * math.log(v) for k, v in factors.items()}
    return {"passenger_change_fraction": ratio - 1,
            "factor_change_fraction": {k: v - 1 for k, v in factors.items()},
            "log_percentage_points": {k: 100 * math.log(v) for k, v in factors.items()},
            "lmdi_passenger_contribution": contributions,
            "lmdi_identity_residual": sum(contributions.values()) - delta}


def great_circle(a, b):
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat, dlon = lat2 - lat1, math.radians(b[1] - a[1])
    x = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(min(1, math.sqrt(x)))


def summarize(rows, start, end):
    if not rows:
        return {"pairs": 0}
    aggregates = {}
    for y in (start, end):
        totals = [sum(r["years"][str(y)][k] for r in rows.values()) for k in ("passengers", "seats", "flights")]
        aggregates[str(y)] = quantities(totals)
    decompositions = [decomposition(row["years"][str(start)], row["years"][str(end)]) for row in rows.values()]
    seats_changes = [d["factor_change_fraction"]["seats_per_flight"] for d in decompositions]
    flight_changes = [d["factor_change_fraction"]["flights"] for d in decompositions]
    p_changes = [d["passenger_change_fraction"] for d in decompositions]
    summed = {key: sum(d["lmdi_passenger_contribution"][key] for d in decompositions)
              for key in ("flights", "seats_per_flight", "load_factor")}
    delta = aggregates[str(end)]["passengers"] - aggregates[str(start)]["passengers"]
    return {"pairs": len(rows), "start": start, "end": end, "aggregates": aggregates,
            "aggregate_decomposition": decomposition(aggregates[str(start)], aggregates[str(end)]),
            "within_pair_lmdi_passenger_contributions_summed": summed,
            "within_pair_identity_residual": sum(summed.values()) - delta,
            "within_pair": {
                "median_seats_per_flight_change": statistics.median(seats_changes),
                "median_flights_change": statistics.median(flight_changes),
                "median_passengers_change": statistics.median(p_changes),
                "seats_per_flight_increased": sum(v > 0 for v in seats_changes),
                "seats_per_flight_increased_over_5pct": sum(v > .05 for v in seats_changes),
                "flights_decreased": sum(v < 0 for v in flight_changes),
                "larger_average_with_fewer_flights": sum(s > 0 and f < 0 for s, f in zip(seats_changes, flight_changes)),
            }}


def run(out):
    reporter, reporter_hash = load(HERE / "out/supply_reporter_panel.json.gz")
    annual, annual_rejections = annual_reporter_rows(reporter)
    source_urls = [s["url"] for s in reporter["sources"]]
    del reporter
    pair_panel, pair_hash = load(HERE / "out/supply_pair_panel.json.gz")
    disagreement = disagreements(pair_panel)
    del pair_panel
    airport_path = HERE.parent / "routes-2026-11/out/airports.json"
    airport_bytes = airport_path.read_bytes()
    airports = json.loads(airport_bytes)
    matched, rejected = fixed_reporters(annual, TARGET_YEARS, disagreement)
    relaxed, relaxed_rejected = fixed_reporters(annual, TARGET_YEARS)
    for pair, record in matched.items():
        a, b = pair.split("-")
        record["distance_km"] = great_circle(airports[a], airports[b]) if a in airports and b in airports else None
        record["country_codes"] = [airports[x][2] if x in airports else None for x in (a, b)]
        record["iata"] = [airports[x][5] if x in airports else None for x in (a, b)]
    periods = []
    for start, end in PERIODS:
        period = summarize(matched, start, end)
        period["same_cohort_relaxed_reporter_disagreement"] = summarize(relaxed, start, end)
        # Pairwise coverage sensitivity is explicitly a different cohort.
        pairwise, reasons = fixed_reporters(annual, (start, end), disagreement)
        period["pairwise_endpoint_cohort_sensitivity"] = {**summarize(pairwise, start, end), "exclusions": reasons}
        periods.append(period)
    capacity_groups = []
    for key, low, high in (("under100", 0, 100), ("100to149", 100, 150), ("150to199", 150, 200), ("200plus", 200, float("inf"))):
        group = {p: r for p, r in matched.items() if low <= r["years"]["2015"]["seats_per_flight"] < high}
        capacity_groups.append({"group": key, "assignment_year": 2015,
                                "periods": [summarize(group, a, b) for a, b in PERIODS]})
    distance_groups = []
    for key, low, high in (("under1500km", 0, 1500), ("1500to4000km", 1500, 4000), ("4000to6500km", 4000, 6500), ("6500pluskm", 6500, float("inf"))):
        group = {p: r for p, r in matched.items() if r["distance_km"] is not None and low <= r["distance_km"] < high}
        distance_groups.append({"group": key, "periods": [summarize(group, a, b) for a, b in PERIODS]})
    examples = []
    for pair in EXAMPLE_PAIRS:
        rows, why = fixed_reporters({pair: annual.get(pair, {})}, TARGET_YEARS, disagreement)
        item = {"pair": pair, "in_main_balanced_cohort": pair in matched, "excluded_reasons": why}
        if pair in matched:
            item.update(matched[pair])
            item["decomposition"] = {f"{a}_{b}": decomposition(item["years"][str(a)], item["years"][str(b)]) for a, b in PERIODS}
        else:
            endpoint_rows, reasons = fixed_reporters({pair: annual.get(pair, {})}, (2019, 2024), disagreement)
            if pair in endpoint_rows:
                item.update(endpoint_rows[pair])
                item["decomposition"] = {"2019_2024": decomposition(item["years"]["2019"], item["years"]["2024"])}
        examples.append(item)
    result = {
        "schema_version": 1, "as_of": "2026-11-11", "status": "descriptive_historical_evolution_not_forecast",
        "quantity": "flight-stage PAS_BRD, ST_PAS, CAF_PAS; both directions, all carriers; counterpart reporters averaged",
        "source_urls": source_urls,
        "inputs": [{"path": "out/supply_reporter_panel.json.gz", "sha256": reporter_hash},
                   {"path": "out/supply_pair_panel.json.gz", "sha256": pair_hash},
                   {"path": "../routes-2026-11/out/airports.json", "sha256": hashlib.sha256(airport_bytes).hexdigest(),
                    "role": "fixed coordinates for descriptive great-circle distance, never current airport activity"}],
        "policy": {
            "years": list(TARGET_YEARS),
            "main_cohort": "One fixed airport-pair cohort with 12 clean months in 2015, 2019 and 2024, using the identical reporting-airport intersection across all three years.",
            "quality": "All monthly triplets finite/nonnegative; source flags rejected; passengers cannot exceed seats; positive traffic/capacity requires flights; no monthly counterpart disagreement >10% in selected years. All-zero months are allowed, annual totals must be positive.",
            "no_fill": "Missing months are not zeros. No interpolation or inferred closures.",
            "selection": "Retrospective endpoint-balanced routes; excludes unobserved entrants, exits and incomplete routes. Not total Europe or causal fleet demand.",
            "same_reporters": "One identical reporting-airport set throughout all selected years; counterpart observations never summed.",
            "identity": "P = flights * (seats/flights) * (passengers/seats)",
            "lmdi": "For P0,P1 >0: contribution_k = (P1-P0)/ln(P1/P0) * ln(factor1_k/factor0_k); equal P uses limit P0.",
            "aggregate_caveat": "Aggregate seats/flight includes route mix within the fixed cohort. Median paired changes and summed within-pair LMDI are provided separately.",
            "capacity_groups": "Assigned by observed mean seats/flight in 2015; no reassignment using future outcomes.",
            "distance": "Great-circle distance from pinned route-research airport coordinates; not payload-range feasibility or current routing.",
            "types": "Average seats/flight does not identify an aircraft type, seating configuration or carrier. No airline profitability claim follows.",
        },
        "input_pairs": len(annual), "main_pairs": len(matched), "relaxed_pairs": len(relaxed),
        "main_pairs_with_coordinates": sum(r["distance_km"] is not None for r in matched.values()),
        "annual_reporter_rejections_by_first_reason": annual_rejections,
        "main_pair_exclusions_by_first_reason": rejected,
        "relaxed_pair_exclusions_by_first_reason": relaxed_rejected,
        "periods": periods, "by_2015_capacity": capacity_groups, "by_distance": distance_groups, "examples": examples,
    }
    out.mkdir(parents=True, exist_ok=True)
    encoded = gzip.compress(json.dumps({"pairs": matched}, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(), mtime=0)
    (out / "route_evolution_pairs.json.gz").write_bytes(encoded)
    result["derived_pairs"] = {"path": "out/route_evolution_pairs.json.gz", "sha256": hashlib.sha256(encoded).hexdigest(), "pairs": len(matched)}
    (out / "route_evolution.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print("main pairs", len(matched), "relaxed", len(relaxed), "coordinates", result["main_pairs_with_coordinates"])
    for p in periods:
        print(p["start"], p["end"], p["aggregate_decomposition"], p["within_pair"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "out")
    run(parser.parse_args().out)
