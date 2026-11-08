"""Свёртка выборки билетов BTS DB1C (рынки) -> домен fare_paid.

Сырые помесячные файлы (40 % билетов внутренних рынков США, строка —
пассажир) живут только на компьютере владельца, в data/raw/db1c/: лицензия
DB1C прямо не заявлена, и до проверки строки не уходят ни на сервер, ни в
репозиторий (решение владельца, 06.11.2026). Сюда приезжает свёртка
`tools/db1c_fetch.py` — по паре и месяцу: число пассажиров выборки, средний
тариф и квантили, доли и средние по трём группам глубины продажи (до 21
дня, 22–90, от 91). Эти агрегаты публиковать можно.

Бонусные билеты (тариф меньше 15 USD — только государственные сборы)
в тарифы не входят, их доля — отдельный показатель share_award
(tools/db1c_fetch.py, AWARD_MAX).

Тариф — MktAmount: валовая сумма по рынку билета, с налогами и сборами
(описание DB1C Market), то есть «в одну сторону» в смысле рынка. Прямые
(один купон) и все рынки — раздельно: экономика сектора считается по
прямым, а «все» нужны, чтобы видеть, насколько пересадка дешевле.
"""

from __future__ import annotations

import json

from ..store import Fact

STATS = ("pax", "mean", "p10", "p25", "p50", "p75", "p90",
         "share_21AP", "share_2290", "share_91UP", "mean_21AP", "mean_2290", "mean_91UP",
         "share_award")


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    doc = json.loads(blob.decode("utf-8"))
    month = str(doc.get("month") or "")
    if len(month) != 7:
        raise ValueError("в свёртке DB1C нет месяца вида ГГГГ-ММ")
    pairs = doc.get("pairs") or {}
    if not pairs:
        raise ValueError(f"в свёртке DB1C за {month} нет пар")
    facts = []
    common = dict(domain="fare_paid", valid_from=f"{month}-01", source_id=ctx["source_id"],
                  artifact_sha=ctx.get("sha"), extracted_by="parser:db1c_agg@1", confidence="exact")
    for pair, segs in pairs.items():
        for seg, st in segs.items():
            for k in STATS:
                v = st.get(k)
                if v is None:
                    continue
                unit = "pax" if k == "pax" else "share" if k.startswith("share") else "USD"
                facts.append(Fact(key=f"{pair}/{month}/{seg}/{k}", value=float(v), unit=unit,
                                  currency="USD" if unit == "USD" else None,
                                  note=f"BTS DB1C, выборка {doc.get('sample_rate', 0.4):.0%} билетов; "
                                       "тариф рынка с налогами и сборами", **common))
    ctx.setdefault("summary", []).append(f"DB1C {month}: пар {len(pairs)}, фактов {len(facts)}")
    return facts
