#!/usr/bin/env python3
"""Статья «Какие маршруты привлекательны для авиакомпании: Европа и Индия» + рейтинг пар (обновляемый).

Данные — out/r1.json (как оценивают маршрут), out/r2.json (открытые данные, слоты, UDAN, доли), out/rating.json
(рейтинг, собирает rating.py из out/pairs_eu.json и out/pairs_in.json); журналы — trace/r1, r2; проверка — verify/.
Поправки проверяющего r1: R² гравитационной модели 0,70–0,76 (r1-120); без «PSO ~4 года» (r1-097); r1-217 не берём.

Пока черновик на русском: после правок владельца — перевод на en/de.

    python3 research/routes-2026-11/rating.py && python3 research/routes-2026-11/build_report.py
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
from _report import ARTICLE_CSS, Sources, article_title, calc_badge, e, mark, n, out_name, page, set_lang  # noqa: E402

S = Sources(HERE)
_PAR = {o["id"]: o.get("parents") or [] for f in sorted(HERE.glob("trace/r*.jsonl"))
        for o in map(json.loads, f.read_text(encoding="utf-8").splitlines())}


def _roots(i, seen=None):
    seen = seen or set()
    if i in S.step or i in seen:
        return [i] if i in S.step else []
    seen.add(i)
    return [r for p in _PAR.get(i, []) for r in _roots(p, seen)]


def cite(*ids):
    return S.cite(*[r for i in ids for r in _roots(i)])


J = lambda f: json.loads((HERE / f).read_text(encoding="utf-8"))  # noqa: E731
R1, R2, RT = J("out/r1.json"), J("out/r2.json"), J("out/rating.json")
VER = {f: J(f"verify/{f}.json") for f in ("r1", "r2") if (HERE / f"verify/{f}.json").exists()}
EU, EUL, IN = RT["europe"]["pairs"], RT["europe"]["long_haul"], RT["india"]["pairs"]
A = J("out/airports.json")
sys.path.insert(0, str(HERE))
from rating import IN_ICAO as IN_CITY  # noqa: E402


def short(name):
    s = re.sub(r"\b(International|Intl\.?|Airport|Aeropuerto|Aéroport|Aeroporto|Flughafen|Airfield)\b", "", name)
    s = re.sub(r"\s+", " ", s).strip(" –-")
    return s[:34]


# Аэропорты в пригородах: OurAirports пишет муниципалитет (Zaventem, Otopeni), а читателю нужен город.
CITYFIX = {"EBBR": "Brussels", "EBCI": "Brussels-Charleroi", "LROP": "Bucharest", "LIME": "Bergamo", "LIMC": "Milan",
           "LIML": "Milan", "EGLL": "London", "EGKK": "London", "EGSS": "London", "EGGW": "London", "EGLC": "London",
           "LFPG": "Paris", "LFPO": "Paris", "LFPB": "Paris", "ESSA": "Stockholm", "ENGM": "Oslo", "EKCH": "Copenhagen",
           "EDDM": "Munich", "LIRF": "Rome", "LIRA": "Rome", "LTFM": "Istanbul", "LTFJ": "Istanbul",
           "UUEE": "Moscow", "UUDD": "Moscow", "UUWW": "Moscow", "LKPR": "Prague", "EPWA": "Warsaw", "EPMO": "Warsaw",
           "LHBP": "Budapest", "LOWW": "Vienna", "EHAM": "Amsterdam", "LSZH": "Zurich", "EIDW": "Dublin",
           "LPPT": "Lisbon", "LGAV": "Athens", "EFHK": "Helsinki", "EVRA": "Riga", "EYVI": "Vilnius",
           "LBSF": "Sofia", "EDDF": "Frankfurt", "EDDB": "Berlin", "LEMD": "Madrid", "LEBL": "Barcelona"}


def city(icao):
    v = A.get(icao) or []
    c = CITYFIX.get(icao) or (v[4] if len(v) > 4 and v[4] else (v[3] if len(v) > 3 else icao))
    c = c.split(" (")[0].split(",")[-1].strip()
    return f"{c} {v[5]}" if len(v) > 5 and v[5] else c


def label(r):
    if "names" in r:
        return f"{city(r['a'])} — {city(r['b'])}"
    return f"{r['a']} — {r['b']}"


AC = J("out/aircraft.json")["pairs"] if (HERE / "out/aircraft.json").exists() else {}
TYPE = {"A20N": "A320neo", "A21N": "A321neo", "B38M": "737 MAX 8", "B39M": "737 MAX 9", "BCS3": "A220-300",
        "A359": "A350-900", "B789": "787-9", "T204": "Ту-214", "SU95": "SJ-100", "MS21": "МС-21"}
COL = {"dom": "var(--sky)", "int": "var(--orange)", "long": "var(--green)"}


def kind(r, india=False):
    if india:
        return "dom"
    if (r.get("km") or 0) > 4500:
        return "long"
    c = r.get("countries") or ["", ""]
    return "dom" if c[0] == c[1] else "int"


def rmap(reg, rows, india=False, w=760):
    """Карта топ-пар: суша Natural Earth (упрощённая вырезка), дуги пар цветом типа перевозок."""
    import math
    land = J(f"out/land_{reg}.json")
    x0, y0, x1, y1 = land["box"]
    k = math.cos(math.radians((y0 + y1) / 2))
    sc = w / ((x1 - x0) * k)
    h = (y1 - y0) * sc
    P = lambda lon, lat: ((lon - x0) * k * sc, (y1 - lat) * sc)  # noqa: E731
    g = [f'<rect width="{w}" height="{h:.0f}" fill="var(--ocean)"/>']
    for poly in land["polys"]:
        d = "M" + "L".join(f"{P(x, y)[0]:.1f},{P(x, y)[1]:.1f}" for x, y in poly) + "Z"
        g.append(f'<path d="{d}" fill="var(--land)" stroke="var(--line)" stroke-width=".5"/>')
    pts = {}
    for i, r in enumerate(rows, 1):
        ia, ib = (r["icao"] if india else (r["a"], r["b"]))
        if ia not in A or ib not in A:
            continue
        (xa, ya), (xb, yb) = P(A[ia][1], A[ia][0]), P(A[ib][1], A[ib][0])
        mx, my = (xa + xb) / 2, (ya + yb) / 2
        dx, dy = xb - xa, yb - ya
        cx, cy = mx - dy * 0.18, my + dx * 0.18
        col = COL[kind(r, india)]
        g.append(f'<path d="M{xa:.1f},{ya:.1f} Q{cx:.1f},{cy:.1f} {xb:.1f},{yb:.1f}" fill="none" stroke="{col}" '
                 f'stroke-width="2.4" opacity=".9"><title>{e(label(r))}: {n(r["pax"])} пасс.</title></path>'
                 f'<circle cx="{(mx + cx) / 2:.1f}" cy="{(my + cy) / 2:.1f}" r="9" fill="var(--bg)" stroke="{col}"/>'
                 f'<text x="{(mx + cx) / 2:.1f}" y="{(my + cy) / 2 + 4:.1f}" text-anchor="middle" font-size="11" '
                 f'fill="var(--ink2)" font-weight="600">{i}</text>')
        for ic, (x, y) in ((ia, (xa, ya)), (ib, (xb, yb))):
            pts[ic] = (x, y)
    for ic, (x, y) in pts.items():
        nm = (r["a"] if False else None)
        lab = city(ic) if not india else next((c for c, v in IN_CITY.items() if v == ic), ic)
        right = x > w - 120
        g.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="var(--ink2)"/>'
                 f'<text x="{x - 6 if right else x + 6:.1f}" y="{y - 5:.1f}" font-size="11.5" fill="var(--ink)" '
                 f'text-anchor="{"end" if right else "start"}" '
                 f'style="paint-order:stroke;stroke:var(--bg);stroke-width:3px">{e(lab)}</text>')
    leg = "".join(f'<span style="color:{COL[k_]}">━ {t}</span> ' for k_, t in
                  (("dom", "внутренний"), ("int", "международный"), ("long", "дальний"))
                  if any(kind(r, india) == k_ for r in rows))
    return (f'<figure class="fig"><svg viewBox="0 0 {w} {h:.0f}" width="100%" font-family="var(--sans)" '
            f'role="img" aria-label="Карта пар">{"".join(g)}</svg><figcaption class="leg">{leg}</figcaption></figure>')


def ac_table(rows, india=False):
    head = ("<tr><th class=r>#</th><th>Пара</th><th>Лучший тип</th><th class=r>Безубыточный тариф, EUR</th>"
            "<th class=r>A320neo</th><th class=r>737 MAX 8</th><th class=r>Рейсов в день</th></tr>")
    body = []
    for r in rows:
        a = AC.get(r["pair"])
        if not a:
            continue
        al = {x["type"]: x for x in a["all"]}
        b = a.get("best")
        f = lambda t: (n(al[t]["fare"]) if t in al and al[t]["ok"] and al[t].get("fare") else "—")  # noqa: E731
        if b:
            seats = (al[b["type"]].get("pax") or 0) / 0.8
            per_day = r["pax"] / 365 / 2 / (seats * 0.8) if seats else None
            best = f"<b>{TYPE.get(b['type'], b['type'])}</b>"
            fare = n(b["fare"])
            pd = n(per_day, 1) if per_day else "—"
        else:
            best = ("Ту-214 / SJ-100 / МС-21 — калькулятор пока не считает" if a.get("russia")
                    else "нет расчёта")
            fare, pd = "—", "—"
        body.append(f"<tr><td class=r>{r['rank']}</td><td class=nm>{e(label(r))}</td><td>{best}</td>"
                    f"<td class=r>{fare}</td><td class=r>{f('A20N')}</td><td class=r>{f('B38M')}</td>"
                    f"<td class=r>{pd}</td></tr>")
    return f'<div class="tw"><table class="txt">{head}{"".join(body)}</table></div>' 


def flags(r):
    f = []
    if r.get("slot3"):
        f.append("слоты: " + ", ".join(r["slot3"]))
    if any(x[:1] == "U" and x[:2] not in ("UK",) for x in (r.get("a", ""), r.get("b", "")) if len(x) == 4):
        f.append("Россия: только перевозчики вне ЕС")
    return "; ".join(f)


def pc(v):
    return "—" if v is None else f"{n(v * 100, 0, sign=True)} %"


def table(rows, india=False, start=0):
    head = ("<tr><th class=r>#</th><th>Пара</th><th class=r>км</th><th class=r>Пассажиров</th>"
            f"<th class=r>Рост {'за 12 мес.' if india else '2024/23'}</th>"
            f"<th class=r>{'Рост 2025/24' if india else 'Загрузка'}</th><th class=r>Индекс</th><th>Ограничения</th></tr>")
    body = "".join(
        f"<tr><td class=r>{r['rank']}</td><td class=nm><b>{e(label(r))}</b></td>"
        f"<td class=r>{n(r['km']) if r.get('km') else '—'}</td><td class=r>{n(r['pax'])}</td>"
        f"<td class=r>{pc(r.get('growth'))}</td>"
        f"<td class=r>{pc(r.get('growth25')) if india else ('—' if r.get('lf') is None else n(r['lf'] * 100, 0) + ' %')}</td>"
        f"<td class=r><b>{n(r['index'])}</b></td><td class=s>{e(flags(r))}</td></tr>" for r in rows[start:])
    return f'<div class="tw"><table class="txt">{head}{body}</table></div>'


def build() -> str:
    set_lang("ru")
    e1, i1 = EU[0], IN[0]
    tr_ru = [r for r in EU[:30] if "Россия" in flags(r)]

    hook = f"""<h1>Какие маршруты привлекательны для авиакомпании: Европа и Индия</h1>
<p class="meta">Исследование FlightCostApp, ноябрь 2026 · как авиакомпании и аэропорты оценивают маршрут, какие данные
для этого открыты, и наш рейтинг {n(len(EU))} пар Европы и {n(len(IN))} пар Индии (будет обновляться)</p>
{calc_badge("routes-2026-11")}
<div class="verdict">
<div><b>Рынок — это пара городов</b><span>сколько людей хотят попасть из одного города в другой, включая тех, кто
сейчас летит со стыковкой или едет в соседний аэропорт{cite('r1-215', 'r1-145')}</span></div>
<div><b>Лоукостер: рынок +10…44 %, тариф −11…21 %</b><span>вход дешёвого перевозчика растит пару, но сбивает
доходность всем{cite('r1-034', 'r1-038', 'r1-009', 'r1-010')}</span></div>
<div><b>Тарифов по паре в открытом доступе нет</b><span>ни в Европе, ни в Индии — поэтому рейтинг стоит на размере
рынка, росте и загрузке{cite('r1-175', 'r2-001')}</span></div>
<div><b>7–8 % маршрутов закрывается за год</b><span>в ЕС в 2025 году закрыли 1 127 маршрутов из примерно 14,8 тыс.;
из маршрутов UDAN после субсидии выжили 7 %{cite('r1-107', 'r1-073')}</span></div></div>
<p class="lede">Какой маршрут открыть — главный вопрос планирования сети. Его решают не по самолёту, а по рынку: сколько
людей хотят летать между двумя городами, растёт ли спрос, сколько мест на паре уже предложено и кем, пустят ли
аэропорты и сколько это стоит. Ниже — как это оценивают авиакомпании и аэропорты, что из этого можно измерить по
открытым данным, и наш рейтинг пар городов для Европы и Индии. Он не говорит «летите сюда»: он показывает, где рынок
большой, растёт и где кресел уже не хватает, — с чего стоит начать собственный расчёт.</p>"""

    nar = R1["narrative"]

    def para(i, fix=None):
        t = nar[i]
        if fix:
            for a, b in fix:
                t = t.replace(a, b)
        ids = re.findall(r"\[(r\d-\d{3})\]", t)
        t = re.sub(r"\s*\[(r\d-\d{3})\]", "", t)
        return f"<p>{e(t)}{cite(*ids)}</p>"

    theory = f"""<section><h2>Как авиакомпании оценивают маршрут</h2>
{para(0)}{para(2, [("около трёх четвертей разброса", "от 70 до 76 % разброса")])}
<h3>Стимуляция спроса и падение доходности</h3>
{para(3)}{para(4)}
<h3>Частота и конкуренция</h3>
{para(5)}{para(6)}
<h3>Инфраструктура, стимулы и субсидии</h3>
{para(7)}{para(9)}{para(10)}
<h3>Метрики, которые публикуют</h3>
{para(8)}{para(11)}</section>"""

    srcs = "".join(f"<tr><td class=nm><b>{e(s['name'])}</b></td><td>{e(s.get('what') or '')}</td>"
                   f"<td>{e(s.get('granularity') or '')}</td><td>{e(s.get('access') or '')}{cite(*s.get('ids', [])[:4])}</td></tr>"
                   for s in R2["sources"][:10])
    data = f"""<section><h2>Что можно измерить по открытым данным</h2>
{para(1)}
<p>В Индии картина похожая. Регулятор DGCA ежемесячно публикует доли авиакомпаний и пассажиров по парам городов —
внутренние помесячно, международные поквартально, — но без перевозчика на паре и без тарифов: за ценами на части
маршрутов DGCA следит, но ряд не публикует{cite('r2-150', 'r2-001')}. Рынок почти дуополия: IndiGo перевёз в 2025 году
около 64 % внутренних пассажиров{cite('r1-064')}.</p>
<div class="tw"><table class="txt"><tr><th>Источник</th><th>Что даёт</th><th>Детализация</th><th>Доступ</th></tr>
{srcs}</table></div>
<p>Итог для рейтинга: размер рынка и рост открыты в обоих регионах, загрузка кресел на паре — только в Европе (Eurostat
публикует кресла), конкуренция на паре и тарифы — нет. Координируемые аэропорты известны частично: Испания, Великобритания,
Дублин, Варшава, часть Франции, четыре аэропорта Индии; Германия не делит свои 17 аэропортов на уровни
{cite('r2-100', 'r2-137', 'r2-157', 'r2-109')}. Поэтому слоты в рейтинге — флажок, а не штраф.</p>
<p>Ещё одна оговорка: в открытой статистике Европы последний полный год — 2024-й. Мы скачали таблицы Eurostat в конце
октября 2026 года, и у всех 32 стран ряды кончаются декабрём 2024-го; для Индии данные есть по
{RT['india']['last_month']}.</p></section>"""

    method = f"""<section><h2>Как мы считаем рейтинг</h2>
<p>Рейтинг отвечает на один вопрос: где рынок уже большой, растёт и где кресел на нём не хватает. По каждой паре
считаются три опоры, каждая — процентиль внутри своего рынка (100 — лучший), индекс — их среднее.</p>
<ul><li><b>Размер рынка</b> — пассажиры за год в обе стороны (логарифм: разница между 200 тысячами и миллионом
важнее, чем между пятью и шестью миллионами).</li>
<li><b>Рост</b> — в Европе 2024 год к 2023-му; в Индии последние 12 месяцев к предыдущим 12 и 2025 год к 2024-му.</li>
<li><b>Недопредложение</b> — только в Европе: загрузка кресел на паре за год, пассажиры ÷ кресла. Высокая загрузка
значит, что существующие перевозчики не успевают за спросом.</li></ul>
<p class="formula">Индекс<sub>Европа</sub> = ⅓ · ( P[ln пассажиров] + P[рост 2024/23] + P[пассажиры ÷ кресла] )<br>
Индекс<sub>Индия</sub> = ⅓ · ( P[ln пассажиров] + P[рост за 12 мес.] + P[рост 2025/24] )<br>
P[x] = доля пар своего рынка с худшим значением x, 0–100</p>
<div class="tw"><table class="txt"><tr><th>Слагаемое</th><th>Что это</th><th>Источник</th></tr>
<tr><td>ln пассажиров</td><td>пассажиров за год в обе стороны; логарифм — чтобы миллионные пары не затмили остальные</td>
<td>Eurostat PAS_CRD (2024), DGCA (12 мес.)</td></tr>
<tr><td>рост</td><td>пассажиры к прошлому году; в Индии 2025/24 — по месяцам, которые есть в обоих годах (в ряду DGCA нет мая
2024)</td><td>те же ряды</td></tr>
<tr><td>пассажиры ÷ кресла</td><td>загрузка кресел на паре за год — мера недопредложения</td><td>Eurostat ST_PAS</td></tr>
</table></div>
<p>В рейтинг попадают пары от 200 тысяч пассажиров в год в Европе и от 150 тысяч в Индии — меньше этого рынок не
заполнит ежедневный рейс узкофюзеляжного самолёта. Европейские пары дальше 4 500 км — отдельной таблицей: это уже не
A320 и не 737. Пара в Европе — пара аэропортов (так публикует Eurostat; лондонские аэропорты не объединены), в Индии
— пара городов (у Мумбаи и Гоа по два аэропорта, они сложены).</p>
<p class="small">Чего рейтинг не учитывает: тарифы и доходность, число перевозчиков на паре, транзит через хабы (Eurostat
считает людей на борту), сезонность, права на полёты и санкции. Пары с российскими аэропортами — это рейсы турецких и
других неевропейских перевозчиков; европейским они закрыты.</p></section>"""

    eu = f"""<section><h2>Европа: топ пар ближне- и среднемагистральных</h2>
<p>Сверху — пары, где одновременно большой рынок, рост и полные самолёты. {n(len(tr_ru))} из первых 30 — Турция и
Россия; без них верх занимают курортные и столичные пары Испании, Германии и Бенилюкса: {e(label(EU[3]))},
{e(label(EU[4]))}, {e(label(EU[6]))}.</p>
{rmap("europe", EU[:5])}
{table(EU[:10])}
<details><summary>Места 11–50</summary>{table(EU[:50], start=10)}</details>
<h3>Дальние пары (больше 4 500 км)</h3>
{rmap("world", EUL[:5])}
{table(EUL[:10])}
<p class="small">Источник: Eurostat avia_par, 2024 год, пары с полным годом данных; загрузка — пассажиры ÷ кресла.</p></section>"""

    ind = f"""<section><h2>Индия: топ пар</h2>
<p>В Индии верх рейтинга — не Дели — Мумбаи (самая большая пара, но её рост умеренный и оба аэропорта упираются в
слоты), а пары, которые растут быстрее рынка: {e(label(IN[0]))}, {e(label(IN[5]))}, {e(label(IN[6]))}. Рост на 50–70 % за
год на паре часто значит новые рейсы или новый аэропорт — его стоит проверять, а не принимать на веру.</p>
{rmap("india", IN[:5], india=True)}
{table(IN[:10], india=True)}
<details><summary>Места 11–50</summary>{table(IN[:50], india=True, start=10)}</details>
<p class="small">Источник: DGCA, внутренние рейсы по парам городов, последние 12 месяцев по {RT['india']['last_month']};
сборка github.com/Vonter/india-aviation-traffic (ODbL).</p></section>"""

    acs = f"""<section><h2>Каким самолётом летать</h2>
<p>Для каждой пары топа калькулятор посчитал безубыточный тариф — сколько должен заплатить пассажир, чтобы рейс окупился
при загрузке 80 %, — на типах, которые сегодня можно получить новыми: A320neo, A321neo, 737 MAX 8 и 9, A220-300, а для
дальних пар — A350-900 и 787-9. На всех узкофюзеляжных парах дешевле всего на пассажира A321neo: на 6–8 % дешевле
A320neo и 737 MAX 8. Но больший самолёт — это и меньше частот: столбец «рейсов в день» показывает, сколько рейсов A321neo
в каждую сторону заполнит рынок пары при загрузке 80 %. Где выходит меньше двух, разумнее меньший тип с удобным
расписанием — частота сама продаёт билеты (S-кривая выше).</p>
<p>Для пар с российскими аэропортами выбор другой. Западные типы российским перевозчикам недоступны, а из российских в
серии сейчас только Ту-214 — сертифицирован, четыре борта в 2026 году; SJ-100 ждёт сертификации к концу 2026 — началу 2027
года, МС-21 — к концу 2027-го. Посчитать их калькулятор пока не может: у Ту-214 нет опубликованного крейсерского расхода,
у SJ-100 — массы пустого, и он честно отвечает «нельзя».</p>
<h3>Европа</h3>{ac_table(EU[:20])}
<h3>Дальние пары</h3>{ac_table(EUL[:10])}
<h3>Индия</h3>{ac_table(IN[:20], india=True)}
<p class="small">Безубыточный тариф — расчёт калькулятора FlightCostApp для июля, загрузка 80 %, заготовки по умолчанию
(лизинг, экипаж, ТОиР, сборы аэропортов, аэронавигация, топливо по региону). «—» — тип на паре невыполним по массе,
дальности или полосе.</p></section>"""

    concl = f"""<section><h2>Что меняем в калькуляторе</h2>
<ol><li>{mark('on_input')}<b>Выбирая пару, смотрите на рынок, а не только на себестоимость</b>: размер, рост и
загрузку на паре — в рейтинге выше; поток по паре калькулятор уже показывает.</li>
<li>{mark('planned')}<b>Рейтинг пар — в режиме «Сеть»</b>: подсказка «рынок большой и растёт» или «слоты» рядом с
выбором пары.</li>
<li>{mark('planned')}<b>Безубыточный тариф против рыночного</b> — как только появятся тарифы по паре (цены агрегатора уже
есть для части рынков), четвёртая опора «запас по цене».</li>
<li>{mark('planned')}<b>Рейтинг обновляется</b> — Индия каждый квартал, Европа — когда Eurostat опубликует 2025 год.</li></ol>
</section>"""

    cnt = {f: Counter(x.get("status") for k, x in v.items() if not k.startswith("_")) for f, v in VER.items()}
    steps = sum(1 for f in (HERE / "trace").glob("r*.jsonl") for _ in f.open(encoding="utf-8"))
    gaps = "".join(f"<li>{e(g if isinstance(g, str) else (g.get('what') or g.get('claim') or json.dumps(g, ensure_ascii=False)))}</li>"
                   for g in (R1.get("gaps") or [])[:5] + (R2.get("gaps") or [])[:5])
    report = f"""<section><h2>Как проверялось</h2>
<p>Два исследователя вели журналы — {n(steps)} шагов (<code>trace/r1–r2</code>): как оценивают маршрут и какие данные
открыты. Отдельные агенты открыли каждый источник и сверили цитаты (<code>verify/</code>): r1 — найдено дословно
{cnt.get('r1', {}).get('found', 0)}, частично {cnt.get('r1', {}).get('partial', 0)}; r2 —
{cnt.get('r2', {}).get('found', 0) or 'проверка идёт'}. Исправлено по проверке: доля объяснённого разброса гравитационной
модели — 70–76 %, а не три четверти «ровно».</p>
<p>Ряды пар собраны скриптами <code>bin/eurostat_pairs.py</code> и <code>bin/india_pairs.py</code>: пару в Европе публикуют
обе страны — берём среднее; в Индии с 2026 года DGCA пишет города с аэропортом в скобках и переименовал часть городов —
имена сведены, иначе рост пары оказался бы артефактом. Ряд 2023 года по Гоа в DGCA задвоен, поэтому рост к 2023 году не
используем.</p>
<details><summary>Чего не нашлось</summary><ul>{gaps}</ul></details>
{S.html()}</section>"""

    return page(article_title("routes-2026-11"),
                ARTICLE_CSS + "<style>figure.fig{margin:14px 0 6px}figcaption.leg{font-size:12px;color:var(--dim)}</style>"
                + hook + theory + data + method + eu + ind + acs + concl + report)


if __name__ == "__main__":
    out = HERE / out_name("ru")
    out.write_text(build(), encoding="utf-8")
    print(f"{out.relative_to(ROOT)}: {out.stat().st_size // 1024} КБ, источников {len(S.num)}")
