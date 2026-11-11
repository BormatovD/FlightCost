#!/usr/bin/env python3
"""Bounded official Eurostat country-of-birth stocks for five residence countries.

Only migr_pop3ctb, DE/ES/FR/IT/NL, years 2005–2025, all ages, both sexes,
persons. Raw replies stay outside the repository. No API keys, login, access
workarounds, source substitutes, production writes or demand-model estimation.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import urlencode

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CHECKED_ON = "2026-11-11"
DATASET = "migr_pop3ctb"
REPORTERS = ("DE", "ES", "FR", "IT", "NL")
YEARS = tuple(range(2005, 2026))
BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/" + DATASET
METADATA = "https://ec.europa.eu/eurostat/cache/metadata/en/demo_pop_esms.htm"
MAX_RESPONSE_BYTES = 5_000_000
MAX_CELLS_PER_REPORTER = 10_000
HISTORICAL = {"AN", "CZ_SK", "RS_ME", "EX_YU", "EX_SU"}
SUBNATIONAL = {"FR91", "FR92", "FR93", "FR94"}
AGGREGATES = set("""
EUR EU28 EU27_2007 EU25 EU15 EU27_2020_FOR EU28_FOR EU27_2007_FOR EU25_FOR
EU15_FOR EFTA EFTA_FOR CC9_23_FOR CC8_22_FOR CC4_10 CC3_07 EXT HDC_EXT
MDC_EXT LDC_EXT NEU27_2020_FOR NEU28_FOR NEU27_2007_FOR EUR_OTH AFR AFR_C
AFR_E AFR_N AFR_S AFR_W AFR_OTH AME AME_N CRB AME_C AME_S AME_OTH ASI ASI_C
ASI_E ASI_S ASI_S_E ASI_W ASI_OTH OCE AU_NZ MEL MIC POL OCE_OTH FOR TOTAL
""".split())


def sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def json_bytes(value, *, compact=False) -> bytes:
    opts = {"separators": (",", ":")} if compact else {"indent": 2}
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, **opts) + "\n").encode()


def dump(path: Path, value, *, compact=False) -> None:
    blob = json_bytes(value, compact=compact)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(blob, mtime=0) if path.suffix == ".gz" else blob)


def url_for(reporter: str) -> str:
    if reporter not in REPORTERS:
        raise ValueError("Residence geography outside the agreed five-country scope")
    return BASE + "?" + urlencode({
        "lang": "EN", "geo": reporter, "sex": "T", "age": "TOTAL", "unit": "NR",
        "sinceTimePeriod": str(YEARS[0]), "untilTimePeriod": str(YEARS[-1]),
    })


def fetch(raw: Path, name: str, url: str, *, refresh=False) -> None:
    path, meta_path = raw / (name + ".raw"), raw / (name + ".meta.json")
    if path.exists() and meta_path.exists() and not refresh:
        return
    import requests
    with requests.get(url, timeout=(10, 40), stream=True) as response:
        chunks, size = [], 0
        for chunk in response.iter_content(64 * 1024):
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise ValueError(f"{name}: response exceeds the 5 MB safety bound")
            chunks.append(chunk)
        blob = b"".join(chunks)
        path.write_bytes(blob)
        dump(meta_path, {
            "url": response.url, "status": response.status_code,
            "content_type": response.headers.get("Content-Type"),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "bytes": size, "sha256": sha(blob),
        })
        # No retry through another host, credential or proxy when access fails.
        response.raise_for_status()


def cached(raw: Path, name: str, expected_url: str, *, is_json=True):
    path, meta_path = raw / (name + ".raw"), raw / (name + ".meta.json")
    blob = path.read_bytes()
    meta = json.loads(meta_path.read_bytes())
    if meta["status"] != 200:
        raise ValueError(f"{name}: HTTP {meta['status']}; not usable data")
    if meta["url"] != expected_url:
        raise ValueError(f"{name}: cache request does not match bounded request")
    if meta["bytes"] != len(blob) or meta["sha256"] != sha(blob):
        raise ValueError(f"{name}: raw cache integrity mismatch")
    if is_json and "json" not in (meta.get("content_type") or "").lower():
        raise ValueError(f"{name}: HTTP 200 is not a JSON dataset")
    src = {"cache_name": name, **meta, "provider": "Eurostat", "access_channel": "official statistics API"}
    return (json.loads(blob) if is_json else blob), src


def categories(dimension: dict) -> list[tuple[str, str]]:
    category = dimension["category"]
    index = category["index"]
    if isinstance(index, list):
        codes = index
    else:
        if sorted(index.values()) != list(range(len(index))):
            raise ValueError("Noncontiguous JSON-stat category positions")
        codes = [code for code, _ in sorted(index.items(), key=lambda item: item[1])]
    return [(code, category.get("label", {}).get(code, code)) for code in codes]


def sparse(value, count: int) -> dict[int, object]:
    if value is None:
        return {}
    if isinstance(value, list):
        if len(value) != count:
            raise ValueError("Wrong JSON-stat array length")
        out = {i: v for i, v in enumerate(value) if v is not None}
    elif isinstance(value, dict):
        out = {int(i): v for i, v in value.items()}
    else:
        raise ValueError("Unsupported JSON-stat value/status layout")
    if any(i < 0 or i >= count for i in out):
        raise ValueError("JSON-stat observation position outside the cube")
    return out


def origin_kind(code: str) -> str:
    if code in HISTORICAL:
        return "historical_geography"
    if code in SUBNATIONAL:
        return "subnational_geography"
    if code in AGGREGATES:
        return "aggregate"
    if code == "NAT":
        return "reporter_relative_native_born"
    if code == "UNK":
        return "unknown_country_of_birth"
    if code in {"RNC", "OTH"}:
        return "other_special_category"
    if re.fullmatch(r"[A-Z]{2}", code):
        return "country_or_territory"
    raise ValueError(f"Unreviewed country-of-birth category {code!r}")


def extract(document: dict, reporter: str, source_id: str) -> tuple[list[dict], dict]:
    expected_dims = {"freq", "c_birth", "age", "unit", "sex", "geo", "time"}
    ids, sizes = document["id"], document["size"]
    if set(ids) != expected_dims or len(ids) != len(expected_dims):
        raise ValueError("Unexpected dimensions: " + str(ids))
    axes = {key: categories(document["dimension"][key]) for key in ids}
    if any(len(axes[key]) != size for key, size in zip(ids, sizes)):
        raise ValueError("Dimension shape mismatch")
    for dim, expected in {"freq": "A", "age": "TOTAL", "unit": "NR", "sex": "T", "geo": reporter}.items():
        if [c for c, _ in axes[dim]] != [expected]:
            raise ValueError(f"{reporter}: ignored {dim} filter")
    if [int(c) for c, _ in axes["time"]] != list(YEARS):
        raise ValueError(f"{reporter}: returned period dimension differs from 2005–2025")
    count = math.prod(sizes)
    if count > MAX_CELLS_PER_REPORTER:
        raise ValueError(f"{reporter}: cube exceeds expected bounded size")
    values = sparse(document.get("value"), count)
    statuses = sparse(document.get("status"), count)
    strides = {key: math.prod(sizes[i + 1:]) for i, key in enumerate(ids)}
    flag_labels = ((document.get("extension") or {}).get("status") or {}).get("label", {})
    result = []
    for birth_pos, (code, label) in enumerate(axes["c_birth"]):
        kind = origin_kind(code)
        amounts, flags = [], []
        for time_pos, _ in enumerate(YEARS):
            flat = birth_pos * strides["c_birth"] + time_pos * strides["time"]
            value, status = values.get(flat), statuses.get(flat)
            if value is not None:
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value) or value < 0 or int(value) != value):
                    raise ValueError(f"{reporter}/{code}: invalid integer population {value!r}")
                value = int(value)
            if status is not None and (not isinstance(status, str) or status not in flag_labels):
                raise ValueError(f"{reporter}/{code}: unexplained source flag {status!r}")
            amounts.append(value)
            flags.append(status)
        result.append({
            "country_of_residence": reporter,
            "c_birth": code,
            "country_of_birth": code if kind == "country_or_territory" else None,
            "country_of_birth_label": label,
            "origin_kind": kind,
            "cross_border_pair": (code != reporter) if kind == "country_or_territory" else None,
            "unit": "persons",
            "values": amounts,
            "flags": flags,
            "source_id": source_id,
        })
    return result, {
        "dataset_label": document["label"],
        "source_updated_at": document.get("updated"),
        "datastructure": (document.get("extension") or {}).get("datastructure"),
        "dimensions": {key: [{"code": c, "label": l} for c, l in axes[key]] for key in ids},
        "flag_labels": flag_labels,
        "expected_cells": count,
        "numeric_cells": sum(v is not None for v in values.values()),
    }


def coverage(series: list[dict]) -> dict:
    values = [v for s in series for v in s["values"]]
    periods = [y for s in series for y, v in zip(YEARS, s["values"]) if v is not None]
    return {
        "series": len(series),
        "series_with_any_numeric_value": sum(any(v is not None for v in s["values"]) for s in series),
        "series_with_all_21_numeric_values": sum(all(v is not None for v in s["values"]) for s in series),
        "expected_cells": len(values),
        "numeric_cells": sum(v is not None for v in values),
        "missing_cells": sum(v is None for v in values),
        "observed_zero_cells": sum(v == 0 for v in values if v is not None),
        "first_year_with_numeric_value": min(periods) if periods else None,
        "last_year_with_numeric_value": max(periods) if periods else None,
        "flags": dict(sorted(Counter(flag for s in series for flag in s["flags"] if flag).items())),
    }


def latest(series: list[dict], code: str) -> dict | None:
    s = next((r for r in series if r["c_birth"] == code), None)
    if s is None:
        return None
    valid = [(y, value, flag) for y, value, flag in zip(YEARS, s["values"], s["flags"]) if value is not None]
    if not valid:
        return None
    year, value, flag = valid[-1]
    return {"c_birth": code, "year": year, "reference_date": f"{year}-01-01", "persons": value, "flag": flag}


def build(raw: Path) -> tuple[dict, dict, list[dict]]:
    sources, all_series, dimensions_by_reporter, traces = {}, [], {}, []
    for reporter in REPORTERS:
        name = "migrant_stock_probe_" + reporter.lower()
        document, provenance = cached(raw, name, url_for(reporter))
        source_id = "eurostat-migr-pop3ctb-" + reporter.lower()
        series, metadata = extract(document, reporter, source_id)
        sources[source_id] = {**provenance, "source_updated_at": metadata["source_updated_at"],
                              "dataset_label": metadata["dataset_label"],
                              "datastructure": metadata["datastructure"], "flag_labels": metadata["flag_labels"]}
        all_series.extend(series)
        dimensions_by_reporter[reporter] = metadata["dimensions"]
        traces.append({
            "id": "migrant-stock-" + reporter.lower(), "checked_on": CHECKED_ON,
            "kind": "extract", "url": provenance["url"],
            "title": f"Eurostat migr_pop3ctb — country of residence {reporter}",
            "quote": metadata["dataset_label"], "locator": "JSON-stat dataset label; filtered dimensions and sparse value/status arrays",
            "http_status": provenance["status"], "sha256": provenance["sha256"],
            "source_updated_at": metadata["source_updated_at"],
            "value": {"country_of_residence": reporter, "years": [2005, 2025],
                      "age": "TOTAL", "sex": "T", "unit": "NR",
                      "expected_cells": metadata["expected_cells"], "numeric_cells": metadata["numeric_cells"]},
            "note": "Country of birth, not citizenship. Population stock on 1 January, not trips. Countries/territories, historical categories and aggregates remain separate; nulls and flags retained.",
        })
    metadata_blob, metadata_source = cached(raw, "migrant_stock_metadata", METADATA, is_json=False)
    if b"demo_pop" not in metadata_blob:
        raise ValueError("Metadata response is not the population metadata page")
    sources["eurostat-population-metadata"] = {**metadata_source, "access_channel": "official metadata webpage"}
    traces.append({
        "id": "migrant-stock-definitions", "checked_on": CHECKED_ON, "kind": "open", "url": METADATA,
        "title": "Eurostat population metadata — definition, voluntary detail and breaks",
        "quote": "group of COB= group of country of birth: native born/foreign born/unknown;",
        "locator": "3.5; 5; 6.1; 7.2; 15.1–15.2",
        "sha256": metadata_source["sha256"],
        "note": "Unit is persons, reference date 1 January. Single-country-of-birth detail is voluntary; aggregate groups are not equivalent to complete bilateral coverage. Census revisions and national residence definitions can affect comparability. Break/estimate/provisional flags must remain visible.",
    })
    groups = {
        "country_series": [s for s in all_series if s["origin_kind"] == "country_or_territory"],
        "aggregate_series": [s for s in all_series if s["origin_kind"] == "aggregate"],
        "other_series": [s for s in all_series if s["origin_kind"] not in {"country_or_territory", "aggregate"}],
    }
    flags = {}
    for source in sources.values():
        for code, label in source.get("flag_labels", {}).items():
            if code in flags and flags[code] != label:
                raise ValueError(f"Conflicting flag definitions for {code}")
            flags[code] = label
    meta = {
        "schema_version": 1, "checked_on": CHECKED_ON, "dataset": DATASET,
        "scope": "research_only; no factor fitted, forecast generated or calculator change",
        "country_of_residence_filter": list(REPORTERS), "years": list(YEARS),
        "reference_dates": [f"{y}-01-01" for y in YEARS],
        "frequency": "annual", "age": "TOTAL", "sex": "T", "source_unit": "NR", "unit": "persons",
        "measure": "resident population by country of birth (stock at the start of year)",
        "not_measured": ["citizenship", "ancestry or all descendants", "annual migration flow", "visits to friends and relatives", "air journeys", "airport or city distribution"],
        "series_layout": "values and flags align positionally with meta.years; missing values and absent flags are null; numeric zero is retained",
        "category_rule": "Eurostat's original codes and labels are retained. Two-letter individual geography codes are country_or_territory except historical AN. Explicit groups, historical entities, NUTS areas, native-born and special categories are separate. No claim of ISO equivalence or sovereignty is inferred.",
        "flag_labels": dict(sorted(flags.items())),
        "collection_status": "all_five_official_requests_returned_HTTP_200_JSON",
        "metadata_url": METADATA,
        "code_sha256": sha(Path(__file__).read_bytes()),
        "sources": sources,
        "limitations": [
            "This is a potential country-pair explanatory input, not an estimated demand coefficient or a forecast.",
            "No missing country-of-birth stock is inferred from citizenship, aggregate foreign-born counts, interpolation or zero filling.",
            "Aggregates overlap one another and must not be added to individual origins; historical countries and subnational origins are not automatically remapped.",
            "A year labels population on 1 January; publication/update time is different and retained for later availability-lag treatment.",
            "This current snapshot is revised history, not a set of vintage files proving what forecasters knew in each earlier year.",
            "Residence and country-of-birth concepts and census revisions require attention to country metadata and preserved break/estimate/provisional flags.",
            "Stock at country level cannot be allocated to airports or inferred to represent two-way travel without further data and estimation.",
        ],
    }
    panel = {"meta": meta, "source_dimensions": dimensions_by_reporter, **groups}
    reporters = {}
    for reporter in REPORTERS:
        rows = [s for s in all_series if s["country_of_residence"] == reporter]
        countries = [s for s in rows if s["origin_kind"] == "country_or_territory"]
        foreign_pairs = [s for s in countries if s["cross_border_pair"]]
        annual = [{"year": year,
                   "country_territory_origins_numeric": sum(s["values"][i] is not None for s in countries),
                   "cross_border_origins_numeric": sum(s["values"][i] is not None for s in foreign_pairs),
                   "country_territory_origins_missing": sum(s["values"][i] is None for s in countries),
                   "observed_zero_country_territory_origins": sum(s["values"][i] == 0 for s in countries if s["values"][i] is not None)}
                  for i, year in enumerate(YEARS)]
        reporters[reporter] = {
            "all_categories": coverage(rows), "country_or_territory": coverage(countries),
            "cross_border_country_pairs": coverage(foreign_pairs),
            "aggregates": coverage([s for s in rows if s["origin_kind"] == "aggregate"]),
            "other_categories": coverage([s for s in rows if s["origin_kind"] not in {"aggregate", "country_or_territory"}]),
            "annual_coverage": annual, "latest_total_population": latest(rows, "TOTAL"),
            "latest_foreign_born_aggregate": latest(rows, "FOR"), "latest_native_born": latest(rows, "NAT"),
            "latest_unknown_birthplace": latest(rows, "UNK"),
            "bilateral_country_input_available": any(v is not None for s in foreign_pairs for v in s["values"]),
        }
    summary = {
        "meta": {"schema_version": 1, "checked_on": CHECKED_ON, "dataset": DATASET,
                 "period": [2005, 2025], "unit": "persons", "country_of_residence": list(REPORTERS),
                 "source_access": "official Eurostat statistics API", "raw_data_bytes": sum(s["bytes"] for k, s in sources.items() if k != "eurostat-population-metadata"),
                 "panel_file": "out/migrant_stock.json.gz", "code_sha256": meta["code_sha256"]},
        "all_categories": coverage(all_series),
        "category_groups": {k: coverage(v) for k, v in groups.items()},
        "reporters": reporters,
        "origin_categories": dict(sorted(Counter(s["origin_kind"] for s in all_series if s["country_of_residence"] == REPORTERS[0]).items())),
        "interpretation": {
            "data_collected": True, "coefficient_estimated": False, "city_allocation_available": False,
            "true_od_measured": False, "calculator_changed": False,
            "de_country_detail_note": "No individual country-of-birth observations in the extracted DE slice; group totals do not fill that bilateral gap."
                if not reporters["DE"]["bilateral_country_input_available"] else None,
        },
        "limitations": meta["limitations"],
    }
    return panel, summary, traces


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True, help="Raw cache directory outside the git repository")
    parser.add_argument("--fetch", action="store_true", help="Fetch missing official replies within the stated scope")
    parser.add_argument("--refresh", action="store_true", help="Refresh the bounded replies; requires --fetch")
    parser.add_argument("--check", action="store_true", help="Recompute and compare without changing derived files")
    args = parser.parse_args()
    raw = args.raw_dir.resolve()
    if raw == ROOT or ROOT in raw.parents:
        raise SystemExit("Raw replies must remain outside the repository")
    if args.refresh and not args.fetch:
        raise SystemExit("--refresh requires --fetch")
    if args.fetch:
        raw.mkdir(parents=True, exist_ok=True)
        for reporter in REPORTERS:
            fetch(raw, "migrant_stock_probe_" + reporter.lower(), url_for(reporter), refresh=args.refresh)
        fetch(raw, "migrant_stock_metadata", METADATA, refresh=args.refresh)
    panel, summary, trace = build(raw)
    panel_blob = gzip.compress(json_bytes(panel, compact=True), mtime=0)
    summary["meta"]["panel_sha256"] = sha(panel_blob)
    outputs = {
        HERE / "out/migrant_stock.json.gz": panel_blob,
        HERE / "out/migrant_stock_summary.json": json_bytes(summary),
        HERE / "trace/migrant_stock.jsonl": b"".join(json_bytes(t, compact=True) for t in trace),
    }
    if args.check:
        for path, blob in outputs.items():
            if not path.exists() or path.read_bytes() != blob:
                raise SystemExit(f"Derived output differs: {path.relative_to(ROOT)}")
        print("OK: migrant-stock panel, summary and trace reproduce exactly")
        return
    for path, blob in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
    print(json.dumps({"reporters": len(REPORTERS), **summary["all_categories"],
                      "panel_gzip_bytes": len(panel_blob)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
