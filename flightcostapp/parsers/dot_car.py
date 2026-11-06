"""Средние оплаченные тарифы по парам аэропортов США — DOT Consumer Airfare
Report, Table 1a (исследование 13, ценообразование).

Зачем. Это единственный открытый ряд СРЕДНЕГО ОПЛАЧЕННОГО тарифа по паре:
цена в одну сторону по всем пассажирам, с первым классом, налогами и
аэропортовыми сборами, без бонусных билетов и без допуслуг (DOT, описание
отчёта). Им проверяется метод «минимальная цена по глубине продажи →
средний тариф» и заменяется допущение «средний чек = минимум × 1,2/2,0»
(решение 210) — сначала на парах США.

Лицензия — U.S. Government Works (data.transportation.gov): хранить и
публиковать можно.

Формат: CSV-выгрузка Socrata (tfrh-tu9e), по строке на пару и квартал.
Колонки ищутся по имени без учёта регистра; нет нужной — ошибка с её
именем, а не молчаливый ноль. Пара — без направления, коды по алфавиту:
отчёт и сам считает тариф «в каждую сторону».

Берутся годы с FROM_YEAR: окно страницы показателей — с 2025-го, год до
него нужен для сравнения год к году.
"""

from __future__ import annotations

import csv
import io

from ..store import Fact

FROM_YEAR = 2024
NEED = ("year", "quarter", "airport_1", "airport_2", "fare", "passengers")


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    text = blob.decode("utf-8-sig", errors="replace")
    rd = csv.reader(io.StringIO(text))
    head = [h.strip().lower() for h in next(rd, [])]
    miss = [c for c in NEED if c not in head]
    if miss:
        raise ValueError(f"в выгрузке DOT нет колонок: {', '.join(miss)}")
    ix = {c: head.index(c) for c in head}

    def num(row, col):
        if col not in ix:
            return None
        v = row[ix[col]].strip().replace(",", "").replace("$", "")
        try:
            return float(v)
        except ValueError:
            return None

    facts, pairs = [], set()
    for row in rd:
        if len(row) < len(head):
            continue
        y, q = num(row, "year"), num(row, "quarter")
        if not y or not q or y < FROM_YEAR:
            continue
        a, b = sorted((row[ix["airport_1"]].strip().upper(), row[ix["airport_2"]].strip().upper()))
        if len(a) != 3 or len(b) != 3:
            continue
        period = f"{int(y)}Q{int(q)}"
        vf = f"{int(y)}-{(int(q) - 1) * 3 + 1:02d}-01"
        base = f"{a}-{b}/{period}"
        common = dict(domain="fare_paid", valid_from=vf, source_id=ctx["source_id"],
                      artifact_sha=ctx.get("sha"), extracted_by="parser:dot_car@1", confidence="exact")
        for col, stat, unit in (("fare", "mean", "USD"), ("fare_low", "mean_low_carrier", "USD"),
                                ("fare_lg", "mean_largest_carrier", "USD"),
                                ("passengers", "pax_per_day", "pax"), ("nsmiles", "miles", "mi")):
            v = num(row, col)
            if v is None or v <= 0:
                continue
            facts.append(Fact(key=f"{base}/{stat}", value=v, unit=unit,
                              currency="USD" if unit == "USD" else None,
                              note="DOT Consumer Airfare Report, Table 1a: в одну сторону, все пассажиры, "
                                   "с налогами и сборами, без допуслуг", **common))
        pairs.add(f"{a}-{b}")
    if not facts:
        raise ValueError(f"в выгрузке DOT нет строк с {FROM_YEAR} года")
    ctx.setdefault("summary", []).append(f"DOT Table 1a с {FROM_YEAR}: пар {len(pairs)}, фактов {len(facts)}")
    return facts
