"""Статья «Проверка модели на Frontier и Southwest» -> report.html, report.en.html, report.de.html.

Данные — только из out/ этой папки (сырые T-100, DB1C и база в репозиторий не кладутся):
  out/fleet.json  — прогон сетей и сверка по статьям (bin/fleet_check.py, items до и после правок);
  out/fares.json  — доходная часть (charts/fares_data.py по свёрткам DB1C и T-100).

    python3 research/verify-2026-11/build_report.py
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from _report import (ARTICLE_CSS, T, Sources, article_title, calc_badge, chain, e, mark, money,  # noqa: E402
                     n, page, whisker, write_all)
import _report as R  # noqa: E402

SLUG = "verify-2026-11"
FL = json.loads((HERE / "out" / "fleet.json").read_text(encoding="utf-8"))
FA = json.loads((HERE / "out" / "fares.json").read_text(encoding="utf-8"))
USD_EUR = 1.13

SRC_T100 = "https://www.transtats.bts.gov/Fields.asp?gnoyr_VQ=FIM"
SRC_F41 = "https://www.transtats.bts.gov/Tables.asp?QO_VQ=EGD"
SRC_DB1C = "https://www.bts.gov/topics/airlines-and-airports/origin-and-destination-survey-data-market"
SRC_F9 = "https://www.prnewswire.com/news-releases/frontier-airlines-reports-fourth-quarter-2025-financial-results-302684727.html"
SRC_WN = "https://investors.southwest.com/sec-filings/all-sec-filings/content/0000092380-26-000002/er-12312025xerdoc.htm"
SRC_B6 = "https://www.businesswire.com/news/home/20260127623494/en/JetBlue-Announces-Fourth-Quarter-2025-Results"
SRC_ALK = "https://finviz.com/news/284702/alaska-air-group-reports-fourth-quarter-and-full-year-2025-results"
SRC_FX = ("https://www.suomenpankki.fi/en/statistics/interest-rates-and-exchange-rates/exchange-rates/"
          "average-annual-exchange-rates-for-the-year-2025/")
SRC_CPI = "https://www.ftportfolios.com/blogs/InvestBlog/2026/8/4/factoid---tuesday,-august-4,-2026"

ITEM_NAMES = {
    "Топливо, тыс. т": ("Топливо", "Fuel", "Treibstoff"),
    "Блок-часы, тыс.": ("Блок-часы", "Block hours", "Blockstunden"),
    "ТОиР": ("ТОиР", "Maintenance", "Instandhaltung"),
    "Экипаж": ("Экипаж", "Crew", "Crew"),
    "Аэропорт + наземка": ("Аэропорт и наземное обсл.", "Airport and handling", "Flughafen und Abfertigung"),
    "Аэропортовые сборы": ("Аэропортовые сборы", "Airport charges", "Flughafenentgelte"),
}


def err(x, fact):
    return (x / fact - 1) * 100


def svg_months(series: dict) -> str:
    """Ряд по месяцам: точки и линия, подписи первого и последнего значения."""
    ks = sorted(series)
    vs = [series[k] for k in ks]
    w, h, L, Rr, Tt, B = 680, 250, 52, 20, 18, 34
    lo, hi = 180, 290
    X = lambda i: L + i / (len(ks) - 1) * (w - L - Rr)          # noqa: E731
    Y = lambda v: Tt + (hi - v) / (hi - lo) * (h - Tt - B)       # noqa: E731
    mon = {"ru": "янв фев мар апр май июн июл авг сен окт ноя дек", "en": "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec",
           "de": "Jan Feb Mär Apr Mai Jun Jul Aug Sep Okt Nov Dez"}[R.LANG].split()
    g = []
    for v in range(lo, hi + 1, 20):
        g.append(f'<line x1="{L}" x2="{w - Rr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--line)"/>'
                 f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end" class="ax">{n(v)}</text>')
    for i, k in enumerate(ks):
        lab = mon[int(k[5:]) - 1] + ("" if i not in (0, len(ks) - 1) and k[5:] != "01" else f" {k[2:4]}")
        g.append(f'<text x="{X(i):.1f}" y="{h - 12}" text-anchor="middle" class="ax">{e(lab)}</text>')
    g.append('<polyline fill="none" stroke="var(--sky)" stroke-width="2" points="'
             + " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vs)) + '"/>')
    for i, v in enumerate(vs):
        g.append(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="3.5" fill="var(--sky)"><title>{k} · {n(v)} USD</title></circle>')
    for i, anc, dx, dy in ((0, "start", 4, -10), (len(vs) - 1, "end", -4, 20)):
        g.append(f'<text x="{X(i) + dx:.1f}" y="{Y(vs[i]) + dy:.1f}" text-anchor="{anc}" class="lab" fill="var(--ink2)">'
                 f'{n(vs[i])} USD</text>')
    g.append(f'<text x="{L}" y="{Tt - 4}" class="ax">USD</text>')
    return f'<svg viewBox="0 0 {w} {h}" class="chart" role="img">{"".join(g)}</svg>'


def svg_distance(pts, a, b) -> str:
    """Тариф пары против расстояния: точка — пара (размер — пассажиры), линия — регрессия."""
    import math
    w, h, L, Rr, Tt, B = 680, 300, 52, 16, 20, 36
    X = lambda km: L + min(km, 5500) / 5500 * (w - L - Rr)        # noqa: E731
    Y = lambda v: Tt + (800 - min(v, 800)) / 800 * (h - Tt - B)    # noqa: E731
    g = []
    for v in range(0, 801, 200):
        g.append(f'<line x1="{L}" x2="{w - Rr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--line)"/>'
                 f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end" class="ax">{n(v)}</text>')
    for km in range(0, 5501, 1000):
        g.append(f'<text x="{X(km):.1f}" y="{h - 16}" text-anchor="middle" class="ax">{n(km)}</text>')
    g.append(f'<text x="{w - Rr}" y="{h - 2}" text-anchor="end" class="ax">{e(T("расстояние, км", "distance, km", "Entfernung, km"))}</text>')
    for km, v, pax in sorted(pts, key=lambda x: -x[2]):
        g.append(f'<circle cx="{X(km):.1f}" cy="{Y(v):.1f}" r="{max(1.2, math.sqrt(pax) / 18):.1f}" fill="var(--sky)" fill-opacity=".28"/>')
    g.append(f'<line x1="{X(0):.1f}" y1="{Y(a):.1f}" x2="{X(5500):.1f}" y2="{Y(a + b * 5.5):.1f}" stroke="var(--green)" stroke-width="2.5"/>')
    g.append(f'<line x1="{X(0):.1f}" y1="{Y(a):.1f}" x2="{X(5500):.1f}" y2="{Y(a):.1f}" stroke="var(--green)" stroke-dasharray="4 4"/>')
    g.append(f'<text x="{X(3000):.1f}" y="{Y(a + b * 5.5) - 30:.1f}" class="lab" fill="var(--ink2)">{n(a)} + {n(b)} USD / 1000 {T("км", "km", "km")}</text>')
    g.append(f'<text x="{X(4300):.1f}" y="{Y(a) + 16:.1f}" class="ax">{e(T("постоянная часть", "fixed part", "fester Teil"))} {n(a)} USD</text>')
    g.append(f'<text x="{L}" y="{Tt - 6}" class="ax">USD</text>')
    return f'<svg viewBox="0 0 {w} {h}" class="chart" role="img">{"".join(g)}</svg>'


def svg_booking(bk) -> str:
    """Тариф покупок за 0–21 и 22–90 дней к покупкам за 91+ день, по дальности."""
    w, h, L, Rr, Tt, B = 680, 260, 44, 10, 26, 40
    lo, hi = 0.8, 1.7
    Y = lambda v: Tt + (hi - v) / (hi - lo) * (h - Tt - B)        # noqa: E731
    gw = (w - L - Rr) / len(bk)
    g = []
    for v in (0.8, 1.0, 1.2, 1.4, 1.6):
        g.append(f'<line x1="{L}" x2="{w - Rr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--line)"'
                 + (' stroke-width="1.5" stroke="var(--dim)"' if v == 1.0 else "") + "/>"
                 f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end" class="ax">{n(v, 1)}</text>')
    for i, b in enumerate(bk):
        x0 = L + i * gw + gw * 0.14
        bw = gw * 0.34
        for j, (k, col) in enumerate((("r21", "var(--sky)"), ("r22", "var(--dim)"))):
            v = b[k]
            y0, y1 = sorted((Y(v), Y(1.0)))
            g.append(f'<rect x="{x0 + j * (bw + 3):.1f}" y="{y0:.1f}" width="{bw:.1f}" height="{max(y1 - y0, 1):.1f}" rx="2" fill="{col}">'
                     f'<title>{n(v, 2)}</title></rect>')
        g.append(f'<text x="{x0 + bw / 2:.1f}" y="{Y(b["r21"]) - 5:.1f}" text-anchor="middle" class="ax">{n(b["r21"], 2)}</text>')
        g.append(f'<text x="{L + i * gw + gw / 2:.1f}" y="{h - 22}" text-anchor="middle" class="ax">{n(b["lo"] / 1000, 1 if b["lo"] % 1000 else 0)}–{n(b["hi"] / 1000, 1 if b["hi"] % 1000 else 0)}</text>')
    g.append(f'<text x="{w - Rr}" y="{h - 4}" text-anchor="end" class="ax">{e(T("дальность пары, тыс. км", "pair distance, thousand km", "Entfernung, Tsd. km"))}</text>')
    g.append(f'<rect x="{L + 4}" y="4" width="10" height="10" fill="var(--sky)"/><text x="{L + 18}" y="13" class="ax">{e(T("куплен за 0–21 день", "bought 0–21 days out", "0–21 Tage vorher gekauft"))}</text>'
             f'<rect x="{L + 200}" y="4" width="10" height="10" fill="var(--dim)"/><text x="{L + 214}" y="13" class="ax">{e(T("за 22–90 дней", "22–90 days out", "22–90 Tage vorher"))}</text>')
    return f'<svg viewBox="0 0 {w} {h}" class="chart" role="img">{"".join(g)}</svg>'


def svg_flow(pts, curve, be) -> str:
    """Средний ÷ 10-й перцентиль против потока пары (лог. шкала): облако пар, медианы, подбор, прежняя ступенька."""
    import math
    w, h, L, Rr, Tt, B = 680, 300, 44, 14, 22, 38
    q0, q1, lo, hi = 1e3, 1e6, 1.0, 4.0
    X = lambda q: L + (math.log10(min(max(q, q0), q1)) - 3) / 3 * (w - L - Rr)   # noqa: E731
    Y = lambda v: Tt + (hi - min(max(v, lo), hi)) / (hi - lo) * (h - Tt - B)     # noqa: E731
    g = []
    for v in (1, 2, 3, 4):
        g.append(f'<line x1="{L}" x2="{w - Rr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--line)"/>'
                 f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end" class="ax">× {n(v)}</text>')
    for q, lab in ((1e3, "1"), (1e4, "10"), (1e5, "100"), (1e6, "1000")):
        g.append(f'<text x="{X(q):.1f}" y="{h - 18}" text-anchor="middle" class="ax">{lab}</text>')
    g.append(f'<text x="{w - Rr}" y="{h - 2}" text-anchor="end" class="ax">{e(T("поток пары, тыс. пассажиров в месяц", "pair traffic, thousand passengers a month", "Verkehr, Tsd. Passagiere im Monat"))}</text>')
    for q, r in pts:
        g.append(f'<circle cx="{X(q):.1f}" cy="{Y(r):.1f}" r="1.6" fill="var(--sky)" fill-opacity=".22"/>')
    step = [(q0, 1.2 * 1.37), (8e4, 1.2 * 1.37), (8e4, 2.0 * 1.37), (q1, 2.0 * 1.37)]
    g.append('<polyline fill="none" stroke="var(--dim)" stroke-width="2" stroke-dasharray="5 4" points="'
             + " ".join(f"{X(q):.1f},{Y(v):.1f}" for q, v in step) + '"/>')
    fit = [(10 ** (3 + k * 0.1), (10 ** (3 + k * 0.1)) ** be) for k in range(31)]
    g.append('<polyline fill="none" stroke="var(--green)" stroke-width="2.5" points="'
             + " ".join(f"{X(q):.1f},{Y(v):.1f}" for q, v in fit) + '"/>')
    for c in curve:
        qm = math.sqrt(max(c["lo"], 1e3) * min(c["hi"], 3e5))
        g.append(f'<circle cx="{X(qm):.1f}" cy="{Y(c["ratio"]):.1f}" r="5" fill="var(--ink2)"><title>{n(c["ratio"], 2)}</title></circle>')
    g.append(f'<text x="{X(1.2e3):.1f}" y="{Y(3.75):.1f}" class="lab" fill="var(--green)">{e(T("подбор: q^0,077", "fit: q^0.077", "Anpassung: q^0,077"))}</text>'
             f'<text x="{X(1.2e3):.1f}" y="{Y(3.45):.1f}" class="lab" fill="var(--dim)">{e(T("прежняя ступенька 1,2 / 2,0", "old step 1.2 / 2.0", "alte Stufe 1,2 / 2,0"))}</text>'
             f'<text x="{X(1.2e3):.1f}" y="{Y(3.15):.1f}" class="lab" fill="var(--ink2)">{e(T("● медиана по корзине потока", "● median per traffic bin", "● Median je Verkehrsklasse"))}</text>')
    return f'<svg viewBox="0 0 {w} {h}" class="chart" role="img">{"".join(g)}</svg>'


def build() -> str:
    S = Sources(HERE)
    for u, t in ((SRC_T100, "BTS TranStats: T-100 Segment (All Carriers), 2025"),
                 (SRC_F41, "BTS TranStats: Form 41 Financial Data — Schedules P-5.2, T-2, 2025"),
                 (SRC_DB1C, "BTS: Origin and Destination Survey — DB1C Market"),
                 (SRC_F9, "Frontier Airlines Reports Fourth Quarter 2025 Financial Results"),
                 (SRC_WN, "Southwest Airlines: Fourth Quarter and Full Year 2025 Results"),
                 (SRC_FX, "Bank of Finland: Average annual exchange rates for the year 2025 (ECB)"),
                 (SRC_B6, "JetBlue Announces Fourth Quarter 2025 Results"),
                 (SRC_ALK, "Alaska Air Group Reports Fourth Quarter and Full Year 2025 Results"),
                 (SRC_CPI, "First Trust: Factoid, August 4, 2026 (US airfares +26.5% y/y in June 2026)")):
        S.url(u, t)
    c_t100, c_f41, c_db1c = S.cite(SRC_T100), S.cite(SRC_F41), S.cite(SRC_DB1C)
    c_f9, c_wn, c_b6, c_alk = S.cite(SRC_F9), S.cite(SRC_WN), S.cite(SRC_B6), S.cite(SRC_ALK)
    c_fx, c_cpi = S.cite(SRC_FX), S.cite(SRC_CPI)
    it = FL["items"]
    ex = FL["example"]
    ff = FA["flow_fit"]
    al, be = ff["alpha"], ff["beta"]
    conv = lambda q: round(1.00 * q ** 0.077 / 1.37, 2)          # noqa: E731 — как network.pair_conv
    tr = FA["trend"]["months"]
    m0, m1 = min(tr), max(tr)
    growth = (tr[m1] / tr[m0] - 1) * 100
    crew = FL["crew"]
    wn_tx, f9_tx = FL["taxi"]["wn_model_fact"], FL["taxi"]["f9_model_fact"]

    body = [ARTICLE_CSS, f'<h1>{e(T("Проверка модели на Frontier и Southwest: где она ошибалась и что поправлено", "Checking the model against Frontier and Southwest: where it was wrong and what was fixed", "Prüfung des Modells an Frontier und Southwest: wo es falsch lag und was korrigiert wurde"))}</h1>',
            calc_badge(SLUG)]

    # ---------- 1. Хук ----------
    body.append('<p class="lede">' + T(
        f"Я прогнал через калькулятор все рейсы двух американских авиакомпаний за 2025 год — {n((FL['deps']['F9'] + FL['deps']['WN']) / 1e6, 2)} млн вылетов — и сравнил итог с их отчётностью по каждой статье расходов. Топливо, ТОиР и блок-время сошлись в пределах 10 %. Четыре вещи модель считала неверно для США: аэронавигацию, аэропортовые сборы, экипаж и руление. Их я поправил, подбирая уровни по <b>другим</b> перевозчикам, а Frontier и Southwest оставил для проверки. Вторая часть — что показали 268 млн записей о проданных билетах: средний чек зависит от толщины пары, и это теперь в расчёте.",
        f"I ran every 2025 flight of two US airlines through the calculator — {n((FL['deps']['F9'] + FL['deps']['WN']) / 1e6, 2)} million departures — and compared the result with their reports, cost line by cost line. Fuel, maintenance and block time matched within 10%. Four things the model got wrong for the US: air navigation, airport charges, crew and taxi time. I fixed them, fitting the levels on <b>other</b> carriers and keeping Frontier and Southwest for the check. The second part is what 268 million sold-ticket records show: the average fare depends on how thick the pair is, and that is now in the calculation.",
        f"Ich habe alle Flüge zweier US-Airlines aus 2025 durch den Rechner laufen lassen — {n((FL['deps']['F9'] + FL['deps']['WN']) / 1e6, 2)} Mio. Abflüge — und das Ergebnis Posten für Posten mit ihren Berichten verglichen. Treibstoff, Instandhaltung und Blockzeit stimmten auf 10 % genau. Vier Dinge rechnete das Modell für die USA falsch: Flugsicherung, Flughafenentgelte, Crew und Rollzeit. Ich habe sie korrigiert, die Niveaus an <b>anderen</b> Airlines angepasst und Frontier und Southwest für die Prüfung aufgehoben. Der zweite Teil zeigt, was 268 Mio. Datensätze verkaufter Tickets sagen: Der Durchschnittspreis hängt davon ab, wie stark eine Strecke ist — und das steckt jetzt in der Rechnung.") + "</p>")
    body.append('<div class="verdict">' + "".join(
        f"<div><b>{a}</b><span>{b}</span></div>" for a, b in (
            (T("−5 % и −9 %", "−5% and −9%", "−5 % und −9 %"),
             T("топливо Frontier и Southwest против годовых отчётов — физика полёта работает",
               "Frontier and Southwest fuel against annual reports — the flight physics works",
               "Treibstoff von Frontier und Southwest gegen die Jahresberichte — die Flugphysik stimmt")),
            (T("0 за небо США", "Zero for US airspace", "Null für den US-Luftraum"),
             T(f"модель брала аэронавигацию — {n(406)} млн USD в год у Southwest; в США её оплачивают налоги в билете",
               f"the model charged air navigation — USD {n(406)} million a year at Southwest; in the US ticket taxes pay for it",
               f"das Modell berechnete Flugsicherung — {n(406)} Mio. USD im Jahr bei Southwest; in den USA zahlen das Ticketsteuern")),
            (T("× 2,9 к экипажу", "× 2.9 for crew", "× 2,9 für die Crew"),
             T("экипаж в США дороже европейской заготовки модели; у Frontier — заметно меньше среднего",
               "US crew costs more than the model's European default; Frontier pays clearly less than average",
               "Crews in den USA kosten mehr als der europäische Standard; Frontier zahlt deutlich weniger als der Schnitt")),
            (T(f"× {n(conv(5000), 2)} … {n(conv(300000), 2)}", f"× {n(conv(5000), 2)} … {n(conv(300000), 2)}", f"× {n(conv(5000), 2)} … {n(conv(300000), 2)}"),
             T("средний чек к минимуму агрегатора — плавно по потоку пары от 5 до 300 тыс. пассажиров в месяц",
               "average fare to the aggregator minimum — smoothly by pair traffic from 5k to 300k passengers a month",
               "Durchschnittspreis zum Aggregator-Minimum — stufenlos nach Verkehr von 5.000 bis 300.000 Passagieren im Monat")))) + "</div>")

    # ---------- 2. Как проверял ----------
    body.append("<section><h2>" + T("Как проверялась модель", "How the model was checked", "Wie das Modell geprüft wurde") + "</h2>")
    body.append("<p>" + T(
        f"Проверить модель экономики рейса на одном рейсе мало: нужна целая авиакомпания — её сеть, её расходы по статьям и то, сколько платят её пассажиры. Почти везде это коммерческая тайна, а в США Министерство транспорта публикует всё три. T-100 — каждый перевозчик, пара, тип самолёта и месяц: рейсы, кресла, пассажиры, время от колодок до колодок{c_t100}. Form 41 — расходы по типам самолётов: топливо, пилоты, ТОиР, аренда и амортизация{c_f41}. DB1C — выборка 40 % проданных билетов на внутренних рынках{c_db1c}. Годовые отчёты компаний дают итоговые строки расходов{c_f9}{c_wn}.",
        f"Checking a flight-economics model on one flight is not enough: you need a whole airline — its network, its costs by line and what its passengers pay. Almost everywhere that is a trade secret; in the US the Department of Transportation publishes all three. T-100 gives every carrier, pair, aircraft type and month: flights, seats, passengers, block-to-block time{c_t100}. Form 41 gives costs by aircraft type: fuel, pilots, maintenance, rent and depreciation{c_f41}. DB1C is a 40% sample of tickets sold in domestic markets{c_db1c}. Annual reports give the company-level cost lines{c_f9}{c_wn}.",
        f"Ein Flugkostenmodell an einem Flug zu prüfen, reicht nicht: Man braucht eine ganze Airline — ihr Netz, ihre Kosten nach Posten und was ihre Passagiere zahlen. Fast überall ist das Geschäftsgeheimnis; in den USA veröffentlicht das Verkehrsministerium alle drei. T-100 enthält je Airline, Strecke, Flugzeugtyp und Monat Flüge, Sitze, Passagiere und Blockzeit{c_t100}. Form 41 enthält Kosten je Flugzeugtyp: Treibstoff, Piloten, Instandhaltung, Miete und Abschreibung{c_f41}. DB1C ist eine 40-%-Stichprobe der im Inland verkauften Tickets{c_db1c}. Die Jahresberichte liefern die Kostenzeilen des Unternehmens{c_f9}{c_wn}.") + "</p>")
    body.append(chain([
        (T("Сеть", "Network", "Netz"), T("T-100 2025: пара × тип, рейсы, кресла, загрузка", "T-100 2025: pair × type, flights, seats, load factor", "T-100 2025: Strecke × Typ, Flüge, Sitze, Auslastung")),
        (T("Калькулятор", "Calculator", "Rechner"), T("каждая пара × тип со штатными ставками модели", "each pair × type at the model's default rates", "jede Strecke × Typ mit den Standardsätzen")),
        (T("Сумма", "Total", "Summe"), T("× число рейсов, по типам и по компании", "× flights, by type and company", "× Flüge, je Typ und Airline")),
        (T("Сверка", "Check", "Abgleich"), T("Form 41 по типам, 10-K по компании", "Form 41 by type, 10-K by company", "Form 41 je Typ, 10-K je Airline"))]))
    body.append("<p>" + T(
        f"Цена топлива — из отчёта каждой компании (2,47 и 2,41 USD за галлон), курс — среднегодовой ЕЦБ за 2025 год, 1,13 USD за евро{c_fx}. Главное правило — правки подбираются по <b>другим</b> перевозчикам: JetBlue, Alaska, Hawaiian, Horizon, Spirit, Allegiant, Sun Country. Подогнать модель под две компании можно всегда, и тогда совпадение ничего не доказывает. Оговорка: уровни ТОиР и владения модели раньше уже сверялись с полосой Form 41 по всем перевозчикам США за 2025 год, поэтому по этим двум статьям совпадение — отчасти проверка на тех же данных.",
        f"Fuel price comes from each company's report (USD 2.47 and 2.41 a gallon), the exchange rate is the ECB 2025 annual average, USD 1.13 per euro{c_fx}. The main rule: fixes are fitted on <b>other</b> carriers — JetBlue, Alaska, Hawaiian, Horizon, Spirit, Allegiant, Sun Country. You can always tune a model to two companies, and then a match proves nothing. A caveat: the model's maintenance and ownership levels were already checked against the Form 41 band of all US carriers for 2025, so for those two lines the match is partly a check on the same data.",
        f"Der Treibstoffpreis stammt aus dem Bericht jeder Airline (2,47 und 2,41 USD je Gallone), der Kurs ist der EZB-Jahresdurchschnitt 2025, 1,13 USD je Euro{c_fx}. Die Hauptregel: Korrekturen werden an <b>anderen</b> Airlines angepasst — JetBlue, Alaska, Hawaiian, Horizon, Spirit, Allegiant, Sun Country. Ein Modell lässt sich immer an zwei Airlines anpassen, und dann beweist eine Übereinstimmung nichts. Einschränkung: Instandhaltung und Besitz wurden schon früher am Form-41-Band aller US-Airlines 2025 abgeglichen; dort ist die Übereinstimmung teils eine Prüfung an denselben Daten.") + "</p></section>")

    # ---------- 3. Аналитика: до и после ----------
    body.append("<section><h2>" + T("Ошибка модели по статьям: до и после правок", "Model error by cost line: before and after the fixes", "Modellfehler je Posten: vor und nach den Korrekturen") + "</h2>")
    for car, name in (("F9", "Frontier"), ("WN", "Southwest")):
        rows = []
        for key, v in it[car].items():
            if key == "Аэронавигация":
                continue
            b, a = err(v["before"], v["fact"]), err(v["after"], v["fact"])
            col = "var(--green)" if abs(a) <= 10 else "var(--sky)"
            rows.append((T(*ITEM_NAMES[key]), a, (min(a, b), max(a, b)), col))
        body.append(f"<h3>{name}</h3>" + whisker(rows, lo=-80, hi=80, ticks=[-75, -50, -25, 0, 25, 50, 75],
                                                fmt=lambda v: n(v, 0, sign=True) + "%", label_w=170, w=600))
    body.append('<p class="small">' + T(
        "Точка — ошибка после правок, конец отрезка — до. Зелёным — в пределах 10 %. Экипаж — пилоты по Form 41 × 1,56: бортпроводников Form 41 по типам не публикует, их доля оценена по структуре затрат IATA ACMG. Аэронавигация не показана: в США она должна быть нулём, а модель давала 75 млн USD у Frontier и 406 млн у Southwest, после правки — 17 и 48 (рейсы в Мексику и на Карибы и грубые границы зон).",
        "The dot is the error after the fixes, the other end of the line is before. Green — within 10%. Crew is Form 41 pilots × 1.56: Form 41 does not report cabin crew by type, their share is estimated from the IATA ACMG cost structure. Air navigation is not shown: in the US it should be zero, the model gave USD 75 million at Frontier and 406 million at Southwest, after the fix 17 and 48 (flights to Mexico and the Caribbean plus coarse zone borders).",
        "Der Punkt ist der Fehler nach der Korrektur, das andere Ende vorher. Grün — innerhalb von 10 %. Crew = Piloten laut Form 41 × 1,56: Form 41 meldet Kabinenpersonal nicht je Typ, sein Anteil ist nach der IATA-ACMG-Kostenstruktur geschätzt. Flugsicherung fehlt im Bild: In den USA müsste sie null sein, das Modell ergab 75 Mio. USD bei Frontier und 406 Mio. bei Southwest, nach der Korrektur 17 und 48 (Flüge nach Mexiko und in die Karibik und grobe Zonengrenzen).") + "</p>")

    # пример рейса
    names = {"fuel": T("Топливо", "Fuel", "Treibstoff"), "enroute": T("Аэронавигация", "Air navigation", "Flugsicherung"),
             "airport_charges": T("Аэропортовые сборы", "Airport charges", "Flughafenentgelte"),
             "ownership": T("Владение", "Ownership", "Besitz"), "maintenance": T("ТОиР", "Maintenance", "Instandhaltung"),
             "crew": T("Экипаж", "Crew", "Crew"), "ground_handling": T("Наземное обслуживание", "Ground handling", "Abfertigung"),
             "distribution": T("Продажи", "Distribution", "Vertrieb")}
    trs = "".join(f'<tr><td>{names[k]}</td><td class="r">{money(ex["before"]["cost"][k])}</td><td class="r">{money(ex["after"]["cost"][k])}</td>'
                  f'<td class="r">{money(ex["after"]["cost"][k] - ex["before"]["cost"][k], sign=True)}</td></tr>'
                  for k in names)
    tb, ta = sum(ex["before"]["cost"].values()), sum(ex["after"]["cost"].values())
    body.append("<h3>" + T("Один рейс: Денвер — Лас-Вегас, A320neo, 186 кресел, загрузка 80 %, июль",
                           "One flight: Denver — Las Vegas, A320neo, 186 seats, 80% load factor, July",
                           "Ein Flug: Denver — Las Vegas, A320neo, 186 Sitze, 80 % Auslastung, Juli") + "</h3>")
    body.append(f'<div class="tw"><table><tr><th>{T("Статья", "Line", "Posten")}</th><th class="r">{T("было", "before", "vorher")}</th>'
                f'<th class="r">{T("стало", "after", "nachher")}</th><th class="r">{T("разница", "change", "Differenz")}</th></tr>{trs}'
                f'<tr><td><b>{T("Итого за рейс", "Total per flight", "Summe je Flug")}</b></td><td class="r"><b>{money(tb)}</b></td>'
                f'<td class="r"><b>{money(ta)}</b></td><td class="r"><b>{money(ta - tb, sign=True)}</b></td></tr>'
                f'<tr><td>{T("Безубыточный тариф", "Break-even fare", "Break-even-Tarif")}</td><td class="r">{money(ex["before"]["be"])}</td>'
                f'<td class="r">{money(ex["after"]["be"])}</td><td class="r">{money(ex["after"]["be"] - ex["before"]["be"], sign=True)}</td></tr></table></div>')
    body.append("<p>" + T(
        "На одном рейсе видно, куда ушли деньги: аэронавигация обнулилась, сборы аэропортов стали ниже, а экипаж вырос почти втрое. Безубыточный тариф для американского рейса поднялся примерно на четверть. Для Европы и России расчёт не изменился: правки срабатывают только по аэропортам США.",
        "One flight shows where the money moved: air navigation went to zero, airport charges fell and crew nearly tripled. The break-even fare of a US flight rose by about a quarter. For Europe and Russia nothing changed: the fixes apply only at US airports.",
        "An einem Flug sieht man, wohin das Geld wanderte: Flugsicherung fällt weg, Flughafenentgelte sinken, die Crew kostet fast das Dreifache. Der Break-even-Tarif eines US-Flugs steigt um etwa ein Viertel. Für Europa und Russland ändert sich nichts: Die Korrekturen greifen nur an US-Flughäfen.") + "</p></section>")

    # ---------- 4. Факты по правкам ----------
    body.append("<section><h2>" + T("Четыре ошибки и почему они были", "Four errors and why they happened", "Vier Fehler und ihre Ursachen") + "</h2>")
    body.append("<h3>" + T("Аэронавигация: за небо США не платят", "Air navigation: nobody pays for US airspace", "Flugsicherung: Für den US-Luftraum zahlt niemand") + "</h3><p>" + T(
        "Управление воздушным движением в США финансируется налогами на билет и топливо; пролётный сбор FAA есть только у транзитных рейсов, которые не садятся в стране. В справочнике это было записано словами, а в расчёте США стояли обычной зоной со средней ставкой. Теперь рейс с посадкой или вылетом в США за американское небо не платит.",
        "US air traffic control is funded by ticket and fuel taxes; the FAA overflight fee applies only to transit flights that do not land in the country. The reference said so in words, but the calculation treated the US as an ordinary zone at an average rate. Now a flight landing or departing in the US pays nothing for US airspace.",
        "Die US-Flugsicherung wird über Ticket- und Treibstoffsteuern finanziert; die FAA-Überfluggebühr gilt nur für Transitflüge ohne Landung. Im Verzeichnis stand das in Worten, die Rechnung behandelte die USA aber als gewöhnliche Zone mit Durchschnittssatz. Jetzt zahlt ein Flug mit Start oder Landung in den USA nichts für den US-Luftraum.") + "</p>")
    k = FL["k_na"]
    body.append("<h3>" + T("Аэропортовые сборы: мировая оценка для США завышена", "Airport charges: the world estimate is too high for the US", "Flughafenentgelte: Die Weltschätzung ist für die USA zu hoch") + "</h3><p>" + T(
        f"Тарифов аэропортов США в базе нет, и модель брала медиану мира — коэффициент 1,10 к базе оценки. Уровень для США я подобрал по JetBlue: модельные сборы его сети против строки «посадочные сборы и аренда» в отчёте дали {n(k['B6'], 2)}{c_b6}. Alaska Air Group дала {n(k['ALK'], 2)}{c_alk}, но это лишь проверка порядка: в расчёт попали 73 % вылетов группы, и при поправке только на Boeing 717 Hawaiian коэффициент был бы около {n(k['ALK_717_only'], 2)}. Остаток у Southwest (+29 %) пока не объяснён: моя гипотеза — долгосрочные договоры в его базах, но она не проверена.",
        f"There are no US airport tariffs in the database, so the model used the world median — a factor of 1.10 on the estimate base. I fitted the US level on JetBlue: modelled charges of its network against the report line \"landing fees and other rents\" gave {n(k['B6'], 2)}{c_b6}. Alaska Air Group gave {n(k['ALK'], 2)}{c_alk}, but only as an order-of-magnitude check: 73% of the group's departures made it into the calculation, and correcting only for Hawaiian's Boeing 717 the factor would be about {n(k['ALK_717_only'], 2)}. The remaining +29% at Southwest is not yet explained; my hypothesis is long-term agreements at its bases, untested.",
        f"Für US-Flughäfen gibt es keine Entgeltordnungen in der Datenbank, also nahm das Modell den Weltmedian — Faktor 1,10 auf die Schätzbasis. Das US-Niveau habe ich an JetBlue angepasst: Modellentgelte seines Netzes gegen die Berichtszeile „Landing fees and other rents“ ergaben {n(k['B6'], 2)}{c_b6}. Alaska Air Group ergab {n(k['ALK'], 2)}{c_alk}, aber nur als Größenordnung: 73 % der Abflüge der Gruppe flossen ein, und mit Korrektur nur für die Boeing 717 von Hawaiian läge der Faktor bei etwa {n(k['ALK_717_only'], 2)}. Der Rest von +29 % bei Southwest ist noch ungeklärt; meine Hypothese sind Langfristverträge an seinen Basen, ungeprüft.") + "</p>")
    crow = "".join(f'<tr{" class=dimrow" if c in ("F9", "WN") else ""}><td>{e(v["name"])}{" · " + T("проверка", "check", "Prüfung") if c in ("F9", "WN") else ""}</td>'
                   f'<td class="r">{n(v["cockpit_per_bh"])}</td><td class="r">{n(v.get("model_before_per_bh"))}</td></tr>'
                   for c, v in sorted(crew.items(), key=lambda x: -x[1]["cockpit_per_bh"]))
    body.append("<h3>" + T("Экипаж: европейский уровень оплаты против американского", "Crew: European pay level versus American", "Crew: europäisches gegen amerikanisches Lohnniveau") + "</h3><p>" + T(
        f"Ставка экипажа в модели — европейского уровня: около 800 евро за блок-час за весь экипаж. В США одни пилоты стоят 1 300–1 950 USD. Множитель для США — {n(FL['crew_factor'], 2)}, подобран по семи перевозчикам вне проверки (пилоты × 1,56 против экипажа модели, взвешено по блок-часам). На Southwest он дал −5 %, на Frontier — +58 %: Frontier платит экипажу на 14–39 % меньше сравнимых компаний. Вывод для калькулятора: уровень оплаты экипажа — свойство перевозчика, и для своей компании его надо задавать на входе.",
        f"The model's crew rate is at a European level: about EUR 800 per block hour for the whole crew. In the US pilots alone cost USD 1,300–1,950. The US factor is {n(FL['crew_factor'], 2)}, fitted on seven carriers outside the check (pilots × 1.56 against the model's crew, weighted by block hours). At Southwest it gave −5%, at Frontier +58%: Frontier pays its crews 14–39% less than comparable airlines. For the calculator: crew pay is a property of the carrier and should be entered for your own airline.",
        f"Der Crew-Satz des Modells liegt auf europäischem Niveau: etwa 800 Euro je Blockstunde für die ganze Crew. In den USA kosten allein die Piloten 1.300–1.950 USD. Der US-Faktor ist {n(FL['crew_factor'], 2)}, angepasst an sieben Airlines außerhalb der Prüfung (Piloten × 1,56 gegen Modell-Crew, gewichtet nach Blockstunden). Bei Southwest ergab er −5 %, bei Frontier +58 %: Frontier zahlt seinen Crews 14–39 % weniger als vergleichbare Airlines. Für den Rechner: Das Lohnniveau ist eine Eigenschaft der Airline und gehört für die eigene Airline in die Eingabe.") + "</p>")
    body.append(f'<details><summary>{T("Пилоты по перевозчикам, USD за блок-час", "Pilots by carrier, USD per block hour", "Piloten je Airline, USD je Blockstunde")}</summary>'
                f'<div class="tw"><table><tr><th>{T("Перевозчик", "Carrier", "Airline")}</th><th class="r">{T("пилоты, Form 41", "pilots, Form 41", "Piloten, Form 41")}</th>'
                f'<th class="r">{T("весь экипаж в модели до правки", "whole crew in the model before", "ganze Crew im Modell vorher")}</th></tr>{crow}</table></div>'
                f'<p class="small">{T("Средние по парку, взвешенные по блок-часам, 2025 год.", "Fleet averages weighted by block hours, 2025.", "Flottendurchschnitt, gewichtet nach Blockstunden, 2025.")}{c_f41}</p></details>')
    tx = FL["taxi"]["examples"]
    body.append("<h3>" + T("Руление: не 26 минут везде", "Taxi: not 26 minutes everywhere", "Rollzeit: nicht überall 26 Minuten") + "</h3><p>" + T(
        f"Руление в модели было стандартным циклом ИКАО — 26 минут на рейс. В T-100 у каждой строки есть время от колодок до колодок и время в воздухе; их разность — руление обоих концов рейса. По всей сети сумма «руление вылета + руление прилёта» подбирается методом наименьших квадратов для каждого аэропорта: получилась оценка для {n(FL['taxi']['n'])} аэропортов — от {n(tx['KDAL'], 1)} минуты на рейс в Далласе Лав-Филд до {n(tx['KORD'], 1)} в Чикаго О'Хара (половина руления рейса). Frontier после этого попал в блок-часы с точностью 1 %. Southwest — нет: он рулит {n(wn_tx[1])} минут на рейс там, где другим нужно {n(wn_tx[0])}, это свойство его модели работы, а не аэропорта.",
        f"The model's taxi time was the standard ICAO cycle — 26 minutes per flight. In T-100 each row has block-to-block time and airborne time; the difference is taxi at both ends. Across the network the sum \"taxi-out + taxi-in\" is fitted per airport by least squares: estimates for {n(FL['taxi']['n'])} airports, from {n(tx['KDAL'], 1)} minutes per flight at Dallas Love Field to {n(tx['KORD'], 1)} at Chicago O'Hare (half the taxi of a flight). Frontier then matched block hours within 1%. Southwest did not: it taxis {n(wn_tx[1])} minutes per flight where others need {n(wn_tx[0])} — a feature of its operating model, not of the airport.",
        f"Die Rollzeit im Modell war der ICAO-Standardzyklus — 26 Minuten je Flug. In T-100 hat jede Zeile Blockzeit und Flugzeit; die Differenz ist das Rollen an beiden Enden. Über das Netz wird „Abrollen + Anrollen“ je Flughafen nach kleinsten Quadraten angepasst: Schätzungen für {n(FL['taxi']['n'])} Flughäfen, von {n(tx['KDAL'], 1)} Minuten je Flug in Dallas Love Field bis {n(tx['KORD'], 1)} in Chicago O'Hare (halbe Rollzeit eines Flugs). Frontier traf danach die Blockstunden auf 1 %. Southwest nicht: Es rollt {n(wn_tx[1])} Minuten je Flug, wo andere {n(wn_tx[0])} brauchen — eine Eigenschaft seines Betriebsmodells, nicht des Flughafens.") + "</p></section>")

    # ---------- 5. Доходная часть ----------
    body.append("<section><h2>" + T("Что показали проданные билеты", "What the tickets sold show", "Was die verkauften Tickets zeigen") + "</h2>")
    aw = [v["share"] for v in FA["award"].values()]
    body.append("<p>" + T(
        f"Выручку модель считает от рыночной цены: медиану дневных минимумов из кэша агрегатора умножает на коэффициент «средний чек к минимуму». Чтобы проверить коэффициент, я свернул DB1C за июль 2025 — июль 2026 года{c_db1c}. Сначала очистка: тариф в DB1C записан с налогами, и билет за мили стоит ровно сбор безопасности, 5,60 USD. Бонусных билетов — {n(min(aw) * 100, 1)}–{n(max(aw) * 100, 1)} % в каждом месяце; между ними и платными в данных провал (10–15 USD — в сотню раз меньше пассажиров, чем 5–10). Бонусные идут отдельным показателем и в средний тариф не входят.",
        f"The model computes revenue from the market price: the median of daily minimums from the aggregator cache times an \"average fare to minimum\" factor. To check that factor I aggregated DB1C for July 2025 — July 2026{c_db1c}. First the cleaning: DB1C fares include taxes, and an award ticket costs exactly the security fee, USD 5.60. Award tickets are {n(min(aw) * 100, 1)}–{n(max(aw) * 100, 1)}% every month; there is a gap between them and paid fares (USD 10–15 has a hundred times fewer passengers than 5–10). Award tickets are a separate measure and are excluded from the average fare.",
        f"Das Modell rechnet den Erlös vom Marktpreis aus: Median der Tagesminima aus dem Aggregator-Cache mal Faktor „Durchschnittspreis zu Minimum“. Um ihn zu prüfen, habe ich DB1C für Juli 2025 — Juli 2026 verdichtet{c_db1c}. Zuerst die Bereinigung: DB1C-Tarife enthalten Steuern, und ein Prämienticket kostet genau die Sicherheitsgebühr, 5,60 USD. Prämientickets machen jeden Monat {n(min(aw) * 100, 1)}–{n(max(aw) * 100, 1)} % aus; zwischen ihnen und bezahlten Tarifen klafft eine Lücke (10–15 USD hat hundertmal weniger Passagiere als 5–10). Prämientickets sind eine eigene Kennzahl und nicht im Durchschnittspreis.") + "</p>")
    body.append("<h3>" + T(f"Средний оплаченный тариф, прямые рейсы, {n(FA['trend']['panel_pairs'])} пар", f"Average fare paid, nonstop, {n(FA['trend']['panel_pairs'])} pairs", f"Bezahlter Durchschnittstarif, nonstop, {n(FA['trend']['panel_pairs'])} Strecken") + "</h3>" + svg_months(tr))
    body.append("<p>" + T(
        f"За год средний тариф по одному набору пар вырос на {n(growth)} %, медианный рост по отдельной паре — {n(FA['trend']['median_pair_growth'] * 100)} %. Порядок совпадает с официальной статистикой: в июне 2026 года индекс авиатарифов США был на 26,5 % выше, чем годом раньше{c_cpi}.",
        f"Over the year the average fare on the same set of pairs rose {n(growth)}%, the median growth per pair {n(FA['trend']['median_pair_growth'] * 100)}%. The order of magnitude matches official statistics: in June 2026 the US airfare index was 26.5% above a year earlier{c_cpi}.",
        f"Innerhalb eines Jahres stieg der Durchschnittstarif auf denselben Strecken um {n(growth)} %, das mittlere Wachstum je Strecke um {n(FA['trend']['median_pair_growth'] * 100)} %. Die Größenordnung entspricht der amtlichen Statistik: Im Juni 2026 lag der US-Flugpreisindex 26,5 % über dem Vorjahr{c_cpi}.") + "</p>")
    da, db, dr2 = FA["distance"]["weighted"]
    ua, ub, ur2 = FA["distance"]["unweighted"]
    body.append("<h3>" + T("Тариф и дальность", "Fare and distance", "Tarif und Entfernung") + "</h3>"
                + svg_distance(FA["scatter_distance"], da, db)
                + '<p class="small">' + T(f"Точка — пара в октябре 2025 года, размер — пассажиры; линия — регрессия по всем 13 месяцам, взвешенная по пассажирам.",
                                          f"Each dot is a pair in October 2025, size = passengers; the line is the regression over all 13 months, weighted by passengers.",
                                          f"Jeder Punkt ist eine Strecke im Oktober 2025, Größe = Passagiere; die Linie ist die Regression über alle 13 Monate, gewichtet nach Passagieren.") + "</p>")
    body.append("<p>" + T(
        f"Билет на 500 км в среднем стоит почти столько же, сколько на 1 500. Регрессия даёт {n(da)} USD постоянной части и {n(db)} USD на каждую тысячу километров и объясняет {n(dr2 * 100)} % разброса; без взвешивания по пассажирам — всего {n(ur2 * 100)} %. Постоянная часть больше переменной до {n(round(da / db * 10) * 100)} км. Это зеркало себестоимости: аэропорт, наземное обслуживание, цикловая часть ТОиР и экипажа от длины рейса не зависят, поэтому и в цене короткий рейс дорог на километр. Широкая полоса по вертикали на одной дальности — в основном конкуренция: на парах, где почти все пассажиры летят ультралоукостерами, средний тариф около {n(FA['ulcc_share'][-1]['mean'])} USD, а там, где их нет, — {n(FA['ulcc_share'][0]['mean'])} USD.",
        f"A 500 km ticket costs on average almost as much as a 1,500 km one. The regression gives a fixed part of USD {n(da)} plus USD {n(db)} per thousand kilometres and explains {n(dr2 * 100)}% of the variance; unweighted by passengers only {n(ur2 * 100)}%. The fixed part exceeds the variable one up to {n(round(da / db * 10) * 100)} km. It mirrors cost: airport, ground handling and the per-cycle part of maintenance and crew do not depend on flight length, so a short flight is dear per kilometre in price too. The wide vertical band at one distance is mostly competition: on pairs where almost all passengers fly ultra-low-cost carriers the average fare is about USD {n(FA['ulcc_share'][-1]['mean'])}, where there are none it is USD {n(FA['ulcc_share'][0]['mean'])}.",
        f"Ein Ticket über 500 km kostet im Schnitt fast so viel wie eines über 1.500 km. Die Regression ergibt einen festen Teil von {n(da)} USD plus {n(db)} USD je tausend Kilometer und erklärt {n(dr2 * 100)} % der Streuung; ungewichtet nur {n(ur2 * 100)} %. Der feste Teil ist bis {n(round(da / db * 10) * 100)} km größer als der variable. Das spiegelt die Kosten: Flughafen, Abfertigung und der zyklische Teil von Instandhaltung und Crew hängen nicht von der Flugdauer ab, also ist ein kurzer Flug auch im Preis teuer je Kilometer. Das breite senkrechte Band bei gleicher Entfernung ist vor allem Wettbewerb: Wo fast alle Passagiere mit Ultra-Low-Cost-Airlines fliegen, liegt der Durchschnittstarif bei etwa {n(FA['ulcc_share'][-1]['mean'])} USD, wo es keine gibt, bei {n(FA['ulcc_share'][0]['mean'])} USD.") + "</p>")
    bk = FA["booking"]
    brow = "".join(f'<tr><td>{n(b["lo"])}–{n(b["hi"])}</td><td class="r">{n(b["r21"], 2)}</td><td class="r">{n(b["r22"], 2)}</td>'
                   f'<td class="r">{n(b["share21"] * 100)} %</td></tr>' for b in bk)
    body.append("<h3>" + T("Надбавка за позднюю покупку", "Late-purchase premium", "Aufschlag für späte Buchung") + "</h3>"
                + svg_booking(bk) + "<p>" + T(
                    "DB1C делит каждый билет на три группы по тому, за сколько дней до вылета он куплен: до 21 дня, 22–90 и от 91. Столбик — во сколько раз средний тариф группы выше, чем у купленных за 91 день и раньше. Это и есть «динамическое ценообразование» в цифрах: цена держится ровно, пока до вылета больше трёх недель, а в последние три недели авиакомпания продаёт остаток кресел опоздавшим и деловым пассажирам дороже.",
                    "DB1C splits every ticket into three groups by how many days before departure it was bought: up to 21, 22–90 and 91 or more. Each bar shows how many times the group's average fare exceeds that of tickets bought 91+ days out. This is \"dynamic pricing\" in numbers: the price stays flat while departure is more than three weeks away, and in the last three weeks the airline sells the remaining seats to late and business travellers at a premium.",
                    "DB1C teilt jedes Ticket nach der Vorlaufzeit in drei Gruppen: bis 21 Tage, 22–90 und ab 91. Jede Säule zeigt, um welchen Faktor der Durchschnittstarif der Gruppe über dem der 91+ Tage vorher gekauften Tickets liegt. Das ist „dynamische Preisbildung“ in Zahlen: Der Preis bleibt flach, solange der Abflug mehr als drei Wochen entfernt ist, und in den letzten drei Wochen verkauft die Airline die restlichen Sitze teurer an Spät- und Geschäftsreisende.") + "</p>"
                f'<div class="tw"><table><tr><th>{T("Дальность, км", "Distance, km", "Entfernung, km")}</th><th class="r">{T("0–21 день к 91+", "0–21 days to 91+", "0–21 Tage zu 91+")}</th>'
                f'<th class="r">{T("22–90 дней к 91+", "22–90 days to 91+", "22–90 Tage zu 91+")}</th><th class="r">{T("доля покупок за 0–21 день", "share bought 0–21 days out", "Anteil 0–21 Tage vorher")}</th></tr>{brow}</table></div>'
                "<p>" + T("Дороже только последние три недели: между «за месяц-два» и «за три месяца и больше» разницы нет. На коротких парах надбавка больше и поздних покупок больше.",
                          "Only the last three weeks cost more: there is no difference between one-to-two months and three months or more ahead. Short pairs have a larger premium and more late purchases.",
                          "Teurer sind nur die letzten drei Wochen: Zwischen ein bis zwei Monaten und drei Monaten oder mehr gibt es keinen Unterschied. Kurze Strecken haben einen größeren Aufschlag und mehr späte Käufe.") + "</p>")
    cm = FA["carriers_mixed"]
    order = [("SY", "Sun Country"), ("F9", "Frontier"), ("NK", "Spirit"), ("G4", "Allegiant"), ("AS", "Alaska"), ("B6", "JetBlue"),
             ("WN", "Southwest"), ("AA", "American"), ("UA", "United"), ("DL", "Delta")]
    body.append("<h3>" + T("Минимум рынка ставит лоукостер", "The market minimum is set by the low-cost carrier", "Das Marktminimum setzt der Billigflieger") + "</h3>"
                + R.bars([(nm, cm[c], "") for c, nm in order if c in cm], fmt=lambda v: "× " + n(v, 2))
                + '<p class="small">' + T("Средний тариф перевозчика к 10-му перцентилю тарифов пары, на парах, где летают и ультралоукостер, и другой перевозчик.",
                                          "Carrier's average fare to the pair's 10th percentile, on pairs served by both an ultra-low-cost and another carrier.",
                                          "Durchschnittstarif der Airline zum 10. Perzentil der Strecke, auf Strecken mit Ultra-Low-Cost- und anderer Airline.") + "</p>")
    body.append("<p>" + T(
        f"Отсюда напрашивался коэффициент по типу перевозчика. Я подобрал его на других компаниях и проверил на Frontier и Southwest — улучшения не вышло: медианная ошибка {n(FL['conv_by_class']['F9']['new'] * 100)} % и {n(FL['conv_by_class']['WN']['new'] * 100)} % против {n(FL['conv_by_class']['F9']['old'] * 100)} % и {n(FL['conv_by_class']['WN']['old'] * 100)} % у прежней ступеньки. В модель это не вошло. Сработала толщина пары.",
        f"This suggested a factor by carrier type. I fitted it on other airlines and checked it on Frontier and Southwest — no improvement: median error {n(FL['conv_by_class']['F9']['new'] * 100)}% and {n(FL['conv_by_class']['WN']['new'] * 100)}% against {n(FL['conv_by_class']['F9']['old'] * 100)}% and {n(FL['conv_by_class']['WN']['old'] * 100)}% for the old step. It did not go into the model. Pair thickness did work.",
        f"Daraus ergab sich ein Faktor nach Airline-Typ. Ich habe ihn an anderen Airlines angepasst und an Frontier und Southwest geprüft — keine Verbesserung: Medianfehler {n(FL['conv_by_class']['F9']['new'] * 100)} % und {n(FL['conv_by_class']['WN']['new'] * 100)} % gegen {n(FL['conv_by_class']['F9']['old'] * 100)} % und {n(FL['conv_by_class']['WN']['old'] * 100)} % bei der alten Stufe. Das kam nicht ins Modell. Die Stärke der Strecke dagegen wirkte.") + "</p>")

    # формула
    body.append("<h3>" + T("Средний чек к минимуму — по потоку пары", "Average fare to minimum — by pair traffic", "Durchschnittspreis zu Minimum — nach Verkehr") + "</h3>")
    body.append('<p class="formula">' + T("чек = минимум × K · q<sup>β</sup> ÷ r", "fare = minimum × K · q<sup>β</sup> ÷ r", "Preis = Minimum × K · q<sup>β</sup> ÷ r") + "</p>")
    body.append(f'<div class="tw"><table class="txt"><tr><th>{T("Слагаемое", "Term", "Term")}</th><th>{T("Что это", "What it is", "Was es ist")}</th><th class="r">{T("Значение", "Value", "Wert")}</th><th>{T("Откуда", "Source", "Quelle")}</th></tr>'
                f'<tr><td>q</td><td>{T("поток пары, пассажиров в месяц, оба направления, все перевозчики", "pair traffic, passengers a month, both directions, all carriers", "Verkehr der Strecke, Passagiere im Monat, beide Richtungen, alle Airlines")}</td><td class="r">{T("из базы", "from the database", "aus der Datenbank")}</td><td>T-100, Eurostat{c_t100}</td></tr>'
                f'<tr><td>K, β</td><td>{T("средний чек ÷ 10-й перцентиль тарифов пары = K · q<sup>β</sup>", "average fare ÷ the pair\'s 10th percentile = K · q<sup>β</sup>", "Durchschnittspreis ÷ 10. Perzentil = K · q<sup>β</sup>")}</td><td class="r">{n(1.00, 2)}; {n(be, 3)}</td><td>DB1C {T("июль — декабрь 2025, прямые", "July — December 2025, nonstop", "Juli — Dezember 2025, nonstop")}{c_db1c}</td></tr>'
                f'<tr><td>r</td><td>{T("медиана минимумов агрегатора к 10-му перцентилю", "median of aggregator minimums to the 10th percentile", "Median der Aggregator-Minima zum 10. Perzentil")}</td><td class="r">{n(1.37, 2)}</td><td><span class="no">{T("оценка: 13 пар США, слабое звено", "estimate: 13 US pairs, weak link", "Schätzung: 13 US-Strecken, schwaches Glied")}</span></td></tr></table></div>')
    body.append(svg_flow(FA["scatter_flow"], ff["curve"], be) + '<p class="small">' + T(
        "Точка — пара в октябре 2025 года: отношение среднего оплаченного тарифа к 10-му перцентилю тарифов пары против потока пары из T-100. Шкала потока логарифмическая. Ступенька пересчитана к 10-му перцентилю (× 1,37), чтобы её можно было сравнить с данными.",
        "Each dot is a pair in October 2025: the ratio of the average fare paid to the pair's 10th-percentile fare against pair traffic from T-100. The traffic axis is logarithmic. The step is converted to the 10th percentile (× 1.37) so it can be compared with the data.",
        "Jeder Punkt ist eine Strecke im Oktober 2025: Verhältnis des bezahlten Durchschnittstarifs zum 10. Perzentil gegen den Verkehr aus T-100. Die Verkehrsachse ist logarithmisch. Die Stufe ist aufs 10. Perzentil umgerechnet (× 1,37), damit sie mit den Daten vergleichbar ist.") + "</p>")
    body.append("<p>" + T(
        "Почему на толстой паре разрыв больше — данные этого не доказывают, но объяснение из практики управления доходами такое: там больше рейсов в день и больше разных пассажиров — и туристы, которые покупают за месяцы по акции, и деловые, которые берут билет за день. Авиакомпания открывает дешёвые классы бронирования, чтобы заполнить самолёт заранее, и держит дорогие для поздних покупателей. На тонкой паре рейс один-два в день, разброс пассажиров меньше, и цены плотнее. Прежняя ступенька «1,2 или 2,0» перепрыгивала эту плавную зависимость: на парах 20–80 тыс. пассажиров в месяц она недооценивала средний чек на четверть.",
        "Why the gap is wider on thick pairs — the data do not prove it, but the revenue-management explanation is: there are more flights a day and a wider mix of passengers — tourists who buy months ahead on promotions and business travellers who buy the day before. The airline opens cheap booking classes to fill the aircraft early and keeps dear ones for late buyers. On a thin pair there are one or two flights a day, a narrower mix and tighter prices. The old \"1.2 or 2.0\" step jumped over this smooth relationship: on pairs with 20–80k passengers a month it underestimated the average fare by a quarter.",
        "Warum der Abstand auf starken Strecken größer ist — die Daten beweisen es nicht, aber die Erklärung aus dem Revenue Management lautet: mehr Flüge am Tag und gemischtere Passagiere — Touristen, die Monate vorher im Angebot buchen, und Geschäftsreisende, die am Vortag kaufen. Die Airline öffnet billige Buchungsklassen, um das Flugzeug früh zu füllen, und hält teure für Spätbucher zurück. Auf schwachen Strecken gibt es ein, zwei Flüge am Tag, weniger Mischung und engere Preise. Die alte Stufe „1,2 oder 2,0“ übersprang diesen glatten Zusammenhang: Bei 20–80 Tsd. Passagieren im Monat unterschätzte sie den Durchschnittspreis um ein Viertel.") + "</p>")
    rr = "".join(f'<tr><td>{n(b["lo"] / 1e3)}–{"∞" if b["hi"] > 1e9 else n(b["hi"] / 1e3)}</td><td class="r">{n(b["step"]["bias"] * 100, 0, sign=True)} %</td>'
                 f'<td class="r">{n(b["step"]["mae"] * 100)} %</td><td class="r">{n(b["flow"]["bias"] * 100, 0, sign=True)} %</td><td class="r">{n(b["flow"]["mae"] * 100)} %</td></tr>'
                 for b in ff["bands"])
    body.append("<p>" + T(
        f"Подбор — на половине пар, проверка — на другой половине ({n(ff['n_test'])} пар-месяцев). Медианная ошибка — {n(ff['all']['flow']['mae'] * 100)} % против {n(ff['all']['step']['mae'] * 100)} % у ступеньки «1,2 или 2,0», а главное — ушло систематическое занижение на парах 20–80 тыс. пассажиров в месяц.",
        f"Fitted on half the pairs, checked on the other half ({n(ff['n_test'])} pair-months). Median error {n(ff['all']['flow']['mae'] * 100)}% against {n(ff['all']['step']['mae'] * 100)}% for the \"1.2 or 2.0\" step, and above all the systematic underestimate on pairs with 20–80k passengers a month is gone.",
        f"Angepasst an der Hälfte der Strecken, geprüft an der anderen ({n(ff['n_test'])} Strecken-Monate). Medianfehler {n(ff['all']['flow']['mae'] * 100)} % gegen {n(ff['all']['step']['mae'] * 100)} % bei der Stufe „1,2 oder 2,0“, vor allem verschwindet die systematische Unterschätzung bei 20–80 Tsd. Passagieren im Monat.") + "</p>")
    body.append(f'<div class="tw"><table><tr><th>{T("Поток, тыс. пасс./мес", "Traffic, k pax/month", "Verkehr, Tsd. Pax/Monat")}</th><th class="r">{T("ступенька: смещение", "step: bias", "Stufe: Verzerrung")}</th><th class="r">{T("ступенька: ошибка", "step: error", "Stufe: Fehler")}</th>'
                f'<th class="r">{T("по потоку: смещение", "by traffic: bias", "nach Verkehr: Verzerrung")}</th><th class="r">{T("по потоку: ошибка", "by traffic: error", "nach Verkehr: Fehler")}</th></tr>{rr}</table></div></section>')

    # ---------- 6. Что меняем ----------
    li = [("in_calc", T("Аэронавигация: рейс с посадкой или вылетом в США за небо США не платит.", "Air navigation: a flight landing or departing in the US pays nothing for US airspace.", "Flugsicherung: Ein Flug mit Start oder Landung in den USA zahlt nichts für den US-Luftraum.")),
          ("in_calc", T("Аэропортовые сборы США без тарифа: коэффициент 0,86 вместо мировых 1,10.", "US airport charges without a tariff: factor 0.86 instead of the world 1.10.", "US-Flughafenentgelte ohne Tarif: Faktor 0,86 statt weltweit 1,10.")),
          ("in_calc", T("Экипаж на рейсах из США: × 2,88 к заготовке; своя ставка через ввод главнее.", "Crew on flights from the US: × 2.88 on the default; your own rate overrides it.", "Crew auf Flügen ab den USA: × 2,88 auf den Standard; eigener Satz hat Vorrang.")),
          ("in_calc", T("Руление по аэропортам из T-100 вместо 26 минут; аэропорт без оценки — по стандарту ИКАО.", "Taxi time by airport from T-100 instead of 26 minutes; airports without an estimate use the ICAO standard.", "Rollzeit je Flughafen aus T-100 statt 26 Minuten; ohne Schätzung gilt der ICAO-Standard.")),
          ("in_calc", T("Средний чек к минимуму — плавно по потоку пары вместо ступеньки 1,2/2,0.", "Average fare to minimum — smoothly by pair traffic instead of the 1.2/2.0 step.", "Durchschnittspreis zu Minimum — stufenlos nach Verkehr statt Stufe 1,2/2,0.")),
          ("in_calc", T("Аэропорт, сменивший код в справочнике, находится по ИКАО (так выпадал Палм-Бич).", "An airport whose code changed in the reference is found by ICAO (this is how Palm Beach dropped out).", "Ein Flughafen mit geändertem Code wird über ICAO gefunden (so fiel Palm Beach heraus).")),
          ("planned", T("Поправка расхода для Boeing 737: у 737-700 модель недобирает 14 %.", "Fuel burn correction for the Boeing 737: the model runs 14% low on the 737-700.", "Verbrauchskorrektur für die Boeing 737: Das Modell liegt bei der 737-700 14 % zu niedrig.")),
          ("planned", T("Тарифы крупных аэропортов США вместо региональной оценки.", "Tariffs of major US airports instead of a regional estimate.", "Entgeltordnungen großer US-Flughäfen statt regionaler Schätzung.")),
          ("planned", T("Ставка экипажа как вход по перевозчику, с подсказкой по классу компании.", "Crew rate as a per-carrier input, with a hint by carrier class.", "Crew-Satz als Eingabe je Airline, mit Richtwert nach Typ."))]
    body.append("<section><h2>" + T("Что меняется в калькуляторе", "What changes in the calculator", "Was sich im Rechner ändert") + "</h2><ol>"
                + "".join(f"<li>{mark(k)}{t}</li>" for k, t in li) + "</ol></section>")

    # ---------- 7. Отчёт ----------
    body.append("<section><h2>" + T("Отчёт", "Report", "Bericht") + "</h2>")
    body.append("<details><summary>" + T("Как проверялось и чего нет", "How it was checked and what is missing", "Wie geprüft wurde und was fehlt") + "</summary><p>" + T(
        "Каждое число черновика пересчитал отдельный агент, не участвовавший в расчёте: две грубые ошибки (число записей и путаница метрик роста цен), неверно описанная сверка Alaska и несколько выводов сильнее данных исправлены до публикации. Чего нет: бортпроводников по типам (оценка по структуре IATA ACMG), тарифов аэропортов США, калибровки расхода для Боингов. Перевод минимума агрегатора в 10-й перцентиль опирается на 13 пар первого сбора цен — его уточнит еженедельный сбор по 30 парам США. Сырые выгрузки T-100, DB1C и база в репозиторий не кладутся; скрипты и агрегаты — в папке исследования.",
        "Every number of the draft was recomputed by a separate agent not involved in the calculation: two gross errors (record count and mixed-up price-growth metrics), a misdescribed Alaska check and several conclusions stronger than the data were fixed before publication. Missing: cabin crew by type (estimated from the IATA ACMG structure), US airport tariffs, a fuel calibration for Boeings. Converting the aggregator minimum to the 10th percentile rests on 13 pairs of the first price collection — weekly collection on 30 US pairs will refine it. Raw T-100, DB1C extracts and the database are not committed; scripts and aggregates are in the research folder.",
        "Jede Zahl des Entwurfs hat ein separater Agent nachgerechnet, der an der Rechnung nicht beteiligt war: zwei grobe Fehler (Datensatzzahl und verwechselte Preiswachstums-Kennzahlen), eine falsch beschriebene Alaska-Prüfung und einige zu starke Schlüsse wurden vor der Veröffentlichung korrigiert. Es fehlen: Kabinenpersonal je Typ (geschätzt nach IATA ACMG), US-Flughafentarife, eine Verbrauchskalibrierung für Boeing. Die Umrechnung vom Aggregator-Minimum zum 10. Perzentil beruht auf 13 Strecken der ersten Preissammlung — die wöchentliche Sammlung auf 30 US-Strecken wird sie verfeinern. Rohdaten von T-100, DB1C und die Datenbank liegen nicht im Repository; Skripte und Aggregate im Forschungsordner.") + "</p></details>")
    body.append(S.html() + "</section>")
    return page(article_title(SLUG), "".join(body))


if __name__ == "__main__":
    write_all(HERE, SLUG, build)
