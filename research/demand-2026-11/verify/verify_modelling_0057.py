#!/usr/bin/env python3
"""Independent arithmetic/cohort audit of the 0057 modelling outputs.

The audit imports neither modelling implementation. It rebuilds annual inputs,
all forecast cases and the fixed-reporter supply cohort from the pinned panels.
It verifies the supplied archive, not the original publisher's live databases.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parents[1]
OUT = HERE / "out"
CHECKS = Counter()
FAILURES = []


def read(name):
    raw = (OUT / name).read_bytes()
    return json.loads(gzip.decompress(raw) if name.endswith(".gz") else raw)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(label, actual, expected, *, rel=2e-9, absolute=2e-5):
    CHECKS[label.split("/")[0]] += 1
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        ok = math.isfinite(actual) and math.isfinite(expected) and math.isclose(actual, expected, rel_tol=rel, abs_tol=absolute)
    else:
        ok = actual == expected
    if not ok:
        FAILURES.append({"check": label, "actual": actual, "expected": expected})


def quantile_80(values):
    a = sorted(values)
    position = (len(a) - 1) * .8
    i, weight = int(position), position % 1
    return a[i] if weight == 0 else a[i] * (1 - weight) + a[i + 1] * weight


def forecast_inputs():
    panel = read("eu_monthly_panel.json.gz")
    check("input/pas_crd_columns", panel["columns"],
          ["month", "pax", "reporters", "relative_reporter_spread", "source_flags_union", "reporter_airports"])
    annual, counts, rejected = {}, {}, Counter()
    for pair, values in panel["pairs"].items():
        buckets = defaultdict(list)
        for row in values:
            buckets[int(row[0][:4])].append(row)
        annual[pair], counts[pair] = {}, {}
        for year, rows in buckets.items():
            counts[pair][year] = len(rows)
            all_months = {f"{year}-{m:02d}" for m in range(1, 13)}
            if len(rows) != 12 or {r[0] for r in rows} != all_months:
                rejected["incomplete_year"] += 1
            elif any(type(r[1]) not in (int, float) or not math.isfinite(r[1]) or r[1] < 0 for r in rows):
                rejected["invalid_value"] += 1
            elif max((r[3] or 0) for r in rows) > .1:
                rejected["reporter_spread_above_10pct"] += 1
            elif any(r[4] for r in rows):
                rejected["source_flag"] += 1
            else:
                annual[pair][year] = math.fsum(r[1] for r in rows)
    return annual, counts, rejected


def recompute_forecast(history, horizon):
    transformed = [math.log1p(v) for v in history]
    ybar = statistics.mean(transformed)
    slope = math.fsum((x - 2) * (y - ybar) for x, y in enumerate(transformed)) / 10
    damped_duration = .8 * (1 - .8 ** horizon) / (1 - .8)
    return [history[-1], max(0, math.exp(transformed[-1] + slope * horizon) - 1),
            max(0, math.exp(transformed[-1] + slope * damped_duration) - 1)]


def audit_metrics(label, recorded, rows, prediction_column, qs):
    check(label + "/n", recorded["n"], len(rows))
    if not rows:
        return
    actual = [r[4] for r in rows]
    predicted = [r[prediction_column] for r in rows]
    differences = [p - a for p, a in zip(predicted, actual)]
    total = math.fsum(actual)
    values = {
        "unique_pairs": len({r[3] for r in rows}),
        "origin_years": sorted({r[2] for r in rows}),
        "target_years": sorted({r[2] + r[1] for r in rows}),
        "actual_passengers": total,
        "predicted_passengers": math.fsum(predicted),
        "wape": math.fsum(map(abs, differences)) / total if total else None,
        "mae_passengers": statistics.mean(map(abs, differences)),
        "signed_bias": math.fsum(differences) / total if total else None,
        "published_zero_targets": actual.count(0),
        "zero_target_mae": statistics.mean(abs(p) for p, a in zip(predicted, actual) if a == 0) if 0 in actual else None,
    }
    factors = [max(p/a, a/p) for p, a in zip(predicted, actual) if p > 0 and a > 0]
    values["positive_factor_n"] = len(factors)
    values["median_error_factor_positive"] = statistics.median(factors) if factors else None
    for key, expected in values.items():
        check(label + "/" + key, recorded[key], expected)
    covered, widths, scored_y = [], [], []
    for row in rows:
        q = qs.get((row[2], prediction_column))
        if q is None:
            continue
        p, y = row[prediction_column], row[4]
        low, high = max(0, (p + 1) * math.exp(-q) - 1), (p + 1) * math.exp(q) - 1
        covered.append(low <= y <= high)
        widths.append(high - low)
        scored_y.append(y)
    interval = {
        "n": len(widths),
        "coverage": statistics.mean(covered) if covered else None,
        "mean_width_passengers": statistics.mean(widths) if widths else None,
        "mean_width_over_mean_actual": math.fsum(widths)/math.fsum(scored_y) if scored_y and sum(scored_y) else None,
    }
    for key, expected in interval.items():
        check(label + "/interval/" + key, recorded["empirical_80pct_interval"][key], expected)


def audit_forecasts():
    data, exported = read("forecast_benchmark.json"), read("forecast_benchmark_cases.json.gz")
    check("hash/forecast_input", data["input"]["sha256"], sha(OUT / "eu_monthly_panel.json.gz"))
    check("hash/forecast_cases", data["case_file"]["sha256"], sha(OUT / "forecast_benchmark_cases.json.gz"))
    annual, counts, rejected = forecast_inputs()
    check("cohort/clean_pair_years", data["annual_input_quality"]["clean_pair_years"], sum(map(len, annual.values())))
    check("cohort/rejected_pair_years", data["annual_input_quality"]["rejected_pair_years_by_first_reason"], dict(rejected))
    all_rows = exported["rows"]
    check("forecast/case_count", len(all_rows), data["case_file"]["rows"])
    unique = {(r[0],r[1],r[2],r[3]) for r in all_rows}
    check("forecast/cases_unique", len(unique), len(all_rows))
    models = ("last_year", "log_trend", "damped_log_trend")
    summary = []
    for result in data["experiments"]:
        lag, horizon = result["availability_lag_years"], result["horizon_years_from_decision"]
        tag = f"forecast/l{lag}h{horizon}"
        rows = [r for r in all_rows if r[:2] == [lag, horizon]]
        indexed = {(r[2], r[3]): r for r in rows}
        expected_cases = set()
        for fold in result["folds"]:
            origin, anchor, target = fold["origin"], fold["origin"] - lag, fold["origin"] + horizon
            years = list(range(anchor-4, anchor+1))
            check(tag + "/anchor", fold["anchor_year"], anchor)
            check(tag + "/training_years", fold["training_years"], years)
            check(tag + "/target", fold["target_year"], target)
            check(tag + "/strict_time", max(years) < target, True)
            eligible = {p for p, v in annual.items() if set(years) <= set(v)}
            reasons, scored = Counter(), 0
            for pair in eligible:
                actual = annual[pair].get(target)
                if actual is None:
                    n = counts[pair].get(target, 0)
                    reasons["absent" if n == 0 else "incomplete" if n < 12 else "quality_rejected"] += 1
                    continue
                scored += 1
                expected_cases.add((origin, pair))
                row = indexed.get((origin, pair))
                check(tag + "/eligible_case_present", row is not None, True)
                if row is None:
                    continue
                check(tag + "/actual", row[4], actual)
                predictions = recompute_forecast([annual[pair][y] for y in years], target-anchor)
                for i in range(3):
                    check(tag + "/prediction/" + models[i], row[5+i], predictions[i])
            check(tag + "/origin_eligible", fold["eligible_at_origin"], len(eligible))
            check(tag + "/origin_scored", fold["complete_clean_target"], scored)
            check(tag + "/origin_missing_reasons", fold["unscored_target"], dict(reasons))
        check(tag + "/case_membership", set(indexed), expected_cases)
        check(tag + "/scored", result["scored_cases"], len(rows))
        check(tag + "/attrition_balance", result["eligible_origin_pair_cases"], result["scored_cases"] + result["unscored_cases"])
        expected_origins = list(range(2009+lag, 2025-horizon))
        check(tag + "/origin_range", [f["origin"] for f in result["folds"]], expected_origins)
        check(tag + "/observation_horizon", result["horizon_years_from_observation"], horizon+lag)
        q_values = {}
        for calibration in result["interval_calibration"]:
            origin = calibration["origin"]
            previous = [r for r in rows if r[2]+horizon <= origin-lag]
            previous_origins = sorted({r[2] for r in previous})
            enough = len(previous) >= 100 and len(previous_origins) >= 3
            check(tag + "/interval_past_n", calibration["past_cases"], len(previous))
            check(tag + "/interval_observed_through", calibration["observed_through"], origin-lag)
            check(tag + "/interval_origins", calibration["completed_prior_origins"], previous_origins)
            check(tag + "/interval_status", calibration["status"], "available" if enough else "insufficient_prior_outcomes")
            for column, model in enumerate(models, 5):
                q = quantile_80([abs(math.log1p(r[4])-math.log1p(r[column])) for r in previous]) if enough else None
                q_values[(origin, column)] = q
                check(tag + "/interval_q/" + model, calibration["q"][model], q)
        subsets = {"all": rows, "pre2020": [r for r in rows if r[2]+horizon < 2020],
                   "pandemic2020_2021": [r for r in rows if 2020 <= r[2]+horizon <= 2021],
                   "recovery2022_2024": [r for r in rows if r[2]+horizon >= 2022]}
        for name, subset in subsets.items():
            for col, model in enumerate(models, 5):
                audit_metrics(tag+"/"+name+"/"+model, result["metrics"][name][model], subset, col, q_values)
        for fold in result["metrics_by_origin"]:
            subset = [r for r in rows if r[2] == fold["origin"]]
            check(tag + "/metric_origin_target", fold["target_year"], fold["origin"] + horizon)
            for col, model in enumerate(models, 5):
                audit_metrics(tag+f"/origin{fold['origin']}/"+model, fold["models"][model], subset, col, q_values)
        summary.append({"lag": lag, "horizon": horizon, "scored_cases": len(rows),
                        "eligible_cases": result["eligible_origin_pair_cases"],
                        "attrition_fraction": result["unscored_cases"] / result["eligible_origin_pair_cases"],
                        "target_years": sorted({r[2]+horizon for r in rows}),
                        "published_zero_targets": sum(r[4] == 0 for r in rows)})
    return summary


def audit_supply_inputs():
    panel = read("supply_reporter_panel.json.gz")
    annual, disagreements, reasons = {}, set(), Counter()
    for pair, rows in panel["pairs"].items():
        yearly, monthly = defaultdict(list), defaultdict(list)
        annual[pair] = {}
        for row in rows:
            year = int(row[0][:4])
            if year in {2015,2019,2024}:
                yearly[(year,row[1])].append(row)
                monthly[row[0]].append(row)
        for month, month_rows in monthly.items():
            for field in (2,3,4):
                v = [r[field] for r in month_rows if r[field] is not None]
                if v and sum(v) and (max(v)-min(v))/statistics.mean(v) > .1:
                    disagreements.add((pair, int(month[:4])))
        for (year, reporter), year_rows in yearly.items():
            reason = None
            months = {f"{year}-{m:02d}" for m in range(1,13)}
            if len(year_rows) != 12 or {r[0] for r in year_rows} != months:
                reason = "incomplete_months"
            elif any(v is None or not math.isfinite(v) or v < 0 for r in year_rows for v in r[2:5]):
                reason = "missing_or_invalid_triplet"
            elif any(r[5] for r in year_rows):
                reason = "source_flag"
            elif any(r[2] > r[3] for r in year_rows):
                reason = "passengers_exceed_seats"
            elif any((r[4] == 0 and (r[2] > 0 or r[3] > 0)) or (r[3] == 0 and r[2] > 0) for r in year_rows):
                reason = "positive_activity_zero_capacity_or_flights"
            if reason is None:
                sums = [math.fsum(r[i] for r in year_rows) for i in (2,3,4)]
                if min(sums) <= 0:
                    reason = "nonpositive_annual_total"
            if reason:
                reasons[reason] += 1
            else:
                annual[pair].setdefault(year,{})[reporter] = sums
    flagged = set()
    for pair, rows in read("supply_pair_panel.json.gz")["pairs"].items():
        for row in rows:
            year = int(row[0][:4])
            if year in {2015,2019,2024} and "reporter_disagreement_above_10pct" in (row[8] or ""):
                flagged.add((pair,year))
    check("supply/raw_reporter_disagreements_match_flags", disagreements, flagged)
    return annual, disagreements, reasons


def supply_cohort(annual, years, reject_disagreement):
    selected, rejected = {}, Counter()
    for pair, available in annual.items():
        if not set(years) <= set(available):
            rejected["no_complete_clean_reporter_in_every_year"] += 1
            continue
        stable = set(available[years[0]])
        for year in years[1:]:
            stable.intersection_update(available[year])
        if not stable:
            rejected["no_same_reporter_across_years"] += 1
            continue
        if any((pair,year) in reject_disagreement for year in years):
            rejected["reporter_disagreement_above_10pct"] += 1
            continue
        selected[pair] = {"reporters": sorted(stable), "years": {
            str(y): quantities([statistics.mean(available[y][r][i] for r in stable) for i in range(3)])
            for y in years}}
    return selected, dict(rejected)


def quantities(values):
    p,s,f = values
    return dict(passengers=p,seats=s,flights=f,seats_per_flight=s/f,load_factor=p/s)


def audit_decomposition(label, recorded, a, b):
    delta = b["passengers"]-a["passengers"]
    ratio = b["passengers"]/a["passengers"]
    factors = ("flights","seats_per_flight","load_factor")
    log_ratios = {key: math.log(b[key])-math.log(a[key]) for key in factors}
    multiplier = delta / math.log(ratio) if abs(ratio-1) > 1e-12 else a["passengers"]
    contributions = {key: multiplier * value for key,value in log_ratios.items()}
    check(label+"/passenger_change",recorded["passenger_change_fraction"],ratio-1)
    for key in factors:
        check(label+"/factor/"+key,recorded["factor_change_fraction"][key],b[key]/a[key]-1)
        check(label+"/log/"+key,recorded["log_percentage_points"][key],100*log_ratios[key])
        check(label+"/lmdi/"+key,recorded["lmdi_passenger_contribution"][key],contributions[key],absolute=.002)
    check(label+"/identity",sum(contributions.values()),delta,absolute=.002)
    check(label+"/reported_residual",recorded["lmdi_identity_residual"],0,absolute=.002)
    return contributions


def audit_supply_summary(label, recorded, pairs, start, end):
    check(label+"/n",recorded["pairs"],len(pairs))
    if not pairs:
        return
    sums = {str(y):quantities([math.fsum(r["years"][str(y)][key] for r in pairs.values())
                              for key in ("passengers","seats","flights")]) for y in (start,end)}
    for year, values in sums.items():
        for key, expected in values.items():
            check(label+"/aggregate/"+year+"/"+key,recorded["aggregates"][year][key],expected)
    audit_decomposition(label+"/decomposition", recorded["aggregate_decomposition"],sums[str(start)],sums[str(end)])
    contributions = defaultdict(list)
    changes = defaultdict(list)
    for row in pairs.values():
        a,b = row["years"][str(start)],row["years"][str(end)]
        logp=math.log(b["passengers"]/a["passengers"])
        lm=(b["passengers"]-a["passengers"])/logp if abs(logp)>1e-12 else a["passengers"]
        for k in ("flights","seats_per_flight","load_factor"):
            contributions[k].append(lm * (math.log(b[k])-math.log(a[k])))
            changes[k].append(b[k]/a[k]-1)
        changes["passengers"].append(b["passengers"]/a["passengers"]-1)
    for key, vals in contributions.items():
        check(label+"/within_lmdi/"+key,recorded["within_pair_lmdi_passenger_contributions_summed"][key],math.fsum(vals),absolute=.002)
    check(label+"/within_identity",sum(map(math.fsum,contributions.values())),sums[str(end)]["passengers"]-sums[str(start)]["passengers"],absolute=.002)
    check(label+"/within_reported_residual",recorded["within_pair_identity_residual"],0,absolute=.002)
    expected={
        "median_seats_per_flight_change":statistics.median(changes["seats_per_flight"]),
        "median_flights_change":statistics.median(changes["flights"]),
        "median_passengers_change":statistics.median(changes["passengers"]),
        "seats_per_flight_increased":sum(v>0 for v in changes["seats_per_flight"]),
        "seats_per_flight_increased_over_5pct":sum(v>.05 for v in changes["seats_per_flight"]),
        "flights_decreased":sum(v<0 for v in changes["flights"]),
        "larger_average_with_fewer_flights":sum(s>0 and f<0 for s,f in zip(changes["seats_per_flight"],changes["flights"]))}
    for key,value in expected.items():
        check(label+"/within/"+key,recorded["within_pair"][key],value)


def audit_supply():
    data=read("route_evolution.json")
    derived=read("route_evolution_pairs.json.gz")["pairs"]
    for row in data["inputs"]:
        check("hash/"+row["path"],row["sha256"],sha(HERE/row["path"]))
    check("hash/derived_supply",data["derived_pairs"]["sha256"],sha(OUT/"route_evolution_pairs.json.gz"))
    annual, disagreement, rejections=audit_supply_inputs()
    matched, exclusions=supply_cohort(annual,[2015,2019,2024],disagreement)
    relaxed, relaxed_exclusions=supply_cohort(annual,[2015,2019,2024],set())
    check("supply/annual_rejections",data["annual_reporter_rejections_by_first_reason"],rejections)
    check("supply/main_exclusions",data["main_pair_exclusions_by_first_reason"],exclusions)
    check("supply/relaxed_exclusions",data["relaxed_pair_exclusions_by_first_reason"],relaxed_exclusions)
    check("supply/main_count",data["main_pairs"],len(matched))
    check("supply/relaxed_count",data["relaxed_pairs"],len(relaxed))
    check("supply/derived_membership",set(derived),set(matched))
    airports=json.loads((HERE.parent/"routes-2026-11/out/airports.json").read_text())
    for pair, row in matched.items():
        check("supply/fixed_reporters",derived[pair]["reporters"],row["reporters"])
        for year, totals in row["years"].items():
            for key,value in totals.items():
                check("supply/annual_quantity",derived[pair]["years"][year][key],value)
        a,b=pair.split("-")
        distance=None
        if a in airports and b in airports:
            p1,p2=map(math.radians,(airports[a][0],airports[b][0]))
            dl=math.radians(airports[b][1]-airports[a][1])
            cos_angle=math.sin(p1)*math.sin(p2)+math.cos(p1)*math.cos(p2)*math.cos(dl)
            distance=6371.0088*math.acos(max(-1,min(1,cos_angle)))
        row["distance_km"]=distance
        check("supply/distance",derived[pair]["distance_km"],distance,absolute=.001)
    check("supply/coordinate_coverage",data["main_pairs_with_coordinates"],sum(r["distance_km"] is not None for r in matched.values()))
    for p in data["periods"]:
        start,end=p["start"],p["end"]
        audit_supply_summary(f"supply/main{start}_{end}",p,matched,start,end)
        audit_supply_summary(f"supply/relaxed{start}_{end}",p["same_cohort_relaxed_reporter_disagreement"],relaxed,start,end)
        pairwise, reasons=supply_cohort(annual,[start,end],disagreement)
        audit_supply_summary(f"supply/pairwise{start}_{end}",p["pairwise_endpoint_cohort_sensitivity"],pairwise,start,end)
        check("supply/pairwise_exclusions",p["pairwise_endpoint_cohort_sensitivity"]["exclusions"],reasons)
    bands={"under100":(0,100),"100to149":(100,150),"150to199":(150,200),"200plus":(200,float("inf")),
           "under1500km":(0,1500),"1500to4000km":(1500,4000),"4000to6500km":(4000,6500),"6500pluskm":(6500,float("inf"))}
    for category in ("by_2015_capacity","by_distance"):
        for group in data[category]:
            lo,hi=bands[group["group"]]
            subset={p:r for p,r in matched.items() if (
                r["distance_km"] is not None and lo<=r["distance_km"]<hi if category=="by_distance"
                else lo<=r["years"]["2015"]["seats_per_flight"]<hi)}
            for p in group["periods"]:
                audit_supply_summary("supply/"+group["group"],p,subset,p["start"],p["end"])
    return {"input_pairs":len(annual),"main_pairs":len(matched),"relaxed_pairs":len(relaxed),
            "main_pairs_with_coordinates":sum(r["distance_km"] is not None for r in matched.values()),
            "excluded_main_fraction":1-len(matched)/len(annual)}


def main():
    forecasts=audit_forecasts()
    supply=audit_supply()
    inputs=["forecast_benchmark.py","route_evolution.py","out/forecast_benchmark.json",
            "out/forecast_benchmark_cases.json.gz","out/route_evolution.json","out/route_evolution_pairs.json.gz"]
    report={
        "checked_on":"2026-11-11", "independent_of_modelling_author":True,
        "status":"fail" if FAILURES else "pass_with_limitations",
        "method":"Separate implementation, no imports from forecast_benchmark.py or route_evolution.py; recomputed from pinned monthly panels.",
        "checks":dict(CHECKS),"checks_total":sum(CHECKS.values()),"failure_count":len(FAILURES),"failures":FAILURES[:100],
        "inputs_sha256":{rel:sha(HERE/rel) for rel in inputs},
        "forecast_experiments":forecasts,"supply":supply,
        "limitations":[
            "Current-vintage archives: historical publication dates and revisions are not reconstructed. A one-year availability lag is a declared sensitivity, not evidence of the real historical release schedule.",
            "Forecast scores condition on complete clean observable target years. Missing exits, entrants and incomplete targets remain unscored, not zero.",
            "Main 10-year experiment with lag=1 has targets only in 2020–2024; no pre-pandemic holdout and no calibrated intervals.",
            "Empirical interval coverage is tested on past-only calibration outcomes, but overlapping origins and repeated routes prevent an independence or distribution-free guarantee.",
            "The baseline experiment does not test the production P/T/F model, explanatory factors, unseen routes or future 2029/2031/2036 forecasts.",
            "Supply decomposition uses a retrospective balanced survivor cohort and fixed reporters; it is descriptive, not a causal forecast of route entry or aircraft purchases.",
            "Seats per flight is an average over aircraft and cabin configurations. It cannot identify a winning type or airline business model.",
            "Audit checks archived inputs and derived arithmetic; it does not reopen all original Eurostat observations or validate current-aircraft capability claims."
        ]}
    (Path(__file__).parent/"modelling_0057.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,default=lambda x:sorted(x))+"\n")
    print(report["status"],report["checks_total"],"checks;",len(FAILURES),"failures")
    if FAILURES:
        print(json.dumps(FAILURES[:8],ensure_ascii=False,default=lambda x:sorted(x),indent=2))
        raise SystemExit(1)


if __name__=="__main__":
    main()
