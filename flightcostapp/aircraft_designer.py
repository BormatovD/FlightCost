"""Strict, versioned hand-off of a 3D design into the *existing* guest workspace.

The bundled v1
catalog is a pinned snapshot of Aircraft Designer's published v1 contract; it
must be updated and reviewed on BOTH sites if that contract changes.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .parsers.aircraft_user import FIELDS

CATALOG = Path(__file__).resolve().parent / "web" / "aircraft-configurations.v1.json"
PROTOCOL = "aircraft-designer/flightcost-design"
ID_PATTERN = re.compile(r"^[a-zA-Z0-9-]{8,80}$")


@lru_cache(maxsize=1)
def catalog() -> dict:
    d = json.loads(CATALOG.read_text(encoding="utf-8"))
    if d.get("schema") != "aircraft-designer/flightcost-configurations" or type(d.get("version")) is not int or d["version"] != 1:
        raise ValueError("Unsupported Aircraft Designer configuration catalog")
    return d


def seats_in_layout(layout: dict) -> int:
    return sum((z["rows"] - 1) * z["seatsPerRow"] + z.get("lastRowSeats", z["seatsPerRow"])
               for z in layout["zones"])


def choices(icao: str) -> list[dict]:
    """Only real Stage-1 models, each with its own engine and cabin."""
    out = []
    for preset in catalog()["aircraft"]:
        if preset["icao"] != icao:
            continue
        for layout in preset["layouts"]:
            out.append({"icao": icao, "aircraftId": preset["aircraftId"],
                        "engine": preset["engine"], "weightProfile": preset["weightProfile"],
                        "layoutId": layout["id"], "seats": seats_in_layout(layout),
                        "default": layout["id"] == preset["defaultLayoutId"]})
    return out


def engine_token(s: str) -> str:
    """Deliberately strict: PW1127G is NOT a LEAP, CFM56-5B4 is NOT -5B."""
    s = re.sub(r"^\s*2\s*[×x]\s*", "", str(s or "").strip(), flags=re.I)
    return re.sub(r"\s+", "", s).casefold()


def engine_matches(a: str, b: str) -> bool:
    # Cyrillic/Latin spelling is an established SAME-engine alias only for PS-90A.
    aliases = {"пс-90а": "ps-90a", "ps-90a": "ps-90a"}
    aa, bb = engine_token(a), engine_token(b)
    return bool(aa and bb and aliases.get(aa, aa) == aliases.get(bb, bb))


def _num(x: Any, key: str, low: float, high: float) -> float:
    if isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x) or not low <= x <= high:
        raise ValueError(f"Aircraft Designer: invalid {key}")
    return float(x)


def validate_design(data: Any) -> dict:
    if not isinstance(data, dict) or data.get("protocol") != PROTOCOL or type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("Aircraft Designer: unknown design version")
    ac, w = data.get("aircraft"), data.get("weights")
    if not isinstance(ac, dict) or not isinstance(w, dict):
        raise ValueError("Aircraft Designer: aircraft/weights missing")
    icao = ac.get("icao")
    if not isinstance(icao, str) or not re.fullmatch(r"[A-Z0-9]{2,4}", icao):
        raise ValueError("Aircraft Designer: invalid ICAO")
    match = next((a for a in choices(icao) if
                  a["aircraftId"] == ac.get("aircraftId") and
                  a["engine"] == ac.get("engine") and
                  a["weightProfile"] == ac.get("weightProfile") and
                  a["layoutId"] == ac.get("layoutId")), None)
    if match is None:
        raise ValueError("Aircraft Designer: unknown model, engine, layout or weight profile")
    zones = ac.get("cabin")
    if not isinstance(zones, list) or not (1 <= len(zones) <= 100):
        raise ValueError("Aircraft Designer: invalid cabin zones")
    seats = 0
    for z in zones:
        if not isinstance(z, dict) or z.get("class") not in ("economy", "business", "premium"):
            raise ValueError("Aircraft Designer: invalid cabin class")
        rows = z.get("rows"); per = z.get("seatsPerRow"); last = z.get("lastRowSeats", per)
        if any(type(n) is not int for n in (rows, per, last)) or not (1 <= rows <= 100 and 2 <= per <= 10 and 1 <= last <= per):
            raise ValueError("Aircraft Designer: invalid seats-per-row")
        _num(z.get("pitchM"), "pitchM", .65, 1.5)
        seats += (rows-1)*per + last
    if type(ac.get("seats")) is not int or not 1 <= seats <= 400 or ac["seats"] != seats:
        raise ValueError("Aircraft Designer: 3D seats differ from cabin rows")
    oew = _num(w.get("oew_kg"), "oew_kg", 1_000, 1_000_000)
    mtow = _num(w.get("mtow_kg"), "mtow_kg", 2_000, 1_000_000)
    mzfw = _num(w.get("mzfw_kg"), "mzfw_kg", 1_000, 1_000_000)
    mlw = _num(w.get("mlw_kg"), "mlw_kg", 1_000, 1_000_000)
    fuel = _num(w.get("fuel_capacity_kg"), "fuel_capacity_kg", 0, 1_000_000)
    if not (oew < mzfw <= mtow and oew < mlw <= mtow and fuel <= mtow):
        raise ValueError("Aircraft Designer: inconsistent masses")
    geo = data.get("geometry")
    if not isinstance(geo, dict):
        raise ValueError("Aircraft Designer: geometry missing")
    _num(geo.get("length_m"), "length_m", 10, 100)
    _num(geo.get("span_m"), "span_m", 10, 100)
    if not isinstance(data.get("model"), dict) or data["model"].get("provisional") is not True:
        raise ValueError("Aircraft Designer: unlabelled engineering model")
    return data


def make_workspace_doc(draft: dict, design: dict, *, user_icao: str, reference_engine: str) -> tuple[dict, bool]:
    """Preserve copied FlightCost parameters, override ONLY observed 3D data.

    MZFW and the full cabin travel in the workspace document for route replay.
    """
    ac = design["aircraft"]; w = design["weights"]
    seats = ac["seats"]
    doc = dict(draft)
    fields = {k: v for k, v in draft.get("fields", {}).items() if k in FIELDS}
    source_passport_max = int(fields.get("seats_max") or seats)
    fields.update({
        "mtow_t": w["mtow_kg"] / 1000,
        "oew_t": w["oew_kg"] / 1000,
        "mlw_t": w["mlw_kg"] / 1000,
        "fuel_capacity_t": w["fuel_capacity_kg"] / 1000,
        "seats_typical": seats,
        # A changed high-density design may exceed the base passport maximum.
        # Its ORIGINAL certified limit is retained separately in metadata;
        # the effective selected-seat cap is NOT a new certification.
        "seats_max": max(seats, source_passport_max),
        "span_m": design["geometry"]["span_m"],
        "length_m": design["geometry"]["length_m"],
    })
    doc.update({
        "icao": user_icao,
        "name": f"{draft.get('name') or ac['icao']} · 3D · {seats} seats",
        "engine": ac["engine"],
        "fields": fields,
        "source": f"Aircraft Designer 3D engineering model, v1; user-selected cabin ({seats} seats), provisional, not certified"
                  + ("; selected seats exceed published type capacity, NOT a new certification"
                     if seats > source_passport_max else ""),
        "source_url": "https://aircraft-designer.app/",
        "publisher": "user workspace (own engineering assumption)",
        "certainty": "exact",  # exactly what was submitted, not a certified claim
        "aircraft_designer": {"design": design, "base_icao": ac["icao"],
                              "mzfw_t": w["mzfw_kg"] / 1000,
                              "cabin_seats": seats,
                              "original_passport_seats_max": source_passport_max,
                              "selected_seats_exceed_passport": seats > source_passport_max},
    })
    same_engine = engine_matches(ac["engine"], reference_engine)
    # Draft burn may only be reused for the SAME engine. A different engine
    # must not inherit e.g. an A20N PW1127 model for the Designer's LEAP.
    if not same_engine:
        doc.pop("burn", None)
    return doc, same_engine


def new_user_key(icao: str, request_id: str) -> str:
    if not isinstance(request_id, str) or not ID_PATTERN.fullmatch(request_id):
        raise ValueError("Aircraft Designer: invalid request ID")
    return f"USER:{icao}-3D-{hashlib.sha256(request_id.encode()).hexdigest()[:12].upper()}"
