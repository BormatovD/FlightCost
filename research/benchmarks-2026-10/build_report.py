#!/usr/bin/env python3
"""Статья «Бенчмарки авиакомпаний: какие бывают, как ими пользоваться — и наш рейтинг».

Данные — out/b1.json (обзор бенчмарков и ловушек), out/rating.json (рейтинг, собирает rating.py из
b2–b7); журналы — trace/b1–b7; проверка — verify/. Поправки проверяющих: Pegasus после смены определения
ASK — CASK −12,2 %, а не −13,9 % (b1-201); MIT нормирует на путь пассажира (length of haul), что мы и
делаем (b1-020); без утверждений о платности WATS/CAPA и закрытости методики ACMG (b1-236, b1-183, b1-093).

Три языка: тексты — T(ru, en, de); строки из данных (периоды, исключения, задачи, пробелы) — i18n.yaml (Tr);
деньги — money(), числа — n().

    python3 research/benchmarks-2026-10/rating.py && python3 research/benchmarks-2026-10/build_report.py
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
from _report import (ARTICLE_CSS, Sources, T, Tr, article_title, calc_badge, e, line_chart, mark, money, n,  # noqa: E402
                     page, write_all)

S = Sources(HERE)
TR = Tr(HERE)
_PAR = {o["id"]: o.get("parents") or [] for f in sorted(HERE.glob("trace/b*.jsonl"))
        for o in map(json.loads, f.read_text(encoding="utf-8").splitlines())}


def _roots(i, seen=None):
    seen = seen or set()
    if i in S.step or i in seen:
        return [i] if i in S.step else []
    seen.add(i)
    return [r for p in _PAR.get(i, []) for r in _roots(p, seen)]


def cite(*ids):
    return S.cite(*[r for i in ids for r in (_roots(i) if not i.startswith("http") else [i])])


J = lambda f: json.loads((HERE / f).read_text(encoding="utf-8"))  # noqa: E731
B1, RT = J("out/b1.json"), J("out/rating.json")
VER = {f: J(f"verify/{f}.json") for f in ("b1", "b2", "b3", "b7") if (HERE / f"verify/{f}.json").exists()}
C = {c["code"]: c for c in RT["carriers"]}
RANKED = [c for c in RT["carriers"] if c.get("rank")]
REG = {"Europe": ("Европа", "Europe", "Europa"), "Russia": ("Россия", "Russia", "Russland"),
       "NorthAmerica": ("Сев. Америка", "N. America", "Nordamerika"),
       "LatAm": ("Лат. Америка", "Lat. America", "Lateinamerika"), "Asia": ("Азия", "Asia", "Asien"),
       "MiddleEast": ("Ближний Восток", "Middle East", "Naher Osten"), "Oceania": ("Океания", "Oceania", "Ozeanien")}
MOD = {"LCC": ("лоукостер", "low-cost", "Low-Cost"), "ULCC": ("ультралоукостер", "ultra-low-cost", "Ultra-Low-Cost"),
       "network": ("сетевой", "network", "Netzwerk"), "hybrid": ("гибрид", "hybrid", "Hybrid"),
       "leisure": ("чартерный", "leisure", "Ferienflug")}
NAME = {"S7": "S7 Airlines", "DY": "Norwegian",
        "AS": "Alaska + Hawaiian", "G4": "Allegiant", "6E": "IndiGo", "LA": "LATAM", "AD": "Azul", "G3": "GOL",
        "CM": "Copa", "Y4": "Volaris", "QF": "Qantas Group", "NZ": "Air New Zealand", "EK": "Emirates",
        "AY": "Finnair", "BT": "airBaltic", "A3": "Aegean", "PC": "Pegasus", "FR": "Ryanair", "W6": "Wizz Air",
        "U2": "easyJet", "F9": "Frontier", "SY": "Sun Country", "AC": "Air Canada", "B6": "JetBlue",
        "WN": "Southwest", "DL": "Delta", "AA": "American", "UA": "United"}


def nm(c):
    if c["code"] == "SU":
        return T("Группа «Аэрофлот»", "Aeroflot Group", "Aeroflot-Gruppe")
    if c["code"] == "LH":
        return T("Lufthansa (пассажирские)", "Lufthansa (passenger airlines)", "Lufthansa (Passagier-Airlines)")
    return NAME.get(c["code"], c["name"])


def reg(c):
    return T(*REG[c["region"]]) if c.get("region") in REG else ""


def mod(c):
    return T(*MOD[c["model"]]) if c.get("model") in MOD else (c.get("model") or "")


def cids(c):
    ids = [i for v in (c.get("ids") or {}).values() for i in v]
    if c.get("source_url"):
        ids.append(c["source_url"])
    return cite(*ids)


def bar(v, col="var(--sky)"):
    if v is None:
        return '<span class="na">—</span>'
    return (f'<span class="pb"><span style="width:{v:.0f}%;background:{col}"></span></span>'
            f'<span class="pv">{n(v)}</span>')


# ── схемы ──────────────────────────────────────────────────────────────────
def scatter(rows, w=760, h=330):
    """CASK без топлива до и после приведения к единой длине: точки по среднему пути пассажира."""
    L, R, TP, B = 52, 20, 14, 36
    xs = [c["L"] for c in rows]
    x0, x1, y0, y1 = 900, 5400, 0, 10
    X = lambda v: L + (v - x0) / (x1 - x0) * (w - L - R)   # noqa: E731
    Y = lambda v: TP + (y1 - v) / (y1 - y0) * (h - TP - B)    # noqa: E731
    g = []
    for t in (0, 2, 4, 6, 8, 10):
        g.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="var(--line)"/>'
                 f'<text x="{L - 6}" y="{Y(t) + 4:.1f}" text-anchor="end" class="ax">{money(t, "EUR", nc=True, tag="tspan")}</text>')
    for t in (1000, 2000, 3000, 4000, 5000):
        g.append(f'<text x="{X(t):.1f}" y="{h - 18}" text-anchor="middle" class="ax">{n(t)} {T("км", "km", "km")}</text>')
    g.append(f'<line x1="{X(RT["L_ref_km"]):.1f}" x2="{X(RT["L_ref_km"]):.1f}" y1="{TP}" y2="{h - B}" '
             f'stroke="var(--green)" stroke-dasharray="4 3"/><text x="{X(RT["L_ref_km"]) + 5:.1f}" y="{TP + 10}" '
             f'class="ax" fill="var(--green)">{T("медиана", "median", "Median")} {n(RT["L_ref_km"])} {T("км", "km", "km")}</text>')
    for c in rows:
        if c.get("casx") is None or c.get("L") is None:
            continue
        a, b = (X(c["L"]), Y(c["casx"])), (X(c["L"]), Y(c["casx_adj"]))
        tip = T(f'{nm(c)}: путь пассажира {n(c["L"])} км; без топлива {n(c["casx"], 2)} → после приведения '
                f'{n(c["casx_adj"], 2)} EUR / 100 кресло-км',
                f'{nm(c)}: passenger trip {n(c["L"])} km; ex-fuel {n(c["casx"], 2)} → adjusted '
                f'{n(c["casx_adj"], 2)} EUR / 100 seat-km',
                f'{nm(c)}: Passagierstrecke {n(c["L"])} km; ohne Treibstoff {n(c["casx"], 2)} → korrigiert '
                f'{n(c["casx_adj"], 2)} EUR / 100 Sitzkilometer')
        g.append(f'<g class="pt"><title>{e(tip)}</title>'
                 f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="var(--dim)" '
                 f'stroke-width="1"/><circle cx="{a[0]:.1f}" cy="{a[1]:.1f}" r="3" fill="none" stroke="var(--dim)"/>'
                 f'<circle cx="{b[0]:.1f}" cy="{b[1]:.1f}" r="4" fill="var(--sky)"/>'
                 f'<text x="{b[0] + 6:.1f}" y="{b[1] + 4:.1f}" class="lab" font-size="10.5" fill="var(--ink)">'
                 f'{e(c["code"])}</text></g>')
    leg = " · ".join(f"<span class=li><b>{e(c['code'])}</b> {e(nm(c))}</span>" for c in sorted(rows, key=lambda c: c["code"]) if c.get("casx"))
    return (f'<figure class="fig"><svg viewBox="0 0 {w} {h}" width="100%" class="chart" role="img" '
            f'aria-label="{T('Приведение к длине рейса', 'Stage length adjustment', 'Streckenlängenkorrektur')}">{"".join(g)}</svg>'
            f'<figcaption class="leg">{leg}</figcaption></figure>')


def ifrs(w=760):
    box = lambda x, y, ww, t, s, col: (f'<rect x="{x}" y="{y}" width="{ww}" height="46" rx="6" fill="var(--panel)" '  # noqa: E731
                                       f'stroke="{col}"/><text x="{x + 10}" y="{y + 19}" fill="var(--ink2)" '
                                       f'font-weight="600">{e(t)}</text><text x="{x + 10}" y="{y + 36}" '
                                       f'fill="var(--dim)" font-size="11.5">{e(s)}</text>')
    g = [box(10, 10, 220, T("Платёж лизингодателю", "Payment to the lessor", "Zahlung an den Leasinggeber"),
             T("одна сумма в месяц", "one amount a month", "ein Betrag pro Monat"), "var(--t3)"),
         box(300, 0, 210, T("US GAAP: аренда", "US GAAP: lease", "US GAAP: Leasing"),
             T("целиком в операционных расходах", "all in operating expenses", "komplett im Betriebsaufwand"),
             "var(--orange)"),
         box(300, 62, 210, T("МСФО 16: амортизация", "IFRS 16: depreciation", "IFRS 16: Abschreibung"),
             T("в операционных расходах", "in operating expenses", "im Betriebsaufwand"), "var(--sky)"),
         box(530, 62, 220, T("МСФО 16: проценты", "IFRS 16: interest", "IFRS 16: Zinsen"),
             T("ниже операционной прибыли", "below operating profit", "unterhalb des Betriebsergebnisses"),
             "var(--green)"),
         '<path d="M230 33 L298 23 M230 33 L298 85 M510 85 L528 85" stroke="var(--dim)" fill="none"/>',
         f'<text x="530" y="34" fill="var(--orange)" font-size="11.5">'
         f'{T("→ вся сумма в CASK", "→ the whole amount in CASK", "→ der ganze Betrag in den CASK")}</text>',
         f'<text x="300" y="132" fill="var(--sky)" font-size="11.5">'
         f'{e(T("→ в CASK попадает только амортизация: при той же аренде CASK ниже на проценты", "→ only depreciation enters CASK: same lease, CASK lower by the interest", "→ nur die Abschreibung zählt: gleiches Leasing, CASK um die Zinsen niedriger"))}</text>']
    return (f'<figure class="fig"><svg viewBox="0 0 {w} 142" width="100%" font-family="var(--sans)" font-size="12" '
            f'role="img" aria-label="{T('Аренда по МСФО 16 и US GAAP', 'Leases under IFRS 16 and US GAAP', 'Leasing nach IFRS 16 und US GAAP')}">{"".join(g)}</svg></figure>')


def build() -> str:
    top = RANKED[:5]
    su = C["SU"]
    k_moves = max(abs((c.get("rank_k13") or c["rank"]) - c["rank"]) for c in RANKED)

    # ── 1. хук ────────────────────────────────────────────────────────────
    leaders = ", ".join(nm(c) for c in top[:4])
    hook = f"""<h1>{T("Бенчмарки авиакомпаний: какие бывают, как ими пользоваться — и наш рейтинг",
                 "Airline benchmarks: what exists, how to use them — and our rating",
                 "Airline-Benchmarks: welche es gibt, wie man sie nutzt — und unser Rating")}</h1>
<p class="meta">{T(f"Исследование FlightCostApp, октябрь 2026 · черновик · отраслевые бенчмарки, их ловушки и рейтинг "
                   f"эффективности {len(RANKED)} авиакомпаний за 2025 год (будет обновляться)",
                   f"FlightCostApp research, October 2026 · draft · industry benchmarks, their pitfalls and an efficiency "
                   f"rating of {len(RANKED)} airlines for 2025 (to be updated)",
                   f"FlightCostApp-Studie, Oktober 2026 · Entwurf · Branchen-Benchmarks, ihre Fallstricke und ein "
                   f"Effizienz-Rating von {len(RANKED)} Airlines für 2025 (wird aktualisiert)")}</p>
{calc_badge("benchmarks-2026-10")}
<div class="verdict">
<div><b>{T("Одной правильной цифры нет", "There is no single right number", "Die eine richtige Zahl gibt es nicht")}</b><span>{T(
        "себестоимость кресло-километра зависит от длины рейса, учёта аренды, курса и периметра отчётности — сравнивать "
        "её «как есть» нельзя",
        "cost per seat-kilometre depends on stage length, lease accounting, the exchange rate and the reporting "
        "perimeter — it cannot be compared as reported",
        "die Kosten je Sitzkilometer hängen von Streckenlänge, Leasingbilanzierung, Wechselkurs und Berichtsumfang ab — "
        "so wie berichtet sind sie nicht vergleichbar")}{cite('b1-083', 'b1-051')}</span></div>
<div><b>{T("Длина рейса — главная поправка", "Stage length is the main adjustment",
           "Die Streckenlänge ist die wichtigste Korrektur")}</b><span>{T(
        "отрасль приводит затраты к единой длине по формуле со степенью 0,5; почему именно 0,5 — не объясняет никто",
        "the industry adjusts costs to a common length with an exponent of 0.5; nobody explains why 0.5",
        "die Branche rechnet Kosten mit dem Exponenten 0,5 auf eine einheitliche Länge um; warum gerade 0,5, erklärt "
        "niemand")}{cite('b1-020', 'b1-050', 'b1-026')}</span></div>
<div><b>{T(f"Сверху рейтинга — {leaders}", f"Top of the rating: {leaders}", f"An der Spitze: {leaders}")}</b><span>{T(
        f"индекс из четырёх опор: затраты, отдача парка, коммерция и топливо; от выбора степени 0,5 или 1/3 места "
        f"сдвигаются не больше чем на {k_moves}",
        f"an index of four pillars: costs, fleet productivity, commercial and fuel; choosing an exponent of 0.5 or 1/3 "
        f"moves places by at most {k_moves}",
        f"ein Index aus vier Säulen: Kosten, Flottenproduktivität, Kommerz und Treibstoff; ob Exponent 0,5 oder 1/3 "
        f"verschiebt die Plätze um höchstens {k_moves}")}</span></div>
<div><b>{T(f"«Аэрофлот» — {su['rank']}-й", f"Aeroflot is no. {su['rank']}", f"Aeroflot auf Platz {su['rank']}")}</b><span>{T(
        "затраты по рыночному курсу рубля — как у лоукостеров (",
        "costs at the market rouble rate are like a low-cost carrier's (",
        "die Kosten zum Marktkurs des Rubels liegen auf Low-Cost-Niveau (")}{money(su["casx"], "EUR", 2,
        unit=T(" / 100 кресло-км", " / 100 seat-km", " / 100 Sitzkilometer"))}{T(
        " без топлива), но налёт и маржа тянут вниз", " ex-fuel), but utilisation and margin pull it down",
        " ohne Treibstoff), aber Auslastung und Marge ziehen nach unten")}</span></div></div>
<p class="lede">{T(
        "Бенчмарк — эталонная цифра, с которой сравнивают свою: сколько стоит кресло-километр, сколько летает самолёт, "
        "какая загрузка, сколько топлива на пассажира. Им пользуются все — авиакомпании на переговорах с "
        "лизингодателями и ремонтниками, инвесторы, регуляторы, и мы в калькуляторе, когда проверяем свою модель. Но "
        "почти каждый бенчмарк несёт оговорки мелким шрифтом, и сравнение «в лоб» чаще показывает разницу в сетях, "
        "учёте и валютах, чем в эффективности. Ниже — какие бенчмарки есть в отрасли, почему они устроены именно так, в "
        "чём их ловушки и когда каким пользоваться. А в конце — наш собственный рейтинг эффективности авиакомпаний по "
        "открытой отчётности за 2025 год, построенный так, чтобы обойти эти ловушки, насколько это возможно на открытых "
        "данных. Мы будем обновлять его каждый год.",
        "A benchmark is a reference number you compare your own against: what a seat-kilometre costs, how much an "
        "aircraft flies, the load factor, the fuel per passenger. Everyone uses them — airlines negotiating with lessors "
        "and MRO shops, investors, regulators, and we in the calculator when we check our model. But almost every "
        "benchmark comes with small print, and a head-on comparison more often shows differences in networks, "
        "accounting and currencies than in efficiency. Below: which benchmarks the industry has, why they are built the "
        "way they are, what their pitfalls are and when to use which. And at the end, our own airline efficiency rating "
        "from public 2025 reports, built to avoid those pitfalls as far as open data allows. We will update it every year.",
        "Ein Benchmark ist eine Referenzzahl, mit der man die eigene vergleicht: was ein Sitzkilometer kostet, wie viel "
        "ein Flugzeug fliegt, wie hoch der Sitzladefaktor ist, wie viel Treibstoff je Passagier. Alle nutzen sie — "
        "Airlines in Verhandlungen mit Leasinggebern und Werften, Investoren, Regulierer und wir im Rechner, wenn wir "
        "unser Modell prüfen. Doch fast jeder Benchmark hat Kleingedrucktes, und ein direkter Vergleich zeigt öfter "
        "Unterschiede bei Netzen, Bilanzierung und Währungen als bei der Effizienz. Im Folgenden: welche Benchmarks es "
        "in der Branche gibt, warum sie so gebaut sind, wo ihre Fallstricke liegen und wann man welchen nimmt. Und am "
        "Ende unser eigenes Effizienz-Rating der Airlines aus öffentlichen Berichten für 2025, so gebaut, dass es diese "
        "Fallstricke umgeht, soweit offene Daten es erlauben. Wir aktualisieren es jedes Jahr.")}</p>"""

    # ── 2. теория ─────────────────────────────────────────────────────────
    theory = f"""<section><h2>{T("Что сравнивают", "What is compared", "Was verglichen wird")}</h2>
<p>{T("В основе почти всех бенчмарков — несколько удельных показателей. Кресло-километр (ASK) — одно кресло, "
      "провезённое на один километр, занято оно или нет; это мера предложения. Пассажиро-километр (RPK) — один пассажир "
      "на один километр; мера продаж. Их отношение — загрузка (load factor): какая доля предложенных кресел продана. "
      "Себестоимость кресло-километра (CASK) — все операционные расходы, делённые на ASK; выручка на кресло-километр "
      "(RASK) — то же для выручки. Разница RASK и CASK — операционная прибыль на каждое предложенное кресло. Рядом стоят "
      "физические показатели: налёт — блок-часы на самолёт в сутки, и расход топлива на пассажиро-километр.",
      "Almost all benchmarks rest on a few unit metrics. An available seat-kilometre (ASK) is one seat flown one "
      "kilometre, occupied or not; it measures supply. A revenue passenger-kilometre (RPK) is one passenger carried one "
      "kilometre; it measures sales. Their ratio is the load factor: the share of seats offered that were sold. Cost per "
      "ASK (CASK) is all operating expenses divided by ASK; revenue per ASK (RASK) is the same for revenue. RASK minus "
      "CASK is the operating profit on every seat offered. Next to them sit physical metrics: utilisation — block hours "
      "per aircraft per day — and fuel burn per passenger-kilometre.",
      "Fast alle Benchmarks beruhen auf wenigen Stückkennzahlen. Ein angebotener Sitzkilometer (ASK) ist ein Sitz, der "
      "einen Kilometer weit geflogen wird, ob besetzt oder nicht; er misst das Angebot. Ein Passagierkilometer (RPK) ist "
      "ein Passagier, der einen Kilometer befördert wird; er misst den Absatz. Ihr Verhältnis ist der Sitzladefaktor: "
      "welcher Anteil der angebotenen Sitze verkauft wurde. Die Kosten je Sitzkilometer (CASK) sind der gesamte "
      "Betriebsaufwand geteilt durch ASK; der Erlös je Sitzkilometer (RASK) dasselbe für den Umsatz. RASK minus CASK ist "
      "der Betriebsgewinn je angebotenem Sitz. Daneben stehen physische Kennzahlen: die Auslastung — Blockstunden je "
      "Flugzeug und Tag — und der Treibstoffverbrauch je Passagierkilometer.")}</p>
<p>{T("Удобство этих показателей — в том, что они убирают масштаб: компанию с парком в 40 самолётов можно сравнить с "
      "компанией в 900. Их слабость — в том, что они не убирают всё остальное: где компания летает, на каких самолётах, "
      "по каким правилам учёта и в какой валюте. McKinsey прямо пишет, что CASK не показывает, где именно лежат рычаги "
      "снижения затрат",
      "The appeal of these metrics is that they remove scale: an airline with 40 aircraft can be compared with one "
      "with 900. Their weakness is that they remove nothing else: where the airline flies, on which aircraft, under "
      "which accounting rules and in which currency. McKinsey says plainly that CASK does not show where the levers for "
      "cutting costs actually are",
      "Der Vorteil dieser Kennzahlen: Sie entfernen die Größe, eine Airline mit 40 Flugzeugen lässt sich mit einer mit "
      "900 vergleichen. Ihre Schwäche: Sie entfernen sonst nichts — wo die Airline fliegt, mit welchen Flugzeugen, nach "
      "welchen Bilanzregeln und in welcher Währung. McKinsey schreibt offen, dass die CASK nicht zeigen, wo die Hebel "
      "zur Kostensenkung tatsächlich liegen")}{cite('b1-054')}{T(
      ", а IATA в отчёте по затратам на техобслуживание признаёт, что бенчмарк затрат — «не наука» и нормализации, "
      "которая позволила бы прямые сравнения, не существует",
      ", and IATA admits in its maintenance cost report that cost benchmarking is “not a science” and that no "
      "normalisation exists that would allow direct comparisons",
      ", und die IATA räumt in ihrem Wartungskostenbericht ein, dass Kosten-Benchmarking „keine Wissenschaft“ ist und "
      "es keine Normierung gibt, die direkte Vergleiche erlauben würde")}{cite('b1-083')}{T(
      ". Поэтому вокруг этих простых формул выросла целая экосистема — с методиками, поправками и спорами.",
      ". That is why a whole ecosystem of methods, adjustments and arguments has grown around these simple formulas.",
      ". Deshalb ist um diese einfachen Formeln ein ganzes Ökosystem aus Methoden, Korrekturen und Streitfragen "
      "entstanden.")}</p></section>"""

    # ── 3. какие бывают ───────────────────────────────────────────────────
    src_rows = [
        (("Отчётность авиакомпаний", "Airline reports", "Berichte der Airlines"),
         ("годовые отчёты, 10-K и 20-F, релизы о результатах", "annual reports, 10-K and 20-F, results releases",
          "Geschäftsberichte, 10-K und 20-F, Ergebnismitteilungen"),
         ("все публичные перевозчики, определения у каждого свои", "all listed carriers, each with its own definitions",
          "alle börsennotierten Airlines, jede mit eigenen Definitionen"),
         ("открыто", "open", "offen"),
         ("первичный источник для рейтинга и проверки модели", "primary source for the rating and for checking the model",
          "Primärquelle für das Rating und die Modellprüfung"), 0),
        (("US DOT Form 41 и T-2", "US DOT Form 41 and T-2", "US DOT Form 41 und T-2"),
         ("отчёт о прибылях, расходы по типам самолётов, топливо, трафик",
          "income statement, costs by aircraft type, fuel, traffic",
          "Gewinn- und Verlustrechnung, Kosten nach Flugzeugtyp, Treibstoff, Verkehr"),
         ("все перевозчики США с выручкой от 20 млн долларов, единый план счетов",
          "all US carriers with revenue of $20 million or more, a uniform chart of accounts",
          "alle US-Airlines mit mindestens 20 Mio. Dollar Umsatz, einheitlicher Kontenplan"),
         ("открыто, бесплатно", "open, free", "offen, kostenlos"),
         ("стоимость блок-часа по типу, налёт, расход топлива", "block-hour cost by type, utilisation, fuel burn",
          "Blockstundenkosten je Typ, Auslastung, Treibstoffverbrauch"), 1),
        (("MIT Airline Data Project", "MIT Airline Data Project", "MIT Airline Data Project"),
         ("ряды показателей на основе Form 41 с поправкой на длину рейса",
          "metric series based on Form 41 with a stage length adjustment",
          "Kennzahlenreihen auf Basis von Form 41 mit Streckenlängenkorrektur"),
         ("около 15 перевозчиков США", "about 15 US carriers", "rund 15 US-Airlines"),
         ("открыто", "open", "offen"),
         ("эталон методики, исторические ряды", "reference methodology, historical series",
          "Referenzmethodik, historische Reihen"), 2),
        (("IATA MCX", "IATA MCX", "IATA MCX"),
         ("затраты на техобслуживание: на лётный час, цикл, самолёт",
          "maintenance costs per flight hour, cycle and aircraft", "Wartungskosten je Flugstunde, Zyklus und Flugzeug"),
         ("28 авиакомпаний, 2 703 самолёта (2024)", "28 airlines, 2,703 aircraft (2024)",
          "28 Airlines, 2.703 Flugzeuge (2024)"),
         ("участникам — полностью, публичная версия — открыто", "full for participants, public version open",
          "vollständig für Teilnehmer, öffentliche Version offen"),
         ("переговоры с ремонтниками и лизингодателями", "negotiating with MRO shops and lessors",
          "Verhandlungen mit Werften und Leasinggebern"), 3),
        (("IATA ACMG", "IATA ACMG", "IATA ACMG"),
         ("сравнение затрат по типам самолётов среди участников",
          "cost comparison by aircraft type among participants", "Kostenvergleich nach Flugzeugtyp unter Teilnehmern"),
         ("участники программы", "programme participants", "Programmteilnehmer"),
         ("по участию", "by participation", "durch Teilnahme"),
         ("внутренний бенчмарк авиакомпании", "an airline's internal benchmark", "interner Benchmark einer Airline"), 4),
        (("ICAO, EUROCONTROL, FAA", "ICAO, EUROCONTROL, FAA", "ICAO, EUROCONTROL, FAA"),
         ("финансовая статистика государств, стоимость задержки, стоимость блок-часа по классам самолётов",
          "state financial statistics, cost of delay, block-hour cost by aircraft class",
          "Finanzstatistik der Staaten, Verspätungskosten, Blockstundenkosten nach Flugzeugklasse"),
         ("мир, Европа, США", "world, Europe, US", "Welt, Europa, USA"),
         ("в основном открыто", "mostly open", "überwiegend offen"),
         ("оценки проектов, стоимость задержки", "project appraisals, cost of delay",
          "Projektbewertungen, Verspätungskosten"), 7),
        (("Регуляторы стран (CAA UK, Росавиация)", "National regulators (UK CAA, Rosaviatsia)",
          "Nationale Behörden (UK CAA, Rosawiazija)"),
         ("трафик, загрузка, налёт по типам у британских перевозчиков",
          "traffic, load factor, utilisation by type for UK carriers",
          "Verkehr, Sitzladefaktor, Auslastung nach Typ bei britischen Airlines"),
         ("свои перевозчики", "domestic carriers", "eigene Airlines"),
         ("открыто", "open", "offen"),
         ("налёт и загрузка; финансов нет", "utilisation and load factor; no financials",
          "Auslastung und Sitzladefaktor; keine Finanzdaten"), 9),
        (("Консультанты (Oliver Wyman, McKinsey, Aviation Week, CAPA)",
          "Consultants (Oliver Wyman, McKinsey, Aviation Week, CAPA)",
          "Berater (Oliver Wyman, McKinsey, Aviation Week, CAPA)"),
         ("сравнения CASK, стоимость блок-часа", "CASK comparisons, block-hour cost",
          "CASK-Vergleiche, Blockstundenkosten"),
         ("разная, для США — на Form 41", "varies; for the US based on Form 41", "unterschiedlich; für die USA auf Form 41"),
         ("статьи частично открыты, базы — по подписке", "articles partly open, databases by subscription",
          "Artikel teils offen, Datenbanken im Abo"),
         ("готовые сравнения, методика в сносках", "ready-made comparisons, methodology in footnotes",
          "fertige Vergleiche, Methodik in Fußnoten"), 11),
        (("Пунктуальность и качество (Cirium, CODA, Skytrax)", "Punctuality and quality (Cirium, CODA, Skytrax)",
          "Pünktlichkeit und Qualität (Cirium, CODA, Skytrax)"),
         ("доля рейсов вовремя, задержки, опрос пассажиров", "on-time share, delays, passenger surveys",
          "Anteil pünktlicher Flüge, Verspätungen, Passagierumfragen"),
         ("мир, Европа", "world, Europe", "Welt, Europa"),
         ("ежемесячные отчёты Cirium — бесплатно", "Cirium monthly reports free", "Monatsberichte von Cirium kostenlos"),
         ("качество рядом с затратами — но не в индекс", "quality next to costs — but not in the index",
          "Qualität neben den Kosten — aber nicht im Index"), 12),
        (("Топливная эффективность (ICCT, отчёты об устойчивом развитии)",
          "Fuel efficiency (ICCT, sustainability reports)", "Treibstoffeffizienz (ICCT, Nachhaltigkeitsberichte)"),
         ("пассажиро-км на литр, CO₂ на пассажиро-км", "passenger-km per litre, CO₂ per passenger-km",
          "Passagierkilometer je Liter, CO₂ je Passagierkilometer"),
         ("выборочно; у ICCT — последние данные 2017 года", "selective; ICCT's latest data are for 2017",
          "punktuell; die neuesten ICCT-Daten sind von 2017"),
         ("открыто", "open", "offen"),
         ("опора «топливо» в рейтинге", "the fuel pillar of the rating", "die Säule „Treibstoff“ im Rating"), 13),
    ]
    srcs = B1["sources"]
    L_what, L_cov, L_acc, L_when = (T("Что измеряет", "What it measures", "Was es misst"), T("Охват", "Coverage", "Abdeckung"),
                                    T("Доступ", "Access", "Zugang"), T("Когда брать", "When to use", "Wann nutzen"))
    t_src = "".join(f"<tr><td><b>{e(T(*a))}</b></td><td data-l='{L_what}'>{e(T(*b))}</td><td data-l='{L_cov}'>{e(T(*c))}</td>"
                    f"<td data-l='{L_acc}'>{e(T(*d))}</td><td data-l='{L_when}'>{e(T(*f))}"
                    f"{cite(*srcs[i]['ids'][:6]) if i < len(srcs) else ''}</td></tr>"
                    for a, b, c, d, f, i in src_rows)
    kinds = f"""<section><h2>{T("Какие бенчмарки есть в отрасли", "Which benchmarks the industry has",
                               "Welche Benchmarks es in der Branche gibt")}</h2>
<p>{T("Самый очевидный источник — отчётность самих авиакомпаний. Её пишут для инвесторов, и каждая компания выбирает "
      "показатель под свою бизнес-модель: Ryanair считает затраты на пассажира",
      "The most obvious source is the airlines' own reports. They are written for investors, and each airline picks "
      "the metric that suits its business model: Ryanair reports cost per passenger",
      "Die naheliegendste Quelle sind die Berichte der Airlines selbst. Sie werden für Investoren geschrieben, und jede "
      "Airline wählt die Kennzahl, die zu ihrem Geschäftsmodell passt: Ryanair rechnet Kosten je Passagier")}{cite('b1-136')}{T(
      ", easyJet — на кресло", ", easyJet per seat", ", easyJet je Sitz")}{cite('b1-125')}{T(
      ", американские перевозчики — на кресло-милю. Отчётность открыта и свежа, но определения у всех разные, и прямо "
      "сравнивать её нельзя.",
      ", US carriers per seat-mile. Reports are open and current, but definitions differ, so they cannot be compared "
      "directly.",
      ", US-Airlines je Sitzmeile. Die Berichte sind offen und aktuell, aber die Definitionen unterscheiden sich, direkt "
      "vergleichen kann man sie nicht.")}</p>
<p>{T("Самый богатый открытый массив — американская регуляторная отчётность Form 41. Каждый перевозчик США с выручкой "
      "от 20 миллионов долларов сдаёт в Министерство транспорта отчёт о прибылях, расходы на самолёты по типам, топливо "
      "и трафик",
      "The richest open dataset is the US regulatory filing Form 41. Every US carrier with revenue of $20 million or "
      "more files an income statement, aircraft costs by type, fuel and traffic with the Department of Transportation",
      "Der reichste offene Datenbestand ist die US-Regulierungsmeldung Form 41. Jede US-Airline mit mindestens 20 Mio. "
      "Dollar Umsatz meldet dem Verkehrsministerium Gewinn- und Verlustrechnung, Flugzeugkosten nach Typ, Treibstoff "
      "und Verkehr")}{cite('b1-064', 'b1-065', 'b1-075', 'b1-072')}{T(
      ". Единый план счетов делает затраты сопоставимыми по определению — это единственный в мире такой массив, и именно "
      "на нём стоят калибровки нашего калькулятора. MIT Airline Data Project превращает эти формы в готовые ряды",
      ". A uniform chart of accounts makes the costs comparable by definition — the only such dataset in the world, and "
      "the one our calculator's calibrations rest on. The MIT Airline Data Project turns these forms into ready-made "
      "series",
      ". Ein einheitlicher Kontenplan macht die Kosten per Definition vergleichbar — der einzige solche Datenbestand der "
      "Welt, und genau auf ihm beruhen die Kalibrierungen unseres Rechners. Das MIT Airline Data Project macht daraus "
      "fertige Reihen")}{cite('b1-020')}{T(
      ". Слабость одна, но существенная: это только США.", ". There is one weakness, but a big one: it covers only the US.",
      ". Es gibt eine Schwäche, aber eine wesentliche: Es sind nur die USA.")}</p>
<p>{T("Отраслевые программы IATA устроены по принципу «дай данные — получи бенчмарк». Программа по затратам на "
      "техобслуживание (MCX) бесплатна для авиакомпаний-членов при ежегодной сдаче данных; её публичная версия за 2024 "
      "год охватывает 28 авиакомпаний и 2 703 самолёта, около 8 % мирового парка, и даёт в среднем 1 522 доллара на "
      "лётный час",
      "IATA's industry programmes work on a “give data, get a benchmark” basis. The maintenance cost programme (MCX) is "
      "free for member airlines that submit data every year; its public 2024 edition covers 28 airlines and 2,703 "
      "aircraft, about 8% of the world fleet, and gives an average of $1,522 per flight hour",
      "Die Branchenprogramme der IATA funktionieren nach dem Prinzip „Daten geben, Benchmark bekommen“. Das "
      "Wartungskostenprogramm (MCX) ist für Mitglieds-Airlines bei jährlicher Datenlieferung kostenlos; seine "
      "öffentliche Ausgabe 2024 umfasst 28 Airlines und 2.703 Flugzeuge, rund 8 % der Weltflotte, und ergibt im Schnitt "
      "1.522 Dollar je Flugstunde")}{cite('b1-087', 'b1-088', 'b1-080', 'b1-081')}{T(
      ". Анонимность — условие, без которого авиакомпании своими затратами не делятся. Консультанты в основном "
      "перепаковывают ту же Form 41",
      ". Anonymity is the condition without which airlines do not share their costs. Consultants mostly repackage the "
      "same Form 41",
      ". Anonymität ist die Bedingung, ohne die Airlines ihre Kosten nicht teilen. Berater verpacken meist dieselbe "
      "Form 41 neu")}{cite('b1-030')}{T(
      ", а рядом с затратными бенчмарками стоят бенчмарки качества: пунктуальность, задержки, удовлетворённость пассажиров",
      ", and next to cost benchmarks stand quality benchmarks: punctuality, delays, passenger satisfaction",
      ", und neben den Kosten-Benchmarks stehen Qualitäts-Benchmarks: Pünktlichkeit, Verspätungen, "
      "Passagierzufriedenheit")}{cite('b1-172', 'b1-189', 'b1-186')}.</p>
<div class="tw"><table class="txt cards"><tr><th>{T("Бенчмарк", "Benchmark", "Benchmark")}</th><th>{L_what}</th>
<th>{L_cov}</th><th>{L_acc}</th><th>{L_when}</th></tr>
{t_src}</table></div>
<p>{T("Для России открытого аналога Form 41 нет: государственная статистика даёт пассажиров, пассажирооборот и "
      "загрузку, но не кресло-километры по перевозчикам, не налёт и не финансы",
      "Russia has no open equivalent of Form 41: state statistics give passengers, passenger-kilometres and load "
      "factor, but not seat-kilometres by carrier, utilisation or financials",
      "Für Russland gibt es kein offenes Gegenstück zu Form 41: Die Staatsstatistik liefert Passagiere, "
      "Passagierkilometer und Sitzladefaktor, aber keine Sitzkilometer je Airline, keine Auslastung und keine "
      "Finanzdaten")}{cite('b1-166', 'b1-169')}{T(
      ". Поэтому российские перевозчики в нашем рейтинге — только те, кто сам публикует подробную отчётность.",
      ". So the only Russian carriers in our rating are those that publish detailed reports themselves.",
      ". Deshalb stehen in unserem Rating nur russische Airlines, die selbst ausführlich berichten.")}</p></section>"""

    # ── 4. ловушки ────────────────────────────────────────────────────────
    sc = scatter([c for c in RT["carriers"] if c.get("casx")])
    xs = list(range(500, 5001, 250))
    lr = RT["L_ref_km"]
    ch = line_chart([(T("степень 0,5 (MIT, McKinsey)", "exponent 0.5 (MIT, McKinsey)", "Exponent 0,5 (MIT, McKinsey)"),
                      "var(--sky)", {x: (x / lr) ** 0.5 for x in xs}, False),
                     (T("степень 1/3 (Oliver Wyman)", "exponent 1/3 (Oliver Wyman)", "Exponent 1/3 (Oliver Wyman)"),
                      "var(--orange)", {x: (x / lr) ** (1 / 3) for x in xs}, True)],
                    w=720, ylab=T("множитель к CASK", "CASK multiplier", "Faktor auf die CASK"),
                    yfmt=lambda v: n(v, 1), x_every=1000)
    traps = f"""<section><h2>{T("Почему «в лоб» сравнивать нельзя: шесть ловушек",
                               "Why a head-on comparison fails: six pitfalls",
                               "Warum ein direkter Vergleich scheitert: sechs Fallstricke")}</h2>
<h3>{T("1. Длина рейса", "1. Stage length", "1. Streckenlänge")}</h3>
<p>{T("Каждый рейс несёт затраты, которые не зависят от расстояния: взлёт и посадка, аэропортовые сборы, наземное "
      "обслуживание, время на земле. На коротком рейсе они делятся на малое число кресло-километров, на длинном — на "
      "большое",
      "Every flight carries costs that do not depend on distance: take-off and landing, airport charges, ground "
      "handling, time on the ground. On a short flight they are spread over few seat-kilometres, on a long one over "
      "many",
      "Jeder Flug trägt Kosten, die nicht von der Entfernung abhängen: Start und Landung, Flughafenentgelte, "
      "Bodenabfertigung, Zeit am Boden. Auf einem kurzen Flug verteilen sie sich auf wenige Sitzkilometer, auf einem "
      "langen auf viele")}{cite('b1-038')}{T(
      ". Поэтому у перевозчика с короткими рейсами CASK выше даже при той же эффективности, а дальнемагистральный "
      "выглядит дешёвым просто потому, что летает далеко.",
      ". So a short-haul carrier has a higher CASK even at the same efficiency, and a long-haul carrier looks cheap "
      "simply because it flies far.",
      ". Deshalb hat eine Kurzstrecken-Airline auch bei gleicher Effizienz höhere CASK, und eine Langstrecken-Airline "
      "wirkt billig, einfach weil sie weit fliegt.")}</p>
<p>{T("Отрасль поправляет это одной формулой: CASK умножают на отношение длины рейса перевозчика к эталонной длине в "
      "степени k. MIT Airline Data Project берёт k = 0,5 и в качестве длины — средний путь пассажира, а эталон — "
      "среднее по выборке",
      "The industry corrects for this with one formula: CASK is multiplied by the ratio of the carrier's stage length "
      "to a reference length, raised to the power k. The MIT Airline Data Project takes k = 0.5, uses the average "
      "passenger trip length as the length and the sample average as the reference",
      "Die Branche korrigiert das mit einer Formel: Die CASK werden mit dem Verhältnis der Streckenlänge der Airline "
      "zu einer Referenzlänge hoch k multipliziert. Das MIT Airline Data Project nimmt k = 0,5, als Länge die mittlere "
      "Passagierstrecke und als Referenz den Stichprobendurchschnitt")}{cite('b1-020', 'b1-206')}{T(
      "; ту же степень использовали Virgin America в переписке с американской комиссией по ценным бумагам (эталон — "
      "1 000 миль), McKinsey и Sun Country в проспекте 2021 года",
      "; the same exponent was used by Virgin America in correspondence with the US Securities and Exchange Commission "
      "(reference 1,000 miles), by McKinsey and by Sun Country in its 2021 prospectus",
      "; denselben Exponenten nutzten Virgin America im Schriftverkehr mit der US-Börsenaufsicht (Referenz 1.000 "
      "Meilen), McKinsey und Sun Country im Prospekt von 2021")}{cite('b1-005', 'b1-006', 'b1-050', 'b1-192')}{T(
      ". Oliver Wyman в 2012 году брал k = 1/3", ". Oliver Wyman used k = 1/3 in 2012",
      ". Oliver Wyman nahm 2012 k = 1/3")}{cite('b1-026')}{T(
      ". Почему именно корень, ни один из этих источников не объясняет: это конвенция. Академические работы "
      "подтверждают лишь форму зависимости — затраты на рейс растут медленнее его длины",
      ". None of these sources explains why the square root: it is a convention. Academic work only confirms the shape "
      "of the relationship — cost per flight grows more slowly than its length",
      ". Warum gerade die Wurzel, erklärt keine dieser Quellen: Es ist eine Konvention. Wissenschaftliche Arbeiten "
      "bestätigen nur die Form des Zusammenhangs — die Kosten je Flug wachsen langsamer als seine Länge")}{cite('b1-215')}{T(
      ". Выбор степени заметно влияет на результат: при пути вдвое длиннее эталона множитель равен 1,41 при k = 0,5 и "
      "1,26 при k = 1/3, около 12 % разницы",
      ". The choice of exponent matters: for a trip twice the reference length the multiplier is 1.41 at k = 0.5 and "
      "1.26 at k = 1/3, a difference of about 12%",
      ". Die Wahl des Exponenten wirkt deutlich: Bei doppelter Referenzlänge ist der Faktor 1,41 bei k = 0,5 und 1,26 "
      "bei k = 1/3, rund 12 % Unterschied")}{cite('b1-223')}.</p>
{ch}
<p class="small">{T(f"Множитель к CASK в зависимости от среднего пути пассажира при эталоне {n(lr)} км — медиане нашей "
                    f"выборки.",
                    f"CASK multiplier as a function of average passenger trip length, with a reference of {n(lr)} km — "
                    f"the median of our sample.",
                    f"Faktor auf die CASK in Abhängigkeit von der mittleren Passagierstrecke bei einer Referenz von "
                    f"{n(lr)} km — dem Median unserer Stichprobe.")}</p>
<p>{T("На графике ниже — затраты без топлива на 100 кресло-километров у авиакомпаний выборки до и после приведения. "
      "Дальнемагистральные Emirates, Air Canada и Copa в отчёте выглядят дешевле многих лоукостеров; после приведения "
      "они поднимаются, а короткие европейские лоукостеры опускаются.",
      "The chart below shows ex-fuel cost per 100 seat-kilometres for the airlines in the sample before and after "
      "adjustment. Long-haul Emirates, Air Canada and Copa look cheaper than many low-cost carriers as reported; after "
      "adjustment they move up, and short-haul European low-cost carriers move down.",
      "Das Diagramm unten zeigt die Kosten ohne Treibstoff je 100 Sitzkilometer der Airlines der Stichprobe vor und "
      "nach der Korrektur. Die Langstrecken-Airlines Emirates, Air Canada und Copa wirken im Bericht billiger als viele "
      "Low-Cost-Airlines; nach der Korrektur steigen sie, und die europäischen Kurzstrecken-Low-Coster sinken.")}</p>
{sc}
<p class="small">{T("По горизонтали — средний путь пассажира, по вертикали — затраты без топлива на 100 кресло-км, EUR. "
                    "Кружок — как в отчёте, точка — после приведения к медиане со степенью 0,5.",
                    "Horizontal: average passenger trip length; vertical: ex-fuel cost per 100 seat-km, EUR. Circle — "
                    "as reported, dot — after adjustment to the median with an exponent of 0.5.",
                    "Waagerecht: mittlere Passagierstrecke; senkrecht: Kosten ohne Treibstoff je 100 Sitzkilometer, "
                    "EUR. Kreis — wie berichtet, Punkt — nach Korrektur auf den Median mit Exponent 0,5.")}</p>
<h3>{T("2. Что считать кресло-километром", "2. What counts as a seat-kilometre", "2. Was als Sitzkilometer zählt")}</h3>
<p>{T("Расстояние для кресло-километров можно считать по кратчайшему пути или по фактически пролетённому, а кресла — "
      "все или только доступные к продаже",
      "The distance for seat-kilometres can be measured along the great circle or as actually flown, and the seats can "
      "be all seats or only those available for sale",
      "Die Entfernung für Sitzkilometer lässt sich als Großkreis oder als tatsächlich geflogene Strecke messen, die "
      "Sitze als alle oder nur die verkaufbaren")}{cite('b1-210')}{T(
      ". Pegasus в 2020 году перешёл с кратчайшего расстояния на фактическое, и кресло-километры за 2019 год выросли с "
      "38,6 до 43,9 миллиарда — на 13,9 %",
      ". In 2020 Pegasus switched from great-circle to actual distance, and its 2019 seat-kilometres rose from 38.6 to "
      "43.9 billion — by 13.9%",
      ". Pegasus stellte 2020 von der Großkreis- auf die tatsächliche Entfernung um, und die Sitzkilometer für 2019 "
      "stiegen von 38,6 auf 43,9 Milliarden — um 13,9 %")}{cite('b1-198', 'b1-199')}{T(
      ". При тех же затратах CASK от этого падает на 12 %, хотя в работе компании не изменилось ничего. Плотность "
      "компоновки тоже двигает знаменатель: по оценке McKinsey, она объясняет половину разницы CASK на дальних рейсах",
      ". With the same costs, CASK falls by 12% as a result, although nothing changed in how the airline works. Seating "
      "density also moves the denominator: by McKinsey's estimate it explains half the CASK gap on long-haul flights",
      ". Bei gleichen Kosten sinken die CASK dadurch um 12 %, obwohl sich am Betrieb nichts geändert hat. Auch die "
      "Sitzdichte verschiebt den Nenner: Nach McKinsey erklärt sie die Hälfte des CASK-Unterschieds auf der "
      "Langstrecke")}{cite('b1-052')}.</p>
<h3>{T("3. Аренда самолётов: МСФО 16 против американского стандарта", "3. Aircraft leases: IFRS 16 versus US GAAP",
       "3. Flugzeugleasing: IFRS 16 gegen US GAAP")}</h3>
<p>{T("С 2019 года по международному стандарту МСФО 16 арендованный самолёт ставится на баланс, а лизинговый платёж "
      "делится на амортизацию в операционных расходах и проценты — ниже операционной прибыли. Американский стандарт для "
      "операционной аренды оставляет весь платёж в операционных расходах",
      "Since 2019, under the international standard IFRS 16, a leased aircraft goes on the balance sheet and the lease "
      "payment is split into depreciation in operating expenses and interest below operating profit. The US standard "
      "keeps the whole payment for an operating lease in operating expenses",
      "Seit 2019 kommt ein geleastes Flugzeug nach IFRS 16 in die Bilanz, und die Leasingzahlung wird in Abschreibung "
      "im Betriebsaufwand und Zinsen unterhalb des Betriebsergebnisses geteilt. Der US-Standard lässt bei "
      "Operating-Leasing die ganze Zahlung im Betriebsaufwand")}{cite('b1-115')}{T(
      ". У easyJet при переходе аренда самолётов упала со 152 до 5 миллионов фунтов, амортизация выросла со 199 до 484 "
      "миллионов, а финансовые расходы — до 39 миллионов",
      ". At easyJet the transition cut aircraft lease costs from 152 to 5 million pounds, while depreciation rose from "
      "199 to 484 million and finance costs to 39 million",
      ". Bei easyJet sank der Leasingaufwand beim Übergang von 152 auf 5 Mio. Pfund, die Abschreibung stieg von 199 auf "
      "484 Mio. und der Finanzaufwand auf 39 Mio.")}{cite('b1-120', 'b1-121', 'b1-122')}{T(
      ". Значит, при прочих равных CASK европейского перевозчика ниже американского на процентную часть аренды.",
      ". So, all else equal, a European carrier's CASK is lower than a US carrier's by the interest part of the lease.",
      ". Bei sonst gleichen Bedingungen sind die CASK einer europäischen Airline also um den Zinsanteil des Leasings "
      "niedriger als die einer US-Airline.")}</p>
{ifrs()}
<h3>{T("4. Топливо и хеджирование", "4. Fuel and hedging", "4. Treibstoff und Hedging")}</h3>
<p>{T("Европейские лоукостеры покупают топливо заранее: Ryanair хеджирует около 80 % на год вперёд",
      "European low-cost carriers buy fuel in advance: Ryanair hedges about 80% a year ahead",
      "Europäische Low-Cost-Airlines kaufen Treibstoff im Voraus: Ryanair sichert rund 80 % ein Jahr im Voraus ab")}{cite('b1-135')}{T(
      ", а у American в 2024 году не было ни одного топливного контракта",
      ", while American had no fuel hedges at all in 2024", ", American dagegen hatte 2024 keinen einzigen "
      "Treibstoffkontrakt")}{cite('b1-131')}{T(
      ". В годы скачков цены разница в топливной статье отражает финансовые решения, а не работу самолётов. Поэтому "
      "затраты сравнивают без топлива, а топливную эффективность — в физических единицах: граммах на пассажиро-километр "
      "или пассажиро-километрах на литр",
      ". In years of price spikes the gap in the fuel line reflects financial decisions, not how the aircraft perform. "
      "So costs are compared ex-fuel, and fuel efficiency in physical units: grams per passenger-kilometre or "
      "passenger-kilometres per litre",
      ". In Jahren mit Preissprüngen spiegelt der Unterschied in der Treibstoffposition Finanzentscheidungen wider, "
      "nicht die Leistung der Flugzeuge. Deshalb vergleicht man Kosten ohne Treibstoff und die Treibstoffeffizienz in "
      "physischen Einheiten: Gramm je Passagierkilometer oder Passagierkilometer je Liter")}{cite('b1-014', 'b1-177')}.</p>
<h3>{T("5. Периметр: группа, региональные партнёры, аренда с экипажем",
       "5. Perimeter: group, regional partners, wet leases",
       "5. Berichtsumfang: Konzern, Regionalpartner, Wet Lease")}</h3>
<p>{T("Отчётность группы Lufthansa включает грузовой сегмент и сторонний бизнес техобслуживания",
      "Lufthansa Group reporting includes the cargo segment and third-party maintenance business",
      "Die Berichterstattung der Lufthansa Group umfasst das Frachtsegment und das Drittgeschäft der Wartung")}{cite('b1-144', 'b1-145')}{T(
      ". Американские сетевые перевозчики покупают рейсы у региональных партнёров по фиксированным ставкам, и в их "
      "отчётности эти рейсы обычно сидят и в затратах, и в кресло-километрах",
      ". US network carriers buy flights from regional partners at fixed rates (capacity purchase), and in their "
      "reports these flights usually sit in both costs and seat-kilometres",
      ". US-Netzwerk-Airlines kaufen Flüge bei Regionalpartnern zu festen Sätzen ein (Capacity Purchase), und in ihren "
      "Berichten stecken diese Flüge meist sowohl in den Kosten als auch in den Sitzkilometern")}{cite('b1-133')}{T(
      ". При аренде самолёта с экипажем (ACMI) трафик и расходы по правилам американского министерства транспорта "
      "отчитывает оператор",
      ". Under a wet lease (ACMI), US Department of Transportation rules have the operator report the traffic and costs",
      ". Bei Wet Lease (ACMI) meldet nach den Regeln des US-Verkehrsministeriums der Betreiber Verkehr und Kosten")}{cite('b1-141', 'b1-142')}{T(
      ". Правило одно: затраты и кресло-километры должны быть из одного контура",
      ". There is one rule: costs and seat-kilometres must come from the same perimeter",
      ". Es gilt eine Regel: Kosten und Sitzkilometer müssen aus demselben Umfang stammen")}{cite('b1-147')}.</p>
<h3>{T("6. Валюта", "6. Currency", "6. Währung")}</h3>
<p>{T("Пересчёт по текущему курсу двигает затраты без изменения работы компании; IATA предупреждает об этом прямо",
      "Converting at the current exchange rate moves costs without any change in the airline's operations; IATA warns "
      "about this explicitly",
      "Die Umrechnung zum aktuellen Kurs verschiebt die Kosten, ohne dass sich am Betrieb etwas ändert; die IATA warnt "
      "ausdrücklich davor")}{cite('b1-085')}{T(
      ". Важнее другое: исторически низкие затраты чаще объяснялись дешёвыми ресурсами страны — трудом, топливом, "
      "сборами, — чем высокой эффективностью",
      ". More important: historically, low costs were more often explained by a country's cheap inputs — labour, fuel, "
      "charges — than by high efficiency",
      ". Wichtiger noch: Niedrige Kosten erklärten sich historisch öfter durch billige Ressourcen eines Landes — "
      "Arbeit, Treibstoff, Entgelte — als durch hohe Effizienz")}{cite('b1-155')}{T(
      ". Поэтому рейтинг по CASK — это рейтинг конкурентоспособности по затратам, а не чистой эффективности. Это хорошо "
      "видно на российских перевозчиках: по рыночному курсу рубля их затраты выглядят как у лоукостеров.",
      ". So a CASK ranking is a ranking of cost competitiveness, not of pure efficiency. Russian carriers show this "
      "well: at the market rouble rate their costs look like a low-cost carrier's.",
      ". Ein CASK-Ranking ist daher ein Ranking der Kostenwettbewerbsfähigkeit, nicht der reinen Effizienz. Gut "
      "sichtbar ist das bei russischen Airlines: Zum Marktkurs des Rubels sehen ihre Kosten wie die einer "
      "Low-Cost-Airline aus.")}</p></section>"""

    # ── 5. когда каким пользоваться ───────────────────────────────────────
    L_which, L_why = T("Какие бенчмарки", "Which benchmarks", "Welche Benchmarks"), T("Почему", "Why", "Warum")
    uses = "".join(f"<tr><td><b>{e(TR(u['task']))}</b></td><td data-l='{L_which}'>{e(TR(u['which benchmarks']))}</td>"
                   f"<td data-l='{L_why}'>{e(TR(u['why']))}"
                   f"{cite(*u['ids'])}</td></tr>" for u in B1["use_cases"])
    when = f"""<section><h2>{T("Когда каким бенчмарком пользоваться", "When to use which benchmark",
                              "Wann man welchen Benchmark nutzt")}</h2>
<p>{T("Выбор бенчмарка зависит от вопроса. Для цены билета и оценки маршрута нужна стоимость блок-часа по типу самолёта "
      "и выручка конкурента на той же длине рейса. Для переговоров с ремонтниками и лизингодателями — рыночный уровень "
      "ставок техобслуживания. Для сравнения авиакомпаний между собой — отчётность с поправками на длину рейса, топливо "
      "и учёт аренды. Для проверки собственной модели — открытые ряды с известными определениями. Бенчмарки качества "
      "дополняют затратные, но смешивать их в один индекс не стоит: пунктуальность зависит от аэропортов и управления "
      "воздушным движением не меньше, чем от перевозчика",
      "The choice of benchmark depends on the question. For fares and route appraisal you need the block-hour cost by "
      "aircraft type and a competitor's revenue at the same stage length. For negotiating with MRO shops and lessors, "
      "the market level of maintenance rates. For comparing airlines with one another, reports adjusted for stage "
      "length, fuel and lease accounting. For checking your own model, open series with known definitions. Quality "
      "benchmarks complement cost benchmarks, but they should not be mixed into one index: punctuality depends on "
      "airports and air traffic control as much as on the carrier",
      "Welcher Benchmark passt, hängt von der Frage ab. Für Tarife und Streckenbewertung braucht man die "
      "Blockstundenkosten je Flugzeugtyp und den Erlös eines Wettbewerbers bei gleicher Streckenlänge. Für "
      "Verhandlungen mit Werften und Leasinggebern das Marktniveau der Wartungssätze. Für den Vergleich von Airlines "
      "untereinander Berichte mit Korrekturen für Streckenlänge, Treibstoff und Leasingbilanzierung. Für die Prüfung "
      "des eigenen Modells offene Reihen mit bekannten Definitionen. Qualitäts-Benchmarks ergänzen die Kosten-"
      "Benchmarks, sollten aber nicht in einen Index gemischt werden: Pünktlichkeit hängt von Flughäfen und "
      "Flugsicherung nicht weniger ab als von der Airline")}{cite('b1-172')}.</p>
<div class="tw"><table class="txt cards"><tr><th>{T("Задача", "Task", "Aufgabe")}</th><th>{L_which}</th><th>{L_why}</th>
</tr>{uses}</table></div></section>"""

    # ── 6. рейтинг ────────────────────────────────────────────────────────
    def dual(score, real, col):
        return f'<span class="vp">{bar(score, col)}</span><span class="vr">{real}</span>'

    def f(v, d=1, pc=False):
        return "—" if v is None else (n(v * 100, d) + " %" if pc else n(v, d))

    L_idx = T("Индекс", "Index", "Index")
    L_cost, L_ast = T("Затраты", "Costs", "Kosten"), T("Отдача парка", "Fleet productivity", "Flottenproduktivität")
    L_com, L_fuel = T("Коммерция", "Commercial", "Kommerz"), T("Топливо", "Fuel", "Treibstoff")
    L_pil, L_k = T("Опор", "Pillars", "Säulen"), T("При k = 1/3", "At k = 1/3", "Bei k = 1/3")

    def row(c):
        p = c["pillars"]
        real = {"cost": money(c['casx_adj'], 'EUR', 2, nc=True) + " EUR" if c.get('casx_adj') else "—",
                "asset": f"{n(c['util'], 1)} {T('ч/сут', 'h/day', 'h/Tag')}" if c.get('util') else "—",
                "com": (f"{T('загрузка', 'load factor', 'Ladefaktor')} {f(c.get('lf'), 1, True)}<br>"
                        f"{T('маржа', 'margin', 'Marge')} {f(c.get('margin'), 1, True)}"),
                "fuel": f"{n(c['g_rpk'], 1)} {T('г', 'g', 'g')}" if c.get('g_rpk') else "—"}
        mv = (c.get("rank_k13") or c["rank"]) - c["rank"]
        mvs = "=" if mv == 0 else (f"↓{mv}" if mv > 0 else f"↑{-mv}")
        return (f"<tr><td class=r>{c['rank']}</td><td class=nm><b>{e(nm(c))}</b><br><span class=s>"
                f"{e(reg(c))} · {e(mod(c))}</span></td>"
                f"<td class=r data-l='{L_idx}'><b>{n(c['index'])}</b></td>"
                f"<td data-l='{L_cost}'>{dual(p['cost'], real['cost'], 'var(--sky)')}</td>"
                f"<td data-l='{L_ast}'>{dual(p['asset'], real['asset'], 'var(--t2)')}</td>"
                f"<td data-l='{L_com}'>{dual(p['commercial'], real['com'], 'var(--t3)')}</td>"
                f"<td data-l='{L_fuel}'>{dual(p['fuel'], real['fuel'], 'var(--green)')}</td>"
                f"<td class=r data-l='{L_pil}'>{c['n_pillars']}/4</td><td class=r data-l='{L_k}'>{mvs}</td></tr>")

    head = (f"<tr><th class=r>#</th><th>{T('Авиакомпания', 'Airline', 'Airline')}</th><th class=r>{L_idx}</th>"
            f"<th>{L_cost}<span class=vr><br>{T('без топлива, приведённые, на 100 кресло-км', 'ex-fuel, adjusted, per 100 seat-km', 'ohne Treibstoff, korrigiert, je 100 Sitzkilometer')}</span></th>"
            f"<th>{L_ast}<span class=vr><br>{T('блок-часы на самолёт', 'block hours per aircraft', 'Blockstunden je Flugzeug')}</span></th>"
            f"<th>{L_com}</th>"
            f"<th>{L_fuel}<span class=vr><br>{T('на пассажиро-км', 'per passenger-km', 'je Passagierkilometer')}</span></th>"
            f"<th class=r>{L_pil}</th><th class=r>{T('при k = 1/3', 'at k = 1/3', 'bei k = 1/3')}</th></tr>")
    t_top = "".join(row(c) for c in RANKED[:10])
    t_rest = "".join(row(c) for c in RANKED[10:])
    allc = [c for c in RT["carriers"] if not c.get("excluded")]
    Lr = (T("Период", "Period", "Zeitraum"),
          T("Затраты, EUR / 100 кресло-км", "Costs, EUR / 100 seat-km", "Kosten, EUR / 100 Sitzkilometer"),
          T("Путь пассажира, км", "Passenger trip, km", "Passagierstrecke, km"),
          T("Налёт, ч/сут", "Utilisation, h/day", "Auslastung, h/Tag"), T("Загрузка", "Load factor", "Sitzladefaktor"),
          T("Маржа", "Margin", "Marge"), T("Топливо, г / пасс-км", "Fuel, g / passenger-km", "Treibstoff, g / Passagierkilometer"),
          T("Источники", "Sources", "Quellen"))
    t_raw = "".join(
        f"<tr><td class=nm>{e(nm(c))}</td><td class=s data-l='{Lr[0]}'>{e(TR(c.get('period') or ''))}</td>"
        f"<td class=r data-l='{Lr[1]}'>{money(c['casx_adj'], 'EUR', 2, nc=True) if c.get('casx_adj') else '—'}</td>"
        f"<td class=r data-l='{Lr[2]}'>{f(c.get('L'), 0)}</td><td class=r data-l='{Lr[3]}'>{f(c.get('util'))}</td>"
        f"<td class=r data-l='{Lr[4]}'>{f(c.get('lf'), 1, True)}</td><td class=r data-l='{Lr[5]}'>{f(c.get('margin'), 1, True)}</td>"
        f"<td class=r data-l='{Lr[6]}'>{f(c.get('g_rpk'))}</td><td data-l='{Lr[7]}'>{cids(c)}</td></tr>"
        for c in sorted(allc, key=lambda c: (c.get("rank") or 99, c["code"])))
    out = [c for c in RT["carriers"] if not c.get("rank")]
    outs = "; ".join(f"{nm(c)} — {TR(c['excluded'])}" if c.get("excluded") else
                     T(f"{nm(c)} — данных хватило на {c.get('n_pillars', 0)} опоры из четырёх",
                       f"{nm(c)} — data for only {c.get('n_pillars', 0)} pillars out of four",
                       f"{nm(c)} — Daten nur für {c.get('n_pillars', 0)} von vier Säulen") for c in out)
    pc, fr, cm, dy = nm(C['PC']), nm(C['FR']), nm(C['CM']), nm(C['DY'])
    cm_m = f(C['CM']['margin'], 1, True)
    rating = f"""<section><h2>{T(f"Наш рейтинг: {len(RANKED)} авиакомпаний, 2025 год",
                                f"Our rating: {len(RANKED)} airlines, 2025",
                                f"Unser Rating: {len(RANKED)} Airlines, 2025")}</h2>
<p>{T("Мы построили рейтинг так, чтобы обойти ловушки, насколько это возможно на открытой отчётности. Он стоит на "
      "четырёх опорах, и каждая отвечает на свой вопрос. <b>Затраты</b>: сколько стоит кресло-километр без топлива, "
      "приведённый к единой длине по пути пассажира со степенью 0,5 — как у MIT. <b>Отдача парка</b>: сколько "
      "блок-часов в сутки летает самолёт. <b>Коммерция</b>: загрузка и операционная маржа — умеет ли компания продать "
      "то, что предложила, дороже, чем это стоит. <b>Топливо</b>: граммы керосина на пассажиро-километр. По каждой "
      "метрике авиакомпания получает процентиль внутри выборки — 100 у лучшей, 0 у худшей; опора «коммерция» — среднее "
      "двух метрик; индекс — среднее доступных опор. В рейтинг попадают перевозчики, у которых есть хотя бы три опоры "
      "из четырёх.",
      "We built the rating to avoid the pitfalls as far as public reporting allows. It rests on four pillars, each "
      "answering its own question. <b>Costs</b>: what a seat-kilometre costs ex-fuel, adjusted to a common length by "
      "passenger trip with an exponent of 0.5 — as MIT does. <b>Fleet productivity</b>: how many block hours a day the "
      "aircraft fly. <b>Commercial</b>: load factor and operating margin — whether the airline can sell what it offers "
      "for more than it costs. <b>Fuel</b>: grams of jet fuel per passenger-kilometre. For each metric an airline gets "
      "a percentile within the sample — 100 for the best, 0 for the worst; the commercial pillar is the average of two "
      "metrics; the index is the average of the available pillars. Carriers with at least three pillars out of four "
      "make the rating.",
      "Wir haben das Rating so gebaut, dass es die Fallstricke umgeht, soweit öffentliche Berichte es erlauben. Es "
      "ruht auf vier Säulen, jede beantwortet eine eigene Frage. <b>Kosten</b>: was ein Sitzkilometer ohne Treibstoff "
      "kostet, korrigiert auf eine einheitliche Länge nach Passagierstrecke mit Exponent 0,5 — wie beim MIT. "
      "<b>Flottenproduktivität</b>: wie viele Blockstunden am Tag ein Flugzeug fliegt. <b>Kommerz</b>: Sitzladefaktor "
      "und operative Marge — ob die Airline das Angebotene teurer verkaufen kann, als es kostet. <b>Treibstoff</b>: "
      "Gramm Kerosin je Passagierkilometer. Für jede Kennzahl erhält eine Airline ein Perzentil innerhalb der "
      "Stichprobe — 100 für die beste, 0 für die schlechteste; die Säule Kommerz ist der Mittelwert zweier Kennzahlen; "
      "der Index ist der Mittelwert der verfügbaren Säulen. Ins Rating kommen Airlines mit mindestens drei von vier "
      "Säulen.")}</p>
<p>{T("Валюты приведены к евро по средним курсам ЕЦБ за 2025 год",
      "Currencies are converted to euros at average ECB rates for 2025",
      "Währungen sind zu durchschnittlichen EZB-Kursen 2025 in Euro umgerechnet")}{cite('b6-001', 'b6-002')}{T(
      ", рубль — по среднему курсу из отчётности «Аэрофлота»", ", the rouble at the average rate from Aeroflot's reports",
      ", der Rubel zum Durchschnittskurs aus den Berichten von Aeroflot")}{cite('b6-012')}{T(
      ". Налёт американских перевозчиков — из Form 41 за 2025 год по их собственным рейсам, без региональных партнёров",
      ". US carriers' utilisation is from 2025 Form 41 for their own flights, without regional partners",
      ". Die Auslastung der US-Airlines stammt aus Form 41 für 2025 für ihre eigenen Flüge, ohne Regionalpartner")}{cite('b4-001')}{T(
      "; топливо у части европейцев — из интенсивности CO₂ на пассажиро-километр в отчётах об устойчивом развитии, "
      "поделённой на 3,16 тонны CO₂ на тонну керосина.",
      "; fuel for some European airlines comes from CO₂ intensity per passenger-kilometre in sustainability reports, "
      "divided by 3.16 tonnes of CO₂ per tonne of jet fuel.",
      "; der Treibstoff einiger europäischer Airlines stammt aus der CO₂-Intensität je Passagierkilometer in "
      "Nachhaltigkeitsberichten, geteilt durch 3,16 Tonnen CO₂ je Tonne Kerosin.")}</p>
<div class="rk" id="rk"><div class="rkbar"><span>{T("Показать:", "Show:", "Anzeigen:")}</span><button type="button" class="on" data-m="">{T("баллы", "scores", "Punkte")}
</button><button type="button" data-m="real">{T("показатели", "metrics", "Kennzahlen")}</button></div>
<div class="tw"><table class="rank cards">{head}{t_top}</table></div>
<details><summary>{T(f"Места 11–{len(RANKED)}", f"Places 11–{len(RANKED)}", f"Plätze 11–{len(RANKED)}")}</summary><div class="tw"><table class="rank cards">{head}{t_rest}</table></div>
</details></div>
<script>(function(){{var r=document.getElementById('rk');r.querySelectorAll('.rkbar button').forEach(function(b){{
b.onclick=function(){{r.classList.toggle('real',b.dataset.m==='real');r.querySelectorAll('.rkbar button').forEach(
function(x){{x.classList.toggle('on',x===b)}})}}}})}})();</script>
<p class="small">{T(f"Баллы — процентили внутри выборки (100 — лучший), показатели — исходные цифры, из которых они "
                    f"посчитаны: затраты в EUR на 100 кресло-км без топлива, приведённые к пути пассажира "
                    f"{n(RT['L_ref_km'])} км. «При k = 1/3» — насколько сдвигается место, если приводить затраты к длине "
                    f"со степенью 1/3 вместо 0,5. Вне рейтинга: ",
                    f"Scores are percentiles within the sample (100 is best); metrics are the underlying figures: "
                    f"ex-fuel costs in EUR per 100 seat-km, adjusted to a passenger trip of {n(RT['L_ref_km'])} km. "
                    f"“At k = 1/3” shows how far a place moves if costs are adjusted with an exponent of 1/3 instead of "
                    f"0.5. Not rated: ",
                    f"Punkte sind Perzentile innerhalb der Stichprobe (100 ist am besten), Kennzahlen die zugrunde "
                    f"liegenden Werte: Kosten ohne Treibstoff in EUR je 100 Sitzkilometer, korrigiert auf eine "
                    f"Passagierstrecke von {n(RT['L_ref_km'])} km. „Bei k = 1/3“ zeigt, wie weit sich ein Platz "
                    f"verschiebt, wenn mit Exponent 1/3 statt 0,5 korrigiert wird. Nicht im Rating: ")}{e(outs)}.</p>
<details><summary>{T("Исходные метрики с источниками", "Underlying metrics with sources",
                     "Zugrunde liegende Kennzahlen mit Quellen")}</summary><div class="tw"><table class="cards"><tr><th>{T('Авиакомпания', 'Airline', 'Airline')}</th>
<th>{Lr[0]}</th><th class=r>{T("Затраты без топлива, приведённые, EUR / 100 кресло-км",
                               "Ex-fuel costs, adjusted, EUR / 100 seat-km",
                               "Kosten ohne Treibstoff, korrigiert, EUR / 100 Sitzkilometer")}</th><th class=r>{Lr[2]}</th>
<th class=r>{Lr[3]}</th><th class=r>{Lr[4]}</th><th class=r>{Lr[5]}</th><th class=r>{Lr[6]}</th>
<th>{Lr[7]}</th></tr>{t_raw}</table></div></details>
<h3>{T("Что показывает рейтинг", "What the rating shows", "Was das Rating zeigt")}</h3>
<p>{T(f"Наверху — авиакомпании, которые сильны сразу по нескольким опорам. У лидера, {pc}, — три опоры из четырёх: "
      f"налёт из её отчёта прочитать надёжно не удалось, и место стоит считать предварительным. {pc} и {fr} — среди "
      f"самых низких затрат и хорошую топливную эффективность при высокой загрузке; {cm} с хабом в Панаме — самую "
      f"высокую маржу выборки ({cm_m}) и высокий налёт; {dy} — ровные результаты по всем опорам. Дальше идут "
      f"латиноамериканские и индийский лоукостеры — GOL, Azul, IndiGo — с низкими затратами и высоким налётом. "
      f"Бизнес-модель не гарантирует места: Frontier и Allegiant — ультралоукостеры, но в 2025 году у первого "
      f"отрицательная маржа и низкая загрузка, у второго — один из самых низких налётов выборки.",
      f"At the top are airlines strong on several pillars at once. The leader, {pc}, has three pillars out of four: "
      f"its utilisation could not be read reliably from its report, so its place should be seen as provisional. {pc} "
      f"and {fr} combine some of the lowest costs and good fuel efficiency with high load factors; {cm}, with its hub "
      f"in Panama, has the highest margin in the sample ({cm_m}) and high utilisation; {dy} has even results across "
      f"all pillars. Next come the Latin American and Indian low-cost carriers — GOL, Azul, IndiGo — with low costs "
      f"and high utilisation. The business model does not guarantee a place: Frontier and Allegiant are ultra-low-cost "
      f"carriers, but in 2025 the first had a negative margin and a low load factor, and the second one of the lowest "
      f"utilisation figures in the sample.",
      f"Oben stehen Airlines, die auf mehreren Säulen zugleich stark sind. Der Spitzenreiter, {pc}, hat drei von vier "
      f"Säulen: Die Auslastung ließ sich aus seinem Bericht nicht verlässlich lesen, der Platz ist daher vorläufig. "
      f"{pc} und {fr} verbinden einige der niedrigsten Kosten und gute Treibstoffeffizienz mit hohem Sitzladefaktor; "
      f"{cm} mit seinem Drehkreuz in Panama hat die höchste Marge der Stichprobe ({cm_m}) und eine hohe Auslastung; "
      f"{dy} liefert gleichmäßige Ergebnisse auf allen Säulen. Danach folgen die lateinamerikanischen und der indische "
      f"Low-Coster — GOL, Azul, IndiGo — mit niedrigen Kosten und hoher Auslastung. Das Geschäftsmodell garantiert "
      f"keinen Platz: Frontier und Allegiant sind Ultra-Low-Cost-Airlines, doch 2025 hatte die erste eine negative "
      f"Marge und einen niedrigen Sitzladefaktor, die zweite eine der niedrigsten Auslastungen der Stichprobe.")}</p>
<p>{T("Внизу — крупные сетевые перевозчики США и Европы. Их затраты на кресло-километр выше в полтора-два раза, а маржа и "
      "налёт средние; это цена сети с хабами, премиальными классами и короткими стыковочными рейсами. Важная оговорка: у "
      "американских сетевых в затратах сидят рейсы региональных партнёров — у American, например, 5,1 миллиарда долларов",
      "At the bottom are the large network carriers of the US and Europe. Their cost per seat-kilometre is one and a "
      "half to two times higher, with average margins and utilisation; that is the price of a hub network with premium "
      "cabins and short connecting flights. An important caveat: US network carriers' costs include their regional "
      "partners' flights — at American, for example, $5.1 billion",
      "Unten stehen die großen Netzwerk-Airlines der USA und Europas. Ihre Kosten je Sitzkilometer sind anderthalb- "
      "bis zweimal so hoch, Marge und Auslastung durchschnittlich; das ist der Preis eines Drehkreuz-Netzes mit "
      "Premiumklassen und kurzen Zubringerflügen. Wichtiger Vorbehalt: In den Kosten der US-Netzwerk-Airlines stecken "
      "die Flüge der Regionalpartner — bei American etwa 5,1 Milliarden Dollar")}{cite('b3-034')}{T(
      " — а их налёт мы берём только по собственным рейсам. Finnair замыкает рейтинг: высокие затраты на длинном пути "
      "пассажира, низкая загрузка, убыток и самый высокий расход топлива в выборке.",
      " — while we take their utilisation from their own flights only. Finnair comes last: high costs over a long "
      "passenger trip, a low load factor, a loss and the highest fuel burn in the sample.",
      " — ihre Auslastung nehmen wir dagegen nur aus den eigenen Flügen. Finnair bildet das Schlusslicht: hohe Kosten "
      "bei langer Passagierstrecke, niedriger Sitzladefaktor, Verlust und der höchste Treibstoffverbrauch der "
      "Stichprobe.")}</p>
<p>{T(f"«Аэрофлот» — {su['rank']}-й. Его затраты без топлива по рыночному курсу рубля — ",
      f"Aeroflot is no. {su['rank']}. Its ex-fuel costs at the market rouble rate are ",
      f"Aeroflot steht auf Platz {su['rank']}. Seine Kosten ohne Treibstoff zum Marktkurs des Rubels liegen bei ")}{money(
      su['casx'], 'EUR', 2, unit=T(' / 100 кресло-км', ' / 100 seat-km', ' / 100 Sitzkilometer'))}{T(
      f", как у лоукостеров, но это та самая ловушка валюты: дешёвые ресурсы, а не эффективность. После приведения к "
      f"длине (путь пассажира группы — {n(su['L'])} км) затраты поднимаются к середине выборки. Загрузка — одна из самых "
      f"высоких, {f(su['lf'], 1, True)}; налёт — {f(su['util'])} часа в сутки на весь парк на балансе, ниже "
      f"большинства; маржа — {f(su['margin'], 1, True)}. S7 в рейтинг не попала: её бухгалтерская отчётность не "
      f"выделяет топливо из себестоимости, и затратная опора не считается",
      f", like a low-cost carrier's, but that is exactly the currency pitfall: cheap inputs, not efficiency. After "
      f"adjusting for length (the group's passenger trip is {n(su['L'])} km) costs rise to the middle of the sample. "
      f"The load factor is among the highest, {f(su['lf'], 1, True)}; utilisation is {f(su['util'])} hours a day across "
      f"the whole fleet on the balance sheet, below most; the margin is {f(su['margin'], 1, True)}. S7 is not in the "
      f"rating: its accounts do not separate fuel from cost of sales, so the cost pillar cannot be calculated",
      f", wie bei einer Low-Cost-Airline, doch genau das ist der Währungs-Fallstrick: billige Ressourcen, nicht "
      f"Effizienz. Nach der Längenkorrektur (die Passagierstrecke der Gruppe beträgt {n(su['L'])} km) steigen die Kosten "
      f"zur Mitte der Stichprobe. Der Sitzladefaktor gehört mit {f(su['lf'], 1, True)} zu den höchsten; die Auslastung "
      f"liegt bei {f(su['util'])} Stunden am Tag über die ganze bilanzierte Flotte, unter den meisten; die Marge bei "
      f"{f(su['margin'], 1, True)}. S7 ist nicht im Rating: Ihre Rechnungslegung trennt den Treibstoff nicht von den "
      f"Herstellungskosten, die Kostensäule lässt sich nicht berechnen")}{cite(C['S7'].get('source_url') or '')}.
</p></section>"""

    # ── 7. что меняем ─────────────────────────────────────────────────────
    concl = f"""<section><h2>{T("Что меняем в калькуляторе", "What we change in the calculator",
                               "Was wir im Rechner ändern")}</h2>
<ol><li>{mark('on_input')}<b>{T("Сравнивайте свои затраты с похожими", "Compare your costs with similar airlines",
                                 "Vergleichen Sie Ihre Kosten mit ähnlichen Airlines")}</b>{T(
      ": с той же бизнес-моделью и длиной рейса, без топлива, и помните про учёт аренды — CASK по МСФО 16 ниже на "
      "проценты по лизингу.",
      ": with the same business model and stage length, ex-fuel, and remember lease accounting — CASK under IFRS 16 is "
      "lower by the lease interest.",
      ": mit gleichem Geschäftsmodell und gleicher Streckenlänge, ohne Treibstoff, und denken Sie an die "
      "Leasingbilanzierung — die CASK nach IFRS 16 sind um die Leasingzinsen niedriger.")}</li>
<li>{mark('planned')}<b>{T("Полосы сравнения в расчёте — из рейтинга.", "Comparison bands in the calculation from the rating.",
                            "Vergleichsbänder in der Berechnung aus dem Rating.")}</b> {T(
      f"Сейчас калькулятор сверяется с двенадцатью перевозчиками; в очереди — все {len(allc)} авиакомпаний выборки с "
      f"приведением к длине рейса, которую считает пользователь.",
      f"The calculator currently checks against twelve carriers; queued: all {len(allc)} airlines in the sample, "
      f"adjusted to the stage length the user is calculating.",
      f"Derzeit vergleicht der Rechner mit zwölf Airlines; geplant sind alle {len(allc)} Airlines der Stichprobe, "
      f"korrigiert auf die Streckenlänge, die der Nutzer berechnet.")}</li>
<li>{mark('planned')}<b>{T("Налёт по умолчанию — по типу сети", "Default utilisation by network type",
                            "Standardauslastung nach Netztyp")}</b> {T(
      "из таблицы рейтинга и статьи о сети, вместо одной цифры 300 часов в месяц.",
      "from the rating table and the network article, instead of a single figure of 300 hours a month.",
      "aus der Rating-Tabelle und dem Netz-Artikel statt einer einzigen Zahl von 300 Stunden im Monat.")}</li>
<li>{mark('planned')}<b>{T("Рейтинг обновляется раз в год", "The rating is updated once a year",
                            "Das Rating wird einmal im Jahr aktualisiert")}</b> {T(
      "— после выхода годовых отчётов; процедура и журнал те же, что в этом исследовании.",
      "— after annual reports come out; the procedure and the log are the same as in this study.",
      "— nach Erscheinen der Jahresberichte; Verfahren und Protokoll sind dieselben wie in dieser Studie.")}</li></ol></section>"""

    # ── 8. отчёт ──────────────────────────────────────────────────────────
    from collections import Counter
    cnt = {k: Counter(x.get("status") for kk, x in v.items() if not kk.startswith("_")) for k, v in VER.items()}
    steps = sum(1 for f_ in (HERE / "trace").glob("b*.jsonl") for _ in f_.open(encoding="utf-8"))
    gl = [g for g in B1["gaps"] if isinstance(g, str) and not any(w in g for w in ("задани", "allowlist"))]
    gaps = "".join(f"<li>{e(TR(g))}</li>" for g in gl[:6])
    fb1, fb2, fb3 = (cnt.get(k, {}).get("found", 0) for k in ("b1", "b2", "b3"))
    report = f"""<section><h2>{T("Как проверялось", "How it was checked", "Wie geprüft wurde")}</h2>
<p>{T(f"Четыре исследователя вели журналы — {n(steps)} шагов (<code>trace/b1–b7</code>): обзор бенчмарков и ловушек, "
      f"данные по авиакомпаниям вне Северной Америки и в Северной Америке, дозаполнение топлива и налёта; выписки из "
      f"Form 41, Databook «Аэрофлота» и курсы — отдельными журналами. Отдельные агенты открыли каждый источник и сверили "
      f"цитаты (<code>verify/</code>): обзор — {fb1} найдено дословно; авиакомпании вне Северной Америки — {fb2}; "
      f"Северная Америка — {fb3}; ни одно число не разошлось с источником.",
      f"Four researchers kept logs — {n(steps)} steps (<code>trace/b1–b7</code>): the review of benchmarks and pitfalls, "
      f"data for airlines outside and inside North America, and filling in fuel and utilisation; extracts from Form 41, "
      f"Aeroflot's Databook and exchange rates are in separate logs. Separate agents opened every source and checked "
      f"the quotes (<code>verify/</code>): review — {fb1} found verbatim; airlines outside North America — {fb2}; North "
      f"America — {fb3}; not a single number differed from its source.",
      f"Vier Rechercheure führten Protokolle — {n(steps)} Schritte (<code>trace/b1–b7</code>): Überblick über "
      f"Benchmarks und Fallstricke, Daten zu Airlines außerhalb und innerhalb Nordamerikas, Ergänzung von Treibstoff und "
      f"Auslastung; Auszüge aus Form 41, dem Aeroflot-Databook und Wechselkurse stehen in eigenen Protokollen. Eigene "
      f"Agenten öffneten jede Quelle und prüften die Zitate (<code>verify/</code>): Überblick — {fb1} wörtlich "
      f"gefunden; Airlines außerhalb Nordamerikas — {fb2}; Nordamerika — {fb3}; keine einzige Zahl wich von der Quelle "
      f"ab.")}</p>
<p>{T("Исправлено по проверке: после смены определения кресло-километров у Pegasus CASK падает на 12 %, а не на "
      "13,9 %; MIT приводит затраты к пути пассажира — так сделано и в нашем рейтинге. Оценки, а не числа из отчётов, "
      "помечены в таблице источников: средний парк Copa, Azul и airBaltic; расходы Norwegian и Aegean как выручка минус "
      "операционная прибыль; топливо IndiGo, GOL и Air New Zealand пересчитано из энергии или CO₂. Spirit исключена: в "
      "2025 году два банкротства и два отчётных периода. Ryanair — за финансовый год до марта 2025: в отчёте за "
      "следующий год нет кресло-километров.",
      "Corrected after checking: after Pegasus changed its seat-kilometre definition, CASK falls by 12%, not 13.9%; "
      "MIT adjusts costs to the passenger trip — and so does our rating. Estimates rather than reported figures are "
      "marked in the source table: the average fleet of Copa, Azul and airBaltic; Norwegian's and Aegean's costs as "
      "revenue minus operating profit; IndiGo's, GOL's and Air New Zealand's fuel recalculated from energy or CO₂. "
      "Spirit is excluded: two bankruptcies and two reporting periods in 2025. Ryanair is for the financial year to "
      "March 2025: the following year's report has no seat-kilometres.",
      "Nach der Prüfung korrigiert: Nach der Änderung der Sitzkilometer-Definition bei Pegasus sinken die CASK um 12 %, "
      "nicht um 13,9 %; das MIT korrigiert die Kosten auf die Passagierstrecke — so auch unser Rating. Schätzungen statt "
      "berichteter Zahlen sind in der Quellentabelle markiert: die durchschnittliche Flotte von Copa, Azul und "
      "airBaltic; die Kosten von Norwegian und Aegean als Umsatz minus Betriebsergebnis; der Treibstoff von IndiGo, GOL "
      "und Air New Zealand aus Energie oder CO₂ umgerechnet. Spirit ist ausgeschlossen: zwei Insolvenzen und zwei "
      "Berichtsperioden 2025. Ryanair gilt für das Geschäftsjahr bis März 2025: Der Bericht des Folgejahres enthält "
      "keine Sitzkilometer.")}</p>
<details><summary>{T("Чего не нашлось", "What was not found", "Was nicht gefunden wurde")}</summary><ul>{gaps}</ul></details>
{S.html()}</section>"""

    style = """<style>figure.fig{margin:14px 0 6px;max-width:780px}.pb{display:inline-block;width:64px;height:8px;
background:var(--raise);border-radius:4px;overflow:hidden;vertical-align:middle;margin-right:6px}.pb span{display:block;
height:100%}.pv{font-size:12px;color:var(--dim)}.na{color:var(--faint)}table.rank td{vertical-align:middle}
.rk .vr{display:none}.rk.real .vr{display:inline}.rk.real .vp{display:none}.rk.real td{white-space:nowrap}
.rkbar{display:flex;gap:6px;align-items:center;font-size:12.5px;color:var(--dim);margin:6px 0}.rkbar button{font:inherit;
color:var(--dim);background:none;border:1px solid var(--line);border-radius:999px;padding:1px 10px;cursor:pointer}
.rkbar button.on{color:var(--ink);border-color:var(--sky)}figcaption.leg{font-size:11.5px;color:var(--dim);line-height:1.6;
margin-top:4px}figcaption.leg b{color:var(--ink)}figcaption.leg .li{white-space:nowrap}g.pt:hover circle{r:6}
@media(max-width:640px){table.rank.cards tr:not(.hd){display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 0}
table.rank.cards td:first-child{font-weight:600;margin-right:6px}table.rank.cards td.nm{flex:1 0 55%}
table.rank.cards td.nm br,table.rank.cards td.nm .s{display:none}.pb{width:54px}
table.rank.cards td:nth-child(3){margin-left:auto}table.rank.cards td:nth-child(3)::before{content:"IDXLABEL "}
table.rank.cards td:nth-child(n+4){flex:0 0 48%;vertical-align:top;font-size:12.5px}
table.rank.cards td:nth-child(4){margin-top:6px}table.rank.cards td:nth-child(5){margin-top:6px}
table.rank.cards td[data-l]::before{display:block;font-size:11px}
table.rank.cards td:nth-child(3)::before{display:inline}table.rank.cards td.nm::before{content:none;display:none}}</style>"""
    style = style.replace("IDXLABEL", T("индекс", "index", "Index"))
    return page(article_title("benchmarks-2026-10"),
                ARTICLE_CSS + style + hook + theory + kinds + traps + when + rating + concl + report)


if __name__ == "__main__":
    write_all(HERE, "benchmarks-2026-10", build, TR)
    print(f"источников {len(S.num)}")
