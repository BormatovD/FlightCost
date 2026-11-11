#!/usr/bin/env python3
"""Collect bounded public research panels; keep all raw responses outside git.

The current Eurostat endpoint can return an HTML maintenance page with HTTP 200.
That is a failed request, not an empty dataset. The explicitly identified DBnomics
archive is a separate access channel with its own source/update/index timestamps.
No application database, production models, private inputs or paid APIs are used.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sys
from urllib.parse import urlencode
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
CHECKED_ON = "2026-11-11"
BASE = "https://api.db.nomics.world/v22/series/Eurostat/"
REPORTERS = ("de", "es", "fr", "it", "nl")
SINCE = "2005-01"
MAX_FILE_BYTES = 50_000_000
PER_PAGE = 1000
PUBLIC_URLS = {
    "india_domestic": "https://raw.githubusercontent.com/Vonter/india-aviation-traffic/main/aggregated/domestic/city.csv",
    "india_international": "https://raw.githubusercontent.com/Vonter/india-aviation-traffic/main/aggregated/international/city.csv",
    "india_commit": "https://api.github.com/repos/Vonter/india-aviation-traffic/commits?path=aggregated/domestic/city.csv&per_page=1",
    "visa": "https://raw.githubusercontent.com/imorte/passport-index-data/main/passport-index-tidy-iso2.csv",
    "visa_commit": "https://api.github.com/repos/imorte/passport-index-data/commits?path=passport-index-tidy-iso2.csv&per_page=1",
    "visa_legacy_catalog": "https://api.github.com/repos/ilyankou/passport-index-dataset/git/trees/master?recursive=1",
    "wb_history": "https://api.worldbank.org/v2/country/all/indicator/SP.POP.TOTL;NY.GDP.PCAP.PP.KD;ST.INT.ARVL?source=2&format=json&per_page=20000&date=2005:2025",
    "wb_country_meta": "https://api.worldbank.org/v2/country?format=json&per_page=400",
    "wpp_catalog": "https://population.un.org/wpp/assets/downloads.json",
    "wpp_population": "https://population.un.org/wpp/assets/Excel%20Files/1_Indicator%20(Standard)/CSV_FILES/WPP2024_TotalPopulationBySex.csv.gz",
    "wpp_togo_update": "https://population.un.org/wpp/assets/Excel%20Files/1_Indicator%20(Standard)/WPP2024_CSV_files_update.zip",
    "wpp_units": "https://population.un.org/wpp/assets/Excel%20Files/1_Indicator%20(Standard)/CSV_FILES/WPP2024_Demographic_Indicators_notes.csv",
    "imf_growth": "https://www.imf.org/external/datamapper/api/v1/NGDP_RPCH",
    "imf_population": "https://www.imf.org/external/datamapper/api/v1/LP",
    "imf_indicators": "https://www.imf.org/external/datamapper/api/v1/indicators",
}


def dump(path, value, compact=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, allow_nan=False,
                      **({"separators": (",", ":")} if compact else {"indent": 2})) + "\n"
    if path.suffix == ".gz":
        path.write_bytes(gzip.compress(text.encode(), mtime=0))
    else:
        path.write_text(text, encoding="utf-8")


def read(raw, name):
    return json.loads((raw / (name + ".raw")).read_bytes())


def provenance(raw, name):
    path = raw / (name + ".raw")
    meta_path = raw / (name + ".meta.json")
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    return {"cache_name": name, "url": meta.get("url"), "http_status": meta.get("status"),
            "retrieved_on": meta.get("retrieved_on", CHECKED_ON),
            "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def fetch(raw, name, url, refresh=False):
    path = raw / (name + ".raw")
    if path.exists() and not refresh:
        return path
    import requests
    fetched = datetime.now(timezone.utc).isoformat()
    with requests.get(url, timeout=(10, 50), stream=True) as response:
        data, size = [], 0
        for chunk in response.iter_content(1024 * 1024):
            size += len(chunk)
            if size > MAX_FILE_BYTES:
                raise ValueError(f"{name}: response exceeds the 50 MB per-file budget")
            data.append(chunk)
        blob = b"".join(data)
        path.write_bytes(blob)
        dump(raw / (name + ".meta.json"), {"url": response.url, "status": response.status_code,
             "bytes": size, "sha256": hashlib.sha256(blob).hexdigest(),
             "retrieved_at": fetched, "retrieved_on": CHECKED_ON,
             "content_type": response.headers.get("Content-Type"),
             "last_modified": response.headers.get("Last-Modified")})
        response.raise_for_status()
    return path


def mirror(raw, name, dataset, dimensions, refresh=False):
    """Download all pages, failing if paging or the advertised total changes."""
    result = []
    offset, total = 0, None
    while total is None or offset < total:
        params = {"limit": PER_PAGE, "offset": offset, "observations": 1,
                  "dimensions": json.dumps(dimensions, separators=(",", ":"))}
        url = BASE + dataset + "?" + urlencode(params)
        page_name = f"{name}_{offset:05d}"
        data = json.loads(fetch(raw, page_name, url, refresh).read_bytes())
        if not isinstance(data.get("series"), dict):
            raise ValueError(f"{page_name}: not a DBnomics series response")
        series = data["series"]
        found = series["num_found"]
        if total is not None and total != found:
            raise ValueError(f"{name}: dataset changed during pagination")
        total = found
        docs = series.get("docs", [])
        if not docs and offset < total:
            raise ValueError(f"{name}: truncated pagination")
        result.append(page_name)
        offset += len(docs)
        print(f"{name}: {offset}/{total}", flush=True)
        if total == 0:
            break
    return result


def mirror_pages(raw, prefix):
    paths = sorted(raw.glob(prefix + "_[0-9][0-9][0-9][0-9][0-9].raw"))
    docs, sources, datasets = [], [], []
    for path in paths:
        document = json.loads(path.read_bytes())
        docs.extend(document["series"]["docs"])
        source = provenance(raw, path.stem)
        dataset = document.get("dataset", {})
        source.update({"source_updated_at": dataset.get("updated_at"),
                       "mirror_indexed_at": dataset.get("indexed_at"),
                       "provider": "Eurostat", "access_channel": "DBnomics archive"})
        sources.append(source)
        datasets.append(dataset)
    if paths:
        expected = json.loads(paths[0].read_bytes())["series"]["num_found"]
        codes = [s["series_code"] for s in docs]
        if len(docs) != expected or len(set(codes)) != expected:
            raise ValueError(f"{prefix}: incomplete or duplicated pages")
    return docs, sources, datasets


def number(value):
    if value is None or value in ("NA", "", ":"):
        return None
    value = float(value)
    if not math.isfinite(value) or value < 0:
        return None
    return value


def numeric_series(series):
    if len(series["period"]) != len(series["value"]):
        raise ValueError("period/value length mismatch")
    return [(period, number(value)) for period, value in zip(series["period"], series["value"])]


def annual_coverage(panel, periods_per_year):
    """Only observed rows count; missing periods are never converted to zeros."""
    years = defaultdict(lambda: defaultdict(list))
    periods = defaultdict(set)
    for pair, rows in panel.items():
        for period, value in rows:
            years[period[:4]][pair].append(value)
            periods[period[:4]].add(period)
    out = {}
    for year, pairs in sorted(years.items()):
        full = {pair: sum(values) for pair, values in pairs.items() if len(values) == periods_per_year}
        expected = {f"{year}-{i:02d}" for i in range(1, 13)} if periods_per_year == 12 else \
                   {f"{year}-Q{i}" for i in range(1, 5)}
        out[year] = {"periods_in_source": len(periods[year]), "pairs_any_observed": len(pairs),
                     "observed_periods": sorted(periods[year]),
                     "periods_absent_entire_extract": sorted(expected - periods[year]),
                     "pair_periods": sum(map(len, pairs.values())), "pairs_full_year": len(full),
                     "pairs_full_year_positive": sum(v > 0 for v in full.values()),
                     "pairs_full_year_zero": sum(v == 0 for v in full.values()),
                     "pairs_partial_year": len(pairs) - len(full)}
    return out


def backtest_eligibility(panel, periods_per_year, min_history_years=5):
    """Coverage audit, not model scores: train cohort is fixed at each origin.

    A complete target is counted AFTER forming the eligible origin cohort. Missing
    targets and observed zero targets remain separate, not silent route closures.
    With five complete training years a ten-year horizon needs fifteen years.
    """
    per_pair = {}
    for pair, rows in panel.items():
        by = defaultdict(list)
        for period, value in rows:
            by[int(period[:4])].append(value)
        per_pair[pair] = {y: sum(vs) for y, vs in by.items() if len(vs) == periods_per_year}
    years = sorted({y for values in per_pair.values() for y in values})
    result = {}
    for horizon in (3, 5, 10):
        origins = []
        for origin in years:
            target = origin + horizon
            if target > max(years):
                continue
            train_years = set(range(origin - min_history_years + 1, origin + 1))
            cohort = {p: ys for p, ys in per_pair.items() if train_years <= ys.keys()}
            if not cohort:
                continue
            available = {p: ys[target] for p, ys in cohort.items() if target in ys}
            origins.append({"origin_year": origin, "target_year": target,
                            "train_years": sorted(train_years), "eligible_origin_pairs": len(cohort),
                            "complete_target_pairs": len(available),
                            "target_missing_or_incomplete": len(cohort) - len(available),
                            "target_observed_zero": sum(v == 0 for v in available.values()),
                            "target_positive": sum(v > 0 for v in available.values())})
        result[str(horizon)] = {"n_origins": len(origins), "origins": origins,
                               "sum_complete_pair_targets": sum(x["complete_target_pairs"] for x in origins)}
    return {"minimum_complete_training_years": min_history_years, "unit": "calendar-year flow",
            "origin_role": "last complete observation year; not a certified publication information cutoff",
            "zero_policy": "explicit reported zeros retained; absent or partial years are unscorable, not zero",
            "availability": "latest archive vintage; origin-year values are not proof of publication availability",
            "horizons": result}


def route_panel(raw, out):
    by_pair = defaultdict(lambda: defaultdict(dict))
    month_flags = defaultdict(lambda: defaultdict(set))
    sources, countries, flags = [], {}, Counter()
    pair_countries = {}
    excluded_reasons, exclusion_labels = defaultdict(set), defaultdict(set)
    # The provider's labels identify these as control areas/centres, not airports.
    # Do not reject every label containing FIR: e.g. UNNN also names an airport.
    control_areas = {"ENOS", "ESMM", "SKED", "EDVV", "LMMM", "HKNA", "LECP"}
    administrative_locations = {"ENCA", "SABA", "SCSC"}
    absent_values = 0
    for cc in REPORTERS:
        series, meta, datasets = mirror_pages(raw, "routes_" + cc)
        if not series:
            continue
        sources.extend(meta)
        countries[cc.upper()] = {"series": len(series), "source_updated_at": datasets[0].get("updated_at"),
                                "mirror_indexed_at": datasets[0].get("indexed_at")}
        for s in series:
            dims = s["dimensions"]
            if dims["freq"] != "M" or dims["unit"] != "PAS" or dims["tra_meas"] != "PAS_CRD":
                raise ValueError("wrong airport flow definition")
            m = re.fullmatch(r"([A-Z]{2})_([A-Z0-9]{4})_([A-Z]{2})_([A-Z0-9]{4})", dims["airp_pr"])
            if not m:
                raise ValueError("unexpected airport pair code")
            reporter, partner = m.group(2), m.group(4)
            pair = "-".join(sorted((reporter, partner)))
            label = datasets[0].get("dimensions_values_labels", {}).get("airp_pr", {}).get(dims["airp_pr"], s["series_name"])
            if reporter == partner:
                excluded_reasons[pair].add("self_pair")
            if re.search(r"\bunknown\b", label, re.I) or "ZZZZ" in (reporter, partner):
                excluded_reasons[pair].add("unknown_airport")
            if re.search(r"\bairport system\b", label, re.I):
                excluded_reasons[pair].add("airport_system")
            if {reporter, partner} & control_areas:
                excluded_reasons[pair].add("airspace_control_area")
            if {reporter, partner} & administrative_locations:
                excluded_reasons[pair].add("administrative_location")
            if "ZSSA" in (reporter, partner):
                excluded_reasons[pair].add("city_location_needs_airport_identity")
            if excluded_reasons[pair]:
                exclusion_labels[pair].add(label)
            geography = {reporter: m.group(1), partner: m.group(3)}
            for airport, country in geography.items():
                pair_countries.setdefault(pair, {}).setdefault(airport, set()).add(country)
            quality = {}
            for attr, values in s.get("observations_attributes", []):
                if attr == "OBS_FLAG":
                    values = values if isinstance(values, list) else [values] * len(s["period"])
                    quality = dict(zip(s["period"], values))
            for period, value in numeric_series(s):
                if period < SINCE or period > CHECKED_ON[:7]:
                    continue
                if value is None:
                    absent_values += 1
                    continue
                observations = by_pair[pair][period]
                if reporter in observations and observations[reporter] != value:
                    raise ValueError("conflicting repeated airport reporter")
                observations[reporter] = value
                if quality.get(period):
                    month_flags[pair][period].add(str(quality[period]))
                    flags[str(quality[period])] += 1
    if not by_pair:
        return {"status": "unavailable", "sources": sources}
    compact, simple = {}, {}
    disagreement = Counter()
    all_months, airports = set(), set()
    for pair, months in sorted(by_pair.items()):
        airports.update(pair.split("-"))
        compact[pair], simple[pair] = [], []
        for month, reports in sorted(months.items()):
            vals = list(reports.values())
            value = sum(vals) / len(vals)
            spread = (max(vals) - min(vals)) / value if value else 0.0
            compact[pair].append([month, value, len(reports), round(spread, 6),
                                  ";".join(sorted(month_flags[pair][month])) or None,
                                  ";".join(sorted(reports))])
            simple[pair].append([month, value])
            all_months.add(month)
            disagreement["one_reporter" if len(reports) == 1 else "two_reporters"] += 1
            if len(reports) > 1 and spread > 0.1:
                disagreement["two_reporters_spread_above_10pct"] += 1
    all_pair_count, all_pair_months = len(compact), sum(map(len, compact.values()))
    excluded = {p: {"reasons": sorted(excluded_reasons[p]), "source_labels": sorted(exclusion_labels[p]),
                    "rows": rows} for p, rows in compact.items() if excluded_reasons[p]}
    dump(out / "eu_excluded_groups.json.gz", {"schema_version": 1,
         "columns": ["month", "pax", "reporters", "relative_reporter_spread", "source_flags_union", "reporter_airports"],
         "quantity": "source-reported passengers, excluded from airport-pair model coverage",
         "reason": "unknown locations, airport systems, control areas and self-pairs are not specific airport pairs",
         "groups": excluded}, compact=True)
    compact = {p: rows for p, rows in compact.items() if not excluded_reasons[p]}
    simple = {p: rows for p, rows in simple.items() if p in compact}
    airports = {a for p in compact for a in p.split("-")}
    disagreement = Counter()
    for rows in compact.values():
        for _, _, n, spread, *_ in rows:
            disagreement["one_reporter" if n == 1 else "two_reporters"] += 1
            if n > 1 and spread > .1:
                disagreement["two_reporters_spread_above_10pct"] += 1
    reference = json.loads((ROOT / "research/routes-2026-11/out/airports.json").read_text())
    unknown = sorted(airports - reference.keys())
    descriptor = {"schema_version": 1, "source_family": "Eurostat avia_par_* via DBnomics archive",
                  "quantity": "PAS_CRD on-flight airport-pair passengers, both directions",
                  "unit": "passengers per calendar month", "definition_excludes": "true journey O&D and flight-stage PAS_BRD",
                  "columns": ["month", "pax", "reporters", "relative_reporter_spread", "source_flags_union", "reporter_airports"],
                  "aggregation": "arithmetic mean of distinct reporting-airport observations; never sum counterpart reports",
                  "reporting_country_cohort": list(countries), "source_metadata": countries,
                  "pair_country_codes_as_published": {p: {a: sorted(cs) for a, cs in geography.items()}
                                                       for p, geography in sorted(pair_countries.items()) if p in compact},
                  "missing_policy": "NA omitted, explicit zero retained, no interpolation",
                  "pairs": compact}
    dump(out / "eu_monthly_panel.json.gz", descriptor, compact=True)
    coverage = {"status": "collected_archive", "pair_months": sum(map(len, simple.values())),
                "all_source_pairs": all_pair_count, "all_source_pair_months": all_pair_months,
                "excluded_non_airport_pairs": len(excluded),
                "excluded_pair_months": sum(len(x["rows"]) for x in excluded.values()),
                "exclusion_reason_counts": dict(Counter(r for x in excluded.values() for r in x["reasons"])),
                "pairs": len(simple), "airports": len(airports), "first_month": min(all_months),
                "last_month": max(all_months), "reporting_countries": countries,
                "year_coverage": annual_coverage(simple, 12), "reporter_agreement": dict(disagreement),
                "missing_values_in_series": absent_values, "source_flags_all_input_series": dict(flags),
                "airports_missing_current_reference": unknown,
                "coordinate_policy": "no historical route is filtered for missing current coordinates",
                "readiness": backtest_eligibility(simple, 12), "sources": sources,
                "limitations": ["Five reporting countries, not a census of all European or world pairs.",
                                "Archive latest period and vintage differ; retrieval date is not observation date.",
                                "Missing route-month may be non-operation, non-publication or a definition change.",
                                "Seats, flights and fares are not in this passenger-only collection.",
                                "Current country/airport coding does not resolve all historic boundary or closure changes."]}
    # A fixed illustration, not selected for a favourable model result.
    coverage["example"] = {"pair": "EDDF-LEBL", "annual": {}}
    by_year = defaultdict(list)
    for month, value in simple.get("EDDF-LEBL", []):
        by_year[month[:4]].append(value)
    for y, vs in sorted(by_year.items()):
        coverage["example"]["annual"][y] = {"months": len(vs), "pax": sum(vs) if len(vs) == 12 else None}
    markets = defaultdict(lambda: {"historical_pairs": 0, "pairs_full_2024": 0, "pax_full_2024": 0})
    for pair, rows in simple.items():
        market = "-".join(sorted("/".join(sorted(cs)) for cs in pair_countries[pair].values()))
        markets[market]["historical_pairs"] += 1
        recent = [v for period, v in rows if period.startswith("2024-")]
        if len(recent) == 12:
            markets[market]["pairs_full_2024"] += 1
            markets[market]["pax_full_2024"] += sum(recent)
    coverage["markets"] = dict(sorted(markets.items()))
    coverage["n_markets"] = len(markets)
    coverage["ambiguous_source_country_codes"] = {
        p: {a: sorted(cs) for a, cs in airports.items() if len(cs) > 1}
        for p, airports in sorted(pair_countries.items()) if any(len(cs) > 1 for cs in airports.values())}
    return coverage


def regional_panel(raw, out):
    units = {"gdp": "PPS EU27_2020 per inhabitant", "pop": "persons on 1 January",
             "emp": "thousand employed persons aged 15-74", "nights": "accommodation nights per month"}
    records, summaries = [], {}
    for name in units:
        series, sources, datasets = mirror_pages(raw, "regions_" + name)
        by_year, regions, periods, observed, flag_counts = Counter(), set(), set(), 0, Counter()
        for s in series:
            dims = s["dimensions"]
            quality = {}
            for attr, values in s.get("observations_attributes", []):
                if attr == "OBS_FLAG":
                    values = values if isinstance(values, list) else [values] * len(s["period"])
                    quality = dict(zip(s["period"], values))
            for period, value in numeric_series(s):
                if value is None or period < "2005" or period > CHECKED_ON[:4]:
                    continue
                flag = quality.get(period) or None
                if name == "nights":
                    if dims.get("month") not in {f"M{m:02d}" for m in range(1, 13)}:
                        raise ValueError("annual TOTAL is not a tourism month")
                    period += "-" + dims["month"][1:]
                    feature = "nights_" + dims["c_resid"]
                elif name == "emp":
                    feature = "employment_" + dims["nace_r2"]
                else:
                    feature = name
                records.append([dims["geo"], period, feature, value, flag])
                if flag:
                    flag_counts[flag] += 1
                observed += 1
                by_year[period[:4]] += 1
                regions.add(dims["geo"])
                periods.add(period)
        summaries[name] = {"status": "collected_archive" if observed else "unavailable",
                           "observations": observed, "regions": len(regions), "region_codes": sorted(regions),
                           "first_period": min(periods) if periods else None, "last_period": max(periods) if periods else None,
                           "by_year": dict(sorted(by_year.items())), "unit": units[name], "sources": sources}
        summaries[name]["source_flags"] = dict(flag_counts)
    dump(out / "regional_history.json.gz", {
        "schema_version": 1, "columns": ["region", "period", "indicator", "value", "source_flags"],
        "units": units, "source_family": "Eurostat via DBnomics archive",
        "geography_selection": "NUTS2 codes assigned to current reference airports with GISCO 2024 polygons in patch 0055",
        "geography_warning": "code matching does not prove constant historical boundaries; no harmonisation performed",
        "employment_warning": "the published M_N is combined; requesting separate M and N yields no such series",
        "tourism_warning": "TOTAL and FOR cover accommodation nights and all arrival modes, not air arrivals",
        "records": sorted(records)}, compact=True)
    return summaries


def india_panel(raw, out, name, quarterly=False):
    path = raw / (name + ".raw")
    groups = defaultdict(list)
    raw_rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    for row in raw_rows:
        year = int(row["Year"])
        if year < 100:
            year += 2000
        period = f"{year}-Q{int(row['Quarter'])}" if quarterly else f"{year}-{int(row['Month']):02d}"
        a, b = (row["City1"].strip().upper(), row["City2"].strip().upper())
        va, vb = number(row["PaxToCity2"]), number(row["PaxFromCity2"])
        if a > b:
            a, b, va, vb = b, a, vb, va
        groups[(a + " | " + b, period)].append((va, vb))
    compact, simple = defaultdict(list), defaultdict(list)
    quality = Counter()
    periods = set()
    for (pair, period), values in sorted(groups.items()):
        unique = set(values)
        if any(a is None or b is None for a, b in unique):
            value, status = None, "missing_direction"
        elif len(unique) > 1:
            value, status = None, "conflicting_duplicate"
        else:
            a, b = next(iter(unique))
            value, status = a + b, "deduplicated_identical" if len(values) > 1 else "observed"
        compact[pair].append([period, value, len(values), status])
        quality[status] += 1
        if value is not None:
            simple[pair].append([period, value])
        periods.add(period)
    doc = {"schema_version": 1, "source": "DGCA, public assembly by Vonter/india-aviation-traffic",
           "license": "ODbL 1.0; adapted panel remains ODbL 1.0, attribution DGCA and Vonter",
           "geographic_unit": "source city labels, sometimes refined to airport-labelled subdivisions",
           "unit": "passengers per calendar quarter" if quarterly else "passengers per calendar month",
           "columns": ["period", "pax_both_directions", "source_rows", "quality"],
           "normalisation": "uppercase and whitespace only; city labels are not assigned to a main airport",
           "duplicate_policy": "identical aligned directional records deduplicated; conflicting totals unresolved and excluded from scoring",
           "missing_policy": "a missing direction is unknown, not zero; no missing period is filled",
           "pairs": dict(sorted(compact.items()))}
    dump(out / (name + "_panel.json.gz"), doc, compact=True)
    nperiods = 4 if quarterly else 12
    return {"status": "collected_public_assembly", "source": provenance(raw, name), "source_rows": len(raw_rows),
            "pairs": len(compact), "pair_periods": len(groups), "usable_pair_periods": sum(map(len, simple.values())),
            "first_period": min(periods), "last_period": max(periods), "quality": dict(quality),
            "year_coverage": annual_coverage(simple, nperiods), "readiness": backtest_eligibility(simple, nperiods),
            "limits": ["Source city labels change; no longitudinal city crosswalk applied yet.",
                       "A missing city pair is not zero demand or proven route closure.",
                       "Conflicting duplicate rows require checking against DGCA original reports.",
                       "Quarterly international observations are never interpolated to months."]}


def macro_history(raw, out):
    from flightcostapp.parsers import wb_wdi
    metadata = read(raw, "wb_country_meta")
    countries = {r["iso2Code"]: {"iso3": r["id"], "name": r["name"]} for r in metadata[1]
                 if r.get("region", {}).get("value") != "Aggregates"}
    doc = read(raw, "wb_history")
    if int(doc[0]["pages"]) != 1 or int(doc[0]["total"]) != len(doc[1]):
        raise ValueError("World Bank panel is paginated or incomplete")
    facts = wb_wdi.parse((raw / "wb_history.raw").read_bytes(), {"source_id": "wb_wdi"})
    rows, coverage = [], defaultdict(Counter)
    for fact in facts:
        _, country, indicator, year = fact.key.split("/")
        if country not in countries:
            continue
        rows.append([country, int(year), indicator, fact.value])
        coverage[indicator][year] += 1
    dump(out / "country_history.json.gz", {"schema_version": 1, "columns": ["country_iso2", "year", "indicator", "value"],
         "source": "World Bank WDI", "source_updated": doc[0].get("lastupdated"), "license": "CC BY 4.0",
         "units": {"gdp_pc_ppp": "constant 2021 international dollars per person", "pop": "persons",
                   "tourist_arrivals": "international arrivals per year, all transport modes"},
         "countries": countries, "records": sorted(rows)}, compact=True)
    return {"status": "collected", "source": provenance(raw, "wb_history"), "source_updated": doc[0].get("lastupdated"),
            "observations": len(rows), "countries": len({r[0] for r in rows}),
            "coverage_by_indicator_year": {k: dict(sorted(v.items())) for k, v in coverage.items()},
            "last_observation": {k: max(v) for k, v in coverage.items()},
            "classification": "historical observations/estimates, current revision; not source projections"}


def scenario_inputs(raw, out):
    targets = {2025, 2026, 2029, 2031, 2036}
    rows, coverage = [], defaultdict(Counter)
    with zipfile.ZipFile(raw / "wpp_togo_update.raw") as archive:
        blob = archive.read("WPP2024_TotalPopulationBySex_Medium_Update.csv")
    update_rows = list(csv.DictReader(io.StringIO(blob.decode("utf-8-sig"))))
    if {row["ISO2_code"] for row in update_rows} != {"TG"}:
        raise ValueError("unexpected geography in the documented Togo-only WPP correction")
    correction = {int(row["Time"]): number(row["PopTotal"]) for row in update_rows}
    replaced = 0
    with gzip.open(raw / "wpp_population.raw", "rt", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if not row["ISO2_code"] or row["Variant"] not in {"Medium", "Low", "High"}:
                continue
            year = int(row["Time"])
            if year not in targets:
                continue
            value = number(row["PopTotal"])
            if value is None:
                continue
            revision = "2024 base edition"
            warning = None
            if row["ISO2_code"] == "TG":
                if row["Variant"] == "Medium":
                    value = correction[year]
                    revision = "2026-01-19 Togo interim correction"
                    replaced += 1
                else:
                    warning = "Togo Low/High not revised with the January 2026 Medium correction; not comparable interval bounds"
            rows.append({"source": "UN WPP 2024", "country_iso2": row["ISO2_code"],
                         "country_iso3": row["ISO3_code"], "year": year, "variable": "population",
                         "scenario": row["Variant"], "value": value * 1000, "unit": "persons",
                         "reference_date": "1 July", "source_revision": revision,
                         "comparability_warning": warning, "kind": "source_projection"})
            coverage["WPP_" + row["Variant"]][str(year)] += 1
    indicators = read(raw, "imf_indicators")["indicators"]
    countries = {r["id"]: r["iso2Code"] for r in read(raw, "wb_country_meta")[1]
                 if r.get("region", {}).get("value") != "Aggregates"}
    for name, code in (("imf_growth", "NGDP_RPCH"), ("imf_population", "LP")):
        values = read(raw, name)["values"][code]
        for iso3, annual in values.items():
            if iso3 not in countries:
                continue
            for year, value in annual.items():
                # Annual trajectory is retained; target years alone cannot compound real growth.
                if not 2025 <= int(year) <= 2036:
                    continue
                rows.append({"source": indicators[code]["source"], "country_iso2": countries[iso3],
                             "country_iso3": iso3, "year": int(year), "variable": code, "scenario": "WEO central",
                             "value": value, "unit": indicators[code]["unit"],
                             "kind": "source_projection" if int(year) >= 2026 else "source_estimate_boundary_unverified"})
                coverage["WEO_" + code][year] += 1
    dump(out / "scenario_inputs.json.gz", {"schema_version": 1, "issue_year": 2026, "target_years": [2029, 2031, 2036],
         "records": sorted(rows, key=lambda r: (r["source"], r["country_iso3"], r["variable"], r["scenario"], r["year"])),
         "notes": ["External demographic/macroeconomic projections are inputs, not FlightCost route forecasts.",
                   "WPP Low/High are fertility variants, not 80/95% confidence bounds.",
                   "Togo Medium incorporates the January 2026 correction; its Low/High are explicitly flagged as unrevised.",
                   "IMF real GDP growth has not been extended beyond the source horizon.",
                   "WEO API lacks per-series latest actual year; 2025 is conservatively tagged estimate/actual boundary unverified.",
                   "WPP total population is multiplied by 1000; WEO LP remains in published millions."]}, compact=True)
    return {"status": "collected_external_projections", "records": len(rows),
            "coverage_by_source_variant_year": {k: dict(sorted(v.items())) for k, v in coverage.items()},
            "wpp_edition": "2024", "weo_edition": indicators["NGDP_RPCH"]["source"],
            "wpp_togo_correction": {"release_date": "2026-01-19", "medium_replaced_rows": replaced,
                                    "low_high": "unrevised, comparability warning attached"},
            "weo_last_modified": indicators["NGDP_RPCH"].get("last-modified"),
            "weo_2036_gdp_available": any(r["year"] == 2036 and r["variable"] == "NGDP_RPCH" for r in rows),
            "sources": [provenance(raw, n) for n in ("wpp_population", "wpp_catalog", "wpp_units", "wpp_togo_update",
                                                     "imf_growth", "imf_population", "imf_indicators")],
            "example_DE": [r for r in rows if r["country_iso2"] == "DE" and r["year"] in (2026, 2029, 2031, 2036)]}


def visa_panel(raw, out):
    paths = sorted(raw.glob("visa_20??-??-??.raw")) + [raw / "visa.raw"]
    rows, snapshots = [], []
    for path in paths:
        snapshot = "2026-02-17" if path.name == "visa.raw" else path.stem.removeprefix("visa_")
        seen, requirements = set(), Counter()
        for row in csv.DictReader(path.open(encoding="utf-8-sig")):
            a, b = row["Passport"].upper(), row["Destination"].upper()
            legacy = "Requirement" not in row
            value = (row.get("Requirement") if not legacy else row.get("Code", "")).strip().lower()
            if (a, b) in seen:
                raise ValueError("duplicate visa pair within snapshot")
            seen.add((a, b))
            if legacy:
                category = "legacy_code_unharmonised"
            elif a == b:
                category = "same_country"
            elif value.isdigit() or value == "visa free":
                category = "visa_free"
            elif value in {"visa on arrival", "eta", "e-visa", "visa required", "no admission", "covid ban", "hayya entry permit"}:
                category = value.replace(" ", "_")
            else:
                category = "unclassified"
            rows.append([snapshot, a, b, category, value])
            requirements[category] += 1
        snapshots.append({"snapshot_date": snapshot, "pairs": len(seen), "categories": dict(requirements),
                          "source": provenance(raw, path.stem)})
    dump(out / "visa_snapshots.json.gz", {"schema_version": 1,
         "columns": ["snapshot_date", "passport_iso2", "destination_iso2", "category", "source_requirement"],
         "classification": "dated collected snapshot, not a law-effective-date history",
         "source": "Passport Index datasets by ilyankou (2019-2025) and imorte (2026), MIT",
         "notes": ["Passport citizenship is not passenger residence or departure airport country.",
                   "2019/2020 Code fields are preserved, not interpreted as visa-free days; codebooks must be reconciled before modelling.",
                   "No backfilling a future snapshot into an earlier forecast origin.",
                   "ETA became a separate dataset category in January 2025; earlier e-visa includes some ETAs.",
                   "COVID bans and temporary Hayya permits remain distinct categories.",
                   "No interpolation of legal change dates between snapshots."], "records": rows}, compact=True)
    return {"status": "collected_dated_snapshots", "observations": len(rows), "snapshots": snapshots,
            "historical_start": min(s["snapshot_date"] for s in snapshots),
            "historical_end": max(s["snapshot_date"] for s in snapshots),
            "not_usable_before": min(s["snapshot_date"] for s in snapshots),
            "warning": "snapshot dates are observations of a curator, not certified dates laws took effect"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=HERE / "out")
    parser.add_argument("--fetch", default="", help="comma-separated: base,routes,regional,visa_history; or all")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    raw, out = args.raw_dir.resolve(), args.out.resolve()
    if raw == ROOT or ROOT in raw.parents:
        raise ValueError("raw responses must be outside the repository")
    raw.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    groups = set(args.fetch.split(","))
    if "all" in groups:
        groups = {"base", "routes", "regional", "visa_history"}
    if "base" in groups:
        for name, url in PUBLIC_URLS.items():
            fetch(raw, name, url, args.refresh)
    if "routes" in groups:
        def get_routes(cc):
            return mirror(raw, "routes_" + cc, "avia_par_" + cc,
                          {"freq": ["M"], "unit": ["PAS"], "tra_meas": ["PAS_CRD"]}, args.refresh)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(get_routes, REPORTERS))
    if "regional" in groups:
        region_doc = json.loads((HERE / "out/tourism_covariates.json").read_text())
        regions = sorted(set(region_doc["airport_region"].values()))
        configs = {
            "gdp": ("nama_10r_3gdp", {"freq": ["A"], "unit": ["PPS_EU27_2020_HAB"]}),
            "pop": ("demo_r_pjanaggr3", {"freq": ["A"], "unit": ["NR"], "age": ["TOTAL"], "sex": ["T"]}),
            "emp": ("lfst_r_lfe2en2", {"freq": ["A"], "unit": ["THS_PER"], "age": ["Y15-74"],
                                       "sex": ["T"], "nace_r2": ["TOTAL", "K", "M_N"]}),
            "nights": ("tour_occ_nin2m", {"unit": ["NR"], "c_resid": ["TOTAL", "FOR"], "nace_r2": ["I551-I553"],
                                         "month": [f"M{m:02d}" for m in range(1, 13)]}),
        }
        for name, (dataset, dims) in configs.items():
            mirror(raw, "regions_" + name, dataset, {**dims, "geo": regions}, args.refresh)
    if "visa_history" in groups:
        tree = read(raw, "visa_legacy_catalog")
        paths = [x["path"] for x in tree["tree"] if x["path"].startswith("legacy/")
                 and x["path"].endswith("/passport-index-tidy-iso2.csv")]
        # One dated snapshot per year, earliest available; no invented annual effective date.
        selected = {}
        for path in sorted(paths):
            selected.setdefault(path.split("/")[1][:4], path)
        for year, path in selected.items():
            fetch(raw, "visa_" + path.split("/")[1],
                  "https://raw.githubusercontent.com/ilyankou/passport-index-dataset/" + tree["sha"] + "/" + path,
                  args.refresh)
    result = route_panel(raw, out)
    summary = {"schema_version": 1, "checked_on": CHECKED_ON, "eu_routes": result,
               "regional": regional_panel(raw, out),
               "india_domestic": india_panel(raw, out, "india_domestic"),
               "india_international": india_panel(raw, out, "india_international", quarterly=True),
               "country_history": macro_history(raw, out), "scenario_inputs": scenario_inputs(raw, out),
               "visa": visa_panel(raw, out)}
    for name in ("india_commit", "visa_commit"):
        commit = read(raw, name)[0]
        summary["india_domestic" if name == "india_commit" else "visa"]["curator_latest_file_commit"] = {
            "sha": commit["sha"], "date": commit["commit"]["committer"]["date"], "url": commit["html_url"]}
    dump(out / "collection_summary.json", summary)
    entries = []
    for key, quantity, frequency in (
        ("eu_routes", "airport-pair PAS_CRD, both directions", "month"),
        ("india_domestic", "DGCA domestic city-pair passengers, both directions", "month"),
        ("india_international", "DGCA international city-pair passengers, both directions", "quarter"),
        ("country_history", "country population, GDP per capita PPP and tourism arrivals", "year"),
        ("scenario_inputs", "external population/GDP scenario drivers", "year"),
        ("visa", "directed passport-country requirement snapshot", "irregular snapshot")):
        entries.append({"id": key, "quantity": quantity, "frequency": frequency, "coverage": summary[key],
                        "record_class": "source_projection_and_estimate" if key == "scenario_inputs" else
                                        "dated_snapshot" if key == "visa" else "historical_observation_or_estimate"})
    for key, value in summary["regional"].items():
        entries.append({"id": "regional_" + key, "frequency": "month" if key == "nights" else "year",
                        "record_class": "historical_observation_or_estimate", "coverage": value})
    gaps = []
    for name, source_id in (("eurostat_bulk_de", "eurostat_direct_api"), ("regional_probe", "eurostat_direct_regional"),
                             ("un_migration_page", "un_migration_page"), ("un_migrants", "un_migration_candidate_xlsx"),
                             ("bts_2025", "bts_candidate_zip")):
        if not (raw / (name + ".raw")).exists():
            continue
        source = provenance(raw, name)
        prefix = (raw / (name + ".raw")).read_bytes()[:500]
        status = "failed_content_type" if source["http_status"] == 200 and b"<html" in prefix.lower() else \
                 "http_error" if source["http_status"] != 200 else "needs_revalidation"
        gaps.append({"id": source_id, "access_status": status, "source": source,
                     "interpretation": "access attempt failed; does not prove the entire publisher or dataset is unavailable"})
    artifacts = []
    for path in sorted(out.glob("*.json.gz")):
        artifacts.append({"file": path.name, "compressed_bytes": path.stat().st_size,
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "kind": "derived panel"})
    inventory = {"schema_version": 1, "collected_on": CHECKED_ON, "issue_year": 2026,
                 "target_years": {"3": 2029, "5": 2031, "10": 2036},
                 "entries": entries, "access_gaps": gaps, "derived_artifacts": artifacts,
                 "not_collected": ["UN bilateral migrant stock table", "BTS T-100 long history", "route fares and dated capacity constraints",
                                   "historical publication vintages for all predictors", "2036 GDP source projection"],
                 "next_minimal_server_request": {"script": "research/demand-2026-11/export_panel.py",
                       "traffic_since": "2024-01-01", "purpose": "latest 2024-2026 traffic, source states, current population catchments and macro facts",
                       "history_note": "production Eurostat/DGCA parsers retain 36 months per raw file; do not expect 2005 history in the server DB"},
                 "own_route_forecasts_created": False}
    dump(out / "data_inventory.json", inventory)
    print(json.dumps({"eu_pairs": result.get("pairs"), "eu_pair_months": result.get("pair_months"),
                      "eu_last_month": result.get("last_month")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
