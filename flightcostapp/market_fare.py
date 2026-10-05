"""Наблюдения рыночной цены: из выгрузки агрегатора в хранилище.

ЧТО ЭТО И ЧЕГО ЭТО НЕ ЕСТЬ. Интерфейс агрегатора отдаёт самое дешёвое
найденное предложение на дату вылета, а не распределение предложений.
Поэтому вид наблюдения назван по измеренному — `fare_min_daily`, минимум
на дату, — и медиана по нему есть медиана ДНЕВНЫХ МИНИМУМОВ за период, а
не медиана цен. Величина осмысленная и полезная: за сколько линия реально
продаётся в среднюю дату. Но если назвать её «медианой цен», через год мы
сравним с ней свой средний чек и повторим ошибку границы учёта, на которой
обожглись со строкой ТОиР у Ryanair.

ГЛУБИНА БРОНИРОВАНИЯ — ИЗМЕРЕНИЕ, А НЕ ПОЛЕ. Цена за шестьдесят дней до
вылета и за семь — разные величины, а не разброс одной. Свёртка без этого
измерения смешает предпродажу с горящим и даст медиану, которой не
соответствует ни одна реальная покупка. Поэтому глубина попадает в ключ
полосами.

ПРЯМЫЕ И С ПЕРЕСАДКОЙ — РАЗНЫЕ РЫНКИ. Мы считаем экономику ОДНОГО
сектора; цена с пересадкой относится к другому продукту и к другой
себестоимости. Смешивать нельзя, поэтому признак прямого рейса тоже в
ключе.

ЦЕНА ХРАНИТСЯ КАК ОПУБЛИКОВАНА (решение 22). Агрегатор отдаёт рубли —
рубли и кладём, с валютой в поле. Пересчёт в евро делает расчёт, беря курс
на дату наблюдения. Пересчитать здесь значило бы зашить сегодняшний курс в
прошлогоднее наблюдение.

СЕТЬ ВНЕ КОНТУРА. Сбор делает отдельный скрипт со своим ключом, сюда
приезжает уже выгрузка. Ключи в реестр не попадают, сырые предложения в
хранилище не попадают тоже: в `observations` едут дневные минимумы, в
`facts` — только агрегаты (решение 9).
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime

from .store import Fact

# Полосы глубины бронирования. Границы не круглые числа ради красоты: цена
# ломается на типичных горизонтах продаж — последняя неделя, две недели,
# месяц, квартал. Полоса, а не точное число дней, потому что наблюдений на
# каждый день не хватит никогда.
DEPTH_BANDS = [
    (0, 7, "d00_07"),
    (8, 14, "d08_14"),
    (15, 30, "d15_30"),
    (31, 60, "d31_60"),
    (61, 120, "d61_120"),
    (121, 9999, "d121_"),
]

KIND = "fare_min_daily"
MIN_OBS = 5          # меньше — не полоса, а несколько случаев


def depth_band(days: int) -> str:
    for lo, hi, name in DEPTH_BANDS:
        if lo <= days <= hi:
            return name
    return "d121_"


def _day(v) -> date | None:
    if not v:
        return None
    s = str(v)[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def read_dump(blob: bytes, *, to_icao: dict[str, str] | None = None) -> list[dict]:
    """Сырая выгрузка -> дневные минимумы.

    Ожидаются колонки `origin_req`, `destination_req`, `departure_at`,
    `price`, `collected_at` и, если есть, `transfers` и `currency`.

    КЛЮЧ ПЕРЕВОДИТСЯ В ИКАО. Агрегатор говорит на ИАТА, весь остальной
    продукт — на ИКАО (решение 103): тариф, зона аэронавигации и
    наблюдения ADS-B ключуются им. Оставить здесь ИАТА значило бы завести
    домен, который не стыкуется ни с чем, и обнаружить это при первой же
    попытке сопоставить цену с себестоимостью.

    `to_icao` — отображение из `store.icao_of_iata()`. Без него пара
    остаётся как пришла, и это помечается: лучше несостыкованный ключ,
    чем молчаливое смешение двух систем в одном домене.
    Свёртка идёт ЗДЕСЬ, а не в хранилище: отдельные предложения — это
    сотни тысяч строк, которые не нужны никому после свёртки, и держать их
    в базе значит повторить историю с полумиллионом фактов реестра бортов.
    """
    text = blob.decode("utf-8", "replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise ValueError("выгрузка пуста")
    # Валюта ОБЯЗАТЕЛЬНА. Прежде стояло `r.get("currency") or "RUB"`:
    # выгрузка без колонки молча ложилась рублями, и 36 567 евровых
    # минимумов легли как «99 RUB» — ошибка в девяносто раз, которую
    # полоса не покажет, числа правдоподобны. Умолчание у валюты — тот же
    # тихий отказ, что мёртвый валидатор (решение 24).
    #
    # Откуда берётся: колонка `currency`, а без неё — из ссылки агрегатора
    # в той же строке (`expected_price_currency=eur`): это его публикация,
    # не наше умолчание. Сколько взято из ссылки — в отчёте разбора.
    need = {"origin_req", "destination_req", "departure_at", "price"}
    missing = need - set(rows[0])
    if missing:
        raise ValueError(f"в выгрузке нет колонок: {', '.join(sorted(missing))}; "
                         f"есть: {', '.join(list(rows[0])[:8])}")

    best: dict[tuple, dict] = {}
    untranslated: set[str] = set()
    skipped = 0
    from_link = 0
    link_cur = re.compile(r"expected_price_currency=([A-Za-z]{3})")

    def currency_of(r) -> str:
        nonlocal from_link
        c = (r.get("currency") or "").strip().upper()
        if c:
            return c
        for v in r.values():
            m = link_cur.search(v or "")
            if m:
                from_link += 1
                return m.group(1).upper()
        return ""

    for r in rows:
        dep = _day(r.get("departure_at"))
        seen = _day(r.get("collected_at")) or date.today()
        try:
            price = float(r["price"])
        except (TypeError, ValueError):
            skipped += 1
            continue
        ccy = currency_of(r)
        if dep is None or price <= 0 or not ccy:
            skipped += 1                     # без валюты цена — не цена
            continue
        # Глубина считается от даты НАБЛЮДЕНИЯ, а не от сегодня: выгрузка
        # может разбираться через неделю после сбора, и тогда «сегодня»
        # дало бы другую полосу той же цене.
        days = (dep - seen).days
        if days < 0:
            skipped += 1                     # вылет раньше наблюдения
            continue
        try:
            direct = int(float(r.get("transfers") or 0)) == 0
        except (TypeError, ValueError):
            direct = True
        o = r["origin_req"].strip().upper()
        d = r["destination_req"].strip().upper()
        if to_icao:
            o, d = to_icao.get(o, o), to_icao.get(d, d)
            if len(o) != 4 or len(d) != 4:
                untranslated.add(f"{r['origin_req']}-{r['destination_req']}")
        pair = f"{o}-{d}"
        key = (pair, dep, depth_band(days), direct)
        cur = best.get(key)
        if cur is None or price < cur["price"]:
            best[key] = {"pair": pair, "dep_date": dep, "band": depth_band(days),
                         "direct": direct, "price": price,
                         "currency": ccy,
                         "observed_at": seen,
                         "carrier": (r.get("airline") or "").strip()}
    out = list(best.values())
    out.sort(key=lambda x: (x["pair"], x["dep_date"], x["band"]))
    if untranslated:
        # Не отказ: наблюдение с непереведённым кодом всё равно ценнее
        # пропуска. Но сказать обязательно — иначе домен тихо наберёт
        # ключи двух систем, и это вскроется через полгода.
        out.append({"__untranslated__": sorted(untranslated)})
    out.append({"__report__": {"skipped": skipped, "currency_from_link": from_link,
                               "no_currency": "currency" not in rows[0]}})
    return out


def collect(store, dump: list[dict], *, source_id: str = "market_fare") -> dict:
    """Дневные минимумы -> таблица наблюдений.

    Ключ несёт ВСЁ, от чего величина зависит (решение 114): пару, полосу
    глубины и признак прямого рейса. Дата вылета идёт моментом
    наблюдения — дедупликация по четвёрке отсечёт повторный разбор той же
    выгрузки.
    """
    warn = [d for d in dump if "__untranslated__" in d]
    rep = next((d["__report__"] for d in dump if "__report__" in d), {})
    dump = [d for d in dump if "__untranslated__" not in d and "__report__" not in d]
    rows = [dict(
        kind=KIND,
        key=f"{d['pair']}/{d['band']}/{'direct' if d['direct'] else 'via'}",
        value=d["price"], unit=(d["currency"] or "").upper(),
        observed_at=d["dep_date"].isoformat(),
        source_id=source_id, ref=d["carrier"] or None,
        note=d["observed_at"].isoformat(),
    ) for d in dump]
    st = store.add_observations(rows)
    st["pairs"] = len({d["pair"] for d in dump})
    st["bands"] = sorted({d["band"] for d in dump})
    st["untranslated"] = warn[0]["__untranslated__"] if warn else []
    st["skipped"] = rep.get("skipped", 0)
    st["currency_from_link"] = rep.get("currency_from_link", 0)
    st["no_currency_column"] = rep.get("no_currency", False)
    if hasattr(store, "mark_source"):
        store.mark_source(source_id, status="ok",
                          message=(f"минимумов {st['added']}, пар {st['pairs']}, "
                                   f"дублей {st['duplicate']}"))
    return st


def explain(store, pair: str, *, min_obs: int = MIN_OBS) -> list[str]:
    """Почему полоса по паре есть или её нет — по одной паре целиком.

    `aggregate` печатает восемь причин и «…и ещё 2066»: механизм говорит,
    что чего-то не сделал, но не даёт спросить про конкретную линию, и
    ответ на вопрос «почему нет DME–OVB» искался по таблице руками.
    Пара принимается в ИКАО или ИАТА (перевод указателем); направление
    как хранится: `UUDD-UNNT` и `UNNT-UUDD` — разные линии.
    """
    p = pair.strip().upper()
    if hasattr(store, "icao_of_iata"):
        m = store.icao_of_iata()
        o, _, d = p.partition("-")
        p = f"{m.get(o, o)}-{m.get(d, d)}"
    out = [f"пара {p}"]
    obs = store.db.execute(
        """SELECT key, unit, COUNT(*), COUNT(DISTINCT substr(note, 1, 10)),
                  MIN(observed_at), MAX(observed_at)
           FROM observations WHERE kind = ? AND key LIKE ?
           GROUP BY key, unit ORDER BY key""", (KIND, p + "/%")).fetchall()
    if not obs:
        rev = store.db.execute(
            "SELECT COUNT(*) FROM observations WHERE kind = ? AND key LIKE ?",
            (KIND, f"{p.split('-')[-1]}-{p.split('-')[0]}/%")).fetchone()[0]
        out.append("наблюдений нет" + (f"; в обратном направлении {rev}" if rev else "")
                   + " — пары не было в сборе или код не переведён")
        return out
    facts = {k: (v, u, vf) for k, v, u, vf in store.db.execute(
        """SELECT key, value, unit, valid_from FROM facts
           WHERE domain = 'market_fare' AND valid_to IS NULL AND key LIKE ?""",
        (p + "/%",))}
    for key, unit, n, n_collect, lo, hi in obs:
        band = key[len(p) + 1:]
        line = (f"  {band:<16} {unit or '?':<4} дат вылета {n:>3} ({lo} … {hi}), "
                f"сборов {n_collect}")
        if key in facts:
            v, u, vf = facts[key]
            line += f" → полоса ЕСТЬ: медиана {v} {u}, с {vf}"
        elif n < min_obs:
            line += f" → полосы нет: дат вылета {n}, нужно {min_obs}"
        else:
            line += " → полосы нет, хотя дат хватает: свёртка не запускалась после сбора?"
        out.append(line)
    units = {u for _, u, *_ in obs}
    if len(units) > 1:
        out.append(f"  ! валюты в наблюдениях смешаны: {', '.join(sorted(units))}")
    return out


def aggregate(store, *, as_of=None, min_obs: int = MIN_OBS,
              source_id: str = "market_fare") -> tuple[list[Fact], list[str]]:
    """Свёртка в домен `market_fare`. В `facts` едут только агрегаты.

    Число наблюдений кладётся ОБЯЗАТЕЛЬНО и в значение, и в текст: полоса
    по пяти датам и по ста пятидесяти выглядят одинаково, а утверждают
    разное.
    """
    import json
    import statistics

    as_of = str(as_of or date.today())
    facts, thin, mixed = [], [], []
    # Валюта берётся из САМИХ наблюдений, а не подставляется. Раньше здесь
    # стояло `unit="RUB"` жёстко: агрегатор запрашивался в рублях, и это
    # молча стало свойством домена. Первая же выгрузка в другой валюте
    # легла бы под рублёвой подписью, и полоса собралась бы из чисел в
    # разных деньгах — та же ошибка, что была с CASK Аэрофлота, только
    # без спасительного различия в два порядка.
    cur_by_key: dict[str, set[str]] = {}
    for k, u in store.db.execute(
            "SELECT key, unit FROM observations WHERE kind = ?", (KIND,)):
        cur_by_key.setdefault(k, set()).add((u or "").upper())
    for key, _n in store.observation_keys(KIND).items():
        curs = {c for c in cur_by_key.get(key, set()) if c}
        if len(curs) > 1:
            # Смешение валют в одном ключе — не повод усреднить, а повод
            # отказаться: медиана рублей и евро не значит ничего.
            mixed.append(f"{key}: валюты {', '.join(sorted(curs))}")
            continue
        cur = next(iter(curs), "")
        vals = sorted(store.observation_stats(KIND, key))
        if len(vals) < min_obs:
            thin.append(f"{key}: дат {len(vals)}, нужно {min_obs}")
            continue
        q = statistics.quantiles(vals, n=4) if len(vals) >= 4 else None
        facts.append(Fact(
            domain="market_fare", key=key, valid_from=as_of,
            # Значение — МЕДИАНА ДНЕВНЫХ МИНИМУМОВ. Имя ключа содержит вид
            # наблюдения, чтобы читающий не принял её за медиану цен.
            value=round(statistics.median(vals), 2),
            unit=cur, currency=cur, value_text=json.dumps(
                {"n_days": len(vals), "min": vals[0], "max": vals[-1],
                 **({"p25": round(q[0], 2), "p75": round(q[2], 2)} if q else {})},
                ensure_ascii=False),
            source_id=source_id, extracted_by="market_fare@1",
            confidence="derived", certainty="exact", node="src_aggregator",
            source_note=("медиана МИНИМУМОВ по датам вылета, а не медиана "
                         "предложений: интерфейс агрегатора отдаёт самое "
                         "дешёвое найденное на дату"),
            note=f"дат {len(vals)}"))
    return facts, thin + mixed
