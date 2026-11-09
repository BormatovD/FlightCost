"""Быстрая приёмка черновиков тарифов агента (решение владельца 09.11.2026).

Агент «тарифы» кладёт черновик в /srv/fca/agent/out, бот пересылает его в
Телеграм и копирует в /srv/fca/master/export/drafts — оттуда его забирает
домой `fca master drafts`. Дома каждый черновик проходит те же две проверки,
что владелец делал руками:

1. парсер `airport_charges` — тот же, что `fca refresh`: схема, отвергнутые
   правила, предупреждения;
2. контрольный оборот A320: рейс из узла того же региона, 148 пассажиров,
   июль — сумма сборов аэропорта против коридора его региона
   (data/charges/_regional.yaml). Вылет за коридор почти всегда — ошибка в
   признаке начисления или в разряде числа.

«Чистый» черновик: парсер принял без отвергнутых правил, оборот в коридоре,
у агента нет сомнений (`doubts` пуст). Чистые принимаются одним ключом
`--accept-clean`, остальные — только поимённо, после просмотра. Решение
принять остаётся за человеком: программа только сужает, что смотреть.

Расчёт оборота идёт по ДОМАШНЕЙ базе без записи в неё: строки черновика
подставляются вместо заведённых строк этого аэропорта через обёртку
хранилища (`DraftStore`), сама база не меняется.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

CHECK_AC, CHECK_PAX, CHECK_SEATS, CHECK_MONTH = "A320", 148, 170, 7
# Откуда контрольный рейс: так же, как собирался коридор региона (research/charges-2026-10:
# Россия и СНГ — внутренний рейс из Шереметьева, остальные — из Франкфурта).
HUB = {"north_america": ("KDEN", "KORD"), "russia_cis": ("UUEE", "ULLI")}
DEFAULT_HUB = ("EDDF", "LEMD")


class DraftStore:
    """Хранилище, в котором тариф одного аэропорта заменён черновиком."""

    def __init__(self, inner, icao: str, facts: list):
        self._inner, self._icao = inner, icao.upper()
        self._rows = {}
        for f in facts:
            d = dataclasses.asdict(f) if dataclasses.is_dataclass(f) else dict(f)
            if d.get("domain") == "airport_charge":
                self._rows[d["key"]] = d

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def current(self, domain, as_of=None, prefixes=None):
        try:
            out = self._inner.current(domain, as_of, prefixes=prefixes)
        except TypeError:
            out = self._inner.current(domain, as_of)
        if domain != "airport_charge":
            return out
        out = {k: v for k, v in out.items() if not k.startswith(self._icao + "/")}
        for k, row in self._rows.items():
            if not prefixes or any(k.startswith(p) for p in prefixes):
                out[k] = row
        return out


def band_of(icao: str) -> tuple[str, str, float | None, float | None]:
    """(код региона, название, низ, верх) коридора оборота A320, EUR."""
    from .econ import regional_charge_k
    _, code, r = regional_charge_k(icao)
    rng = r.get("range_eur")
    if rng:
        return code, r.get("name", code), float(rng[0]), float(rng[1])
    med = r.get("median_eur")
    if med:
        # Регион без набора тарифов (сверен по отчётам): «в разы» — коридор ×0,5…×2.
        return code, r.get("name", code), med * 0.5, med * 2.0
    return code, r.get("name", code), None, None


def check(blob: bytes, store) -> dict:
    from .parsers import airport_charges
    out: dict = {"icao": None, "verdict": "look", "reasons": []}
    try:
        doc = json.loads(blob)
        out["icao"] = str(doc.get("icao") or "").upper() or None
        doubts = [str(x) for x in (doc.get("doubts") or [])]
    except ValueError as e:
        out.update(verdict="reject", reasons=[f"не JSON: {e}"])
        return out
    out["doubts"] = doubts
    ctx = {"source_id": "airport_charges_tier1", "extracted_by": "drafts", "node": "src_airport_tariff"}
    try:
        facts = airport_charges.parse(blob, ctx)
    except Exception as e:                                         # noqa: BLE001
        out.update(verdict="reject", reasons=[f"парсер отверг: {str(e)[:300]}"])
        return out
    out["facts"] = len(facts)
    rejected = list(ctx.get("rejected") or [])
    out["warnings"] = list(ctx.get("warnings") or [])
    if rejected:
        out["reasons"].append(f"отвергнуто правил: {len(rejected)}")
    if doubts:
        out["reasons"].append(f"сомнений агента: {len(doubts)}")
    icao = out["icao"]
    code, name, lo, hi = band_of(icao)
    out["region"], out["band"] = name, (lo, hi)
    hubs = HUB.get(code, DEFAULT_HUB)
    orig = hubs[1] if hubs[0] == icao else hubs[0]
    try:
        from . import econ
        res = econ.route_economics(DraftStore(store, icao, facts), orig, icao, aircraft=CHECK_AC,
                                   load_factor=CHECK_PAX / CHECK_SEATS, seats=CHECK_SEATS, month=CHECK_MONTH)
        lines = {k: v for k, v in (res.charge_lines or {}).items() if k.startswith(icao + "/")}
        out["turnaround_eur"] = round(sum(lines.values())) if lines else None
    except Exception as e:                                         # noqa: BLE001
        out["reasons"].append(f"оборот не посчитан: {type(e).__name__}: {str(e)[:200]}")
        out["turnaround_eur"] = None
    t = out.get("turnaround_eur")
    if t is not None and lo is not None and not (lo <= t <= hi):
        out["reasons"].append(f"оборот {t:,.0f} EUR вне коридора региона {lo:,.0f}–{hi:,.0f}".replace(",", " "))
    if t is None and not any(r.startswith("оборот") for r in out["reasons"]):
        out["reasons"].append("оборот не посчитан")
    out["verdict"] = "clean" if not out["reasons"] else "look"
    return out
