"""Россия: пассажиры по парам городов за год, внутренние линии — домен `traffic`.

ПЕРВОИСТОЧНИК НЕИЗВЕСТЕН (решение 202). Таблицу передали из аналитического
агентства без ссылки на публикацию. Сверка с итогами аэропортов за 2024 год:
у аэропортов почти без международных рейсов (Мурманск, Южно-Сахалинск,
Калининград, Петропавловск, Ижевск) сумма пар сходится с итогом в пределах
округления; у аэропортов с международными — 60–90% итога, как и должно быть
для внутренних линий. Числа целые, без округления, направления
несимметричны — на гравитационную модель не похоже. Поэтому поток
берётся, но подписывается как сводка без первоисточника, а не как
публикация ведомства.

Таблица «От — До — Расстояние — <год> Янв-Дек» с кодами городов ИАТА
(`От2`, `До2`) и видом перевозки (`РЕГ` — регулярные, `НРГ` — нет). Год —
из заголовка колонки пассажиров. В выгрузке за 2024 год — 2 360 строк,
84,1 млн пассажиров: это внутренние перевозки российских авиакомпаний
целиком, включая чартерные (НРГ, 2,5 млн).

Что делается со строкой:

1. РЕГ и НРГ складываются: поток пары — все, кто летел.
2. Оба направления складываются, как у остальных источников.
3. Код города -> аэропорт. Москва (`MOW`) — город, а не аэропорт: поток
   не делится по Шереметьево, Домодедово, Внуково и Жуковскому, а
   хранится под `@MOW`, и читатель показывает его для любого из них с
   пометкой «весь город». Остальные коды ИАТА переводятся указателем
   хранилища. Кириллические внутренние коды (ЯМБ, ТИЛ), «Прочие [регион]»
   и названия городов вместо кода не переводятся — их поток и доля в
   сводке разбора.
4. Год хранится годом (`"A"` в ряду): месяцев в таблице нет, делить на
   двенадцать — выдумать сезонность. Читатель берёт 1/12 как средний
   месяц и пишет это.
"""

from __future__ import annotations

import io
import re

WHO = "parser:ru_pairs@1"
REPORTER = "RUPAIRS"
# Код города, под которым ИАТА сводит несколько аэропортов. Поток по
# аэропортам не делится — хранится городом (решение 201).
CITY_CODES = {"MOW": "@MOW"}
_IATA = re.compile(r"^[A-Z]{3}$")


def _cell(v) -> str:
    return "" if v is None else str(v).strip()


def parse(blob: bytes, ctx: dict) -> list:
    import openpyxl
    from ..traffic import pack
    wb = openpyxl.load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    head = [_cell(x) for x in next(rows)]
    low = [h.lower() for h in head]
    try:
        i_kind = next(i for i, h in enumerate(low) if "рег" in h)
        i_a, i_b = head.index("От2"), head.index("До2")
        i_pax = next(i for i, h in enumerate(head) if re.search(r"\b(19|20)\d{2}\b", h))
    except (StopIteration, ValueError):
        raise ValueError(f"не похоже на таблицу пассажиров по парам: заголовок {head}") from None
    year = re.search(r"\b((?:19|20)\d{2})\b", head[i_pax]).group(1)
    if "янв-дек" not in head[i_pax].lower().replace(" ", "").replace("\n", ""):
        raise ValueError(f"колонка {head[i_pax]!r} — не год целиком (Янв-Дек): месяцев в "
                         f"таблице нет, неполный год прочёлся бы как полный")
    store = ctx.get("store")
    to_icao = store.icao_of_iata(ctx.get("today")) if store is not None else {}

    def code(c):
        if c in CITY_CODES:
            return CITY_CODES[c], ""
        if not _IATA.match(c):
            return None, "не код ИАТА"
        i = to_icao.get(c)
        return (i, "") if i else (None, "нет ИКАО")

    agg: dict[tuple, list] = {}
    miss: dict[str, float] = {}
    why: dict[str, str] = {}
    total = 0.0
    for r in rows:
        if not r or len(r) <= max(i_a, i_b, i_pax):
            continue
        try:
            pax = float(r[i_pax] or 0)
        except (TypeError, ValueError):
            continue
        if pax <= 0:
            continue
        total += pax
        ca, cb = _cell(r[i_a]), _cell(r[i_b])
        a, wa = code(ca)
        b, wb_ = code(cb)
        if not a or not b:
            for c, i, w in ((ca, a, wa), (cb, b, wb_)):
                if not i:
                    miss[c] = miss.get(c, 0.0) + pax
                    why[c] = w
            continue
        if a == b:
            continue
        x, y = sorted((a, b))
        agg.setdefault((REPORTER, x, y, f"{year}-A"), [0.0, None, None])[0] += pax
    if not agg:
        raise ValueError("ни одной пары с переводимыми кодами")
    facts = pack(agg, ctx=ctx, who=WHO,
                 note=lambda rep, a, b: (
                     f"сводка по РФ без первоисточника (аналит. агентство), внутренние линии, {year} год "
                     f"целиком: пассажиры, оба "
                     f"направления, регулярные и нерегулярные"
                     + ("; Москва — весь город (Шереметьево, Домодедово, Внуково, Жуковский), "
                        "по аэропортам не делится" if "@MOW" in (a, b) else "")))
    ctx.setdefault("parsed_prefixes", []).append(REPORTER)
    lost = sum(miss.values())
    head_miss = sorted(miss, key=miss.get, reverse=True)[:8]
    ctx["summary"] = list(ctx.get("summary", []))
    ctx["summary"].insert(0,
        f"{year} год: пар {len(agg)}, пассажиров {total / 1e6:.1f} млн"
        + (f"; без перевода {len(miss)} кодов, {lost / total * 100:.1f}% пассажиров: "
           + ", ".join(f"{c} ({why[c]})" for c in head_miss) if miss else ""))
    return facts
