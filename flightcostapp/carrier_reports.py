"""Carrier-report drafts, evidence checks and explicit local acceptance.

python -m flightcostapp.carrier_reports draft.json
python -m flightcostapp.carrier_reports draft.json --accept FR/2026

Accepted YAML uses the existing carrier_benchmark refresh/snapshot path.
"""
from __future__ import annotations

import argparse
import calendar
import csv
import io
import fcntl
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import socket
import tempfile
from datetime import date
from urllib.parse import urlparse, parse_qs
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[1]
SEGMENTS = {"lowcost", "network", "hybrid_leisure"}
MAX_BYTES = 30 * 1024 * 1024


def catalog(directory=None):
    """Official document links and identifiers, including candidates from the study."""
    directory = Path(directory or ROOT / "data" / "benchmarks")
    rows = {}
    for path in sorted(directory.glob("*.yaml")):
        for doc in yaml.safe_load_all(path.read_text("utf8")):
            if not doc:
                continue
            code = str(doc["carrier"])
            rows[code] = {k: doc.get(k) for k in (
                "carrier", "name", "source_url", "scope", "segment", "entity_id",
                "period_start", "period_end", "published_at", "report_id", "source_sha256")}
            rows[code]["available_metrics"] = sorted(doc.get("values", {}))
            rows[code]["supporting_sources"] = sorted({
                value["source_url"] for value in doc.get("values", {}).values()
                if value.get("source_url") and value["source_url"] != doc.get("source_url")})
    study = ROOT / "research" / "benchmarks-2026-10" / "out" / "rating.json"
    if study.exists():
        for row in json.loads(study.read_text("utf8"))["carriers"]:
            if row.get("excluded"):
                continue
            code = row["code"]
            item = rows.setdefault(code, {"carrier": code, "name": row["name"]})
            item["segment"] = item.get("segment") or {"LCC": "lowcost", "ULCC": "lowcost", "network": "network", "hybrid": "hybrid_leisure", "leisure": "hybrid_leisure"}.get(row.get("model"))
            item["source_url"] = item.get("source_url") or row.get("source_url")
    return list(rows.values())


def add_months(day, months):
    month = day.year * 12 + day.month - 1 + months
    year, zero_month = divmod(month, 12)
    return date(year, zero_month + 1, min(day.day, calendar.monthrange(year, zero_month + 1)[1]))


def _public_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("source_url must be public HTTPS")
    for answer in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(answer[4][0]).is_global:
            raise ValueError("source_url resolves to a non-public address")


class _PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def evidence(url, directory):
    """Download source independently of the model, checking redirects as well."""
    from .agent_run import extract_text_safe
    _public_url(url)
    opener = urllib.request.build_opener(_PublicRedirect())
    with opener.open(urllib.request.Request(url, headers={"User-Agent": "FlightCostApp/1.0 (+https://flightcost.app)"}), timeout=60) as response:
        blob = response.read(MAX_BYTES + 1)
    if len(blob) > MAX_BYTES:
        raise ValueError("report exceeds 30 MB")
    if blob.startswith((b"%PDF-", b"PK")):
        suffix = ".pdf" if blob.startswith(b"%PDF-") else ".xlsx"
        path = Path(directory) / (hashlib.sha256(blob).hexdigest() + suffix)
        path.write_bytes(blob)
        text = extract_text_safe(path)
    else:
        from html import unescape
        text = unescape(re.sub(r"<[^>]+>", " ", blob.decode("utf8", "replace")))
    if not text or text.startswith("(текст не извлечён:"):
        raise ValueError("source text unavailable")
    return {"text": text, "sha256": hashlib.sha256(blob).hexdigest(), "url": url}


def report_index(text):
    """Select bounded original-text windows for costs, traffic and report periods."""
    lines = text.splitlines()
    groups = (
        ("Operating expenses", r"operating (?:costs|expenses)|total (?:operating )?expenses|total (?:operating )?costs"),
        ("Fuel expense", r"(?:aircraft |aviation |jet )?fuel(?: and oil| costs?| expenses?)?|combustible"),
        ("Capacity ASK/ASM", r"available seat|\bASKs?\b|\bASMs?\b"),
        ("Traffic RPK/RPM", r"revenue passenger|\bRPKs?\b|\bRPMs?\b"),
        ("Passengers", r"passengers? (?:carried|transported|enplaned)|revenue passengers|\bpassengers\b"),
        ("Report period", r"(?:fiscal |financial )?year ended|year ending|twelve months ended|full.year|reporting period"),
    )
    windows = []
    covered = set()
    for label, pattern in groups:
        regex = re.compile(pattern, re.I)
        candidates = []
        for index, line in enumerate(lines):
            if not regex.search(line):
                continue
            nearby = " ".join(lines[max(0, index - 1):index + 4])
            numbers = len(re.findall(r"\d[\d,.]*", nearby))
            # Adjacent numeric tables outrank contents pages and narrative references.
            score = min(numbers, 12) + (3 if re.search(r"\d[\d,.]*", line) else 0)
            candidates.append((-score, index))
        picked = 0
        for _, index in sorted(candidates):
            if index in covered:
                continue
            start, stop = max(0, index - 2), min(len(lines), index + 6)
            windows.append(f"=== {label}: original lines {start + 1}–{stop} ===\n" + "\n".join(lines[start:stop]))
            covered.update(range(start, stop))
            picked += 1
            if picked == 5:
                break
    return "\n\n".join(windows)


def benchmark_ready(doc):
    """A usable ex-fuel benchmark needs all five source quantities and period FX."""
    values = doc.get("values") or {}
    keys = ("opex_eur", "fuel_cost_eur", "ask_km", "rpk_km", "pax")
    if any(key not in values for key in keys):
        return False
    try:
        numbers = {key: float(values[key]["value"]) for key in keys}
        if (any(not math.isfinite(value) or value <= 0 for value in numbers.values())
                or numbers["fuel_cost_eur"] >= numbers["opex_eur"]
                or numbers["rpk_km"] > numbers["ask_km"]):
            return False
        currency = values["opex_eur"].get("currency")
        if currency == "EUR":
            return True
        fx = float(values.get("fx_per_eur", {}).get("value", 0))
        return bool(currency and math.isfinite(fx) and fx > 0)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def ecb_period_mean(url, text):
    """Compute a period mean from an official ECB CSV with explicit request dates."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "data-api.ecb.europa.eu" or "/EXR/" not in parsed.path:
        return None
    query = parse_qs(parsed.query)
    if len(query.get("startPeriod", [])) != 1 or len(query.get("endPeriod", [])) != 1:
        raise ValueError("ECB mean requires exact startPeriod and endPeriod")
    start_text, end_text = query["startPeriod"][0], query["endPeriod"][0]
    start = date.fromisoformat(start_text + "-01-01" if len(start_text) == 4 else start_text)
    end = date.fromisoformat(end_text + "-12-31" if len(end_text) == 4 else end_text)
    if start > end:
        raise ValueError("ECB requested period is reversed")
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    entries = list(reader)
    if not entries:
        raise ValueError("ECB CSV contains no observations")
    frequencies = {row.get("FREQ") for row in entries}
    if len(frequencies) != 1 or not frequencies.issubset({"A", "D"}):
        raise ValueError("ECB CSV requires one annual or daily frequency")
    expected_freq = next(iter(frequencies))
    if expected_freq == "A" and (start != date(start.year, 1, 1) or end != date(start.year, 12, 31)):
        raise ValueError("published ECB annual mean requires exactly one full calendar year")
    currencies = {row.get("CURRENCY") for row in entries}
    if (len(currencies) != 1 or None in currencies or "" in currencies
            or any(row.get("CURRENCY_DENOM") != "EUR" or row.get("FREQ") != expected_freq for row in entries)):
        raise ValueError("ECB CSV requires one currency per EUR and matching annual/daily frequency")
    values, days = [], []
    for row in entries:
        if row.get("OBS_VALUE") in (None, ""):
            continue
        value = float(row["OBS_VALUE"])
        if not math.isfinite(value) or value <= 0:
            raise ValueError("ECB observation must be positive and finite")
        time_period = row.get("TIME_PERIOD", "")
        if expected_freq == "A":
            if start.year != end.year or time_period != str(start.year):
                raise ValueError("ECB annual observation must match the full requested calendar year")
        else:
            day = date.fromisoformat(time_period)
            if not start <= day <= end or day in days:
                raise ValueError("ECB daily observation is outside requested period or duplicated")
            days.append(day)
        values.append(value)
    if not values or (expected_freq == "A" and len(values) != 1):
        raise ValueError("ECB annual/daily observations missing or ambiguous")
    if days and ((min(days) - start).days > 7 or (end - max(days)).days > 7):
        raise ValueError("ECB daily observations do not cover both ends of requested period")
    value = math.fsum(values) / len(values)
    currency = next(iter(currencies))
    quote = next(line for line in text.splitlines()[1:] if line.strip())[:300]
    basis = (f"ECB published annual mean, {start.isoformat()}–{end.isoformat()}, {currency} per EUR"
             if expected_freq == "A" else
             f"Arithmetic mean of {len(values)} ECB daily observations, {start.isoformat()}–{end.isoformat()}, {currency} per EUR; sum(OBS_VALUE)/{len(values)}")
    return {"value": value, "currency": currency, "period_start": start.isoformat(), "period_end": end.isoformat(),
            "count": len(values), "frequency": expected_freq, "source_url": url, "quote": quote,
            "page": "ECB CSV TIME_PERIOD, OBS_VALUE", "basis": basis}


def check_report(doc, today=None):
    """Formal checks supplement manual review of definitions and source numbers."""
    from .parsers.carrier_benchmark import parse
    today = today or date.today()
    errors = []
    for key in ("name", "source", "scope", "entity_id", "segment_basis", "report_id"):
        if not isinstance(doc.get(key), str) or not doc[key].strip():
            errors.append(f"missing {key}")
    if not re.fullmatch(r"[A-Z0-9]{2,12}", str(doc.get("carrier", ""))):
        errors.append("invalid carrier")
    if doc.get("segment") not in SEGMENTS:
        errors.append("invalid segment")
    try:
        start, end, published = (date.fromisoformat(doc[key]) for key in ("period_start", "period_end", "published_at"))
        if not 330 <= (end - start).days <= 380 or end > published or published > today:
            errors.append("require a completed full annual period and valid publication date")
        if doc.get("year") != end.year:
            errors.append("year must match period_end")
    except (KeyError, TypeError, ValueError):
        errors.append("invalid report dates")
    ev = doc.get("evidence") or {}
    url = doc.get("source_url")
    if not isinstance(url, str) or not url.startswith("https://") or ev.get("url") != url or not ev.get("sha256"):
        errors.append("source evidence missing")
    norm = lambda s: " ".join(str(s).split()).casefold()
    values = doc.get("values")
    if not isinstance(values, dict) or not values:
        return errors + ["values missing"]
    for key, row in values.items():
        if not isinstance(row, dict):
            errors.append(f"{key}: invalid value record")
            continue
        value = row.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            errors.append(f"{key}: invalid number")
        row_ev = row.get("evidence") or ev
        row_url = row.get("source_url") or url
        text = norm(row_ev.get("text", ""))
        if row_ev.get("url") != row_url or not row_ev.get("sha256"):
            errors.append(f"{key}: evidence source mismatch")
        if not row.get("page") or not row.get("quote") or norm(row.get("quote")) not in text:
            errors.append(f"{key}: quote/page missing or quote absent from source")
    def number(key):
        value = values.get(key, {}).get("value")
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    ask, rpk, pax = (number(k) for k in ("ask_km", "rpk_km", "pax"))
    if ask is not None and rpk is not None and rpk > ask:
        errors.append("RPK exceeds ASK")
    opex, fuel = number("opex_eur"), number("fuel_cost_eur")
    if opex is not None and fuel is not None and fuel > opex:
        errors.append("fuel exceeds operating expenses")
    money = [v for k, v in values.items() if k.endswith("_eur") and k != "fx_per_eur" and isinstance(v, dict)]
    currencies = {v.get("currency") for v in money}
    if money and (None in currencies or "" in currencies or len(currencies) != 1):
        errors.append("monetary values require one consistent source currency")
    if currencies and currencies != {"EUR"} and not number("fx_per_eur"):
        errors.append("non-EUR report requires the mean period exchange rate with evidence")
    try:
        parse(yaml.safe_dump(doc, allow_unicode=True).encode(), {"source_id": "carrier_benchmark"})
    except (ValueError, TypeError, KeyError) as exc:
        errors.append(str(exc))
    return errors


def accept(doc, directory=None):
    """Serialize acceptance so simultaneous revisions preserve neighboring contours."""
    directory = Path(directory or ROOT / "data" / "benchmarks")
    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(directory, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        return _accept_locked(doc, directory)
    finally:
        os.close(fd)


def _accept_locked(doc, directory):
    """Explicitly replace this carrier/year only, preserving other report contours."""
    errors = check_report(doc)
    if errors:
        raise ValueError("; ".join(errors))
    directory = Path(directory or ROOT / "data" / "benchmarks")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{doc['carrier']}-{doc['year']}.yaml"
    # One file may contain multiple contours. Find an existing matching document first.
    matches = []
    for candidate in directory.glob("*.yaml"):
        docs = list(yaml.safe_load_all(candidate.read_text("utf8")))
        if any(x and str(x.get("carrier")) == doc["carrier"] and x.get("year") == doc["year"] for x in docs):
            matches.append((candidate, docs))
    if len(matches) > 1:
        raise ValueError("duplicate accepted carrier/year; resolve before acceptance")
    accepted = {k: v for k, v in doc.items() if k not in ("evidence", "doubts")}
    accepted["source_sha256"] = doc["evidence"]["sha256"]
    accepted["values"] = {
        key: {**{field: value for field, value in row.items() if field != "evidence"},
              "source_sha256": (row.get("evidence") or doc["evidence"])["sha256"]}
        for key, row in doc["values"].items()}
    if matches:
        path, docs = matches[0]
        previous = next(x for x in docs if x and str(x.get("carrier")) == doc["carrier"] and x.get("year") == doc["year"])
        for field in ("period_end", "published_at"):
            if previous.get(field) and str(doc[field]) < str(previous[field]):
                raise ValueError("cannot replace an accepted report with an older " + field)
        docs = [accepted if x and str(x.get("carrier")) == doc["carrier"] and x.get("year") == doc["year"] else x for x in docs]
    else:
        if path.exists():
            raise ValueError("destination contains another report")
        docs = [accepted]
    payload = yaml.safe_dump_all(docs, allow_unicode=True, sort_keys=False)
    if path.exists() and path.read_text("utf8") == payload:
        return path
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf8") as out:
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft", type=Path)
    parser.add_argument("--accept", metavar="CARRIER/YEAR", help="explicitly accept one reviewed report")
    args = parser.parse_args(argv)
    draft = json.loads(args.draft.read_text("utf8"))
    reports = draft.get("reports", [])
    if args.accept and sum(f"{r.get('carrier')}/{r.get('year')}" == args.accept for r in reports) != 1:
        parser.error("--accept must select exactly one report")
    rejected = False
    for report in reports:
        key = f"{report.get('carrier')}/{report.get('year')}"
        errors = check_report(report)
        print(key, "REJECT " + "; ".join(errors) if errors else "REVIEW", report.get("name"), report.get("period_end"), report.get("segment"), report.get("source_url"))
        print("scope:", report.get("scope"), "segment basis:", report.get("segment_basis"), "doubts:", report.get("doubts", []))
        rejected = rejected or bool(errors)
        if key == args.accept:
            if errors:
                rejected = True
            else:
                print("accepted:", accept(report))
    return 2 if rejected else 0


if __name__ == "__main__":
    raise SystemExit(main())
