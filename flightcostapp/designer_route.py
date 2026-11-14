"""Route adapter for a saved A320ceo or A320neo design in the active guest workspace."""
from __future__ import annotations

import json
import os
import subprocess
from functools import lru_cache
from pathlib import Path

from .fuel import Feasibility, FuelResult, ReserveSpec, icao_distance_nm

ROUTE_MODELS = {
    ("A20N", "a320neo", "LEAP-1A"): "a320neo-leap-mission-v1",
    ("A320", "a320ceo", "CFM56-5B"): "a320ceo-cfm56-5b-mission-v1",
}
DESIGNER_REVISION = "6d3ee2d02849477b0f5eb0b24a95986b1595b044"


def _runner() -> str | None:
    override = os.environ.get("FCA_DESIGNER_RUNNER")
    if override is not None:
        return override or None
    installed = Path("/srv/fca/designer") / DESIGNER_REVISION / "scripts/flightcost-route.ts"
    return str(installed) if installed.is_file() else None


def model_for(design: dict) -> str | None:
    ac = design.get("aircraft") or {}
    return ROUTE_MODELS.get((ac.get("icao"), ac.get("aircraftId"), ac.get("engine")))


@lru_cache(maxsize=256)
def _call(runner: str, payload: str, expected_model: str) -> dict:
    try:
        result = subprocess.run(["node", runner], input=payload, text=True,
                                capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Расчёт Aircraft Designer недоступен") from exc
    if result.returncode:
        # The runner also diagnoses a saved configuration it cannot reproduce.
        raise ValueError("Aircraft Designer: " + (result.stderr.strip().splitlines() or ["ошибка модели"])[0][:220])
    response = json.loads(result.stdout)
    if response.get("model") != expected_model:
        raise ValueError("Несовместимая версия маршрутизатора Aircraft Designer")
    return response


def _run(design: dict, route: dict | None = None) -> dict:
    expected = model_for(design)
    if expected is None:
        raise ValueError("Неизвестная конфигурация Aircraft Designer")
    runner = _runner()
    if not runner:
        raise ValueError("Для сохранённой 3D-конфигурации нужен расчёт Aircraft Designer")
    return _call(runner, json.dumps({"design": design, "route": route}, sort_keys=True, allow_nan=False), expected)


def saved_model(design: dict) -> str | None:
    if model_for(design) and _runner():
        return _run(design)["model"]
    return None


def saved_design(store, key: str) -> dict | None:
    if key.startswith(("USER:A20N-3D-", "USER:A320-3D-")) and getattr(store, "gdb", None):
        doc = store.gdb.get_doc(store.ws, "aircraft", key) or {}
        design = (doc.get("aircraft_designer") or {}).get("design") or {}
        if model_for(design):
            return design
    return None


def trip_fuel(design: dict, gcd_nm: float, pax: int, spec: ReserveSpec) -> FuelResult:
    distance, distance_note = icao_distance_nm(gcd_nm)
    route = {"distanceNm": distance, "pax": pax, "contingency": spec.contingency_frac,
             "finalMin": spec.final_reserve_min}
    if spec.alternate_nm is not None:
        route["alternateNm"] = spec.alternate_nm
    result = _run(design, route)
    r = result["route"]
    feasible = Feasibility(max_pax=r["maxPax"])
    for key, reason in r["limits"].items():
        feasible.limit(key, reason)
    phases = {"taxi": "Руление", "climb": "Набор", "cruise": "Крейсер", "descent": "Снижение"}
    reserve = r["reserves"]
    return FuelResult(trip_kg=r["tripKg"], block_h=r["blockMin"] / 60,
                      airborne_h=(r["blockMin"] - r["minutes"]["taxi"]) / 60,
                      takeoff_mass_kg=r["takeoffMassKg"], feasible=feasible, method="designer",
                      phases={name: r["fuel"][key] for key, name in phases.items()},
                      times={name: r["minutes"][key] / 60 for key, name in phases.items()},
                      note=f"Aircraft Designer · {design['aircraft']['engine']} · {distance_note}",
                      tier_note=result["model"],
                      reserve_kg=reserve["totalKg"], reserve_parts={
                          "Непредвиденный": reserve["contingencyKg"], "Запасной": reserve["alternateKg"],
                          "Конечный": reserve["finalKg"]})
