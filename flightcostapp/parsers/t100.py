"""BTS T-100 Segment — пассажиропоток пар с концом в США, домен `traffic`.

Выгрузка TranStats «T-100 Segment (All Carriers)»: строка — перевозчик ×
пара × тип ВС × класс услуги × месяц, направленно. Здесь она сворачивается
в то же, что даёт Eurostat: пара по алфавиту, месяц, оба направления,
ВСЕ перевозчики — пассажиры, кресла, выполненные рейсы.

Почему отчётчик один — `T100`, а не источник данных (DU, DF, IU, IF).
Отчёты сторон у Eurostat описывают ОДИН и тот же поток и усредняются, а
источники T-100 — РАЗНЫЕ перевозчики на одной паре (американские и
иностранные на JFK–LHR) и складываются. Сложение делается здесь, в
разборе, чтобы читатель знал одно правило: отчётчики — это стороны,
а не части.

Классы услуги: F — регулярные пассажирские, L — нерегулярные
пассажирские. Грузовые (G, P) не берутся: пассажиров у них нет, а их
рейсы и «кресла» исказили бы средний борт рынка.

Коды — ИАТА, переводятся в ИКАО указателем хранилища (`icao_of_iata`).
Непереведённые не теряются молча: их число и примеры — в сводке.
Данные правительства США, ограничений на использование нет.
"""

from __future__ import annotations

import csv
import gzip
import io
import zipfile

from ..store import Fact

WHO = "parser:t100@2"
REPORTER = "T100"
PAX_CLASSES = {"F", "L"}
NEED = {"PASSENGERS", "SEATS", "DEPARTURES_PERFORMED", "ORIGIN", "DEST", "YEAR",
        "MONTH", "CLASS"}


def _text(blob: bytes) -> str:
    if blob[:2] == b"\x1f\x8b":
        blob = gzip.decompress(blob)
    elif blob[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            blob = z.read(name)
    return blob.decode("utf-8-sig", errors="replace")


def _f(x) -> float:
    try:
        return float(x or 0)
    except ValueError:
        return 0.0


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    rd = csv.DictReader(io.StringIO(_text(blob)))
    cols = {c.strip().upper() for c in (rd.fieldnames or [])}
    if not NEED <= cols:
        raise ValueError(f"не похоже на T-100 Segment: нет колонок {sorted(NEED - cols)}")
    store = ctx.get("store")
    to_icao = store.icao_of_iata(ctx.get("today")) if store is not None else {}
    agg: dict[tuple, list[float]] = {}
    miss: dict[str, int] = {}
    for raw in rd:
        r = {k.strip().upper(): (v or "").strip() for k, v in raw.items() if k}
        if r["CLASS"] not in PAX_CLASSES:
            continue
        o, d = to_icao.get(r["ORIGIN"]), to_icao.get(r["DEST"])
        if not o or not d:
            for c, i in ((r["ORIGIN"], o), (r["DEST"], d)):
                if not i:
                    miss[c] = miss.get(c, 0) + 1
            continue
        if o == d:
            continue
        mon = f"{int(r['YEAR']):04d}-{int(r['MONTH']):02d}"
        a, b = sorted((o, d))
        s = agg.setdefault((a, b, mon), [0.0, 0.0, 0.0])
        s[0] += _f(r["PASSENGERS"])
        s[1] += _f(r["SEATS"])
        s[2] += _f(r["DEPARTURES_PERFORMED"])
    if not agg:
        raise ValueError("ни одной пассажирской строки с переводимыми кодами"
                         + (f"; без ИКАО: {', '.join(sorted(miss)[:10])}" if miss else ""))
    from ..traffic import pack
    facts = pack({(REPORTER, a, b, m): v for (a, b, m), v in agg.items() if v[0]},
                 ctx=ctx, who=WHO,
                 note="BTS T-100 Segment: все перевозчики, классы F и L, оба направления")
    ctx.setdefault("parsed_prefixes", []).append(REPORTER)       # store добавит «/»
    months = sorted({m for _, _, m in agg})
    ctx["summary"] = list(ctx.get("summary", []))
    ctx["summary"].insert(0,
        f"пар {len({(a, b) for a, b, _ in agg})}, месяцев {months[0]}…{months[-1]}"
        + (f"; без ИКАО {len(miss)} кодов ИАТА (строк {sum(miss.values())}), например "
           + ", ".join(sorted(miss, key=miss.get, reverse=True)[:8]) if miss else ""))
    return facts
