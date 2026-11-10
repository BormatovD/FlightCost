"""GISCO: точки подписи регионов NUTS (центр региона), домен `macro`.

Нужны, чтобы привязать аэропорт к региону NUTS без полигонов: ближайшая точка подписи
уровня 3 (для туризма — уровня 2). У границ регионов возможна ошибка соседа; для
показателей, которые меняются плавно (ВВП, ночёвки), это терпимо, и так и подписано.

GeoJSON: `features[].properties.{NUTS_ID, LEVL_CODE, CNTR_CODE, NAME_LATN}`,
`geometry.coordinates = [долгота, широта]`. Ключ: `nuts_lb/<код>`, текст
«широта,долгота|уровень|страна|название». © EuroGeographics для административных границ.
"""

from __future__ import annotations

import json

from ..store import Fact

WHO = "parser:gisco_nuts@1"


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    d = json.loads(blob)
    out = []
    for f in d.get("features") or []:
        p, g = f.get("properties") or {}, (f.get("geometry") or {}).get("coordinates")
        nid = p.get("NUTS_ID") or f.get("id")
        if not nid or not g or len(g) < 2:
            continue
        lon, lat = float(g[0]), float(g[1])
        out.append(Fact(domain="macro", key=f"nuts_lb/{nid}", valid_from=ctx.get("today") or "2021-01-01",
                        value=float(p.get("LEVL_CODE", len(nid) - 2)), unit="уровень NUTS",
                        value_text=f"{lat:.4f},{lon:.4f}|{p.get('LEVL_CODE')}|{p.get('CNTR_CODE')}|{p.get('NAME_LATN')}",
                        source_id=ctx["source_id"], artifact_sha=ctx.get("sha"), extracted_by=WHO,
                        node=ctx.get("node")))
    if not out:
        raise ValueError("в GeoJSON нет точек NUTS")
    ctx.setdefault("summary", []).append(f"точек NUTS {len(out)}")
    return out
