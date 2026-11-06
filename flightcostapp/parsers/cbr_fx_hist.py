"""История курса рубля к евро, Банк России: XML_dynamic.asp -> домен fx.

ЕЦБ рубль не котирует, ежедневный `cbr_fx` кладёт один день. Ряду цены
топлива в России после демпфера (страница «План и показатели») и расчёту
на прошлую дату нужен курс на каждый месяц с 2025 года — без него месяц
пропускается, и линия начиналась с того дня, когда заработал ежедневный
сборщик.

Запрос: динамика официального курса евро (код ЦБ R01239) с 01.01.2025 по
сегодня. Формат: windows-1251, `<Record Date="dd.mm.yyyy">` с `Nominal` и
`Value` (запятая десятичная). Пишется только рубль за евро — кроссы через
рубль для прошлых дат не нужны, доллар и прочее даёт история ЕЦБ.
"""

from __future__ import annotations

import re

from ..store import Fact

RECORD = re.compile(r'<Record\s+Date="(\d{2})\.(\d{2})\.(\d{4})"[^>]*>.*?<Nominal>(\d+)</Nominal>'
                    r'.*?<Value>([\d,\.]+)</Value>', re.S)
MIN_DAYS = 20


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    text = blob.decode("windows-1251", errors="replace")
    if 'ID="R01239"' not in text and "R01239" not in text:
        raise ValueError("в ответе Банка России нет ряда евро (R01239)")
    pts = sorted((f"{y}-{m}-{d}", float(v.replace(",", ".")) / int(n))
                 for d, m, y, n, v in RECORD.findall(text))
    if len(pts) < MIN_DAYS:
        raise ValueError(f"в ряду Банка России {len(pts)} дней, ожидалось не менее {MIN_DAYS}")
    facts = [Fact(domain="fx", key="RUB", valid_from=d,
                  valid_to=pts[i + 1][0] if i + 1 < len(pts) else None,
                  value=round(v, 6), unit="per_EUR", currency="RUB",
                  source_id=ctx["source_id"], artifact_sha=ctx.get("sha"),
                  extracted_by="parser:cbr_fx_hist@1", confidence="exact",
                  note="официальный курс Банка России, история")
             for i, (d, v) in enumerate(pts)]
    ctx.setdefault("summary", []).append(
        f"ЦБ РФ, рубль за евро с {pts[0][0]} по {pts[-1][0]}: {len(pts)} дней")
    return facts
