#!/usr/bin/env python3
"""Build research-only price and lease histories for four aircraft segments.

Offline: python research/aircraft-prices-2026-11/history.py
Refresh public-source extractions (PyMuPDF and project dependencies needed):
python research/aircraft-prices-2026-11/history.py --refresh --cache-dir /tmp/fca-price-history

Raw PDFs/HTML must stay outside the repository. No accepted data are written.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
AS_OF = "2026-11-11"
SEGMENTS = [
    {"id": "turboprop", "title_ru": "Турбовинтовые", "types": ["AT46", "AT76", "DH8D"]},
    {"id": "regional", "title_ru": "Региональные реактивные", "types": ["E75L", "E195", "E295", "CRJ9"]},
    {"id": "narrowbody", "title_ru": "Узкофюзеляжные", "types": ["A20N", "A21N", "B738", "B38M"]},
    {"id": "widebody", "title_ru": "Широкофюзеляжные", "types": ["A332", "A359", "B77W", "B789"]},
]
NAMES = {
    "AT46": "ATR 42-600", "AT76": "ATR 72-600", "DH8D": "Dash 8-400", "E75L": "E175",
    "E195": "E195-E1", "E295": "E195-E2", "CRJ9": "CRJ900", "A20N": "A320neo",
    "A21N": "A321neo", "B738": "737-800", "B38M": "737 MAX 8", "A332": "A330-200",
    "A359": "A350-900", "B77W": "777-300ER", "B789": "787-9",
}
TYPE_SEGMENT = {code: seg["id"] for seg in SEGMENTS for code in seg["types"]}
ICLG = "https://iclg.com/practice-areas/aviation-finance-and-leasing/02-the-aviation-finance-market-robust-demand-entrenched-supply-chain-challenges-and-strong-market-performance/"
ORIEL = "https://www.istat.org/ISTAT-Online/ISTAT-Online/Aircraft-Supporting-Assets/ArtMID/1205/ArticleID/1697/Appraisal-Embraer-E-Jet-E2"
TURBO = "https://www.truenoord.com/wp-content/uploads/2023/06/Turboprop_report_onscreen.pdf"
REGIONAL = "https://www.truenoord.com/wp-content/uploads/2025/06/Regional-Jet-Market-Report_4-pages.pdf"
CROSSOVER_2021 = "https://www.truenoord.com/wp-content/uploads/2021/05/TrueNoord-Insight-Crossover-Jets-Market-Report-2021.pdf"
REGIONAL_2022 = "https://www.truenoord.com/wp-content/uploads/2022/07/TrueNoord-Insight-Regional-Jet-Market-Report-2022.pdf"
PDFS = {
    "truenoord-turboprop-2023": {"url": TURBO, "file": "truenoord-turboprop-2023.pdf",
        "sha256": "efc609503f714fb3a30043ccd8961e1d81700447f858797fe1318d16e9935749",
        "published": "2023-06", "title": "TrueNoord Turboprop Market Report, June 2023",
        "family": "TrueNoord average Avitas/mba/Cirium 2023"},
    "truenoord-regional-2025": {"url": REGIONAL, "file": "truenoord-regional-2025-summary.pdf",
        "sha256": "273c7f594d24064270222bb1def35483ac548f4372705e6ba0450d5f7ebec436",
        "published": "2025-05", "title": "TrueNoord 70-Seat Regional Jet Market Report, May 2025",
        "family": "TrueNoord average Avitas/IBA/mba/Cirium 2025"},
    "truenoord-regional-2022": {"url": REGIONAL_2022, "file": "truenoord-regional-2022.pdf",
        "sha256": "1212bd7058c725557a041ed667a931ce80f8d6e5f105e1b3d2253716b522b59a",
        "published": "2022-07", "title": "TrueNoord Regional Jet Market Report, July 2022",
        "family": "TrueNoord average Avitas/IBA/Cirium 2022"},
}


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def age(value):
    if value == "new" or value == 0:
        return {"category": "new", "years": 0, "basis": "source_new_or_zero_year_column"}
    if value is None:
        return {"category": "unknown", "basis": "not_stated"}
    return {"category": "aged", "years": value, "basis": "constant_age_appraisal_column"}


def record(ident, code, kind, period, years, amount, *, high=None, source_id, source_url,
           family, locator, variant=None, basis=None, quality="published_number", notes=None):
    return {"id": ident, "icao": code, "kind": kind, "period": period,
        "period_precision": "quarter" if "Q" in period else "month" if len(period) == 7 else "year",
        "age": age(years), "variant": variant or NAMES[code],
        "valuation_basis": basis or ("market_value_condition_unspecified" if kind == "value" else "market_monthly_lease"),
        "amount_low_usd": amount, "amount_high_usd": amount if high is None else high,
        "estimate_type": "point" if high is None or high == amount else "range",
        "source_id": source_id, "source_url": source_url, "source_family": family,
        "locator": locator, "quality": quality, "extraction_basis": "published_text_or_table",
        "notes": notes or [], "scope": "research_only_not_accepted"}


def ensure_cache(path, url):
    if not path.exists():
        from urllib.request import urlopen
        with urlopen(url, timeout=45) as response:
            path.write_bytes(response.read())
    return path


def extract_avac(cache):
    # Reuse the tested HTML rowspan/colspan reader from the original research.
    from analyze import Tables, grid, AIRCRAFT, AVAC_URLS
    aliases = {**AIRCRAFT, "emb195": "E195", "crj900ng": "CRJ9"}
    observations, sources = [], []
    for year, url in AVAC_URLS.items():
        path = ensure_cache(cache / f"avac-{year}.html", url)
        tables = Tables(path.read_text(encoding="utf-8")).tables
        source_id = f"avac-{year}"
        sources.append({"id": source_id, "url": url, "title": f"AVAC jet values and lease rates, October {year}",
            "period": f"{year}-10", "source_family": "AVAC", "source_sha256": digest(path),
            "limitations": ["Nominal appraiser age columns, not observed ageing of one aircraft.",
                "Technical flags are retained; different specifications are not joined into one series.",
                "Lease rates assessed independently from aircraft values."]})
        for kind, table in zip(("value", "lease"), tables[:2]):
            rows = grid(table)
            if rows[1][3:7] != ["New", "5", "10", "20"] or rows[1][9:13] != ["New", "5", "10", "20"]:
                raise ValueError(f"Changed AVAC {year} table headers")
            for ri, row in enumerate(rows[2:], 3):
                for offset in (1, 7):
                    label = row[offset]
                    clean = re.sub(r"\([^)]*\)", "", label)
                    code = aliases.get(re.sub(r"[^a-z0-9]", "", clean.lower()))
                    if code not in NAMES:
                        continue
                    for ai, years in enumerate(("new", 5, 10, 20)):
                        cell = row[offset + 2 + ai]
                        number = re.fullmatch(r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)([^0-9]*)", cell)
                        if not number:
                            continue
                        flags_raw = " ".join(re.findall(r"\(([^)]*)\)", label) + [row[offset + 1], number[2]])
                        meanings = ({"†": "HGW", "‡": "LGW", "§": "IGW", "♠": "Winglets", "♣": "Sharklets", "♥": "Enhanced"}
                            if year == 2017 else {"†": "Enhanced", "‡": "IGW", "♯": "LGW", "§": "HGW", "∞": "conversion"})
                        flags = set()
                        for token in ("Enhanced", "HGW", "LGW", "IGW", "Winglets", "Sharklets"):
                            if token.lower() in flags_raw.lower():
                                flags.add(token)
                        flags.update(v for k, v in meanings.items() if k in flags_raw)
                        val = round(float(number[1].replace(",", "")) * (1e6 if kind == "value" else 1000))
                        o = record(f"history-{source_id}-{code.lower()}-{kind}-{years}", code, kind,
                            f"{year}-10", years, val, source_id=source_id, source_url=url, family="AVAC",
                            locator=f"{'JET VALUES' if kind == 'value' else 'JET LEASE RATES'}; row {ri}; {label}; column {years}",
                            variant="CRJ900NG" if code == "CRJ9" else NAMES[code], quality="published_table")
                        o.update(source_label=label, technical_specification=sorted(flags), specification_flags_raw=flags_raw.strip(),
                                 source_cell=cell, source_sha256=digest(path))
                        if years != "new":
                            o["notes"].append("Nominal age column; AVAC 2020 explicitly permits e.g. 4–6 rather than exactly five years.")
                        observations.append(o)
    return observations, sources


def path_points(items):
    """Read the published vector line, including cubic curves; never infer outside it."""
    points = []
    for item in items:
        if item[0] == "l":
            points.extend([tuple(item[1]), tuple(item[2])])
        elif item[0] == "c":
            ps = item[1:]
            for k in range(101):
                t = k / 100
                points.append(tuple((1-t)**3*ps[0][j] + 3*(1-t)**2*t*ps[1][j]
                    + 3*(1-t)*t*t*ps[2][j] + t**3*ps[3][j] for j in (0, 1)))
        else:
            raise ValueError(f"Unsupported line operation {item[0]}")
    return sorted(set(points))


def read_curve(points, x):
    if x < points[0][0] - .75 or x > points[-1][0] + .75:
        return None
    x = min(max(x, points[0][0]), points[-1][0])
    for a, b in zip(points, points[1:]):
        if a[0] <= x <= b[0]:
            return a[1] if a[0] == b[0] else a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0])
    return points[-1][1]


def extract_charts(cache):
    import fitz
    # Calibration uses printed axes. Value scale is USD millions, lease scale USD thousands/month.
    # DH8D's 0-year curve ends in 2021; no extrapolated new-aircraft values are created thereafter.
    # Paths are pinned to source hashes so a revised PDF cannot silently change their meaning.
    configs = [
        ("truenoord-turboprop-2023", 51, "6.1(i)", "AT46", "value", {0:39, 3:40, 5:41, 10:42}, (2011,67.5692,2023,521.8102), (2,236.599,18,141.684)),
        ("truenoord-turboprop-2023", 51, "6.1(ii)", "AT76", "value", {0:35, 3:36, 5:37, 10:38}, (2011,65.9644,2023,523.1944), (4,386.406,22,279.626)),
        ("truenoord-turboprop-2023", 51, "6.1(iii)", "DH8D", "value", {0:43, 3:44, 5:45, 10:46}, (1998,70.1339,2022,522.5520), (4,546.647,24,428.003)),
        ("truenoord-turboprop-2023", 53, "6.3(i)", "AT46", "lease", {0:30, 3:31, 5:32, 10:33}, (2011,75.5441,2023,524.9791), (40,460.895,180,367.930)),
        ("truenoord-turboprop-2023", 53, "6.3(ii)", "AT76", "lease", {0:34, 3:35, 5:36, 10:37}, (2011,75.4834,2023,524.7594), (50,606.239,200,501.653)),
        ("truenoord-turboprop-2023", 53, "6.3(iii)", "DH8D", "lease", {0:38, 3:39, 5:40, 10:41}, (2011,75.54,2023,524.76), (50,762.866,230,646.660)),
        ("truenoord-regional-2025", 42, "6.3", "E75L", "lease", {0:25}, (2005,95.8671,2024,529.2801), (160,753.254,240,618.357)),
        ("truenoord-regional-2025", 43, "6.5", "CRJ9", "value", {5:23, 10:21, 15:22}, (2006,149.6588,2024,500.4548), (5,760.7213,21,639.0268)),
        ("truenoord-regional-2025", 44, "6.6", "CRJ9", "lease", {5:22, 10:23, 15:24}, (2009,102.6564,2024,526.5354), (50,291.2831,210,177.1771)),
        ("truenoord-regional-2022", 34, "32", "E195", "value", {3:25, 5:26, 10:27}, (2009,111.5341,2022,498.8361), (5,723.4477,35,638.7521)),
    ]
    observations, sources, curves = [], [], []
    documents = {}
    for ident, source in PDFS.items():
        path = ensure_cache(cache / source["file"], source["url"])
        if digest(path) != source["sha256"]:
            raise ValueError(f"PDF changed; re-check chart paths: {path.name}")
        documents[ident] = fitz.open(path)
        sources.append({"id": ident, "url": source["url"], "title": source["title"],
            "published": source["published"], "source_family": source["family"], "source_sha256": source["sha256"],
            "limitations": ["Historical curves are averages of appraiser opinions, not disclosed transaction prices.",
                "Chart digitization is approximate and kept distinct from text/table amounts.",
                "Digitization tolerance describes extraction, not market dispersion or a confidence interval.",
                "Only historical current-market-value and market-lease-rate figures are extracted; future base-value charts are excluded."]})
    for source_id, page, figure, code, kind, paths, xcal, ycal in configs:
        source = PDFS[source_id]
        drawings = documents[source_id][page].get_drawings()
        first_year, first_x, last_year, last_x = xcal
        low_yval, low_y, high_yval, high_y = ycal
        for years, index in paths.items():
            points = path_points(drawings[index]["items"])
            cid = f"{source_id}-fig{figure}-{code.lower()}-{kind}-{years}"
            curves.append({"id": cid, "source_id": source_id, "pdf_page": page+1, "figure": figure,
                "drawing_index": index, "x_calibration": list(xcal), "y_calibration": list(ycal),
                "vector_points": [[round(x,4),round(y,4)] for x,y in points]})
            for year in range(max(2016, first_year), last_year+1):
                if code == "DH8D" and years == 0 and year > 2021:
                    continue
                x = first_x + (last_x-first_x)*(year-first_year)/(last_year-first_year)
                y = read_curve(points, x)
                if y is None:
                    continue
                value = low_yval + (high_yval-low_yval)*(low_y-y)/(low_y-high_y)
                scale, rounding, tolerance = (1e6,100000,200000) if kind == "value" else (1000,1000,2000)
                amount = round(value*scale/rounding)*rounding
                o = record(f"history-{cid}-{year}",code,kind,str(year),years,amount,
                    source_id=source_id,source_url=source["url"],family=source["family"],
                    locator=f"PDF p.{page+1}, Figure {figure}, {years}-year curve, year {year}",
                    quality="chart_digitized", basis="average_appraised_current_market_value" if kind=="value" else "average_appraised_monthly_lease",
                    notes=["Value read from the published historical line at the labelled annual position, not a tabulated source number.",
                        "Geometric interpolation stays within the drawn source line; no absent years are extrapolated."])
                o.update(extraction_basis="pdf_vector_curve_at_printed_annual_axis", curve_id=cid,
                    extraction_rounding_usd=rounding, digitization_tolerance_usd=tolerance,
                    extraction_coordinates={"x":round(x,4),"y":round(y,4)},source_sha256=source["sha256"])
                if code == "CRJ9":
                    o["notes"].append("The 2025 report labels this CRJ900 without a NextGen restriction; it is not joined to AVAC CRJ900NG.")
                observations.append(o)
    return observations, sources, curves


def new_text_observations():
    values = []
    for kind, amount in (("value",33900000),("lease",242000)):
        o = record(f"history-truenoord-2021-e295-{kind}", "E295", kind, "2021-01", "new", amount,
            source_id="truenoord-crossover-2021", source_url=CROSSOVER_2021,
            family="TrueNoord average Avitas/CV/IBA/ICF/MBA/Oriel 2021",
            locator="PDF p.5 summary; p.34 Figure 29 values and p.37 Figure 31 leases, Air Finance Journal January 2021",
            basis="average_appraised_current_market_value" if kind=="value" else "average_appraised_monthly_lease",
            notes=["A published average of six appraiser opinions, not a midpoint computed from a market range.",
                "The January 2021 date is explicitly attached to the source figures; the report was published in May.",
                "Future base-value projections on pp.35–36 are not historical market values and are excluded."])
        o["source_sha256"] = "c3f9a68ba346bf064cb4a73c932547ec71a4233f769cf0148d737cbbece31b84"
        values.append(o)
    o = record("history-truenoord-2022-e195-lease-10", "E195", "lease", "2022", 10, 100000,
        source_id="truenoord-regional-2022", source_url=REGIONAL_2022,
        family=PDFS["truenoord-regional-2022"]["family"], locator="PDF p.35, section 6.3.5 E195, final paragraph",
        notes=["Approximate current lease opinion for a ten-year-old E195; publication July 2022, exact valuation month not stated.",
            "The source describes a possible small recovery since the second half of 2021, not a precise deal or a closed range."])
    o.update(estimate_type="approximate", source_sha256=PDFS["truenoord-regional-2022"]["sha256"])
    values.append(o)
    for code, kind, years, low, high, locator in [
        ("A332","value",12,30e6,None,"Widebody Aircraft, previous-generation values; A330-200, age 12"),
        ("B77W","value",12,57e6,None,"Widebody Aircraft, Boeing 777-300ER value, age 12"),
        ("A359","lease","new",1190000,1250000,"Widebody Aircraft, latest-generation market lease rates"),
        ("B789","lease","new",1070000,1150000,"Widebody Aircraft, latest-generation market lease rates"),
        ("A332","lease",12,324000,345000,"Widebody Aircraft, previous-generation market lease rates, age 12"),
        ("B77W","lease",12,450000,587000,"Widebody Aircraft, previous-generation market lease rates, age 12"),
    ]:
        values.append(record(f"history-iba-2026q1-{code.lower()}-{kind}-{years}",code,kind,"2026-Q1",years,low,high=high,
            source_id="iba-iclg-2026",source_url=ICLG,family="IBA",locator=locator,
            notes=["Appraisal opinion, not a disclosed deal. The reference period is Q1, not an invented month."]))
    for kind, amount in (("value",45e6),("lease",285000)):
        values.append(record(f"history-oriel-2026-e295-{kind}","E295",kind,"2026","new",amount,
            source_id="oriel-istat-e2-2026",source_url=ORIEL,family="Oriel",locator="Values and Lease Rates; new E195-E2; footnote to value table",
            variant="E195-E2, PW1923G",basis="full_life_market_value" if kind=="value" else "market_monthly_lease",
            notes=["Current opinion published 2026-03-12 after start-of-year revision; exact valuation month not stated, so year precision retained.",
                "New values have full-life condition; this is not the half-life basis of all used ages.",
                "The value uses the rounded USD45m prose figure; the January 2026 value table separately lists USD45.31m. The table date is not assumed for the lease rate."]))
    return values


def base_recent():
    src = json.loads((HERE/"out/additional_observations.json").read_text())
    observations = []
    for o in src["observations"]:
        if o["icao"] not in NAMES or o["source_id"].startswith("avac-"):
            continue
        if o.get("variant") == "A321-200NY":
            continue  # the main A321neo panel retains NX; XLR is not pooled into it
        r = record("history-"+o["id"],o["icao"],o["kind"],o["period"],o["age"],o["amount_low_usd"],
            high=o["amount_high_usd"],source_id=o["source_id"],source_url=o["source"],family="IBA",
            locator=o.get("locator","See original extraction and trace/prices.jsonl"),variant=o.get("variant"),
            basis=o.get("maintenance_basis") or o.get("valuation_basis"),notes=o.get("notes",[]))
        r["baseline_research_id"] = o["id"]
        r["estimate_type"] = o.get("estimate_type",r["estimate_type"])
        observations.append(r)
    return observations


def build(data):
    observations = data["observations"] + base_recent() + new_text_observations()
    seen=set()
    groups=defaultdict(list)
    for o in observations:
        if o["id"] in seen:
            raise ValueError(f"Duplicate observation ID {o['id']}")
        seen.add(o["id"])
        if not 0 < o["amount_low_usd"] <= o["amount_high_usd"]:
            raise ValueError(f"Invalid amount {o['id']}")
        parts=[o["icao"],o["kind"],str(o["age"].get("years","unknown")),o["variant"],o["valuation_basis"],
               o["source_family"],','.join(o.get("technical_specification",[])),o["extraction_basis"]]
        key="series-"+hashlib.sha256('|'.join(parts).encode()).hexdigest()[:16]
        o["series_key"]=key
        groups[key].append(o)
    observations.sort(key=lambda o:(TYPE_SEGMENT[o["icao"]],o["icao"],o["kind"],o["period"],o["age"].get("years",-1),o["id"]))
    series=[]
    for key,rows in sorted(groups.items()):
        first=rows[0]
        series.append({"id":key,**{k:first[k] for k in ("icao","kind","age","variant","valuation_basis","source_family","extraction_basis")},
            "technical_specification":first.get("technical_specification",[]),
            "observation_ids":[o["id"] for o in sorted(rows,key=lambda o:o["period"])]})
    aircraft=[]
    for code in NAMES:
        rows=[o for o in observations if o["icao"]==code]
        coverage={}
        for cohort in ("new","aged","unknown"):
            coverage[cohort]={}
            for kind in ("value","lease"):
                selected=[o for o in rows if o["age"]["category"]==cohort and o["kind"]==kind]
                years=sorted({int(o["period"][:4]) for o in selected})
                coverage[cohort][kind]={"count":len(selected),"years":years,"periods":sorted({o["period"] for o in selected}),
                    "missing_years_2016_2026":[y for y in range(2016,2027) if y not in years],
                    "source_ids":sorted({o["source_id"] for o in selected})}
        aircraft.append({"icao":code,"label":NAMES[code],"segment":TYPE_SEGMENT[code],"coverage":coverage})
    sources=data["sources"]+[
        {"id":"truenoord-crossover-2021","url":CROSSOVER_2021,"title":"TrueNoord Crossover Jets Market Report, May 2021",
            "published":"2021-05","period":"2021-01","source_family":"TrueNoord average Avitas/CV/IBA/ICF/MBA/Oriel 2021",
            "source_sha256":"c3f9a68ba346bf064cb4a73c932547ec71a4233f769cf0148d737cbbece31b84",
            "limitations":["Average of six appraiser opinions reproduced from Air Finance Journal January 2021; not disclosed deals.",
                "Half-life assumptions in future base-value figures are not silently applied to the separate historical CMV figures."]},
        {"id":"iba-iclg-2026","url":ICLG,"title":"IBA / Jon Whaley: aviation finance market, ICLG 2026","published":"2026-06-03","period":"2026-Q1","source_family":"IBA", "limitations":["Appraisal, not disclosed deal; published lease ranges depend on lessee credit.","A321NX and NY kept separate; half-life describes maintenance condition.","No new verbatim quote: existing trace/prices.jsonl already contains 22 quoted words from this URL."]},
        {"id":"oriel-istat-e2-2026","url":ORIEL,"title":"Oriel / Máximo Gainza: Appraisal Embraer E-Jet E2","published":"2026-03-12","period":"2026","source_family":"Oriel","limitations":["New values are full-life; specified PW1923G engine.","Publication month is not silently treated as an exact valuation month."]},
    ]
    # Register inherited podcast URL without assuming a particular old registry schema.
    known={s['id'] for s in sources}
    for o in observations:
        if o['source_id'] not in known:
            sources.append({"id":o['source_id'],"url":o['source_url'],"title":"IBA official podcast, May 2026","source_family":o['source_family'],
                "limitations":["Approximate spoken figures from the publisher transcript; see original source registry and trace."]})
            known.add(o['source_id'])
    return {"meta":{"schema_version":1,"as_of":AS_OF,"scope":"research_only_not_accepted","currency":"USD",
        "value_unit":"USD per aircraft","lease_unit":"USD per month","price_concept":"market appraisal; catalogue and deals excluded",
        "inputs_sha256":{"out/history_source_observations.json":digest(HERE/"out/history_source_observations.json"),
            "out/additional_observations.json":digest(HERE/"out/additional_observations.json"),
            "history.py":digest(HERE/"history.py"),
            "trace/history.jsonl":digest(HERE/"trace/history.jsonl")},
        "observation_count":len(observations),"types":len(NAMES),
        "plot_rules":["Main panels use new-aircraft observations only; aged and unknown-age observations are separate.",
            "Never connect different series_key values; break large chronological gaps within a series as well.",
            "Quarter and year dates remain coarse periods, not fabricated month observations.",
            "Chart digitization tolerance is not a market range; range bounds only represent published ranges.",
            "No missing value is replaced by zero, an extrapolation or a current price carried backward."],
        "selection_notes":["ATR42-600 replaces ATR72-500 because the available primary report has comparable new-aircraft history for the -600.",
            "E195-E1 replaces E190 because AVAC publishes explicit new-E195 historical values and leases in 2016–2019.",
            "Segmentation groups by operating market; E195-E2 also overlaps the small-narrowbody market."]},
        "segments":SEGMENTS,"aircraft":aircraft,"observations":observations,"series":series,"sources":sources,
        "quality_counts":dict(Counter(o['quality'] for o in observations)),
        "limitations":["Appraiser and technical basis can change; separate series are not automatically comparable.",
            "The 2023 turboprop report's text and plotted averages differ; chart values are retained as a distinct basis.",
            "DH8D new curves end in 2021; used values thereafter are not relabelled as new.",
            "Research histories do not change production data/prices, original summary.json or calculator rates."]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh',action='store_true')
    parser.add_argument('--cache-dir',type=Path)
    args=parser.parse_args()
    source_path=HERE/'out/history_source_observations.json'
    if args.refresh:
        if args.cache_dir is None:
            parser.error('--refresh needs --cache-dir outside the repository')
        cache=args.cache_dir.resolve()
        if cache==ROOT or ROOT in cache.parents:
            parser.error('raw-source cache must be outside the repository')
        cache.mkdir(parents=True,exist_ok=True)
        avac,avac_sources=extract_avac(cache)
        charts,chart_sources,curves=extract_charts(cache)
        dump(source_path,{"scope":"research_only_not_accepted","observations":avac+charts,"sources":avac_sources+chart_sources})
        dump(HERE/'out/history_chart_extraction.json',{"method":"Published PDF vector geometry, calibrated to printed axes; approximate values rounded before use.","curves":curves})
    data=json.loads(source_path.read_text())
    result=build(data)
    dump(HERE/'out/segments_history.json',result)
    print(f"History: {len(result['observations'])} observations, {len(NAMES)} types, {len(SEGMENTS)} segments")


if __name__=='__main__':
    main()
