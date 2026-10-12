"""Официальные курсы Банка России: XML_daily.asp -> домен fx.

Зачем второй справочник курсов. ЕЦБ не котирует рубль с марта 2022 года,
и до этого модуля рубль брался из объявленного файла `data/fx/RUB.yaml`
с котировкой на отчётную дату — к октябрю ей было десять месяцев. Для
пересчёта счетов это терпимо с пометкой, для переключателя валюты на
витрине — нет: человек видит «в рублях» и верит числу.

Что берётся. Банк России публикует курс РУБЛЯ к сорока с лишним валютам.
Домен `fx` хранит единицы валюты ЗА ОДИН ЕВРО (как ЕЦБ и CRCO), поэтому:

    RUB за EUR  = Value(EUR) / Nominal(EUR)              — прямая котировка
    X   за EUR  = RUB за EUR / (Value(X) / Nominal(X))   — кросс через рубль

Кросс-курс — величина второго сорта: он собран из двух котировок одного
банка и несёт обе их погрешности. В `fx.py` у источника приоритет ниже
ЕЦБ, так что доллар, юань, рупия и прочее из тридцатки ЕЦБ остаются за
ЕЦБ, а отсюда идут рубль и валюты, которых у ЕЦБ нет: тенге, сум, драм,
манат. Для них это свежее объявленного файла, и провенанс так и говорит:
«кросс через рубль по ЦБ РФ».

Формат: windows-1251, `<Valute>` с `CharCode`, `Nominal`, `Value` (запятая
десятичная). Дата — атрибут `Date` корня, dd.mm.yyyy.
"""

from __future__ import annotations

import re

from ..store import Fact

VALUTE = re.compile(
    r"<Valute[^>]*>.*?<CharCode>([A-Z]{3})</CharCode>.*?<Nominal>(\d+)</Nominal>"
    r".*?<Value>([\d,\.]+)</Value>.*?</Valute>", re.S)
DAY = re.compile(r"<ValCurs[^>]*\bDate=\"(\d{2})\.(\d{2})\.(\d{4})\"")
MIN_CURRENCIES = 20


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    text = blob.decode("windows-1251", errors="replace")
    m = DAY.search(text)
    if not m:
        raise ValueError("в файле Банка России не найдена дата котировок")
    day = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"

    per_rub: dict[str, float] = {}
    for code, nominal, value in VALUTE.findall(text):
        per_rub[code] = float(value.replace(",", ".")) / int(nominal)   # рублей за единицу
    if len(per_rub) < MIN_CURRENCIES:
        raise ValueError(f"разобрано {len(per_rub)} валют, ожидалось не менее {MIN_CURRENCIES}")
    if "EUR" not in per_rub:
        raise ValueError("в файле Банка России нет курса евро — пересчитать в домен fx нельзя")

    rub_per_eur = per_rub["EUR"]
    common = dict(domain="fx", valid_from=day, unit="per_EUR",
                  source_id=ctx["source_id"], artifact_sha=ctx.get("sha"),
                  extracted_by="parser:cbr_fx@1", confidence="exact")
    facts = [Fact(key="RUB", value=round(rub_per_eur, 6), currency="RUB",
                  note="официальный курс Банка России", **common)]
    for code, rub_per_unit in per_rub.items():
        if code in ("EUR", "RUB") or rub_per_unit <= 0:
            continue
        facts.append(Fact(key=code, value=round(rub_per_eur / rub_per_unit, 6), currency=code,
                          note="кросс через рубль по курсам Банка России", **common))
    ctx.setdefault("summary", []).append(
        f"ЦБ РФ на {day}: {rub_per_eur:.4f} RUB за EUR, кроссов {len(facts) - 1}")
    return facts
