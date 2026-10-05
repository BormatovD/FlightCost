"""Справочные курсы ЕЦБ: eurofxref-daily.xml -> домен fx.

Около тридцати валют, обновление в рабочие дни. Формат курса совпадает с
тем, в котором CRCO публикует свои: единиц валюты за один евро. Это не
случайность — CRCO берёт курсы у того же ЕЦБ, поэтому значения домена
однородны независимо от источника.

Чего у ЕЦБ нет: тенге, риала Катара и прочих валют вне тридцатки. Часть
из них выводится через привязку к доллару (см. flightcostapp/fx.py),
остальные остаются без курса, и правила в них честно пропускаются.
"""

from __future__ import annotations

import re

from ..store import Fact

CUBE = re.compile(r"<Cube\s+currency='([A-Z]{3})'\s+rate='([\d.]+)'\s*/>")
DAY = re.compile(r"<Cube\s+time='(\d{4}-\d{2}-\d{2})'")


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    text = blob.decode("utf-8", errors="replace").replace('"', "'")
    m = DAY.search(text)
    day = m.group(1) if m else (ctx.get("today") or "")
    if not day:
        raise ValueError("в файле ЕЦБ не найдена дата котировок")

    facts = [Fact(
        domain="fx", key=cur, valid_from=day, value=float(rate),
        unit="per_EUR", currency=cur,
        source_id=ctx["source_id"], artifact_sha=ctx.get("sha"),
        extracted_by="parser:ecb_fx@1", confidence="exact",
        note="справочный курс ЕЦБ",
    ) for cur, rate in CUBE.findall(text)]
    if len(facts) < 20:
        raise ValueError(f"разобрано {len(facts)} валют, ожидалось не менее 20")
    return facts
