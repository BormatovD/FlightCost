"""Курсы валют, которых нет у ЕЦБ — объявленные, с источником.

ЗАЧЕМ. Порядок разрешения курса задан решением 22: из документа, затем
ЕЦБ, затем официальный паритет, затем пропуск с предупреждением. Второй
слой не покрывает рубль, тенге, найру и египетский фунт — ЕЦБ их не
котирует, и это записано открытым вопросом карты с самого начала.

Без курса величина в такой валюте не участвует ни в чём: рублёвый CASK
Аэрофлота не встал бы в полосу, рублёвая цена билета не сравнилась бы с
евровым безубыточным чеком. Пропуск честен, но бесполезен.

ЧТО ЗДЕСЬ МОЖНО И ЧЕГО НЕЛЬЗЯ. Можно объявить курс, назвав издателя и
дату котировки. Нельзя написать число «примерно так»: поле `source`
обязательно, и без него строка отвергается. Курс без издателя — это
ровно та выдуманная константа, против которой построен весь контур.

КУРС — НЕ СТАВКА (решение 23). У ставки есть интервал «с и по», у курса
котировка на дату, и берётся последняя известная. Поэтому здесь дата
котировки, а не период действия, и старый курс лучше отсутствующего.
"""

from __future__ import annotations

from ..store import Fact


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    import yaml

    docs = [d for d in yaml.safe_load_all(blob.decode("utf-8")) if d]
    if not docs:
        raise ValueError("файл пуст")
    facts = []
    for d in docs:
        for req in ("currency", "source"):
            if not d.get(req):
                raise ValueError(f"нет обязательного поля {req!r}")
        cur = str(d["currency"]).upper()
        for q in d.get("quotes") or []:
            if "per_eur" not in q or not q.get("date"):
                raise ValueError(
                    f"{cur}: у котировки нужны `date` и `per_eur` — "
                    f"сколько единиц валюты за один евро")
            kind = (q.get("kind") or "spot").lower()
            if kind not in ("spot", "period_average"):
                raise ValueError(
                    f"{cur}/{q['date']}: `kind` должен быть spot или "
                    f"period_average — курс на дату и средний за период "
                    f"считаются по-разному и смешивать их нельзя")
            facts.append(Fact(
                domain="fx", key=cur, value=float(q["per_eur"]),
                unit="per_EUR", currency="", valid_from=str(q["date"]),
                value_text="", source_id=ctx["source_id"],
                artifact_sha=ctx.get("sha"),
                extracted_by=ctx.get("extracted_by", "parser:fx_declared@1"),
                confidence="exact",
                # Средний за период — не котировка на дату. Годится для
                # годовых величин отчётности и НЕ годится для пересчёта
                # цены билета, купленного вчера.
                certainty=("exact" if kind == "spot" else "reading_unconfirmed"),
                error_cost=q.get("error_cost"),
                confirm_by=(q.get("confirm_by") if kind == "spot"
                            else "котировка на дату вместо среднего за период"),
                node="src_fx_declared",
                source_note=f"{d['source']}; {kind}",
                note=d.get("source_url", "")))
    ctx.setdefault("summary", []).append(
        f"валют {len({f.key for f in facts})}, котировок {len(facts)}")
    return facts
