"""Доходность парка лизингодателя из отчётности SEC (XBRL, companyfacts) — домен `macro`.

Проверка гипотезы «рынок лизинга догоняет доковидный уровень» (исследование цен, ноябрь 2026):
арендная плата за год ÷ средняя за год балансовая стоимость самолётов в операционной аренде.
Показатель медленный — договоры на 8–12 лет переоцениваются по 10–15 % парка в год, — зато одной
методикой за много лет.

companyfacts: `facts.us-gaap.<понятие>.units.USD[] = {val, fy, fp, form, frame, start, end}`.
Выручка — годовые значения (frame `CY2019`), парк — на конец года (frame `CY2019Q4I`).
Понятия перебираются по списку: компании меняют теги (ASC 842 с 2019 года). Не нашлось —
разбор называет, какие «lease»-понятия в файле есть.

Ключи: `lessor/<тикер>/lease_yield/<год>` (доля), `…/lease_revenue/<год>`, `…/lease_assets/<год>` (USD).
"""

from __future__ import annotations

import json

from ..store import Fact

WHO = "parser:lessor_xbrl@1"
REV = ("OperatingLeaseLeaseIncome", "OperatingLeasesIncomeStatementLeaseRevenue", "OperatingLeaseIncome",
       "OperatingLeasesIncomeStatementMinimumLeaseRevenue")
ASSETS = ("PropertySubjectToOrAvailableForOperatingLeaseNet", "PropertySubjectToOperatingLeaseNet",
          "FlightEquipmentSubjectToOperatingLeasesNet")


def _series(gaap: dict, names, instant: bool) -> tuple[str | None, dict[int, float]]:
    for n in names:
        units = ((gaap.get(n) or {}).get("units") or {}).get("USD") or []
        out = {}
        for u in units:
            fr = str(u.get("frame") or "")
            if instant and fr.startswith("CY") and fr.endswith("Q4I") and fr[2:6].isdigit():
                out[int(fr[2:6])] = float(u["val"])
            elif not instant and len(fr) == 6 and fr.startswith("CY") and fr[2:].isdigit():
                out[int(fr[2:])] = float(u["val"])
        if len(out) >= 3:
            return n, out
    return None, {}


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    d = json.loads(blob)
    gaap = (d.get("facts") or {}).get("us-gaap") or {}
    tick = ctx.get("ticker") or str(d.get("cik"))
    rn, rev = _series(gaap, REV, False)
    an, ast = _series(gaap, ASSETS, True)
    if not rev or not ast:
        have = sorted(k for k in gaap if "lease" in k.lower() or "flight" in k.lower())[:25]
        raise ValueError(f"{d.get('entityName')}: нет {'выручки аренды' if not rev else 'парка в аренде'}; "
                         f"понятия в файле: {have}")
    common = dict(source_id=ctx["source_id"], artifact_sha=ctx.get("sha"), extracted_by=WHO, node=ctx.get("node"))
    out = []
    for y, v in sorted(rev.items()):
        out.append(Fact(domain="macro", key=f"lessor/{tick}/lease_revenue/{y}", valid_from=f"{y}-12-31",
                        value=v, unit="USD", note=f"{d.get('entityName')}, us-gaap:{rn}", **common))
        if y in ast and y - 1 in ast:
            avg = (ast[y] + ast[y - 1]) / 2
            out.append(Fact(domain="macro", key=f"lessor/{tick}/lease_yield/{y}", valid_from=f"{y}-12-31",
                            value=v / avg, unit="доля в год",
                            note=f"{d.get('entityName')}: {rn} ÷ среднее {an} на начало и конец года", **common))
    for y, v in sorted(ast.items()):
        out.append(Fact(domain="macro", key=f"lessor/{tick}/lease_assets/{y}", valid_from=f"{y}-12-31",
                        value=v, unit="USD", note=f"{d.get('entityName')}, us-gaap:{an}, на конец года", **common))
    ys = sorted(int(f.key.rsplit("/", 1)[1]) for f in out if "/lease_yield/" in f.key)
    ctx.setdefault("summary", []).append(f"{d.get('entityName')}: доходность за {ys[0]}–{ys[-1]}" if ys
                                         else f"{d.get('entityName')}: годы выручки и парка не совпали")
    return out
