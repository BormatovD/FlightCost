"""Route-length-adjusted, ex-fuel benchmarks from accepted carrier facts."""
from __future__ import annotations

import calendar
import json
import math
from collections import defaultdict
from datetime import date

SEGMENTS = {"lowcost": "Лоукостеры", "network": "Сетевые",
            "hybrid_leisure": "Гибридные и туристические"}


def anniversary(day: date, months: int) -> date:
    year, month = divmod(day.year * 12 + day.month - 1 + months, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def quantile(values: list[float], fraction: float) -> float:
    values = sorted(values)
    position = (len(values) - 1) * fraction
    low = math.floor(position)
    high = math.ceil(position)
    return values[low] + (values[high] - values[low]) * (position - low)


def comparison(store, distance_km: float, as_of: date, include_stale=False) -> dict:
    out = {"distance_km": distance_km, "exponent": 0.5, "carriers": [], "segments": []}
    if not math.isfinite(distance_km) or distance_km <= 0:
        return out
    rows = store.db.execute(
        "SELECT key,value,value_text,currency,note FROM facts "
        "WHERE domain='carrier_benchmark' AND valid_to IS NULL").fetchall()
    reports = defaultdict(dict)
    for row in rows:
        code, period, metric = row["key"].split("/", 2)
        reports[(code, period)][metric] = row
    latest_period = {}
    for (code, _), facts in reports.items():
        meta = json.loads(facts.get("opex_eur", next(iter(facts.values())))["value_text"] or "{}")
        end = meta.get("period_end")
        published = meta.get("published_at")
        if end and end <= as_of.isoformat() and (not published or published <= as_of.isoformat()):
            entity = meta.get("entity_id") or code
            latest_period[entity] = max(latest_period.get(entity, ""), end)
    candidates = []
    for (code, period), facts in reports.items():
        meta = json.loads(facts.get("opex_eur", next(iter(facts.values())))["value_text"] or "{}")
        segment = meta.get("segment")
        if segment not in SEGMENTS or not meta.get("period_end"):
            continue
        end = date.fromisoformat(meta["period_end"])
        if end.isoformat() != latest_period.get(meta.get("entity_id") or code):
            continue
        published = meta.get("published_at")
        if end > as_of or (published and date.fromisoformat(published) > as_of):
            continue
        if as_of > anniversary(end, 24):
            continue
        stale = as_of > anniversary(end, 18)
        if stale and not include_stale:
            continue
        def number(key):
            row = facts.get(key)
            return row["value"] if row else None
        ask, rpk, pax = number("ask_km"), number("rpk_km"), number("pax")
        opex, fuel = number("opex_eur"), number("fuel_cost_eur")
        if any(x is None or not math.isfinite(x) or x <= 0 for x in (ask, rpk, pax, opex, fuel)):
            continue
        if fuel >= opex:
            continue
        currency = facts["opex_eur"]["currency"] or "EUR"
        fuel_currency = facts["fuel_cost_eur"]["currency"] or "EUR"
        if fuel_currency != currency:
            continue
        rate = 1.0 if currency == "EUR" else number("fx_per_eur")
        if rate is None or not math.isfinite(rate) or rate <= 0:
            continue
        sector = rpk / pax
        casx = (opex - fuel) / rate / ask * 100
        candidates.append({
            "carrier": f"{code}/{period}", "code": code,
            "entity_id": meta.get("entity_id") or code,
            "name": meta.get("name") or code, "scope": meta.get("scope", ""),
            "segment": segment, "period_start": meta.get("period_start"),
            "period_end": end.isoformat(), "stale": stale,
            "age_months": (as_of.year-end.year)*12+as_of.month-end.month,
            "source_url": meta.get("report_source_url") or meta.get("source_url") or facts["opex_eur"]["note"],
            "sector_km": sector, "casx_cents": casx,
            "adjusted_cents": casx * math.sqrt(sector / distance_km)})
    # One latest accepted, eligible observation per independent entity.
    latest = {}
    for item in sorted(candidates, key=lambda c: (c["period_end"], c["code"])):
        latest[item["entity_id"]] = item
    out["carriers"] = sorted(latest.values(), key=lambda c: c["name"])
    for segment, name in SEGMENTS.items():
        observations = [c for c in out["carriers"] if c["segment"] == segment]
        values = [c["adjusted_cents"] for c in observations]
        out["segments"].append({
            "id": segment, "name": name, "n": len(values), "observations": observations,
            **{key: quantile(values, q) if len(values) >= 5 else None
               for key, q in (("p25", .25), ("p50", .5), ("p75", .75))}})
    return out
