"""Всемирный банк, WDI: население, ВВП на душу по ППС, въездной туризм по странам — домен `macro`.

Входы гравитационной модели спроса (исследование «Спрос», ноябрь 2026): уровень дохода
и туристичность страны. Ответ API v2 — JSON `[meta, [строки]]`, строка:
`{"indicator": {"id"}, "country": {"id": ISO2}, "countryiso3code", "date": "2024", "value"}`.
Агрегаты (регионы, группы дохода) у Банка тоже с двухбуквенными кодами — они остаются: к
аэропорту по стране они не присоединятся, а для сводки полезны.

Ключ: `country/<ISO2>/<показатель>/<год>`. Лицензия — CC BY 4.0.
"""

from __future__ import annotations

import json

from ..store import Fact

WHO = "parser:wb_wdi@1"
UNITS = {"SP.POP.TOTL": "человек", "NY.GDP.PCAP.PP.KD": "USD ППС 2021 на жителя",
         "ST.INT.ARVL": "прибытий в год", "NY.GDP.PCAP.KD": "USD 2015 на жителя"}
NAMES = {"SP.POP.TOTL": "pop", "NY.GDP.PCAP.PP.KD": "gdp_pc_ppp", "ST.INT.ARVL": "tourist_arrivals",
         "NY.GDP.PCAP.KD": "gdp_pc"}


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    d = json.loads(blob)
    if not isinstance(d, list) or len(d) < 2 or not isinstance(d[1], list):
        raise ValueError(f"ответ API не [meta, строки]: {str(d)[:200]}")
    meta, rows = d[0], d[1]
    if int(meta.get("pages", 1) or 1) > 1:
        raise ValueError(f"неполный ответ API: страниц {meta.get('pages')}, получена только одна; "
                         "увеличьте per_page в адресе")
    if meta.get("total") is not None:
        try:
            total = int(str(meta["total"]))
        except ValueError:
            raise ValueError(f"некорректное число строк API total: {meta['total']!r}") from None
        if total != len(rows):
            raise ValueError(f"неполный ответ API: total={total}, получено строк {len(rows)}")
    out, kinds = [], set()
    for r in rows:
        v, ind, c, y = r.get("value"), (r.get("indicator") or {}).get("id"), (r.get("country") or {}).get("id"), r.get("date")
        if v is None or not ind or not c or not str(y).isdigit():
            continue
        name = NAMES.get(ind, ind)
        kinds.add(name)
        out.append(Fact(domain="macro", key=f"country/{c}/{name}/{y}", valid_from=f"{y}-01-01",
                        value=float(v), unit=UNITS.get(ind), source_id=ctx["source_id"],
                        artifact_sha=ctx.get("sha"), extracted_by=WHO, node=ctx.get("node"),
                        note=f"World Bank WDI {ind}"))
    ctx.setdefault("summary", []).append(f"показатели {sorted(kinds)}, строк {len(out)}")
    return out
