"""EUROCONTROL CRCO: ставки en-route по тарифным зонам.

Детерминированный контур. EUROCONTROL публикует ставки не только в PDF,
но и в табличном txt, предназначенном для загрузки в их собственный RSO
Distance Tool. Агент для этого источника не нужен.

Формат, разделитель — табуляция:
    ED  2026/07/01  2026/07/31  9789                    Germany
    LS  2026/07/01  2026/07/31  17117  0.920409  CHF    Switzerland

Колонки: код зоны, начало действия, конец, ставка в сотых долях EUR,
курс национальной валюты (только для не-евро государств), код валюты,
название.

Ключ — код тарифной зоны, а не государства. У Испании их две (LE
континент, GC Канары), у Португалии тоже (LP Лиссабон, AZ Санта-Мария).
Совпадает с первыми двумя буквами кода ИКАО аэропорта, что и позволяет
связать аэропорт со ставкой без отдельного справочника.
"""

from __future__ import annotations

import re

from ..store import Fact

SCALE = 100.0          # ставка публикуется в сотых долях


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    text = blob.decode("utf-8", errors="replace")
    facts: list[Fact] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        col = [c.strip() for c in raw.split("\t")]
        if len(col) < 4 or not re.fullmatch(r"[A-Z0-9]{2}", col[0]):
            continue
        zone, vfrom, vto, value = col[0], col[1], col[2], col[3]
        if not value.isdigit():
            continue
        fx = col[4] if len(col) > 4 and col[4] else None
        cur = col[5] if len(col) > 5 and col[5] else "EUR"
        name = col[-1] if len(col) > 6 else ""

        facts.append(Fact(
            domain="enroute_rate", key=zone,
            valid_from=vfrom.replace("/", "-"),
            valid_to=_day_after(vto),
            value=int(value) / SCALE,
            unit="EUR_per_service_unit", currency="EUR",
            source_id=ctx["source_id"], artifact_sha=ctx.get("sha"),
            extracted_by="parser:crco_enroute@1", confidence="exact",
            note=name or None,
        ))
        if fx:
            facts.append(Fact(
                domain="fx", key=cur, valid_from=vfrom.replace("/", "-"),
                valid_to=_day_after(vto), value=float(fx),
                unit="per_EUR", currency=cur,
                source_id=ctx["source_id"], artifact_sha=ctx.get("sha"),
                extracted_by="parser:crco_enroute@1", confidence="exact",
                note=f"курс, применённый CRCO для {name}",
            ))
    return facts


def _day_after(d: str) -> str:
    """Интервал в файле включает последний день, в хранилище valid_to
    исключающий — иначе в последний день месяца ставка исчезает."""
    from datetime import date, timedelta

    y, m, dd = (int(x) for x in d.split("/"))
    return (date(y, m, dd) + timedelta(days=1)).isoformat()
