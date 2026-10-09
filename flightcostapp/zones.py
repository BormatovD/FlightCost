"""Мировые границы FIR из `data/geo/zones_world.json` (парсер `fir_world`).

Пока один потребитель — обход закрытого неба: ему нужны полигоны зон,
закрытых перевозчику. Слияние с полигонами EUROCONTROL для начисления
сборов (Европа — точные, остальное — отсюда) живёт в `airspace`.
"""

from __future__ import annotations

import json
from pathlib import Path

ZONES_WORLD = Path("data/geo/zones_world.json")


def load_world(path: Path | None = None) -> dict:
    """id → {"prefix", "rings": [[(lat, lon), …], …]}. Нет файла — пустой
    словарь, и вызывающий обязан сказать это вслух (решение 37)."""
    p = Path(path or ZONES_WORLD)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("schema") != "fca.zones/1":
        raise ValueError(f"{p}: неизвестная схема {data.get('schema')!r}")
    return {z["id"]: {"prefix": z["prefix"],
                      "rings": [[tuple(pt) for pt in r] for r in z["rings"]]}
            for z in data["zones"]}


def closed_polygons(carrier: str, as_of, closures, zones: dict | None = None) -> dict:
    """Полигоны зон, закрытых для пролёта перевозчику этой страны на дату."""
    if zones is None:
        zones = load_world()
    as_of = str(as_of)
    out = {}
    for zid, z in zones.items():
        for cl in closures:
            if cl.active(as_of) and cl.applies_to(carrier.upper()) and cl.zone_hit(zid):
                out[zid] = z["rings"]
                break
    return out
