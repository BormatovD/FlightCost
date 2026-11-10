"""Визовый режим между странами — Passport Index (MIT), домен `macro`.

Барьер спроса в гравитационной модели: при визе поток ниже, при безвизе — выше.
CSV tidy: `Passport,Destination,Requirement`, значения — число безвизовых дней,
`visa free`, `visa on arrival`, `eta`, `e-visa`, `visa required`, `no admission`, `-1`
(своя страна). Шкала в значении: 0 — свободно (безвиз, по прибытии, своя страна),
1 — электронное разрешение (eta, e-visa), 2 — виза, 3 — въезд закрыт.

Ключ: `visa/<паспорт ISO2>-<страна ISO2>`, текст — как в файле.
"""

from __future__ import annotations

import csv
import io

from ..store import Fact

WHO = "parser:visa_index@1"
LEVEL = {"visa free": 0, "visa on arrival": 0, "-1": 0, "eta": 1, "e-visa": 1, "visa required": 2,
         "no admission": 3}


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    rows = csv.DictReader(io.StringIO(blob.decode("utf-8-sig")))
    out, odd = [], set()
    for r in rows:
        a, b, req = (r.get("Passport") or "").upper(), (r.get("Destination") or "").upper(), \
            (r.get("Requirement") or "").strip().lower()
        if len(a) != 2 or len(b) != 2:
            continue
        lvl = 0 if req.isdigit() else LEVEL.get(req)
        if lvl is None:
            odd.add(req)
            continue
        out.append(Fact(domain="macro", key=f"visa/{a}-{b}", valid_from=ctx.get("today") or "2026-01-01",
                        value=float(lvl), unit="0 свободно · 1 электронно · 2 виза · 3 закрыто",
                        value_text=req, source_id=ctx["source_id"], artifact_sha=ctx.get("sha"),
                        extracted_by=WHO, node=ctx.get("node")))
    if odd:
        ctx.setdefault("summary", []).append(f"незнакомые значения пропущены: {sorted(odd)[:8]}")
    if len(out) < 1000:
        raise ValueError(f"пар всего {len(out)} — не та таблица")
    return out
