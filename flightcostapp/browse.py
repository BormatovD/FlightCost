"""Просмотр хранилища на сайте (решение 219).

Что видно построчно, решает реестр: у источника `public: full` — строки
показываются с атрибуцией; `public: none` (цены агрегатора, сводка по РФ
без первоисточника, наблюдения OpenSky, ставки «проверить условия») — на
сайте только число записей. Источник без поля считается закрытым:
открыть случайно хуже, чем забыть открыть.

Домены названы по-человечески и сгруппированы так, как их ищет новый
человек: «типы ВС», «аэропорты», «поток по парам», а не `aircraft`,
`airport`, `traffic`. У типов ВС факт — одно свойство (`A320/mtow_t`),
поэтому они показываются сводно: строка — тип, свойства — по нажатию.
"""

from __future__ import annotations

from datetime import date

PAGE = 50

# Порядок — как ищет новый человек; домены вне списка идут в конце «прочее».
DOMAINS = [
    ("aircraft", "Типы ВС", "Паспорт типа: массы, крейсер, двигатели, кресла — из openap, EASA и своих типов"),
    ("airport", "Аэропорты", "Координаты и коды ИКАО/ИАТА — OurAirports"),
    ("airport_limits", "Полосы аэропортов", "Длина, ширина и покрытие ВПП — OurAirports"),
    ("traffic", "Поток по парам", "Пассажиры, перевезённые между аэропортами: Eurostat, BTS T-100, DGCA"),
    ("airport_charge", "Сборы аэропортов", "Ставки сборов по аэропортам и статьям"),
    ("enroute_rate", "Аэронавигация: ставки зон", "Ставка за единицу обслуживания по государствам"),
    ("terminal_rate", "Аэронавигация: терминальные", "Ставки терминальных зон"),
    ("jet_fuel_price", "Цена топлива", "Котировки авиакеросина"),
    ("fx", "Курсы валют", "Курсы к евро: ЕЦБ, Банк России, CRCO"),
    ("carrier_benchmark", "Отчётность перевозчиков", "Величины из годовых отчётов: выручка, расходы, блок-часы"),
    ("fleet_benchmark", "Экономика флота", "Form 41 США и IATA/EUROCONTROL ACMG"),
    ("city", "Города", "Население городов от 15 тыс. — GeoNames, для модели потока"),
    ("market_fare", "Цены билетов", "Медианы дневных минимумов агрегатора"),
    ("observed", "Наблюдённые рейсы", "ADS-B OpenSky: сводки по парам и типам"),
]
TITLE = {d: t for d, t, _ in DOMAINS}


def policy(registry: dict) -> dict:
    """{источник: 'full' | 'none'} и подпись лицензии для атрибуции."""
    out = {}
    for sid, sv in (registry or {}).get("sources", {}).items():
        out[sid] = {"public": sv.get("public") == "full",
                    "license": str(sv.get("license") or "").strip(),
                    "title": sv.get("title") or sid}
    return out


def _public_ids(registry, store=None, open_all=False) -> list[str]:
    """Источники, чьи строки видны. Локально (`open_all`) — все: данные
    ваши, лицензия ограничивает публикацию, а не просмотр у себя."""
    if open_all and store is not None:
        return sorted(r[0] for r in store.db.execute("SELECT DISTINCT source_id FROM facts"))
    return sorted(s for s, v in policy(registry).items() if v["public"])


def catalog(store, registry, as_of=None, open_all=False) -> dict:
    """Домены с числом записей: открытых построчно и закрытых."""
    as_of = str(as_of or date.today())
    pub = set(_public_ids(registry, store, open_all))
    pol = policy(registry)
    counts: dict = {}
    for dom, sid, n in store.db.execute(
            """SELECT domain, source_id, COUNT(*) FROM facts
               WHERE valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)
               GROUP BY domain, source_id""", (as_of, as_of)):
        c = counts.setdefault(dom, {"open": 0, "closed": 0, "sources": {}})
        c["open" if sid in pub else "closed"] += n
        c["sources"][sid] = {"n": n, "public": sid in pub,
                             "title": (pol.get(sid) or {}).get("title", sid),
                             "license": (pol.get(sid) or {}).get("license", "")}
    order = [d for d, _, _ in DOMAINS] + sorted(set(counts) - set(TITLE))
    out = []
    for d in order:
        if d not in counts:
            continue
        note = next((x for k, _, x in DOMAINS if k == d), "")
        out.append({"domain": d, "title": TITLE.get(d, d), "note": note, **counts[d]})
    return {"as_of": as_of, "domains": out}


def rows(store, registry, domain: str, q: str = "", page: int = 0, as_of=None,
         open_all=False) -> dict:
    """Страница открытых строк домена; закрытые — числом."""
    as_of = str(as_of or date.today())
    pub = _public_ids(registry, store, open_all)
    page = max(0, int(page or 0))
    pol = policy(registry)
    like = f"%{q.strip()}%" if q and q.strip() else None
    base = ("FROM facts WHERE domain = ? AND valid_from <= ? "
            "AND (valid_to IS NULL OR valid_to > ?)")
    args: list = [domain, as_of, as_of]
    if like:
        base += " AND (key LIKE ? OR value_text LIKE ?)"
        args += [like, like]
    mark = ",".join("?" * len(pub)) or "''"
    closed = store.db.execute(f"SELECT COUNT(*) {base} AND source_id NOT IN ({mark})",
                              args + pub).fetchone()[0]
    if domain == "aircraft":
        return _aircraft(store, base, args, pub, mark, closed, page, pol)
    total = store.db.execute(f"SELECT COUNT(*) {base} AND source_id IN ({mark})",
                             args + pub).fetchone()[0]
    out = []
    for r in store.db.execute(
            f"""SELECT key, value, unit, value_text, currency, valid_from, source_id,
                       confidence, certainty {base} AND source_id IN ({mark})
                ORDER BY key LIMIT ? OFFSET ?""",
            args + pub + [PAGE, page * PAGE]):
        out.append({"key": r[0], "value": r[1], "unit": r[2], "text": (r[3] or "")[:400],
                    "currency": r[4], "from": r[5], "source": r[6],
                    "source_title": (pol.get(r[6]) or {}).get("title", r[6]),
                    "confidence": r[7], "certainty": r[8]})
    return {"domain": domain, "title": TITLE.get(domain, domain), "total": total,
            "closed": closed, "page": page, "pages": (total + PAGE - 1) // PAGE,
            "rows": out, "kind": domain}


def _aircraft(store, base, args, pub, mark, closed, page, pol) -> dict:
    """Типы ВС сводно: строка — тип, свойства — словарём."""
    types = [r[0] for r in store.db.execute(
        f"""SELECT DISTINCT substr(key, 1, instr(key || '/', '/') - 1) AS t {base}
            AND source_id IN ({mark}) ORDER BY t""", args + pub)]
    total = len(types)
    pick = types[page * PAGE:(page + 1) * PAGE]
    out = []
    for t in pick:
        props = {}
        srcs = set()
        for k, v, u, txt, src in store.db.execute(
                f"""SELECT key, value, unit, value_text, source_id {base}
                    AND source_id IN ({mark}) AND key LIKE ? ORDER BY key""",
                args + pub + [t + "/%"]):
            props[k.split("/", 1)[1] if "/" in k else k] = {
                "value": v, "unit": u, "text": (txt or "")[:200]}
            srcs.add((pol.get(src) or {}).get("title", src))
        out.append({"key": t, "props": props, "sources": sorted(srcs)})
    return {"domain": "aircraft", "title": TITLE["aircraft"], "total": total,
            "closed": closed, "page": page, "pages": (total + PAGE - 1) // PAGE,
            "rows": out, "kind": "aircraft"}


def is_public(registry, source_id: str) -> bool:
    return bool((policy(registry).get(source_id) or {}).get("public"))
