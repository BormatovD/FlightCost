"""Полная стоимость эксплуатации по семействам ВС (IATA ACMG через EUROCONTROL).

EUROCONTROL Standard Inputs for Economic Analyses, глава «Aircraft
operating costs»: десять семейств, стоимость на борт в год, на лётный
час, на цикл и на кресло-километр. Данные — сбор IATA Airline Cost
Management Group за финансовый 2019 год (51 перевозчик, 35% мирового
пассажирооборота), пересчитанные EUROCONTROL в цены 2025 года по
инфляции. Лицензия книги — CC BY 4.0, таблица лежит в открытом
репозитории книги, поэтому забирается машиной.

ЧТО ЭТО ЗА ЧИСЛО. Всё вместе: топливо, сборы, ТОиР, экипаж, владение,
накладные — то есть сравнивается не со статьёй, а с ИТОГОМ модели на
блок-час. Отношение «на цикл / на час» — среднее плечо выборки в часах;
оно нужно, чтобы сравнивать на том же плече, а не на своём.

Вторая таблица той же главы — структура расходов (доли статей, 2019,
керосин 66,9 USD/барр). Из неё — отношение кабинного экипажа к лётному,
которого нет в Form 41 по типам.

Числа — как в файле. Пересчёт в евро и на наше плечо — в `bench.py`.
"""

from __future__ import annotations

import io
import json
import re

from ..store import Fact

WHO = "parser:acmg_cost@1"
BOOK = "EUROCONTROL Standard Inputs for Economic Analyses, гл. Aircraft operating costs"

COLS = {
    "per_aircraft": ("per_aircraft_year", "MUSD"),
    "per_flt_hr": ("per_flight_hour", "USD"),
    "per_flt_cycle": ("per_flight_cycle", "USD"),
    "per_seats": ("per_ask", "USc"),
    "per_ton_km": ("per_atk", "USc"),
}


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s.strip()).strip("_").upper()


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(blob), data_only=True, read_only=True)
    rows = [r for r in wb.worksheets[0].iter_rows(values_only=True) if r and r[0]]
    if not rows:
        raise ValueError("лист пуст")
    head = [str(h or "").strip() for h in rows[0]]
    idx = {h: i for i, h in enumerate(head)}
    if "Aircraft.type" not in idx and "Category" in idx:
        return _structure(rows, idx, ctx)
    missing = [c for c in COLS if c not in idx]
    if "Aircraft.type" not in idx or missing:
        raise ValueError(f"не та таблица: ожидались Aircraft.type и {', '.join(COLS)}; "
                         f"есть {', '.join(head)}")
    day = ctx.get("today") or ""
    facts = []
    for r in rows[1:]:
        fam = str(r[idx["Aircraft.type"]]).strip()
        for col, (name, unit) in COLS.items():
            v = r[idx[col]]
            if v is None:
                continue
            facts.append(Fact(
                domain="fleet_benchmark", key=f"ACMG/{_slug(fam)}/{name}",
                valid_from=day, value=float(v), unit=unit, currency="USD",
                value_text=json.dumps({"family": fam, "prices": "USD 2025",
                                       "data_year": "FY2019"}, ensure_ascii=False),
                source_id=ctx["source_id"], artifact_sha=ctx.get("sha"),
                extracted_by=WHO, confidence="exact", node="src_acmg",
                source_note="IATA ACMG FY2019, пересчёт EUROCONTROL в цены 2025 по инфляции",
                note=BOOK))
    ctx.setdefault("summary", []).append(f"семейств {len(rows) - 1}, величин {len(facts)}")
    ctx.setdefault("parsed_prefixes", []).extend(
        sorted({f.key.rsplit("/", 1)[0] for f in facts}))
    return facts


def _structure(rows, idx, ctx) -> list[Fact]:
    day = ctx.get("today") or ""
    facts = []
    for r in rows[1:]:
        cat, sub, v = r[idx["Category"]], r[idx["Subcategory"]], r[idx["Value"]]
        facts.append(Fact(
            domain="fleet_benchmark", key=f"ACMG/STRUCTURE/{_slug(sub)}",
            valid_from=day, value=float(v), unit="share",
            value_text=json.dumps({"category": cat, "subcategory": sub,
                                   "data_year": "2019"}, ensure_ascii=False),
            source_id=ctx["source_id"], artifact_sha=ctx.get("sha"),
            extracted_by=WHO, confidence="exact", node="src_acmg",
            source_note="структура расходов перевозчиков, 2019, керосин 66,9 USD/барр",
            note=BOOK))
    ctx.setdefault("summary", []).append(f"структура: статей {len(facts)}")
    ctx.setdefault("parsed_prefixes", []).append("ACMG/STRUCTURE")
    return facts
