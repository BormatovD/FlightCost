#!/usr/bin/env python3
"""Independent full-row supply audit, using normalized SQL source cells.

No collection code is imported. The raw HTTP cache and the temporary SQLite
database remain outside git. Airport exclusions are checked against the prior
audited identity decisions and explicit source labels; no traffic cutoff is used.
"""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import sqlite3

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "out"
MEASURES = {"PAS_BRD": ("pax", "PAS"), "ST_PAS": ("seats", "SEAT"), "CAF_PAS": ("flights", "FLIGHT")}


def load(path):
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.raw_dir, args.work_dir):
        if path.resolve().is_relative_to(HERE.parents[2]):
            raise SystemExit("Raw and verification cache must stay outside the repository")
    args.work_dir.mkdir(parents=True, exist_ok=True)
    db_path = args.work_dir / "supply-verification.sqlite3"
    if db_path.exists():
        db_path.unlink()
    db = sqlite3.connect(db_path)
    db.execute("PRAGMA journal_mode=OFF")
    db.execute("PRAGMA synchronous=OFF")
    db.execute("CREATE TABLE fact(pair TEXT, month TEXT, reporter TEXT, metric TEXT, value REAL, flag TEXT, PRIMARY KEY(pair,month,reporter,metric)) WITHOUT ROWID")
    summary = load(OUT / "supply_summary.json")
    previous = load(OUT / "eu_excluded_groups.json.gz")["groups"]
    failures, checks = [], {}

    def same(name, actual, stored):
        if actual != stored:
            failures.append({"check": name, "independent": actual, "stored": stored})

    def row_same(name, actual, stored, tolerance=5.1e-7):
        if len(actual) != len(stored):
            failures.append({"check": name, "problem": "column count"})
            return
        for i, (a, b) in enumerate(zip(actual, stored)):
            ok = math.isclose(a, b, rel_tol=1e-12, abs_tol=tolerance) if isinstance(a, (int,float)) and isinstance(b, (int,float)) else a == b
            if not ok and len(failures) < 50:
                failures.append({"check": name, "column": i, "independent": a, "stored": b})

    for artifact in summary["artifacts"]:
        path = OUT / artifact["file"]
        same("artifact hash:" + path.name, sha(path), artifact["sha256"])
        same("artifact size:" + path.name, path.stat().st_size, artifact["bytes"])
    source_map = {s["cache_name"]: s for s in summary["sources"]}
    raw_pages, raw_values, series_count, missing, labels = 0, 0, Counter(), Counter(), defaultdict(set)
    countries = {}
    for country in ("de", "es", "fr", "it", "nl"):
        seen, total = set(), None
        for path in sorted(args.raw_dir.glob(f"supply_{country}_[0-9][0-9][0-9][0-9][0-9].raw")):
            raw = load(path)
            metadata = load(path.with_suffix(".meta.json"))
            same("raw metadata hash:" + path.stem, sha(path), metadata["sha256"])
            same("raw source hash:" + path.stem, sha(path), source_map[path.stem]["sha256"])
            same("raw HTTP status:" + path.stem, metadata["status"], 200)
            same("raw source URL:" + path.stem, metadata["url"], source_map[path.stem]["url"])
            dataset = raw["dataset"]
            for key, source_key in (("updated_at", "source_updated_at"), ("indexed_at", "mirror_indexed_at")):
                same(path.stem + ":" + source_key, dataset.get(key), source_map[path.stem][source_key])
            if total is not None:
                same(country + ":pagination total", raw["series"]["num_found"], total)
            total = raw["series"]["num_found"]
            batch = []
            for series in raw["series"]["docs"]:
                if series["series_code"] in seen:
                    failures.append({"check": "duplicate source series", "code": series["series_code"]})
                seen.add(series["series_code"])
                dims = series["dimensions"]
                metric, unit = MEASURES[dims["tra_meas"]]
                same("frequency", dims["freq"], "M")
                same("unit:" + dims["tra_meas"], dims["unit"], unit)
                series_count[dims["tra_meas"]] += 1
                cc1, reporter, cc2, other = dims["airp_pr"].split("_")
                same("airport identity lengths", (len(cc1),len(reporter),len(cc2),len(other)), (2,4,2,4))
                pair = "-".join(sorted((reporter,other)))
                labels[pair].add(dataset["dimensions_values_labels"]["airp_pr"][dims["airp_pr"]])
                attrs = dict(series.get("observations_attributes", []))
                flags = attrs.get("OBS_FLAG", [None] * len(series["period"]))
                if not isinstance(flags, list):
                    flags = [flags] * len(series["period"])
                same("source attribute length", len(flags), len(series["period"]))
                same("source value length", len(series["value"]), len(series["period"]))
                for month, value, flag in zip(series["period"], series["value"], flags):
                    if not "2005-01" <= month <= "2026-11":
                        continue
                    if value in (None,"NA","",":"):
                        missing[dims["tra_meas"]] += 1
                        continue
                    value = float(value)
                    if not math.isfinite(value) or value < 0:
                        raise ValueError("invalid source value")
                    batch.append((pair, month, reporter, metric, value, metric + ":" + str(flag) if flag else None))
                    raw_values += 1
            db.executemany("INSERT INTO fact VALUES(?,?,?,?,?,?)", batch)
            raw_pages += 1
        same(country + ":complete series pagination", len(seen), total)
        countries[country.upper()] = len(seen)
        same(country + ":series count", len(seen), summary["reporting_countries"][country.upper()]["series"])
        db.commit()
    same("series totals", dict(series_count), summary["series"])
    same("missing source cells", dict(missing), summary["source_missing_values"])
    reasons = {}
    for pair, values in labels.items():
        why = set(previous.get(pair, {}).get("reasons", []))
        codes = set(pair.split("-"))
        if len(codes) == 1: why.add("self_pair")
        if "ZZZZ" in codes or any(re.search(r"\bunknown\b", label, re.I) for label in values): why.add("unknown_airport")
        if any(re.search(r"\bairport system\b", label, re.I) for label in values): why.add("airport_system")
        if codes.intersection({"ENOS","ESMM","SKED","EDVV","LMMM","HKNA","LECP"}): why.add("airspace_control_area")
        if codes.intersection({"ENCA","SABA","SCSC"}): why.add("administrative_location")
        if "ZSSA" in codes: why.add("city_location_needs_airport_identity")
        if why: reasons[pair] = sorted(why)
    db.execute("CREATE TABLE excluded(pair TEXT PRIMARY KEY)")
    db.executemany("INSERT INTO excluded VALUES(?)", [(p,) for p in reasons])
    db.execute("CREATE TABLE reporter AS SELECT pair,month,reporter, MAX(CASE WHEN metric='pax' THEN value END) AS pax, MAX(CASE WHEN metric='seats' THEN value END) AS seats, MAX(CASE WHEN metric='flights' THEN value END) AS flights, GROUP_CONCAT(flag,';') AS flags FROM fact GROUP BY pair,month,reporter")
    db.execute("CREATE INDEX reporter_key ON reporter(pair,month,reporter)")
    panel = load(OUT / "supply_reporter_panel.json.gz")
    expected_valid_pairs = {x[0] for x in db.execute("SELECT DISTINCT pair FROM reporter WHERE pair NOT IN (SELECT pair FROM excluded)")}
    same("valid pair set", sorted(expected_valid_pairs), sorted(panel["pairs"]))
    reporter_rows = 0
    for pair, stored_rows in panel["pairs"].items():
        expected = db.execute("SELECT month,reporter,pax,seats,flights,flags FROM reporter WHERE pair=? ORDER BY month,reporter", (pair,)).fetchall()
        same(pair + ":reporter row count", len(expected), len(stored_rows))
        for row, actual in zip(expected, stored_rows):
            row = list(row)
            row[-1] = ";".join(sorted(row[-1].split(";"))) if row[-1] else None
            row_same(pair + ":reporter:" + row[0] + ":" + row[1], row, actual)
            reporter_rows += 1
    del panel
    excluded = load(OUT / "supply_excluded_groups.json.gz")["groups"]
    expected_excluded = set(reasons).intersection({x[0] for x in db.execute("SELECT DISTINCT pair FROM reporter")})
    same("excluded pair set", sorted(expected_excluded), sorted(excluded))
    for pair, item in excluded.items():
        same(pair + ":exclusion reason", reasons[pair], item["reasons"])
        same(pair + ":source labels", sorted(labels[pair]), item["source_labels"])
        rows = db.execute("SELECT month,reporter,pax,seats,flights,flags FROM reporter WHERE pair=? ORDER BY month,reporter", (pair,)).fetchall()
        same(pair + ":excluded reporter row count", len(rows), len(item["reporter_rows"]))
        for row, actual in zip(rows, item["reporter_rows"]):
            row = list(row)
            row[-1] = ";".join(sorted(row[-1].split(";"))) if row[-1] else None
            row_same(pair + ":excluded:" + row[0], row, actual)
    del excluded
    pair_panel = load(OUT / "supply_pair_panel.json.gz")
    same("aggregate pair set", sorted(expected_valid_pairs), sorted(pair_panel["pairs"]))
    complete = "pax IS NOT NULL AND seats IS NOT NULL AND flights IS NOT NULL"
    db.execute(f"CREATE TABLE matched AS SELECT pair,month,AVG(CASE WHEN {complete} THEN pax END) AS pax,AVG(CASE WHEN {complete} THEN seats END) AS seats,AVG(CASE WHEN {complete} THEN flights END) AS flights,SUM({complete}) AS reporters,GROUP_CONCAT(CASE WHEN {complete} THEN reporter END,';') AS common,GROUP_CONCAT(flags,';') AS flags,MAX(pax) AS max_p,MIN(pax) AS min_p,AVG(pax) AS avg_p,MAX(seats) AS max_s,MIN(seats) AS min_s,AVG(seats) AS avg_s,MAX(flights) AS max_f,MIN(flights) AS min_f,AVG(flights) AS avg_f FROM reporter WHERE pair NOT IN (SELECT pair FROM excluded) GROUP BY pair,month")
    db.execute("CREATE INDEX matched_key ON matched(pair,month)")
    quality, year_counts = Counter(), defaultdict(Counter)
    pair_months = matched_months = 0
    for pair, stored_rows in pair_panel["pairs"].items():
        rows = db.execute("SELECT * FROM matched WHERE pair=? ORDER BY month", (pair,)).fetchall()
        same(pair + ":pair row count", len(rows), len(stored_rows))
        for row, actual in zip(rows, stored_rows):
            _, month, pax, seats, flights, count, common, flags, *spreads = row
            common = ";".join(sorted(common.split(";"))) if common else None
            flags = ";".join(sorted(set(flags.split(";")))) if flags else None
            lf = pax / seats if seats else None
            gauge = seats / flights if flights else None
            consistency = []
            if count and ((seats == 0 and pax > 0) or (flights == 0 and (seats > 0 or pax > 0))): consistency.append("positive_activity_with_zero_capacity_or_flights")
            if lf is not None and lf > 1: consistency.append("passengers_exceed_available_seats")
            if any(avg and (hi-lo)/avg > .1 for hi,lo,avg in zip(spreads[0::3],spreads[1::3],spreads[2::3])): consistency.append("reporter_disagreement_above_10pct")
            expected = [month,pax,seats,flights,lf,gauge,common,flags,";".join(consistency) or None]
            row_same(pair + ":aggregate:" + month, expected, actual)
            pair_months += 1
            year_counts[month[:4]]["pair_months_any_measure"] += 1
            if count:
                matched_months += 1
                year_counts[month[:4]]["pair_months_matched_triplet"] += 1
                quality["one_common_reporter" if count == 1 else "two_common_reporters"] += 1
            else: quality["no_complete_common_reporter"] += 1
            quality.update(consistency)
            if flags: quality["source_quality_flag_present"] += 1
    for year,count in db.execute("SELECT year,COUNT(*) FROM (SELECT pair,SUBSTR(month,1,4) AS year,COUNT(*) AS n FROM matched WHERE reporters>0 GROUP BY pair,year HAVING n=12) GROUP BY year"):
        year_counts[year]["pairs_with_12_matched_months"] = count
    same("year coverage", dict(year_counts), summary["year_coverage"])
    same("quality", dict(quality), summary["quality"])
    for key, value in (("pairs",len(expected_valid_pairs)),("reporter_month_rows",reporter_rows),("pair_months_any_measure",pair_months),("pair_months_matched_triplet",matched_months)):
        same(key, value, summary[key])
    for i,metric in enumerate(("pax","seats","flights")):
        count = db.execute(f"SELECT COUNT({metric}) FROM reporter WHERE pair NOT IN (SELECT pair FROM excluded)").fetchone()[0]
        same(metric + " source values", count, summary[metric + "_reporter_values"])
    same("first month", db.execute("SELECT MIN(month) FROM matched").fetchone()[0], summary["first_month"])
    same("last month", db.execute("SELECT MAX(month) FROM matched").fetchone()[0], summary["last_month"])
    for pair, years in summary["diagnostic_annual"].items():
        expected_years = {}
        for year, count, p,s,f in db.execute("SELECT SUBSTR(month,1,4),COUNT(*),SUM(pax),SUM(seats),SUM(flights) FROM matched WHERE pair=? AND reporters>0 GROUP BY SUBSTR(month,1,4) HAVING COUNT(*)=12",(pair,)):
            expected_years[year] = {"months":12,"pax_brd":p,"seats":s,"flights":f,"seat_load_factor":p/s if s else None,"seats_per_flight":s/f if f else None,"definition":"flight-stage, all three metrics from common reporters per month"}
        same(pair + ":annual diagnostics", expected_years, years)
    del pair_panel
    baseline = load(OUT / "eu_monthly_panel.json.gz")["pairs"]
    supply_pairs = expected_valid_pairs
    baseline_pairs = set(baseline)
    joined = 0
    for pair in supply_pairs & baseline_pairs:
        baseline_months = {r[0] for r in baseline[pair]}
        joined += sum(month in baseline_months for (month,) in db.execute("SELECT month FROM matched WHERE pair=?",(pair,)))
    expected_overlap = {"baseline_pairs":len(baseline_pairs),"pairs_with_both_datasets":len(supply_pairs & baseline_pairs),"supply_pairs_not_in_baseline":len(supply_pairs-baseline_pairs),"baseline_pairs_without_supply":len(baseline_pairs-supply_pairs),"matching_pair_month_keys":joined,"meaning":"key alignment only; PAS_CRD and PAS_BRD are different quantities"}
    same("PAS_CRD key overlap", expected_overlap, summary["overlap_with_pas_crd_panel"])
    primary_values = 0
    primary_empty_files = []
    for path in sorted(args.raw_dir.glob("supply_primary_*.raw")):
        raw = load(path)
        if raw.get("class") != "dataset":
            continue
        if not raw.get("value"):
            primary_empty_files.append(path.name)
            continue
        dims = raw["dimension"]
        code = next(iter(dims["airp_pr"]["category"]["index"]))
        _, reporter, _, other = code.split("_")
        pair = "-".join(sorted((reporter,other)))
        measure = next(iter(dims["tra_meas"]["category"]["index"]))
        metric, unit = MEASURES[measure]
        same("primary singleton axes", all(s == 1 for s in raw["size"][:-1]) and raw["id"][-1] == "time", True)
        same("primary unit", next(iter(dims["unit"]["category"]["index"])), unit)
        periods = {index:year for year,index in dims["time"]["category"]["index"].items()}
        for index,value in raw.get("value",{}).items():
            month = periods[int(index)]
            if "2005-01" <= month <= "2026-11":
                found = db.execute("SELECT value FROM fact WHERE pair=? AND month=? AND reporter=? AND metric=?",(pair,month,reporter,metric)).fetchone()
                same(f"primary:{pair}:{month}:{metric}", found[0] if found else None, value)
                primary_values += 1
    checks = {"raw_pages":raw_pages,"source_series":dict(series_count),"source_values":raw_values,"reporter_rows_checked":reporter_rows,"pair_months_checked":pair_months,"matched_triplets":matched_months,"primary_singleton_values_checked":primary_values,"primary_files_with_no_published_values":primary_empty_files,"quality":dict(quality),"PAS_CRD_key_overlap":expected_overlap}
    result = {"stage":"0056-v2","status":"pass_with_limitations" if not failures else "fail","independent":True,"summary_sha256":sha(OUT / "supply_summary.json"),"method":"Normalized SQL source cells, independent pivot and matched-reporting aggregate; all stored reporter and pair rows compared. No collector module imported.","checks":checks,"failures":failures,"limitations":["The five-country cohort and archive horizon are preserved; historical retrieval in 2026 is not current 2026 traffic.","Primary Eurostat singleton comparisons confirm the listed examples only. Full archive provenance remains explicitly DBnomics rather than a fresh primary bulk export.","PAS_BRD/ST_PAS is realized flight-stage occupancy. PAS_CRD is used only for key overlap, never as the occupancy numerator.","Nonphysical or inconsistent ratios remain flagged, not silently clipped or interpreted as unmet demand.","Aircraft type, airline, fare and within-day schedule are absent; gauge is seats per reported flight, not an identified aircraft type.","Airport identity exclusions are kept separate without a minimum-demand or survival filter."]}
    (HERE / "supply_0056_v2.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    db.close()
    print(result["status"],json.dumps(checks,ensure_ascii=False),"failures:",len(failures))


if __name__ == "__main__":
    main()
