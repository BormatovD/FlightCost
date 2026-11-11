#!/usr/bin/env python3
"""Reproduce aircraft-price research tables; optional refresh of historical AVAC cells.

    python research/aircraft-prices-2026-11/analyze.py
    python research/aircraft-prices-2026-11/analyze.py --refresh-avac --cache-dir EXTERNAL_DIRECTORY

Research extraction does not modify accepted data/prices or calculator defaults.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import statistics
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from flightcostapp import prices as PR  # noqa: E402

AS_OF = "2026-11-11"
AVAC_URLS = {
    2016: "https://aviationstrategy.aero/newsletter/Nov-2016/5/Jet-values-and-lease-rates",
    2017: "https://aviationstrategy.aero/newsletter/Nov-2017/5/Jet-values-and-lease-rates",
    2018: "https://aviationstrategy.aero/newsletter/Nov-2018/5/Jet-values-and-lease-rates",
    2019: "https://aviationstrategy.aero/newsletter/Nov-2019/5/Jet-Values-and-Lease-Rates",
    2020: "https://aviationstrategy.aero/newsletter/Oct-2020/4/Jet-Values-and-Lease-Rates",
}
AIRCRAFT = {
    "a319": "A319", "a319neo": "A19N", "a320200": "A320", "a320neo": "A20N",
    "a321200": "A321", "a321neo": "A21N", "a330200": "A332", "a330300": "A333",
    "a330900neo": "A339", "a350900": "A359", "a3501000": "A35K", "a220300": "BCS3",
    "737800": "B738", "737max8": "B38M", "737max9": "B39M", "777300er": "B77W",
    "7878": "B788", "7879": "B789", "emb175": "E75L", "emb195e2": "E295",
    "787800": "B788", "787900": "B789", "crj900ng": "CRJ9",
}


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class Tables(HTMLParser):
    """Read only tables; retain row/column spans rather than guessing column positions."""
    def __init__(self, text):
        super().__init__()
        self.tables, self.table, self.row, self.cell = [], None, None, None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("th", "td") and self.row is not None:
            self.cell = [dict(attrs), []]

    def handle_data(self, data):
        if self.cell is not None:
            self.cell[1].append(data)

    def handle_endtag(self, tag):
        if tag in ("th", "td") and self.cell is not None:
            self.row.append((self.cell[0], " ".join("".join(self.cell[1]).split())))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def grid(rows):
    carry = {}
    out = []
    for cells in rows:
        values = {c: v for c, (n, v) in carry.items() if n > 0}
        next_carry = {c: (n - 1, v) for c, (n, v) in carry.items() if n > 1}
        col = 0
        for attrs, value in cells:
            while col in values:
                col += 1
            for k in range(int(attrs.get("colspan", 1))):
                values[col + k] = value
                n = int(attrs.get("rowspan", 1))
                if n > 1:
                    next_carry[col + k] = (n - 1, value)
            col += int(attrs.get("colspan", 1))
        out.append([values.get(c, "") for c in range(max(values, default=-1) + 1)])
        carry = next_carry
    return out


def refresh_avac(cache, accepted):
    import requests
    cache = cache.resolve()
    if cache == ROOT or ROOT in cache.parents:
        raise ValueError("The raw-page cache must be outside the repository")
    cache.mkdir(parents=True, exist_ok=True)
    have = {(o["icao"], o["kind"], o["month"], o.get("age"), o["source"]) for o in accepted}
    additions, scans = [], []
    for year, url in AVAC_URLS.items():
        path = cache / f"avac-{year}.html"
        if not path.exists():
            result = requests.get(url, timeout=30)
            result.raise_for_status()
            path.write_text(result.text, encoding="utf-8")
        raw = path.read_bytes()
        tables = Tables(raw.decode("utf-8")).tables
        if len(tables) < 2:
            raise ValueError(f"AVAC {year}: expected value and lease tables")
        found = 0
        for kind, table in zip(("value", "lease"), tables[:2]):
            expanded = grid(table)
            if any(len(row) != 13 for row in expanded) or expanded[1][3:7] != ["New", "5", "10", "20"] \
                    or expanded[1][9:13] != ["New", "5", "10", "20"]:
                raise ValueError(f"AVAC {year}: age-table layout changed")
            for ri, row in enumerate(expanded):
                for offset in (1, 7):
                    name = row[offset]
                    base_name = re.sub(r"\([^)]*\)", "", name)
                    code = AIRCRAFT.get(re.sub(r"[^a-z0-9]", "", base_name.lower()))
                    if not code:
                        continue
                    for ai, age in enumerate(("new", 5, 10, 20)):
                        cell = row[offset + 2 + ai]
                        match = re.fullmatch(r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)([^0-9]*)", cell)
                        if not match:
                            continue
                        value = float(match[1].replace(",", "")) * (1e6 if kind == "value" else 1e3)
                        ident = (code, kind, f"{year}-10", age, url)
                        if ident in have or age == "new":
                            continue
                        found += 1
                        additions.append({
                            "id": f"avac-{year}-{code.lower()}-{kind}-{age}", "icao": code, "kind": kind,
                            "period": f"{year}-10", "age": age, "age_basis": "appraiser_column",
                            "amount_low_usd": value, "amount_high_usd": value, "estimate_type": "point",
                            "source_id": f"avac-{year}", "source": url, "source_label": name,
                            "specification_flags": " ".join(re.findall(r"\(([^)]*)\)", name)
                                + [row[offset + 1], match[2], "".join(c for c in name if c in "†‡§♯♠♣♥∞*")]).strip(),
                            "locator": f"{'JET VALUES' if kind == 'value' else 'JET LEASE RATES'}; row {ri + 1}; {name}; column {age}",
                            "scope": "research_only_not_accepted",
                        })
        scans.append({"year": year, "source": url, "source_sha256": hashlib.sha256(raw).hexdigest(),
                      "additional_age_cells": found})
    return additions, scans


def compact(o):
    lo, hi = PR.usd_bounds(o)
    qualifier = "range" if PR.is_range(o) else "point"
    if re.search(r"\bup to\b", o.get("quote", ""), re.I):
        qualifier = "upper_bound"
    return {"id": PR.observation_id(o), "icao": o["icao"], "kind": o["kind"], "period": str(o["month"]),
            "age": o.get("age"), "amount_low_usd": lo, "amount_high_usd": hi,
            "estimate_type": qualifier, "source": o["source"]}


def analyze(accepted, extra):
    observations = [compact(o) for o in accepted]
    coverage = {"total": len(accepted), "types": len({o["icao"] for o in accepted}),
                "by_kind": dict(sorted(Counter(o["kind"] for o in accepted).items())),
                "by_year": dict(sorted(Counter(o["month"][:4] for o in accepted).items())),
                "by_age": dict(sorted(Counter(str(o.get("age", "unknown")) for o in accepted).items())),
                "type_codes": sorted({o["icao"] for o in accepted})}
    catalog = []
    for item in (o for o in observations if o["kind"] == "list"):
        matches = [o for o in observations if o["icao"] == item["icao"] and o["kind"] == "value"
                   and o["age"] == "new" and o["period"][:4] == item["period"][:4]]
        for market in matches:
            catalog.append({"icao": item["icao"], "list_month": item["period"], "market_month": market["period"],
                            "list_usd": item["amount_low_usd"], "market_usd": market["amount_low_usd"],
                            "ratio": item["amount_low_usd"] / market["amount_low_usd"],
                            "sources": [item["source"], market["source"]]})
    matched = defaultdict(dict)
    for o in observations:
        if o["kind"] in ("value", "lease") and o["estimate_type"] == "point":
            matched[(o["icao"], o["period"], str(o["age"]), o["source"])][o["kind"]] = o
    pairs = []
    for (icao, month, age, source), rows in sorted(matched.items()):
        if set(rows) != {"value", "lease"}:
            continue
        v, l = rows["value"]["amount_low_usd"], rows["lease"]["amount_low_usd"]
        pairs.append({"icao": icao, "month": month, "age": rows["value"]["age"], "source": source,
                      "value_usd": v, "lease_usd_month": l, "monthly_fraction": l / v})
    by_year = []
    for year in sorted({r["month"][:4] for r in pairs}):
        rows = [r for r in pairs if r["month"].startswith(year)]
        by_year.append({"year": int(year), "n": len(rows),
                        "median_fraction": statistics.median(r["monthly_fraction"] for r in rows)})
    fixed_years = (2016, 2017, 2018, 2019, 2020)
    cohorts = [{(r["icao"], str(r["age"])) for r in pairs if r["month"].startswith(str(y))}
               for y in fixed_years]
    common = set.intersection(*cohorts)
    fixed_cohort = {
        "members": [{"icao": k[0], "age": k[1]} for k in sorted(common)],
        "years": [{"year": y, "n": len(common),
                   "median_fraction": statistics.median(r["monthly_fraction"] for r in pairs
                       if r["month"].startswith(str(y)) and (r["icao"], str(r["age"])) in common)}
                  for y in fixed_years],
    }
    shocks = []
    for icao in ("A20N", "A21N", "B38M", "A359"):
        rows = {r["month"][:4]: r for r in pairs if r["icao"] == icao and r["age"] == "new"}
        if not {"2019", "2020"}.issubset(rows):
            continue
        a, b = rows["2019"], rows["2020"]
        shocks.append({"icao": icao, "from_month": a["month"], "to_month": b["month"],
                       "value_change": b["value_usd"] / a["value_usd"] - 1,
                       "lease_change": b["lease_usd_month"] / a["lease_usd_month"] - 1,
                       "sources": [a["source"], b["source"]]})
    def ages(rows):
        grouped = defaultdict(dict)
        for o in rows:
            if o["kind"] in ("lease", "value") and o["age"] is not None:
                grouped[(o["icao"], o["kind"], o["period"], o["source"])][str(o["age"])] = o
        result = []
        for (icao, kind, period, source), series in sorted(grouped.items()):
            if "new" not in series:
                continue
            new = series["new"]["amount_low_usd"]
            for age, o in series.items():
                if age == "new":
                    continue
                result.append({"icao": icao, "kind": kind, "period": period, "age": int(float(age)),
                               "new_usd": new, "aged_usd": o["amount_low_usd"],
                               "fraction_of_new": o["amount_low_usd"] / new, "source": source,
                               "age_basis": "nominal_appraiser_column",
                               "comparison_scope": "type, period and source matched; equipment and maintenance state may differ"})
        return result
    extra_rows = extra.get("observations", [])
    recent_pairs = []
    for lease in (o for o in extra_rows if o["kind"] == "lease" and o["source_id"] == "iba-iclg-2026"):
        value = next((o for o in extra_rows if o["kind"] == "value" and all(o.get(k) == lease.get(k)
                     for k in ("icao", "variant", "period", "age", "source_id"))), None)
        if value:
            v = value["amount_low_usd"]
            lo, hi = lease["amount_low_usd"], lease["amount_high_usd"]
            recent_pairs.append({"icao": lease["icao"], "variant": lease["variant"], "age": lease["age"],
                                 "period": lease["period"], "source": lease["source"], "value_usd": v,
                                 "lease_usd_month_low": lo, "lease_usd_month_high": hi,
                                 "monthly_fraction_low": lo / v, "monthly_fraction_high": hi / v,
                                 "monthly_fraction_midpoint": (lo / 2 + hi / 2) / v,
                                 "value_basis": value["maintenance_basis"]})
    # Fixed worked scenario, not an observed operating record or a market average.
    from flightcostapp.fleet import parametric
    fx_path = ROOT / "research/_fx.json"
    fx = json.loads(fx_path.read_text(encoding="utf-8"))
    usd_per_eur = fx["rates"]["USD"]
    fleet = parametric("A20N", 79, 180)
    block_h, monthly_h, pax = 2.12, 300, 144
    anchor = next(o for o in extra_rows if o["id"] == "iba-2026q1-a20n-a320-200n-lease")
    low, high = anchor["amount_low_usd"], anchor["amount_high_usd"]
    mid = low / 2 + high / 2
    base_flight = fleet.lease_eur_month * block_h / monthly_h
    scenario = {
        "inputs": {"icao": "A20N", "route": "EDDF–LEBL", "mtow_t": 79, "seats": 180,
                   "load_factor": 0.8, "passengers": pax, "block_hours": block_h,
                   "monthly_hours": monthly_h, "input_basis": "illustrative fixed scenario; block time is assumed"},
        "fx": {"usd_per_eur": usd_per_eur, "as_of": fx["as_of"], "input": "research/_fx.json",
               "input_sha256": hashlib.sha256(fx_path.read_bytes()).hexdigest()},
        "anchor": {"id": anchor["id"], "period": anchor["period"], "source": anchor["source"],
                   "low_usd_month": low, "high_usd_month": high, "midpoint_usd_month": mid},
        "default_lease_eur_month": fleet.lease_eur_month,
        "default_ownership_eur_flight": base_flight,
        "research_ownership_eur_flight_low": low / usd_per_eur * block_h / monthly_h,
        "research_ownership_eur_flight_high": high / usd_per_eur * block_h / monthly_h,
        "research_ownership_eur_flight_midpoint": mid / usd_per_eur * block_h / monthly_h,
        "midpoint_delta_eur_flight": mid / usd_per_eur * block_h / monthly_h - base_flight,
        "midpoint_delta_eur_passenger": (mid / usd_per_eur * block_h / monthly_h - base_flight) / pax,
        "utilisation_sensitivity": [
            {"monthly_hours": h, "low_eur_flight": low / usd_per_eur * block_h / h,
             "high_eur_flight": high / usd_per_eur * block_h / h,
             "midpoint_eur_flight": mid / usd_per_eur * block_h / h}
            for h in (240, 300, 360)
        ],
        "limitations": ["This varies ownership cost only, not fuel, maintenance, crew or total flight cost.",
                        "A Q1 2026 lease estimate is converted using the explicitly dated FX snapshot; it is not an observed Q1 EUR contract.",
                        "The midpoint is a scenario input; neither the mean of deals nor an expectation over a probability distribution is supplied."],
    }
    return {
        "meta": {"as_of": AS_OF, "input": "data/prices/_observations.yaml",
                 "input_sha256": hashlib.sha256(PR.PATH.read_bytes()).hexdigest(),
                 "additional_input_sha256": hashlib.sha256((HERE / "out/additional_observations.json").read_bytes()).hexdigest(),
                 "all_amounts": "nominal USD at source period; lease per month; no CPI adjustment"},
        "coverage": coverage,
        "catalog_comparisons": catalog,
        "lease_value_pairs": pairs,
        "lease_value_by_year": by_year,
        "lease_value_fixed_cohort": fixed_cohort,
        "shock_2019_2020": shocks,
        "age_comparisons": ages(observations),
        "expanded_age_comparisons": ages(observations + [o for o in extra_rows if o["source_id"].startswith("avac-")]),
        "recent_observations": [o for o in extra_rows if o["period"][:4] >= "2023"],
        "recent_lease_value_pairs": recent_pairs,
        "additional_coverage": {"total": len(extra_rows), "by_source": dict(sorted(Counter(o["source_id"] for o in extra_rows).items()))},
        "qualified_existing": [o for o in observations if o["estimate_type"] != "point" or o["age"] is None],
        "example": scenario,
        "limitations": [
            "The accepted sample is not representative of all aircraft or years; there are no disclosed per-aircraft transaction prices.",
            "Catalogue and appraisal comparisons preserve different months within the same year; the ratio is not a measured transaction discount.",
            "Annual median lease/value ratios use changing compositions; use fixed aircraft and ages for a time trend.",
            "AVAC age columns are appraisal categories. The 2020 note permits 4–6 years for the nominal 5-year column; specification flags also differ.",
            "Some age categories predate the actual fleet age of a new type and must not be fitted as observed physical depreciation.",
            "IBA 2026 figures are appraiser estimates, with lessee-credit and maintenance-basis assumptions; quarter precision is preserved.",
            "A320neo 2022 'up to' is an upper bound. The generic A350 2024 quote does not independently establish the variant or age.",
            "Research-only additions do not change accepted records or calculator defaults. Missing public observations do not prove that no sources exist.",
        ],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh-avac", action="store_true")
    ap.add_argument("--cache-dir", type=Path)
    args = ap.parse_args()
    accepted = PR.load()["observations"]
    extra_path = HERE / "out/additional_observations.json"
    extra = json.loads(extra_path.read_text(encoding="utf-8")) if extra_path.exists() else {"observations": []}
    if args.refresh_avac:
        if args.cache_dir is None:
            ap.error("--refresh-avac requires --cache-dir outside the repository")
        cells, scans = refresh_avac(args.cache_dir, accepted)
        extra["observations"] = cells + [o for o in extra["observations"] if not o["source_id"].startswith("avac-")]
        extra["avac_extractions"] = scans
        dump(extra_path, extra)
    if not extra_path.exists():
        dump(extra_path, extra)
    result = analyze(accepted, extra)
    dump(HERE / "out/summary.json", result)
    print(f"Accepted: {result['coverage']['total']} observations; exact lease/value pairs: {len(result['lease_value_pairs'])}; research additions: {len(extra['observations'])}")


if __name__ == "__main__":
    main()
