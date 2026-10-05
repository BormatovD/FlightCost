"""OurAirports: полосы -> ограничения аэродрома.

Длина и ширина полосы, покрытие и превышение аэродрома определяют, может
ли тип вообще сюда прилететь. До сих пор модель считала экономику рейса
A388 в аэропорт с полосой в полтора километра и ничего не замечала.

Источник тот же, что для координат, и уже качается: отдельного поиска не
понадобилось. Берётся самая длинная полоса аэродрома — она и определяет,
что сюда садится.
"""

from __future__ import annotations

import csv
import io

from ..store import Fact

FT_TO_M = 0.3048


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    rows = csv.DictReader(io.StringIO(blob.decode("utf-8-sig", errors="replace")))
    day = ctx.get("today") or ""
    best: dict[str, dict] = {}

    for r in rows:
        icao = (r.get("airport_ident") or "").strip().upper()
        if not icao:
            continue
        try:
            length = float(r.get("length_ft") or 0) * FT_TO_M
            width = float(r.get("width_ft") or 0) * FT_TO_M
        except ValueError:
            continue
        if length <= 0:
            continue
        # Закрытые полосы не считаются: аэродром может годами числиться с
        # длинной полосой, которая давно не эксплуатируется.
        if str(r.get("closed") or "0").strip() in ("1", "yes", "true"):
            continue
        cur = best.get(icao)
        if cur is None or length > cur["length_m"]:
            best[icao] = {"length_m": length, "width_m": width,
                          "surface": (r.get("surface") or "").strip(),
                          "lighted": str(r.get("lighted") or "0").strip() in ("1", "yes")}

    if len(best) < 500:
        raise ValueError(f"аэродромов с полосами {len(best)}, ожидалось "
                         f"не менее 500 — файл похож на обрезанный")

    facts: list[Fact] = []
    for icao, d in best.items():
        for name, val, unit in (("runway_length_m", d["length_m"], "m"),
                                ("runway_width_m", d["width_m"], "m")):
            if val <= 0:
                continue
            facts.append(Fact(
                domain="airport_limits", key=f"{icao}/{name}", valid_from=day,
                value=round(val, 1), unit=unit,
                source_id=ctx["source_id"], artifact_sha=ctx.get("sha"),
                extracted_by="parser:ourairports_runways@1", confidence="exact",
                note="самая длинная действующая полоса"))
        facts.append(Fact(
            domain="airport_limits", key=f"{icao}/runway_surface",
            valid_from=day, value_text=d["surface"] or "неизвестно",
            unit="surface", source_id=ctx["source_id"],
            artifact_sha=ctx.get("sha"),
            extracted_by="parser:ourairports_runways@1", confidence="exact"))
    return facts
