"""Поправки к расходу openap -> факты `aircraft/<тип>/burn_calib` (решение 225)."""

from __future__ import annotations

import json

from ..store import Fact

LIMITS = (0.5, 2.0)      # шире — это не поправка модели, а другая модель


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    d = json.loads(blob.decode("utf-8"))
    day = d.get("as_of") or ctx.get("today") or ""
    facts = []
    for icao, t in (d.get("types") or {}).items():
        k = float(t["factor"])
        if not LIMITS[0] <= k <= LIMITS[1]:
            raise ValueError(f"{icao}: поправка {k} вне {LIMITS}")
        if not t.get("basis") or not t.get("sources"):
            raise ValueError(f"{icao}: поправка без основания или источников не заводится")
        facts.append(Fact(
            domain="aircraft", key=f"{icao.upper()}/burn_calib", valid_from=day,
            value=k, unit="множитель", source_id=ctx["source_id"],
            artifact_sha=ctx.get("sha"),
            extracted_by=ctx.get("extracted_by", "parser:burn_calib@1"),
            confidence="exact", node=ctx.get("node"),
            note=f"{t['basis']}; Form 41: {t.get('form41') or 'не сверено'}",
            source_note=" | ".join(t["sources"])))
    if not facts:
        raise ValueError("в файле поправок нет ни одного типа")
    return facts
