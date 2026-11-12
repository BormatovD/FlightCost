#!/usr/bin/env python3
"""Conservative IATI Datastore v3 research snapshot. No third-party packages.

Creates *candidate evidence*, not accepted investment projects or flight forecasts.
Authentication stays in an HTTP header; never write or log the API key.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import gzip
import json
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_URL = "https://api.iatistandard.org/datastore/activity/select"
KEY_HEADER = "Ocp-Apim-Subscription-Key"
# DAC sector codes; always check @vocabulary on a structured activity before classifying.
SECTORS = {
    "33210": "tourism_policy", "33220": "tourism_hospitality",
    "32110": "manufacturing_policy", "32120": "manufacturing_development",
    "21010": "transport_policy", "21020": "road_transport",
    "21030": "rail_transport", "21040": "water_transport",
    "21050": "air_transport", "21061": "storage",
    "23030": "electricity_generation", "32210": "mineral_prospecting",
}
COUNTRIES = {"EG": "EGY", "MA": "MAR", "KE": "KEN", "ET": "ETH",
             "TZ": "TZA", "CV": "CPV", "NG": "NGA", "ZA": "ZAF",
             "GH": "GHA", "CI": "CIV"}
TRANSACTION_TYPES = {"1": "incoming_funds", "2": "outgoing_commitment",
                     "3": "disbursement", "4": "expenditure",
                     "11": "incoming_commitment", "12": "outgoing_pledge",
                     "13": "incoming_pledge"}
FIELDS = "activity_id,iati_identifier,iati_json"
MAX_RESPONSE_BYTES = 24_000_000


def elements(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def first(value):
    return elements(value)[0] if elements(value) else None


def text_value(value):
    """Read IATI structured JSON text(), nested narrative, or optional scalar."""
    if value is None:
        return None
    if isinstance(value, list):
        for item in value:
            result = text_value(item)
            if result is not None:
                return result
        return None
    if isinstance(value, dict):
        if value.get("text()") is not None:
            return str(value["text()"])
        for key in ("narrative", "name", "title"):
            if key in value:
                return text_value(value[key])
        return None
    return str(value)


def attr(value, attribute):
    item = first(value)
    return item.get("@" + attribute) if isinstance(item, dict) else None


def decimal_string(value):
    if value is None:
        return None
    try:
        number = Decimal(str(value).strip())
        if not number.is_finite():
            return None
        return format(number, "f")
    except (InvalidOperation, ValueError):
        return None


def parse_coordinates(pos):
    if not pos:
        return None
    try:
        # Official IATI format is latitude longitude (not longitude latitude).
        tokens = str(pos).split()
        if len(tokens) != 2:
            return None
        latitude, longitude = (float(v) for v in tokens)
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            return None
        return {"lat": latitude, "lon": longitude}
    except ValueError:
        return None


def decode_structured(doc):
    raw = doc.get("iati_json")
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, dict):
        raise ValueError("IATI response missing structured iati_json; refusing flat multi-valued fields")
    activities = elements(raw.get("iati-activity"))
    if len(activities) != 1 or not isinstance(activities[0], dict):
        raise ValueError("Unexpected activity structure in iati_json")
    return activities[0]


def normalize_activity(doc, fetched_at):
    raw = decode_structured(doc)
    identifier = text_value(raw.get("iati-identifier")) or text_value(doc.get("iati_identifier"))
    if not identifier:
        raise ValueError("Activity missing stable IATI identifier")

    recipient_countries = []
    for elem in elements(raw.get("recipient-country")):
        if isinstance(elem, dict) and elem.get("@code"):
            recipient_countries.append({"iso2": elem["@code"],
                                        "share_pct": decimal_string(elem.get("@percentage"))})

    sectors = []
    for elem in elements(raw.get("sector")):
        if not isinstance(elem, dict):
            continue
        vocabulary, code = str(elem.get("@vocabulary", "")), str(elem.get("@code", ""))
        sectors.append({"code": code, "vocabulary": vocabulary,
                        "share_pct": decimal_string(elem.get("@percentage")),
                        "category": SECTORS.get(code) if vocabulary == "1" else None})

    locations = []
    for location in elements(raw.get("location")):
        if not isinstance(location, dict):
            continue
        point = first(location.get("point"))
        position = text_value(point.get("pos")) if isinstance(point, dict) else None
        locations.append({
            "name": text_value(location.get("name")),
            "coordinates": parse_coordinates(position),
            "exactness_code": attr(location.get("exactness"), "code"),
            "reach_code": attr(location.get("location-reach"), "code"),
            "location_class_code": attr(location.get("location-class"), "code"),
            # Coordinates may describe an entire city/region; not necessarily a construction site.
        })

    transactions = []
    for transaction in elements(raw.get("transaction")):
        if not isinstance(transaction, dict):
            continue
        value = first(transaction.get("value"))
        value = value if isinstance(value, dict) else {}
        txcode = str(attr(transaction.get("transaction-type"), "code") or "")
        transactions.append({
            "kind_code": txcode,
            "kind": TRANSACTION_TYPES.get(txcode, "other"),
            "date": attr(transaction.get("transaction-date"), "iso-date"),
            "amount": decimal_string(text_value(value)),
            "currency": value.get("@currency") or raw.get("@default-currency"),
            "value_date": value.get("@value-date"),
        })

    budgets = []
    for budget in elements(raw.get("budget")):
        if not isinstance(budget, dict):
            continue
        value = first(budget.get("value"))
        value = value if isinstance(value, dict) else {}
        budgets.append({
            "start": attr(budget.get("period-start"), "iso-date"),
            "end": attr(budget.get("period-end"), "iso-date"),
            "amount": decimal_string(text_value(value)),
            "currency": value.get("@currency") or raw.get("@default-currency"),
            "type_code": budget.get("@type"),
            "status_code": budget.get("@status"),
        })

    dates = []
    for item in elements(raw.get("activity-date")):
        if isinstance(item, dict):
            dates.append({"type_code": item.get("@type"), "date": item.get("@iso-date")})

    return {
        "source_id": "iati_datastore_v3",
        "iati_identifier": identifier,
        "reporting_org": attr(raw.get("reporting-org"), "ref"),
        "title": text_value(raw.get("title")),
        "description": text_value(raw.get("description")),
        "recipient_countries": recipient_countries,
        "sectors": sectors,
        "status_code": attr(raw.get("activity-status"), "code"),
        "activity_dates": dates,
        "locations": locations,
        "transactions": transactions,
        "budgets": budgets,
        "reported_last_updated_at": raw.get("@last-updated-datetime"),
        "snapshot_at": fetched_at,
        "historically_available_before_snapshot": "unverified",
        "source_url": API_URL,
        "notes": [
            "One IATI activity may cover multiple countries and sites; do not assign total funds to any one airport.",
            "Budget, commitment, disbursement and expenditure are different cash-flow stages; never sum across them.",
            "Reporting organisation's last-updated datetime is NOT the first public disclosure date.",
        ],
    }


def query_url(country, rows=50, start=0):
    if country not in COUNTRIES:
        raise ValueError("Unsupported ISO2 country code: " + country)
    if not 1 <= rows <= 1000 or start < 0:
        raise ValueError("Invalid IATI pagination")
    q = f"recipient_country_code:{country} AND sector_code:({' '.join(SECTORS)})"
    params = {"q": q, "rows": rows, "start": start, "fl": FIELDS,
              "wt": "json", "sort": "activity_id asc"}
    return API_URL + "?" + urlencode(params)


def request_page(url, key, opener=urlopen):
    request = Request(url, headers={KEY_HEADER: key, "Accept": "application/json",
                                    "User-Agent": "FlightCost-Research/0061 (+https://flightcost.app)"})
    try:
        with opener(request, timeout=50) as result:
            data = result.read(MAX_RESPONSE_BYTES + 1)
            if len(data) > MAX_RESPONSE_BYTES:
                raise ValueError("Response too large; lower --rows")
    except HTTPError as error:
        descriptions = {401: "IATI key missing/invalid", 403: "IATI quota or permission denied",
                        429: "IATI request limit reached"}
        raise RuntimeError(f"IATI HTTP {error.code}: {descriptions.get(error.code, 'request failed')}") from None
    except URLError as error:
        raise RuntimeError(f"IATI network error: {type(error.reason).__name__}") from None
    payload = json.loads(data)
    response = payload.get("response") if isinstance(payload, dict) else None
    if not isinstance(response, dict) or not isinstance(response.get("docs"), list) or not isinstance(response.get("numFound"), int):
        raise ValueError("Unexpected IATI SOLR response structure")
    return response, hashlib.sha256(data).hexdigest(), data


def read_key(key_file):
    path = Path(key_file).expanduser()
    # Explicit environment variable is useful for CI, but secret never appears in diagnostics.
    key = os.environ.get("FCA_IATI_API_KEY", "").strip()
    if not key:
        if not path.exists():
            raise RuntimeError(f"IATI key not found: {path}. See README-0061-IATI.md")
        key = path.read_text(encoding="utf-8").strip()
        if os.name != "nt" and path.stat().st_mode & 0o007:
            raise RuntimeError("IATI key file must not be readable by other users")
    if not key or any(ch.isspace() for ch in key):
        raise RuntimeError("Empty/malformed IATI key")
    return key


def atomic_json(path, payload):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    os.replace(tmp, path)


def run(argv=None, *, opener=urlopen, sleeper=time.sleep, clock=None):
    parser = argparse.ArgumentParser(description="IATI project candidates, point-in-time snapshot (research only)")
    parser.add_argument("--key-file", default="~/.config/flightcost/iati.key")
    parser.add_argument("--countries", default="KE,TZ,MA,EG,ET,CV", help="Comma-separated ISO2 codes")
    parser.add_argument("--rows", type=int, default=30)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--pause", type=float, default=13.0, help="Seconds between calls; respect Exploratory limits")
    parser.add_argument("--out", default=None, help="Snapshot directory, outside git (recommended: analysis/iati/YYYY-MM-DD)")
    parser.add_argument("--probe", action="store_true", help="One authenticated request only, no records written")
    parser.add_argument("--dry-run", action="store_true", help="Show safe planned queries, no key or network")
    args = parser.parse_args(argv)
    countries = [x.strip().upper() for x in args.countries.split(",") if x.strip()]
    if not countries or len(countries) != len(set(countries)) or any(c not in COUNTRIES for c in countries):
        parser.error("Invalid or duplicate country codes")
    if not 1 <= args.rows <= 100 or not 1 <= args.max_pages <= 3 or args.pause < 0:
        parser.error("Pilot limits: rows 1–100; max-pages 1–3; pause >= 0")
    if args.dry_run:
        for c in countries[:1 if args.probe else len(countries)]:
            print(c, query_url(c, 1 if args.probe else args.rows))
        return None

    key = read_key(args.key_file)
    now = clock() if clock else datetime.now(timezone.utc)
    captured_at = now.astimezone(timezone.utc).isoformat(timespec="seconds")
    output = Path(args.out or f"analysis/iati/{now:%Y-%m-%dT%H%M%SZ}")
    manifest = {"snapshot_at": captured_at, "source": API_URL,
                "version": "0061-pilot", "key_in_files": False,
                "historical_backtest_eligible": False, "countries": [],
                "warnings": ["Current IATI snapshot only: NOT eligible for 2015–2025 historical backtesting."]}
    candidates = {}
    # First probe takes exactly one call, making it safe on the Exploratory tier.
    if args.probe:
        resp, _sha, _data = request_page(query_url(countries[0], rows=1), key, opener)
        print(f"IATI API OK | country={countries[0]} | matching={resp['numFound']} | key: accepted")
        return manifest

    # Create a private, timestamped snapshot directory before the first page.
    # An interrupted run has no completed manifest and must never be used as a dataset.
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    output.chmod(0o700)
    raw_folder = output / "raw"
    raw_folder.mkdir(mode=0o700)
    calls = 0
    for country in countries:
        total_seen = 0
        total_found = None
        shas = []
        for page in range(args.max_pages):
            if calls:
                sleeper(args.pause)
            url = query_url(country, args.rows, page * args.rows)
            response, checksum, body = request_page(url, key, opener)
            calls += 1
            # Preserve the actual public response as captured, not just derived columns.
            raw_name = f"{country}-{page:03d}.json.gz"
            raw_path = raw_folder / raw_name
            with gzip.open(raw_path, "wb") as stream:
                stream.write(body)
            raw_path.chmod(0o600)
            shas.append({"file": "raw/" + raw_name, "response_sha256": checksum})
            total_found = response["numFound"]
            docs = response["docs"]
            if not docs:
                break
            for doc in docs:
                record = normalize_activity(doc, captured_at)
                # Preserve one record per activity even if found in multiple country searches.
                existing = candidates.get(record["iati_identifier"])
                if existing and existing != record:
                    raise ValueError("Conflicting source records for the same IATI identifier")
                candidates[record["iati_identifier"]] = record
            total_seen += len(docs)
            if total_seen >= total_found:
                break
        manifest["countries"].append({"iso2": country, "api_matched": total_found,
                                      "rows_retrieved": total_seen,
                                      "truncated": total_found is not None and total_seen < total_found,
                                      "page_sha256": shas})
    manifest["unique_activities"] = len(candidates)
    manifest["api_calls"] = calls
    manifest["warnings"].append("Totals are NOT investment amounts; candidate activities are NOT all investments.")
    # JSONL: deterministic order, preserves each activity's structured amounts and locations.
    with (output / "candidates.jsonl").open("x", encoding="utf-8") as stream:
        for identifier in sorted(candidates):
            stream.write(json.dumps(candidates[identifier], ensure_ascii=False, sort_keys=True) + "\n")
    atomic_json(output / "manifest.json", manifest)
    (output / "manifest.json").chmod(0o600)
    (output / "candidates.jsonl").chmod(0o600)
    print(f"IATI candidates={len(candidates)} calls={calls} saved={output}")
    for item in manifest["countries"]:
        print(f"  {item['iso2']}: retrieved={item['rows_retrieved']} / matched={item['api_matched']}"
              + (" (PARTIAL SAMPLE)" if item["truncated"] else ""))
    return manifest


if __name__ == "__main__":
    try:
        run()
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"IATI: {exc}", file=sys.stderr)
        sys.exit(1)
