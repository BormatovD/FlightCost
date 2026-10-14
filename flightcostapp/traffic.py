"""Пассажиропоток по паре аэропортов (M10, решение 195).

Одна точка чтения для сети, маршрута и подбора типа. Цепочка источников,
каждый со своей подписью, первый найденный побеждает:

1. заданное человеком — вне этого модуля, в сети и в рабочем месте;
2. опубликованная статистика — домен `traffic` (Eurostat `avia_par_*`,
   дальше BTS T-100 и CAA), пассажиры перевезённые, оба направления;
3. оценка по наблюдённым рейсам × кресла × загрузка — в `network.py`.

Поток — вход обращения «какая доля рынка нужна», а не прогноз доли
(решение 154). Модуль ничего не делит между перевозчиками.
"""

from __future__ import annotations

import json
from datetime import date

PUBLISHERS = {"eurostat_par": "Eurostat avia_par", "t100": "BTS T-100",
              "dgca_domestic": "DGCA", "dgca_international": "DGCA"}


# Ряд пары — одним фактом на год (решение 197): ключ
# `<отчётчик>/<ИКАО-ИКАО>/<ГГГГ>`, значение — пассажиры за год, в тексте —
# месяцы `{"01": [пасс, кресел, рейсов], …}`. Помесячный факт на каждую
# меру давал 740 тыс. строк и 270 МБ снимка на две выгрузки; годовой —
# в сорок раз меньше, а читатель всё равно работает с месяцами.
MIN_PAX_YEAR = 1000          # пара с меньшим годовым потоком — не рынок, а перегоны и чартеры


def pack(agg: dict, *, ctx: dict, who: str, note) -> list:
    """{(отчётчик, A, B, "ГГГГ-ММ" | "ГГГГ-Qn"): [пасс, кресел|None, рейсов|None]} -> факты.

    `note` — строка или функция (отчётчик, A, B) -> строка: у DGCA подпись
    своя у пар, где город отнесён к главному аэропорту."""
    from .store import Fact
    years: dict[tuple, dict[str, list]] = {}
    for (rep, a, b, mon), v in agg.items():
        years.setdefault((rep, a, b, mon[:4]), {})[mon[5:]] = v
    out, small = [], 0
    for (rep, a, b, y), months in sorted(years.items()):
        pax = sum((v[0] or 0) for v in months.values())
        if pax < MIN_PAX_YEAR:
            small += 1
            continue
        out.append(Fact(
            domain="traffic", key=f"{rep}/{a}-{b}/{y}", valid_from=ctx.get("today") or "",
            value=float(pax), unit="пасс/год",
            value_text=json.dumps({m: [round(x) if x is not None else None for x in v]
                                   for m, v in sorted(months.items())}, separators=(",", ":")),
            source_id=ctx["source_id"], artifact_sha=ctx.get("sha"), extracted_by=who,
            confidence="exact", certainty="exact", node=ctx.get("node") or "src_traffic",
            note=note(rep, a, b) if callable(note) else note))
    if small:
        ctx.setdefault("summary", []).append(
            f"пропущено пар-лет с потоком меньше {MIN_PAX_YEAR} пасс./год: {small}")
    return out


def _db(store):
    return getattr(store, "db", None) or store.base.db


def published(store, a_icao: str, b_icao: str, as_of=None, month: int | None = None) -> dict | None:
    """Опубликованный поток пары, пасс./мес, или None.

    Обе стороны пары отчитываются об одном и том же (Германия о FRA–BCN,
    Испания о BCN–FRA) — месяц берётся средним по отчётам, а расхождение
    сторон называется. Без месяца — среднее за последние 12 опубликованных
    месяцев; с месяцем — среднее этого календарного месяца по годам: поток
    в августе и в феврале различается вдвое, и годовое среднее для летнего
    расчёта занижало бы рынок.
    """
    if not a_icao or not b_icao or a_icao == b_icao:
        return None
    as_of = str(as_of or date.today())
    a, b = sorted((a_icao.upper(), b_icao.upper()))
    rows = _db(store).execute(
        """SELECT key, value_text, source_id, note FROM facts
           WHERE domain = 'traffic' AND key LIKE ? AND valid_from <= ?
             AND (valid_to IS NULL OR valid_to > ?)""",
        (f"%/{a}-{b}/%", as_of, as_of)).fetchall()
    by_month: dict[str, dict[str, float]] = {}
    extra: dict[str, dict[str, dict[str, float]]] = {"seats": {}, "flights": {}}
    srcs, quarterly, notes = set(), set(), set()
    for key, txt, src, fnote in rows:
        parts = key.split("/")
        if len(parts) != 3 or parts[1] != f"{a}-{b}" or not txt:
            continue
        rep, _, year = parts
        for mm, (pax, seats, flights) in json.loads(txt).items():
            if pax is None:
                continue
            if mm.startswith("Q"):
                # Квартал (DGCA, международные): средний месяц — треть
                # квартала. Сезонность внутри квартала не выдумывается.
                q = int(mm[1:])
                for k in range(3):
                    mon = f"{year}-{(q - 1) * 3 + k + 1:02d}"
                    by_month.setdefault(mon, {})[rep] = float(pax) / 3
                    quarterly.add(rep)
                continue
            mon = f"{year}-{mm}"
            by_month.setdefault(mon, {})[rep] = float(pax)
            if seats:
                extra["seats"].setdefault(mon, {})[rep] = float(seats)
            if flights:
                extra["flights"].setdefault(mon, {})[rep] = float(flights)
        srcs.add(src)
        if fnote and "город, а не аэропорт" in fnote:
            notes.add(fnote.split("; ", 1)[1])
    if not by_month:
        return None
    months = sorted(by_month)
    if month:
        pick = [m for m in months if int(m[5:]) == int(month)]
        how = f"среднее за {int(month):02d}-й месяц по {len(pick)} г."
    else:
        pick = months[-12:]
        how = (f"среднее за {len(pick)} мес. ({pick[0]}…{pick[-1]})" if len(pick) > 1
               else f"за {pick[0]}")
    if not pick:
        return None
    vals = [sum(by_month[m].values()) / len(by_month[m]) for m in pick]
    gap = max((abs(r[0] - r[1]) / max(r) for r in
               (tuple(by_month[m].values()) for m in pick) if len(r) == 2 and max(r)),
              default=None)
    pub = ", ".join(sorted(PUBLISHERS.get(s, s) for s in srcs))
    note = f"{pub}: пассажиры перевезённые, оба направления, {how}"
    if gap is not None and gap > 0.05:
        note += f"; отчёты сторон расходятся до {gap * 100:.0f}%"
    if quarterly:
        note += "; данные квартальные — месяц взят третью квартала"
    for n in sorted(notes):
        note += f"; {n}"
    # Средний борт рынка и его загрузка — по тем же месяцам, где есть и
    # пассажиры, и кресла с рейсами.
    def avg(meas):
        got = [sum(extra[meas][m].values()) / len(extra[meas][m]) for m in pick if m in extra[meas]]
        return sum(got) / len(got) if len(got) == len(pick) else None
    seats, flights = avg("seats"), avg("flights")
    mkt = {}
    pax_avg = sum(vals) / len(vals)
    if flights:
        mkt["flights_month"] = flights
        mkt["pax_per_flight"] = pax_avg / flights
    if seats:
        mkt["seats_month"] = seats
        mkt["lf"] = pax_avg / seats
        if flights:
            mkt["seats_per_flight"] = seats / flights
    return {"pax_month": pax_avg, "src": note, "months": pick, "market": mkt,
            "last": months[-1], "series": {m: sum(by_month[m].values()) / len(by_month[m])
                                           for m in months[-24:]}}


def obs_seats(store, a_icao: str, b_icao: str, as_of=None) -> tuple[float | None, str]:
    """Средние кресла рейса пары по типам наблюдённых бортов (решение 198),
    оба направления, взвешено числом рейсов. (None, "") — типов нет."""
    tot = n = 0.0
    types: dict[str, int] = {}
    for k in (f"{a_icao}-{b_icao}", f"{b_icao}-{a_icao}"):
        try:
            row = store.get("observed", f"seats/{k}", as_of)
        except Exception:                                  # noqa: BLE001
            row = None
        if row is None or not row["value"]:
            continue
        meta = json.loads(row["value_text"] or "{}")
        w = float(meta.get("n") or 1)
        tot += float(row["value"]) * w
        n += w
        for t, c in (meta.get("types") or {}).items():
            types[t] = types.get(t, 0) + c
    if not n:
        return None, ""
    mix = ", ".join(f"{t} {c}" for t, c in sorted(types.items(), key=lambda x: -x[1])[:4])
    return tot / n, f"{tot / n:.0f} кресел по типам ({mix})"


def observed(store, a_icao: str, b_icao: str, as_of=None) -> dict | None:
    """Оценка по наблюдённым рейсам (ADS-B): рейсов в неделю × недель в
    месяце × кресел × загрузка. Кресла — по типам наблюдённых бортов, если
    они известны (решение 198), иначе плоские 180. Оценка, а не измерение:
    загрузка — допущение, и подпись это говорит."""
    from .network import MARKET_LF, MARKET_SEATS, WEEKS_PER_MONTH, observed_frequency
    try:
        freq, window = observed_frequency(store, as_of)
    except Exception:                                      # noqa: BLE001
        return None
    wk = (freq.get(f"{a_icao}-{b_icao}") or 0.0) + (freq.get(f"{b_icao}-{a_icao}") or 0.0)
    if not wk:
        return None
    seats, why = obs_seats(store, a_icao, b_icao, as_of)
    seats_txt = why or f"{MARKET_SEATS} кресел (типы бортов не известны)"
    return {"pax_month": wk * WEEKS_PER_MONTH * (seats or MARKET_SEATS) * MARKET_LF,
            "src": (f"оценка: наблюдённые рейсы всех перевозчиков {wk:.1f}/нед (окно {window} сут.) "
                    f"× {seats_txt} × загрузка {MARKET_LF:.2f}"),
            "estimate": True}


def pair_flow(store, a_icao: str, b_icao: str, as_of=None, month: int | None = None) -> dict:
    """Поток пары по цепочке: опубликованный, иначе оценка, иначе ответ «нет»
    с причиной — пустое значение без причины читалось бы как ноль."""
    pub = published(store, a_icao, b_icao, as_of, month)
    if pub:
        return {**pub, "estimate": False}
    est = observed(store, a_icao, b_icao, as_of)
    if est:
        return est
    return {"pax_month": None,
            "src": "нет: в опубликованной статистике (Eurostat, BTS T-100, DGCA) пары нет, "
                   "рейсов по паре не наблюдали; для RU и KZ открытой статистики по парам "
                   "не публикуется"}


NEARBY_KM = 80        # «тот же город»: второй аэропорт Мумбаи — 35 км, Москвы — до 50


_COORDS: dict = {}


def _coords(store) -> dict:
    """ИКАО -> (lat, lon, ключ справочника) по домену `airport`, один раз на базу."""
    db = _db(store)
    key = id(db)
    if key not in _COORDS:
        out = {}
        for k, txt in db.execute(
                "SELECT key, value_text FROM facts WHERE domain='airport' AND valid_to IS NULL"):
            p = (txt or "").split("|", 3)
            if len(p) < 2 or not p[1]:
                continue
            try:
                lat, lon = (float(x) for x in p[0].split(",", 1))
            except ValueError:
                continue
            out[p[1]] = (lat, lon, k)
        _COORDS.clear()
        _COORDS[key] = out
    return _COORDS[key]


def nearby(store, a_icao: str, b_icao: str, as_of=None, month: int | None = None) -> list[dict]:
    """Пары с ДРУГИМ аэропортом того же города (до 80 км) и опубликованным
    потоком — чтобы Дели–Нави-Мумбаи не читался как «весь Мумбаи».

    Кандидаты — только партнёры другого конца по домену `traffic`, а не
    все аэропорты в радиусе: их десятки, поток есть у единиц."""
    import math
    co = _coords(store)
    db = _db(store)
    out = []
    for here, other in ((a_icao, b_icao), (b_icao, a_icao)):
        if here not in co:
            continue
        partners = set()
        for (k,) in db.execute(
                "SELECT DISTINCT key FROM facts WHERE domain='traffic' AND valid_to IS NULL "
                "AND (key LIKE ? OR key LIKE ?)", (f"%/{other}-%", f"%-{other}/%")):
            pair = k.split("/")[1] if k.count("/") >= 2 else ""
            x, _, y = pair.partition("-")
            partners.add(y if x == other else x)
        la, lo, _ = co[here]
        for p in sorted(partners - {here, other}):
            if p not in co:
                continue
            pl, po, pkey = co[p]
            d = 6371 * 2 * math.asin(math.sqrt(
                math.sin(math.radians(pl - la) / 2) ** 2 + math.cos(math.radians(la))
                * math.cos(math.radians(pl)) * math.sin(math.radians(po - lo) / 2) ** 2))
            if d > NEARBY_KM:
                continue
            pub = published(store, other, p, as_of, month)
            if pub:
                out.append({"replace": here, "with": p, "with_key": pkey, "other": other,
                            "km": round(d), "pax_month": pub["pax_month"]})
    return sorted(out, key=lambda x: -x["pax_month"])
