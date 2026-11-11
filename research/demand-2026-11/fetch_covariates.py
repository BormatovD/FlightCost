#!/usr/bin/env python3
"""Build small dated research covariates from bounded public API responses.

Raw downloads must stay outside the repository. Without --refresh, reuse the
explicit cache; benchmark.py itself never contacts the network. These are
retrospective data vintages, not a reconstruction of historical availability.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from flightcostapp.parsers import eurostat_json, wb_wdi  # noqa: E402

URLS = {
    "wb_macro": "https://api.worldbank.org/v2/country/all/indicator/NY.GDP.PCAP.PP.KD;SP.POP.TOTL;ST.INT.ARVL?source=2&format=json&date=2022:2023&per_page=5000",
    "eurostat_nights": "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/tour_occ_nin2m?format=JSON&lang=EN&unit=NR&nace_r2=I551-I553&c_resid=TOTAL&c_resid=FOR&time=2022&time=2023",
    "gisco_regions": "https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_10M_2024_4326_LEVL_2.geojson",
}


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def in_ring(lon, lat, ring):
    inside = False
    for a, b in zip(ring, ring[1:] + ring[:1]):
        x1, y1 = a[:2]
        x2, y2 = b[:2]
        if (y1 > lat) != (y2 > lat):
            crossing = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
            if lon < crossing:
                inside = not inside
    return inside


def regions_with_bounds(document):
    result = []
    for feature in document["features"]:
        geometry = feature.get("geometry") or {}
        polygons = ([geometry["coordinates"]] if geometry.get("type") == "Polygon"
                    else geometry.get("coordinates", []) if geometry.get("type") == "MultiPolygon" else [])
        for poly in polygons:
            outer = poly[0]
            xs, ys = [p[0] for p in outer], [p[1] for p in outer]
            result.append((feature["properties"]["NUTS_ID"], (min(xs), min(ys), max(xs), max(ys)), poly))
    return result


def assign_regions(airports, regions):
    assigned, ambiguous = {}, []
    for code, row in sorted(airports.items()):
        lat, lon = row[:2]
        matches = set()
        for region, (x0, y0, x1, y1), poly in regions:
            if x0 <= lon <= x1 and y0 <= lat <= y1 and in_ring(lon, lat, poly[0]) \
                    and not any(in_ring(lon, lat, hole) for hole in poly[1:]):
                matches.add(region)
        if len(matches) == 1:
            assigned[code] = matches.pop()
        elif len(matches) > 1:
            ambiguous.append(code)
    return assigned, ambiguous


def build(cache, out_dir, retrieved_on):
    airports = json.loads((ROOT / "research/routes-2026-11/out/airports.json").read_text())
    countries = {row[2] for row in airports.values()}
    raw = {name: (cache / f"{name}.json").read_bytes() for name in URLS}
    sha = {name: hashlib.sha256(blob).hexdigest() for name, blob in raw.items()}
    wb = json.loads(raw["wb_macro"])
    facts = wb_wdi.parse(raw["wb_macro"], {"source_id": "wb_wdi"})
    by = defaultdict(lambda: defaultdict(dict))
    for f in facts:
        _, country, indicator, year = f.key.split("/")
        if country in countries:
            by[indicator][year][country] = f.value
    out_dir.mkdir(parents=True, exist_ok=True)
    income = {"source": URLS["wb_macro"], "source_updated": wb[0].get("lastupdated"),
              "retrieved_on": retrieved_on, "raw_sha256": sha["wb_macro"],
              "indicator": "NY.GDP.PCAP.PP.KD", "unit": "constant 2021 international dollars per person (PPP)",
              "transformation": "only countries represented in airport reference; no imputation",
              "values": {y: dict(sorted(values.items())) for y, values in sorted(by["gdp_pc_ppp"].items())}}
    write(out_dir / "income_covariates.json", income)

    nights_doc = json.loads(raw["eurostat_nights"])
    nights = eurostat_json.parse(raw["eurostat_nights"], {
        "source_id": "eurostat_nights_nuts2", "indicator": "nights", "dims": {"c_resid": ["TOTAL", "FOR"]},
        "unit_text": "accommodation nights per month"})
    month_groups = defaultdict(dict)
    for f in nights:
        _, region, indicator, period = f.key.split("/")
        if len(period) != 7:
            continue
        month_groups[(region, indicator, period[:4])][period[5:]] = f.value
    annual = {(r, kind, y): sum(months.values()) for (r, kind, y), months in month_groups.items()
              if set(months) == {f"{m:02d}" for m in range(1, 13)} and all(v >= 0 for v in months.values())}
    region_map, ambiguous = assign_regions(airports, regions_with_bounds(json.loads(raw["gisco_regions"])))
    values, regions_used = {}, set()
    for year in ("2022", "2023"):
        values[year] = {}
        for code, region in region_map.items():
            v = annual.get((region, "nights.TOTAL", year))
            if v is not None and v > 0:
                values[year][code] = v
                regions_used.add(region)
    tourism = {"source": URLS["eurostat_nights"], "geography_source": URLS["gisco_regions"],
               "source_updated": nights_doc.get("updated"), "retrieved_on": retrieved_on,
               "raw_sha256": {k: sha[k] for k in ("eurostat_nights", "gisco_regions")},
               "geography_version": "NUTS 2024, polygons at 1:10 million, WGS84",
               "unit": "total accommodation nights per NUTS2 region per year",
               "method": "sum all 12 reported monthly TOTAL values; strict point-in-polygon including holes; no nearest-region fallback",
               "airport_region": dict(sorted(region_map.items())), "ambiguous_airports_excluded": ambiguous,
               "values": values,
               "limitations": ["Coast/boundary simplification can leave airports unassigned.",
                               "2024 boundaries and 2026 data vintage describe retrospective 2022/2023 observations.",
                               "Regional nights include residents and arrivals by all transport modes.",
                               "A regional total is not an airport catchment measurement or the pair's passenger seasonality."]}
    write(out_dir / "tourism_covariates.json", tourism)
    access = {"checked_on": retrieved_on, "raw": [{"name": k, "url": URLS[k], "sha256": sha[k], "bytes": len(raw[k])}
                                                   for k in URLS],
              "wb_returned_rows": wb[0].get("total"), "wb_tourist_arrivals_2022_2023": sum(len(v) for v in by["tourist_arrivals"].values()),
              "income_countries": {y: len(v) for y, v in income["values"].items()},
              "regional_nights_monthly_facts": len(nights), "mapped_airports": len(region_map),
              "tourism_airports": {y: len(v) for y, v in values.items()}, "tourism_regions": len(regions_used),
              "server_panel_needed_for": ["calculator's population catchments and full P/T/F validation",
                                          "passenger-month seasonality", "business, diaspora, dated visa comparisons"]}
    write(out_dir / "access.json", access)
    return access


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=HERE / "out")
    parser.add_argument("--refresh", action="store_true", help="download the three bounded public datasets")
    parser.add_argument("--retrieved-on", default=date.today().isoformat())
    args = parser.parse_args()
    cache = args.cache_dir.resolve()
    if cache == ROOT or ROOT in cache.parents:
        raise ValueError("raw downloads must be outside the repository")
    cache.mkdir(parents=True, exist_ok=True)
    if args.refresh:
        import requests
        for name, url in URLS.items():
            response = requests.get(url, timeout=(10, 45))
            response.raise_for_status()
            # Bounded periods are small; reject an unexpected changed API response.
            if len(response.content) > 10_000_000:
                raise ValueError(f"unexpected response size for {name}")
            response.json()
            (cache / f"{name}.json").write_bytes(response.content)
    print(json.dumps(build(cache, args.out.resolve(), args.retrieved_on), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
