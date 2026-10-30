#!/usr/bin/env python3
"""Статья «Сколько стоит авиатопливо: мир и Россия» — HTML в оформлении сайта, на трёх языках.

Структура — research/STYLE.md; ориентир каждого раздела — как это меняет расчёт
рейса. Данные: out/fuel.json (мир), out/ru.json (Россия); проверка —
verify/f1.json, verify/r1.json; ссылки на источники — из журналов trace/*.jsonl.
Тексты — T(ru, en, de); строки из данных — i18n.yaml (Tr); деньги — money().

    python3 research/fuel-2026-10/build_report.py      # из корня репозитория → report.html, report.en.html, report.de.html
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
from _report import (Sources, T, Tr, article_title, calc_badge, chain, e,  # noqa: E402
                     line_chart, mark, money, n, page, write_all)
import _report  # noqa: E402

J = lambda p: json.loads((HERE / p).read_text(encoding="utf-8"))  # noqa: E731
D, RU = J("out/fuel.json"), J("out/ru.json")
VF, VR = J("verify/f1.json"), J("verify/r1.json")
S = Sources(HERE)
TR = Tr(HERE)
cite = S.cite


def ev(name):
    return next(r for r in D["regions"] if r["region"].startswith(name))["evidence"]


# ── Россия «сегодня» (сентябрь 2026) в той же мере, что регионы ───────────
# Биржа ТС-1 — с НДС (22 % в 2026): переводим в цену без НДС, добавляем наценку
# ТЗК группы аэропортов и сбор за заправку, переводим в $ по курсу ЦБ и делим на
# USGC того же месяца. Наценки — прейскурант без НДС к бирже месяца без НДС.
RU_EX, RU_FX, RU_USGC = 126_263 / 1.22, 85.04, 1355           # сентябрь 2026
RU_DAMPER = 58_421 + 3_024                                     # демпфер + обратный акциз
RU_GROUPS = {"Центр": (0.285, 2210), "Сибирь": (0.18, 3758), "Дальний Восток": (0.68, 4225)}


def ru_mult(markup, fee, damper=0):
    return ((RU_EX * (1 + markup) + fee - damper) / RU_FX) / RU_USGC


RU_MID = ru_mult(*RU_GROUPS["Центр"])
RU_LO, RU_HI = ru_mult(*RU_GROUPS["Сибирь"]), ru_mult(*RU_GROUPS["Дальний Восток"])
RU_NET = ru_mult(*RU_GROUPS["Центр"], damper=RU_DAMPER)

# Названия регионов: ключ — русское (на нём держатся расчёты и сравнения), подпись — по языку.
REG = {"Северная Америка": ("North America", "Nordamerika"), "Европа": ("Europe", "Europa"),
       "Ближний Восток": ("Middle East", "Naher Osten"), "Азия и Океания": ("Asia and Oceania", "Asien und Ozeanien"),
       "Россия": ("Russia", "Russland"), "Африка": ("Africa", "Afrika"),
       "Латинская Америка": ("Latin America", "Lateinamerika"),
       "Казахстан и СНГ": ("Kazakhstan and CIS", "Kasachstan und GUS"), "Индия": ("India", "Indien")}


def reg(name):
    return T(name, *REG[name])


# Итог для модели: (регион, множитель «в крыло» к USGC, диапазон, уверенность,
# на чём держится — (ru, en, de), шаги журнала). «{net}» — множитель России после демпфера.
MODEL = [
    ("Северная Америка", 1.08, (1.04, 1.18), "средняя",
     ("статистика BTS 2025", "BTS statistics 2025", "BTS-Statistik 2025"), ev("North")),
    ("Европа", 1.10, (1.05, 1.15), "низкая",
     ("спот ×1,05 + примесь SAF 2 %; надбавка «в крыло» — допущение",
      "spot ×1.05 + 2 % SAF blend; the into-plane add-on is an assumption",
      "Spot ×1,05 + 2 % SAF-Beimischung; der Aufschlag ins Flugzeug ist eine Annahme"), ev("Europe")),
    ("Ближний Восток", 1.10, (0.90, 1.20), "низкая",
     ("спот ×0,90–1,04; «в крыло» IATA 2023 ≈ ×1,2", "spot ×0.90–1.04; into-plane IATA 2023 ≈ ×1.2",
      "Spot ×0,90–1,04; ins Flugzeug IATA 2023 ≈ ×1,2"), ev("Middle")),
    ("Азия и Океания", 1.10, (0.95, 1.20), "заглушка",
     ("только спот ×0,95–1,05", "spot only ×0.95–1.05", "nur Spot ×0,95–1,05"), ev("Asia")),
    ("Россия", RU_MID, (RU_LO, RU_HI), "низкая",
     ("биржа ТС-1 без НДС + наценка ТЗК; после демпфера ×{net}",
      "TS-1 jet fuel on the exchange excl. VAT + TZK mark-up; after the damper ×{net}",
      "Börsenpreis TS-1 ohne MwSt. + TZK-Aufschlag; nach dem Dämpfer ×{net}"), ["r1-067", "r1-026", "r1-030", "r1-021"]),
    ("Африка", 1.20, (1.10, 2.00), "низкая",
     ("AFRAA: +17 % к мировой средней", "AFRAA: +17 % above the world average", "AFRAA: +17 % über dem Weltdurchschnitt"),
     ev("Africa")),
    ("Латинская Америка", 1.22, (1.21, 1.24), "низкая",
     ("одна авиакомпания (LATAM 2025)", "a single airline (LATAM 2025)", "eine einzige Airline (LATAM 2025)"), ev("Latin")),
    ("Казахстан и СНГ", 1.45, (1.39, 1.49), "низкая",
     ("Казахстан, январь 2026", "Kazakhstan, January 2026", "Kasachstan, Januar 2026"), ev("CIS")),
    ("Индия", 1.47, (1.30, 1.90), "низкая",
     ("Дели, международные рейсы, май 2026; внутренние — + налоги",
      "Delhi, international flights, May 2026; domestic — plus taxes",
      "Delhi, internationale Flüge, Mai 2026; Inland — plus Steuern"), ev("South Asia")),
]
CONF = {"средняя": "var(--sky)", "низкая": "var(--orange)", "заглушка": "var(--orange)"}
CONF_T = {"средняя": ("medium", "mittel"), "низкая": ("low", "niedrig"), "заглушка": ("placeholder", "Platzhalter")}


def why(w):
    return T(*w).replace("{net}", n(RU_NET, 2))


# Пример расчёта: A320 Франкфурт — Барселона, 80 % загрузки — топливо по цене USGC
# в калькуляторе FlightCost (расчётное ядро, 30.10.2026): 4,49 т, 3 502 EUR.
EX_FUEL_T, EX_COST = 4.49, 3502

# Спот USGC по месяцам, $/т (FRED, ×332 гал/т) — шаги журнала r1.
USGC = {"2025-07": (745, "r1-176"), "2025-08": (672, "r1-176"), "2026-01": (674, "r1-171"),
        "2026-03": (1227, "r1-172"), "2026-04": (1304, "r1-177"), "2026-06": (1010, "r1-173"),
        "2026-07": (1130, "r1-174"), "2026-08": (1236, "r1-175"), "2026-09": (1355, "r1-179")}


def whisker() -> str:
    lo_, hi_ = 0.5, 2.1
    W, L, R, ROW = 760, 190, 70, 30
    X = lambda v: L + (v - lo_) / (hi_ - lo_) * (W - L - R)   # noqa: E731
    H = 26 + ROW * len(MODEL)
    g = []
    for t in (0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0):
        sw = ' stroke-width="2"' if t == 1.0 else ""
        g.append(f'<line x1="{X(t):.1f}" x2="{X(t):.1f}" y1="14" y2="{H - 14}" stroke="var(--line)"{sw}/>'
                 f'<text x="{X(t):.1f}" y="{H - 2}" text-anchor="middle" class="ax">×{n(t, 1)}</text>')
    for i, (name, m, (a, b), conf, _, _) in enumerate(MODEL):
        y, col = 26 + i * ROW, CONF[conf]
        g.append(f'<text x="{L - 10}" y="{y + 4}" text-anchor="end" class="lab2">{e(reg(name))}</text>'
                 f'<line x1="{X(a):.1f}" x2="{X(b):.1f}" y1="{y}" y2="{y}" stroke="{col}" stroke-width="2"/>'
                 f'<line x1="{X(a):.1f}" x2="{X(a):.1f}" y1="{y - 5}" y2="{y + 5}" stroke="{col}"/>'
                 f'<line x1="{X(b):.1f}" x2="{X(b):.1f}" y1="{y - 5}" y2="{y + 5}" stroke="{col}"/>'
                 f'<circle cx="{X(m):.1f}" cy="{y}" r="5" fill="{col}"/>'
                 f'<text x="{X(b) + 8:.1f}" y="{y + 4}" class="lab" fill="var(--ink2)">×{n(m, 2)}</text>')
        if name == "Россия":
            g.append(f'<circle cx="{X(RU_NET):.1f}" cy="{y}" r="5" fill="none" stroke="var(--green)" stroke-width="2"/>'
                     f'<text x="{X(RU_NET):.1f}" y="{y - 9}" text-anchor="middle" class="ax">'
                     f'{T("после демпфера", "after the damper", "nach dem Dämpfer")}</text>')
    return f'<svg viewBox="0 0 {W} {H}" class="chart" role="img">{"".join(g)}</svg>'


def world_chart() -> str:
    """Цена «в крыло», $/т: в среднем по регионам, самый дорогой и самый дешёвый."""
    mults = {r: m for r, m, *_ in MODEL}
    avg = sum(mults.values()) / len(mults)
    top = max(mults, key=mults.get)
    low = min(mults, key=mults.get)
    months = sorted(USGC)
    idx = {m: i for i, m in enumerate(months)}
    ser = [(f"{reg(top)} ×{n(mults[top], 2)}", "var(--orange)", {idx[m]: USGC[m][0] * mults[top] for m in months}, False),
           (f"{T('в среднем', 'average', 'Durchschnitt')} ×{n(avg, 2)}", "var(--ink2)",
            {idx[m]: USGC[m][0] * avg for m in months}, False),
           (f"{reg(low)} ×{n(mults[low], 2)}", "var(--sky)", {idx[m]: USGC[m][0] * mults[low] for m in months}, False)]
    svg = line_chart(ser, w=720, ylab=T("{cur} за тонну в баке", "{cur} per tonne in the tank", "{cur} je Tonne im Tank"),
                     x_every=1, cur="USD")
    for m, i in idx.items():
        svg = svg.replace(f'class="ax">{i}</text>', f'class="ax">{m[5:]}.{m[2:4]}</text>')
    return svg, avg, top, low


def ap_date(d) -> str:
    """Месяц цены аэропорта: «2026-06». Только год и месяц, без пояснений из данных."""
    s = str(d)[:7]
    m = re.match(r"\d{4}(-\d{2})?", str(d))
    return m.group() if m else s


def build() -> str:
    sf = Counter(x["status"] for k, x in VF.items() if not k.startswith("_"))
    sr = Counter(x["status"] for k, x in VR.items() if not k.startswith("_"))
    chart, avg, top, low = world_chart()
    mults = {r: m for r, m, *_ in MODEL}
    today = USGC["2026-09"][0]
    d_eu = round(EX_COST * (mults['Европа'] - 1), -1)
    d_af = round(EX_COST * (mults['Африка'] - 1), -1)
    d_in = round(EX_COST * (mults['Индия'] - 1), -1)
    x_lo, x_hi = n(1.08, 2), n(1.47, 2)
    ru_mid, ru_net = n(RU_MID, 2), n(RU_NET, 2)

    # 1. хук — сразу о расчёте
    hook = f"""<h1>{T("Сколько стоит авиатопливо: мир и Россия", "What jet fuel costs: the world and Russia",
                    "Was Kerosin kostet: die Welt und Russland")}</h1>
<p class="meta">{T("Исследование FlightCostApp, октябрь 2026 · как цена топлива в разных странах меняет расчёт рейса",
                   "FlightCostApp research, October 2026 · how fuel prices in different countries change the cost of a flight",
                   "FlightCostApp-Recherche, Oktober 2026 · wie der Kerosinpreis in verschiedenen Ländern die Flugkosten "
                   "verändert")}</p>
{calc_badge("fuel-2026-10")}
<div class="verdict">
<div><b>{T("Треть затрат рейса", "A third of a flight's cost", "Ein Drittel der Flugkosten")}</b><span>{T(
        "топливо — около 30 % расходов авиакомпании, у лоукостеров больше 40 %\n",
        "fuel is about 30 % of an airline's costs, over 40 % at low-cost carriers\n",
        "Kerosin macht etwa 30 % der Kosten einer Airline aus, bei Billigfliegern über 40 %\n")}{cite('f1-034', 'f1-115')}</span></div>
<div><b>{T("Оптом — почти одинаково", "Wholesale — almost the same everywhere", "Im Großhandel — fast überall gleich")}</b><span>{T(
        "оптовая цена в регионах мира отличается от американской не больше чем на\n10 %",
        "wholesale prices in the world's regions differ from the US price by no more than 10 %",
        "der Großhandelspreis in den Weltregionen weicht vom US-Preis um höchstens 10 % ab")
        }{cite('f1-005', 'f1-006', 'f1-038')}</span></div>
<div><b>{T(f"«В баке» — от ×{x_lo} до ×{x_hi}", f"Into-plane — from ×{x_lo} to ×{x_hi}",
           f"Ins Flugzeug — von ×{x_lo} bis ×{x_hi}")}</b><span>{T(
        "доставка, хранение, налоги и примеси дают разницу до половины цены\n",
        "delivery, storage, taxes and blending make a difference of up to half the price\n",
        "Transport, Lagerung, Steuern und Beimischungen machen bis zur Hälfte des Preises aus\n")
        }{cite('f1-056', 'f1-099', 'f1-068')}</span></div>
<div><b>{T("Россия — после демпфера дешевле всех", "Russia — the cheapest of all after the damper",
           "Russland — nach dem Dämpfer am billigsten")}</b><span>{T(
        f"в сентябре 2026 ×{ru_mid} к американской цене, а с учётом\nвозврата из бюджета — ×{ru_net}",
        f"in September 2026 ×{ru_mid} of the US price, and ×{ru_net} after the refund from the state budget",
        f"im September 2026 ×{ru_mid} zum US-Preis, nach der Erstattung aus dem Staatshaushalt ×{ru_net}")
        }{cite('r1-067', 'r1-068')}</span></div></div>
<p class="lede">{T(
        f"До этого исследования калькулятор считал топливо везде по одной американской цене. Для рейса A320 из\n"
        f"Франкфурта в Барселону это {money(EX_COST)} за {n(EX_FUEL_T, 1)} т. Тот же рейс с ценой «в баке» Европы — так он\n"
        f"считается теперь — стоит на\n"
        f"{money(d_eu)} больше, Африки — на {money(d_af)},\n"
        f"Индии — на {money(d_in)}. Ниже — откуда эти множители и насколько им можно верить.",
        f"Before this research the calculator priced fuel everywhere at a single US price. For an A320 flight from "
        f"Frankfurt to Barcelona that is {money(EX_COST)} for {n(EX_FUEL_T, 1)} t. The same flight at Europe's into-plane "
        f"price — which is how it is calculated now — costs "
        f"{money(d_eu)} more, at Africa's {money(d_af)} more, at India's {money(d_in)} more. Below: where these "
        f"multipliers come from and how far they can be trusted.",
        f"Vor dieser Recherche bewertete der Rechner Kerosin überall mit einem einzigen US-Preis. Für einen A320-Flug von "
        f"Frankfurt nach Barcelona sind das {money(EX_COST)} für {n(EX_FUEL_T, 1)} t. Derselbe Flug kostet zum Preis ins "
        f"Flugzeug in Europa — so wird er jetzt gerechnet — {money(d_eu)} mehr, in Afrika {money(d_af)} mehr, in Indien {money(d_in)} mehr. Unten: woher diese "
        f"Faktoren kommen und wie weit man ihnen trauen kann.")}</p>"""

    # 2. теория — коротко
    theory = f"""<section><h2>{T("Откуда разница: путь тонны керосина",
                                 "Where the difference comes from: the journey of a tonne of jet fuel",
                                 "Woher der Unterschied kommt: der Weg einer Tonne Kerosin")}</h2>
{chain([(T("НПЗ", "Refinery", "Raffinerie"), T("керосин из нефти", "jet fuel from crude oil", "Kerosin aus Rohöl")),
        (T("Спот или биржа", "Spot or exchange", "Spot oder Börse"),
         T("оптовая цена в узле: USGC, Сингапур, Роттердам, биржа СПб",
           "wholesale price at a hub: USGC, Singapore, Rotterdam, St Petersburg exchange",
           "Großhandelspreis an einem Knotenpunkt: USGC, Singapur, Rotterdam, Börse St. Petersburg")),
        (T("Доставка", "Delivery", "Transport"), T("трубопровод, танкер, вагон", "pipeline, tanker, rail tank car",
                                                   "Pipeline, Tanker, Kesselwagen")),
        (T("ТЗК аэропорта", "Airport fuel supplier", "Betankungsdienst am Flughafen"),
         T("хранение, контроль, заправщик, маржа", "storage, quality control, refueller, margin",
           "Lagerung, Qualitätskontrolle, Tankwagen, Marge")),
        (T("«В крыло»", "Into-plane", "Ins Flugzeug"), T("тонна в баке + налоги и примеси",
                                                          "a tonne in the tank + taxes and blends",
                                                          "eine Tonne im Tank + Steuern und Beimischungen"))])}
<p>{T("<b>Спот</b> — оптовая цена партиями в тысячи тонн. Ориентир калькулятора — побережье Мексиканского залива США\n"
      "(USGC), его ежедневно публикует Управление энергетической информации США",
      "<b>Spot</b> is the wholesale price for lots of thousands of tonnes. The calculator's benchmark is the US Gulf Coast "
      "spot (USGC), published daily by the US Energy Information Administration (EIA)",
      "<b>Spot</b> ist der Großhandelspreis für Partien von Tausenden Tonnen. Bezugspunkt des Rechners ist der Spot am "
      "US-Golf (USGC), den die US-Energieinformationsbehörde (EIA) täglich veröffentlicht")}{cite('f1-038')}.
{T("<b>Цена «в крыло»</b> — то, что авиакомпания платит за тонну в баке: к споту добавляются доставка, хранение, услуги\n"
   "топливозаправочного комплекса аэропорта (ТЗК) и налоги. Именно её и нужно считать в рейсе.",
   "<b>The into-plane price</b> is what an airline pays for a tonne in the aircraft's tank: delivery, storage, the "
   "services of the airport's into-plane fuel supplier (in Russia, the TZK) and taxes are added to the spot. This is the "
   "price a flight has to be costed at.",
   "<b>Der Preis ins Flugzeug („into-plane“)</b> ist das, was eine Airline für eine Tonne im Tank zahlt: Zum Spot kommen "
   "Transport, Lagerung, die Leistungen des Betankungsdienstleisters am Flughafen (in Russland TZK) und Steuern hinzu. "
   "Genau mit diesem Preis muss ein Flug gerechnet werden.")}</p>
<p>{T("<b>Керосин — не нефть.</b> Разница между ценой керосина и нефти (crack spread, «маржа переработки») до 2021 года\n"
      "держалась около 10–20 $ за баррель, а в 2022 и в 2026 году доходила до 60–90 $: в кризис керосин дорожает быстрее\n"
      "нефти (график IATA Jet Fuel Price Monitor по данным S&amp;P Global Platts). Поэтому калькулятор берёт цену именно\n"
      "керосина, а не пересчитывает её из нефти.",
      "<b>Jet fuel is not crude oil.</b> The gap between the price of jet fuel and crude (the crack spread, the “refining "
      "margin”) stayed at about $10–20 a barrel until 2021, but reached $60–90 in 2022 and again in 2026: in a crisis jet "
      "fuel gets dearer faster than crude (IATA Jet Fuel Price Monitor chart based on S&amp;P Global Platts data). That is "
      "why the calculator takes the price of jet fuel itself rather than deriving it from crude.",
      "<b>Kerosin ist nicht Rohöl.</b> Der Abstand zwischen Kerosin- und Rohölpreis (Crack-Spread, „Raffineriemarge“) lag "
      "bis 2021 bei etwa 10–20 $ je Barrel, erreichte 2022 und 2026 aber 60–90 $: In der Krise verteuert sich Kerosin "
      "schneller als Rohöl (Grafik des IATA Jet Fuel Price Monitor nach Daten von S&amp;P Global Platts). Deshalb nimmt "
      "der Rechner den Kerosinpreis selbst, statt ihn aus dem Ölpreis abzuleiten.")}</p>
<p>{T("На международных рейсах топливо почти везде без налогов; на внутренних бывают налоги (Индия — налог штата 1–29 % и\n"
      "акциз 11 %",
      "On international flights fuel is untaxed almost everywhere; domestic flights can carry taxes (India: a state tax of "
      "1–29 % and an excise of 11 %",
      "Auf internationalen Flügen ist Kerosin fast überall steuerfrei; auf Inlandsflügen gibt es teils Steuern (Indien: "
      "Steuer des Bundesstaats von 1–29 % und Verbrauchsteuer von 11 %")}{cite('f1-075', 'f1-084')}){T(
      ", в ЕС — обязательная примесь 2 % экологичного топлива, около +4 % к цене\n",
      "; in the EU the mandatory 2 % blend of sustainable aviation fuel (SAF) adds about 4 % to the price",
      "; in der EU verteuert die Pflichtbeimischung von 2 % nachhaltigem Flugkraftstoff (SAF) den Preis um etwa 4 %")
      }{cite('f1-129', 'f1-131')}. {T(
      "В России цена складывается на бирже в рублях, а государство возвращает авиакомпаниям часть\n"
      "через <b>демпфер</b> — налоговый вычет, зависящий от разницы внутренней и экспортной цены",
      "In Russia the price is set on the exchange in roubles, and the state returns part of it to airlines through the "
      "<b>damper</b> — Russia's fuel price compensation mechanism: a tax deduction that depends on the gap between the "
      "domestic and the export price",
      "In Russland bildet sich der Preis an der Börse in Rubel, und der Staat erstattet den Airlines einen Teil über den "
      "<b>Dämpfer</b> — einen Steuerabzug, der von der Differenz zwischen Inlands- und Exportpreis abhängt")
      }{cite('r1-041', 'r1-046')}.</p></section>"""

    # 3. аналитика — точки и динамика
    analytics = f"""<section><h2>{T("Сколько платят в разных регионах", "What airlines pay in different regions",
                                     "Was Airlines in verschiedenen Regionen zahlen")}</h2>
<p>{T("Множитель цены «в баке» к американскому споту: точка — оценка, линия — разброс. Синим — подтверждено статистикой,\n"
      "оранжевым — одна точка или допущение. Для России — сентябрь 2026, полый кружок — после возврата демпфера.",
      "Multiplier of the into-plane price to the US spot: dot — estimate, line — range. Blue — backed by statistics, "
      "orange — a single data point or an assumption. For Russia — September 2026; the hollow circle — after the damper "
      "refund.",
      "Faktor des Preises ins Flugzeug zum US-Spot: Punkt — Schätzung, Linie — Spanne. Blau — durch Statistik belegt, "
      "Orange — ein einzelner Datenpunkt oder eine Annahme. Für Russland — September 2026, der hohle Kreis — nach der "
      "Erstattung über den Dämpfer.")}</p>
{whisker()}
<h3>{T("Как это выглядит во времени", "How it looks over time", "Wie es über die Zeit aussieht")}</h3>
<p>{T(f"Цена тонны в баке: американский спот, умноженный на множитель самого дешёвого региона, среднего и самого дорогого.\n"
      f"Правая точка — «сегодня» (сентябрь 2026, {money(today, 'USD', unit='/т')} на споте): она и есть точка на рисунке "
      f"выше. Линии — спот,\nумноженный на постоянный множитель: настоящего ряда цен «в баке» по регионам в открытом "
      f"доступе нет. Шкала рисунка пересчитывается переключателем валюты.",
      f"Price of a tonne in the tank: the US spot multiplied by the multiplier of the cheapest region, the average and the "
      f"most expensive one. The right-hand point is “today” (September 2026, {money(today, 'USD', unit='/t')} on the "
      f"spot): it is the dot in the chart above. The lines are the spot times a constant multiplier: no actual series of "
      f"into-plane prices by region is publicly available. The chart's scale follows the currency switch.",
      f"Preis einer Tonne im Tank: der US-Spot, multipliziert mit dem Faktor der billigsten Region, des Durchschnitts und "
      f"der teuersten. Der rechte Punkt ist „heute“ (September 2026, {money(today, 'USD', unit='/t')} am Spot): Er ist "
      f"der Punkt in der Grafik oben. Die Linien sind der Spot mal einem konstanten Faktor: Eine echte Reihe der Preise "
      f"ins Flugzeug nach Regionen ist nicht öffentlich verfügbar. Die Skala der Grafik folgt dem Währungsschalter.")}</p>
{chart}
<p class="small">{T("Мировой шок марта 2026 (спот вырос почти вдвое за месяц",
                    "The global shock of March 2026 (the spot nearly doubled in a month",
                    "Der weltweite Schock im März 2026 (der Spot hat sich binnen eines Monats fast verdoppelt")
                  }{cite('r1-171', 'r1-172')}) {T(
        "двигает все регионы\nвместе — множитель к споту меняется меньше, чем сам спот. Поэтому калькулятору нужен свежий "
        "спот и постоянный\nмножитель региона, а не цена каждого аэропорта. Россия — исключение: её цена от спота почти не "
        "зависит, а демпфер в\n2026 менялся от 0 до 58 тыс. руб/т",
        "moves all regions together — the multiplier to the spot changes less than the spot itself. So the calculator needs "
        "a fresh spot and a constant regional multiplier, not the price at every airport. Russia is the exception: its price "
        "hardly depends on the spot, and in 2026 the damper ranged from 0 to 58 thousand roubles per tonne",
        "bewegt alle Regionen gemeinsam — der Faktor zum Spot ändert sich weniger als der Spot selbst. Deshalb braucht der "
        "Rechner einen aktuellen Spot und einen konstanten Regionalfaktor, nicht den Preis jedes Flughafens. Russland ist "
        "die Ausnahme: Sein Preis hängt kaum vom Spot ab, und der Dämpfer schwankte 2026 zwischen 0 und 58.000 Rubel je "
        "Tonne")}{cite('r1-044', 'r1-067')}{T(", поэтому для неё нужен свой месячный ряд.",
                                               ", so Russia needs its own monthly series.",
                                               ", daher braucht Russland eine eigene Monatsreihe.")}</p>
<p>{T("<b>Но и множитель не постоянен.</b> По графику IATA Fuel Monitor (данные Platts) спот регионов к Северной Америке "
      "до шока держался в пределах ±5–9 % (Ближний Восток ×0,91, Азия ×0,94, Европа ×0,99), в марте–апреле 2026 регионы "
      "поменялись местами — Азия и Европа ушли на +10–24 %, — а сейчас Европа ×1,05, Азия ×0,92, Ближний Восток ×0,88. "
      "Постоянный множитель в спокойное время ошибается на несколько процентов, в шок — до 20 %. Ряд по регионам IATA не "
      "публикует, только график и цифру за неделю: последняя мировая средняя — 196,70 $/баррель",
      "<b>But the multiplier is not constant either.</b> According to the IATA Fuel Monitor chart (Platts data), regional "
      "spot prices relative to North America stayed within ±5–9 % before the shock (Middle East ×0.91, Asia ×0.94, "
      "Europe ×0.99); in March–April 2026 the regions swapped places — Asia and Europe went to +10–24 % — and now Europe "
      "is ×1.05, Asia ×0.92, the Middle East ×0.88. A constant multiplier is off by a few per cent in calm times and by "
      "up to 20 % in a shock. IATA does not publish the regional series, only the chart and the weekly figure: the latest "
      "global average is $196.70/bbl",
      "<b>Aber auch der Faktor ist nicht konstant.</b> Laut der Grafik des IATA Fuel Monitor (Daten von Platts) lag der "
      "regionale Spot gegenüber Nordamerika vor dem Schock innerhalb von ±5–9 % (Naher Osten ×0,91, Asien ×0,94, Europa "
      "×0,99); im März–April 2026 tauschten die Regionen die Plätze — Asien und Europa gingen auf +10–24 % —, heute liegt "
      "Europa bei ×1,05, Asien bei ×0,92, der Nahe Osten bei ×0,88. Ein konstanter Faktor liegt in ruhigen Zeiten um "
      "einige Prozent daneben, im Schock um bis zu 20 %. Die IATA veröffentlicht die Regionalreihe nicht, nur die Grafik "
      "und den Wochenwert: Der letzte weltweite Durchschnitt liegt bei 196,70 $/Barrel")}{cite('f2-002', 'f2-003')}.
{T("Цифры по регионам сняты с графика (точность ±2–3 $/баррель) только для этой проверки; сам ряд — собственность Platts, "
   "и в статью он не выносится.",
   "The regional figures were read off the chart (accuracy ±2–3 $/bbl) for this check only; the series itself is Platts' "
   "property and is not reproduced here.",
   "Die Regionalwerte wurden nur für diese Prüfung aus der Grafik abgelesen (Genauigkeit ±2–3 $/Barrel); die Reihe selbst "
   "gehört Platts und wird hier nicht wiedergegeben.")}{cite('f2-004', 'f2-005')}</p></section>"""

    # 4. факты — компактно
    rows = "".join(
        f"<tr><td><b>{e(reg(r))}</b></td><td class=r>×{n(m, 2)}</td><td class=r>{n(a, 2)}–{n(b, 2)}</td>"
        f"<td class=r>{money(round(EX_COST * (m - 1), -1), sign=True)}</td>"
        f"<td><span style=\"color:{CONF[c]}\">{e(T(c, *CONF_T[c]))}</span></td><td class=s>{e(why(w))}{cite(*evs)}</td></tr>"
        for r, m, (a, b), c, w, evs in MODEL)
    ap = "".join(f"<tr><td>{e(TR(a['city'].split(',')[0]))}</td><td class=r>{n(a['price_rub_t'])}</td>"
                 f"<td>{e(ap_date(a['date']))}</td>"
                 f"<td class=s>{cite(*a.get('evidence') or [])}</td></tr>" for a in RU["airports"])
    facts = f"""<section><h2>{T("Таблица для расчёта", "Table for the calculation", "Tabelle für die Berechnung")}</h2>
<div class="tw"><table><tr><th>{T("Регион", "Region", "Region")}</th><th class=r>{T("Множитель", "Multiplier", "Faktor")}</th>
<th class=r>{T("Разброс", "Range", "Spanne")}</th>
<th class=r>{T("Рейс A320 FRA–BCN", "A320 flight FRA–BCN", "Flug A320 FRA–BCN")}</th>
<th>{T("Уверенность", "Confidence", "Verlässlichkeit")}</th><th>{T("На чём держится", "Based on", "Grundlage")}</th></tr>{rows}</table></div>
<p class="small">{T(
        f"Колонка рейса — сколько добавит или снимет регион к расчёту по американской цене на том же рейсе\n"
        f"({n(EX_FUEL_T, 1)} т топлива). Россия — до демпфера; после возврата рейс дешевле американского.",
        f"The flight column shows how much the region adds to or takes off the US-price calculation for the same flight "
        f"({n(EX_FUEL_T, 1)} t of fuel). Russia — before the damper; after the refund the flight is cheaper than at the "
        f"US price.",
        f"Die Flugspalte zeigt, wie viel die Region gegenüber der Rechnung zum US-Preis auf demselben Flug "
        f"({n(EX_FUEL_T, 1)} t Kerosin) hinzufügt oder abzieht. Russland — vor dem Dämpfer; nach der Erstattung ist der "
        f"Flug billiger als zum US-Preis.")}</p>
<details><summary>{T("Россия: цены ТЗК в аэропортах, руб/т без НДС",
                     "Russia: into-plane fuel supplier (TZK) prices at airports, RUB/t excl. VAT",
                     "Russland: Preise der Betankungsdienstleister (TZK) an Flughäfen, RUB/t ohne MwSt.")}</summary>
<div class="tw"><table><tr><th>{T("Аэропорт", "Airport", "Flughafen")}</th><th class=r>{T("Цена", "Price", "Preis")}</th>
<th>{T("С", "From", "Ab")}</th><th>{T("Источник", "Source", "Quelle")}</th></tr>{ap}</table></div>
<p class="small">{T(
        "Наценка к бирже без НДС: Центр около +29 %, Сибирь +18…+42 %, Дальний Восток +42…+68 %. Биржевая цена\n"
        "керосина ТС-1 — с НДС (подтверждено по данным биржи владельцем проекта), в расчёте она переведена в цену без НДС.\n"
        "Росавиация сводную таблицу цен ТЗК по аэропортам больше не публикует.",
        "Mark-up over the exchange price excl. VAT: Centre about +29 %, Siberia +18…+42 %, Far East +42…+68 %. The St "
        "Petersburg exchange (SPIMEX) price of TS-1 jet fuel includes VAT (confirmed by the project owner from exchange "
        "data); in the calculation it is converted to a price excl. VAT. Rosaviatsia (Russia's Federal Air Transport "
        "Agency) no longer publishes its summary table of TZK prices by airport.",
        "Aufschlag auf den Börsenpreis ohne MwSt.: Zentrum etwa +29 %, Sibirien +18…+42 %, Ferner Osten +42…+68 %. Der "
        "Börsenpreis (St. Petersburger Börse, SPIMEX) für das Kerosin TS-1 enthält die MwSt. (vom Projektinhaber anhand "
        "von Börsendaten bestätigt); in der Rechnung ist er in einen Preis ohne MwSt. umgerechnet. Die Rosawiazija "
        "(russische Luftverkehrsbehörde) veröffentlicht ihre Übersicht der TZK-Preise nach Flughäfen nicht mehr.")
        }</p></details></section>"""

    # 5. выводы — что вводим
    concl = f"""<section><h2>{T("Что меняем в калькуляторе", "What we change in the calculator", "Was wir im Rechner ändern")}</h2>
<ol><li>{mark('in_calc')}{T(
        "<b>Цена топлива = спот USGC × множитель региона аэропорта вылета</b> (таблица выше; решение 235). Множитель\n"
        "виден отдельным шагом в разборе расчёта с уверенностью; при низкой уверенности надбавка сверх спота идёт в долю\n"
        "«выдуманного». Спот обновляется как раньше, множители — при пересборке этой статьи.",
        "<b>Fuel price = USGC spot × multiplier of the departure airport's region</b> (table above; decision 235). The "
        "multiplier shows as its own step in the calculation breakdown, with its confidence; at low confidence the add-on "
        "above the spot counts towards the “made-up” share. The spot is updated as before, the multipliers whenever this "
        "article is rebuilt.",
        "<b>Kerosinpreis = USGC-Spot × Faktor der Region des Abflughafens</b> (Tabelle oben; Entscheidung 235). Der Faktor "
        "erscheint als eigener Schritt in der Aufschlüsselung, mit seiner Verlässlichkeit; bei geringer Verlässlichkeit "
        "zählt der Aufschlag über dem Spot zum Anteil des „Ausgedachten“. Der Spot wird wie bisher aktualisiert, die "
        "Faktoren bei jedem Neubau dieses Artikels.")}</li>
<li>{mark('in_calc')}{T(
        "<b>Россия по группам аэропортов</b> — Центр, Сибирь, Дальний Восток со своей наценкой ТЗК и сбором (сентябрь 2026,\n"
        "без демпфера). Урал и юг пока считаются по Центру.",
        "<b>Russia by airport group</b> — Centre, Siberia, Far East, each with its own TZK mark-up and fee (September "
        "2026, without the damper). The Urals and the south are priced as the Centre for now.",
        "<b>Russland nach Flughafengruppen</b> — Zentrum, Sibirien, Ferner Osten mit eigenem TZK-Aufschlag und eigener "
        "Gebühr (September 2026, ohne Dämpfer). Ural und Süden werden vorerst wie das Zentrum gerechnet.")}</li>
<li>{mark('in_calc')}{T(
        "<b>Демпфер</b> (решение 236): российскому перевозчику, заправляющемуся в России, цена топлива уменьшается на\n"
        "демпфер последнего опубликованного месяца и возврат акциза (2 800 руб/т × 1,08 = 3 024 руб/т) — отдельным шагом\n"
        "разбора, где видна цена с ним и без него. Значения — расчёт Рейтер по формуле НК: её вход — экспортные котировки,\n"
        "их в открытом доступе нет. Новый месяц дописывает агент обновлений.",
        "<b>The damper</b> (decision 236): for a Russian carrier fuelling in Russia, the fuel price is reduced by the "
        "damper of the latest published month and the excise refund (2,800 RUB/t × 1.08 = 3,024 RUB/t) — as a separate "
        "step in the breakdown showing the price with and without it. The values are Reuters' calculation under the Tax "
        "Code formula, whose input — export quotes — is not public. The update agent adds each new month.",
        "<b>Der Dämpfer</b> (Entscheidung 236): Für einen russischen Carrier, der in Russland tankt, sinkt der Preis um "
        "den Dämpfer des letzten veröffentlichten Monats und die Verbrauchsteuer-Erstattung (2.800 RUB/t × 1,08 = "
        "3.024 RUB/t) — als eigener Schritt der Aufschlüsselung mit Preis mit und ohne. Die Werte sind die Berechnung von "
        "Reuters nach der Formel des Steuergesetzbuchs, deren Eingang — Exportnotierungen — nicht öffentlich ist. Neue "
        "Monate trägt der Aktualisierungsagent nach.")}</li>
<li>{mark('in_calc')}{T(
        "<b>Индия, внутренние рейсы</b> (решение 236): цена IOCL для внутренних авиакомпаний по Дели (с акцизом 11 % и\n"
        "VAT) пересчитывается на штат аэропорта вылета через его VAT — от 1 % (Уттар-Прадеш, Керала) до 25–29 %\n"
        "(Западная Бенгалия, Тамилнад); сниженные ставки Дели и Махараштры (7 %) действуют до середины ноября 2026.\n"
        "Международные рейсы — без VAT и акциза, по множителю региона.",
        "<b>India, domestic flights</b> (decision 236): IOCL's price for domestic airlines in Delhi (with 11 % excise and "
        "VAT) is converted to the state of the departure airport through its VAT — from 1 % (Uttar Pradesh, Kerala) to "
        "25–29 % (West Bengal, Tamil Nadu); the reduced rates of Delhi and Maharashtra (7 %) run until mid-November 2026. "
        "International flights — without VAT and excise, at the regional multiplier.",
        "<b>Indien, Inlandsflüge</b> (Entscheidung 236): Der IOCL-Preis für inländische Airlines in Delhi (mit 11 % "
        "Verbrauchsteuer und VAT) wird über die VAT des Bundesstaats des Abflughafens umgerechnet — von 1 % (Uttar "
        "Pradesh, Kerala) bis 25–29 % (Westbengalen, Tamil Nadu); die gesenkten Sätze von Delhi und Maharashtra (7 %) "
        "gelten bis Mitte November 2026. Internationale Flüge — ohne VAT und Verbrauchsteuer, mit dem Regionalfaktor.")}</li>
<li>{mark('in_calc')}{T(
        "<b>Множитель сдвигается вместе с региональным спотом</b> (решение 236): множитель каждого региона привязан к\n"
        "дате своей точки, и при свежем соотношении спота региона к Северной Америке (оцифровка недельного графика IATA\n"
        "Fuel Monitor) калькулятор берёт его сдвиг: сейчас Европа ×1,19 вместо ×1,10, Индия ×1,39 вместо ×1,47. Сам ряд —\n"
        "данные Platts: в расчёт идёт, но не публикуется; без него — постоянный множитель из таблицы.",
        "<b>The multiplier moves with the regional spot</b> (decision 236): each region's multiplier is tied to the date of "
        "its data point, and with a fresh ratio of the regional spot to North America (digitised from the weekly IATA Fuel "
        "Monitor chart) the calculator applies the shift: Europe is now ×1.19 instead of ×1.10, India ×1.39 instead of "
        "×1.47. The series itself is Platts data: it is used in the calculation but not published; without it — the "
        "constant multiplier from the table.",
        "<b>Der Faktor bewegt sich mit dem regionalen Spot</b> (Entscheidung 236): Der Faktor jeder Region ist an das "
        "Datum ihres Datenpunkts gebunden, und mit einem aktuellen Verhältnis des regionalen Spots zu Nordamerika "
        "(digitalisiert aus der wöchentlichen Grafik des IATA Fuel Monitor) übernimmt der Rechner die Verschiebung: Europa "
        "jetzt ×1,19 statt ×1,10, Indien ×1,39 statt ×1,47. Die Reihe selbst sind Platts-Daten: Sie fließen in die "
        "Rechnung ein, werden aber nicht veröffentlicht; ohne sie — der konstante Faktor aus der Tabelle.")}</li>
<li>{mark('planned')}{T(
        "<b>Индия, международные цены IOCL</b> — свежих (июль–октябрь 2026) в открытом доступе нет; пока множитель.",
        "<b>India, IOCL international prices</b> — no recent ones (July–October 2026) are public; the multiplier for now.",
        "<b>Indien, internationale IOCL-Preise</b> — keine aktuellen (Juli–Oktober 2026) öffentlich; vorerst der Faktor.")}</li>
<li>{mark('on_input')}{T(
        "<b>Своя цена.</b> Если знаете свою цену «в крыло» по договору — задайте её вручную (EUR за кг, со всеми\n"
        "надбавками и без НДС): она заменит расчёт. Демпфер к своей цене не применяется — вычтите его сами. Иностранный\n"
        "перевозчик в России демпфер не получает: укажите это в условиях начисления (эксплуатант — иностранный).",
        "<b>Your own price.</b> If you know your contract into-plane price, enter it manually (EUR per kg, with all "
        "add-ons, excl. VAT): it replaces the calculation. The damper is not applied to your own price — subtract it "
        "yourself. A foreign carrier in Russia does not receive the damper: set this in the charge conditions (operator — "
        "foreign).",
        "<b>Eigener Preis.</b> Wer seinen vertraglichen Preis ins Flugzeug kennt, gibt ihn von Hand ein (EUR je kg, mit "
        "allen Aufschlägen, ohne MwSt.): Er ersetzt die Rechnung. Der Dämpfer wird auf den eigenen Preis nicht "
        "angewendet — selbst abziehen. Ein ausländischer Carrier in Russland erhält den Dämpfer nicht: in den "
        "Entgeltbedingungen angeben (Betreiber — ausländisch).")}</li></ol>
<p class="small">{T(
        "Честно: вне США множители держатся на одной точке или допущении. Это точнее одной американской цены на\n"
        "весь мир, но каждое число помечено, и его можно заменить своим.",
        "To be frank: outside the US the multipliers rest on a single data point or an assumption. That is more accurate "
        "than one US price for the whole world, but every number is flagged and can be replaced with your own.",
        "Ehrlich gesagt: Außerhalb der USA beruhen die Faktoren auf einem einzelnen Datenpunkt oder einer Annahme. Das ist "
        "genauer als ein einziger US-Preis für die ganze Welt, aber jede Zahl ist gekennzeichnet und lässt sich durch "
        "eine eigene ersetzen.")}</p></section>"""

    # 6. отчёт — свернуть
    # Закрыто владельцем проекта: биржевая цена ТС-1 — с НДС; таблицы Росавиации больше нет.
    # Фильтр — по русскому оригиналу, перевод — после.
    closed = ("НДС", "favt", "IATA регионы в виде ряда")
    gaps = "".join(f"<li>{e(TR(x))}</li>" for x in D["gaps"] + RU["gaps"] if not any(c in x for c in closed))
    gaps += "<li>" + T("Ряд цен по регионам: IATA его не публикует (только график и неделя), полный ряд — у Platts по "
                       "лицензии; для проверки множителей график оцифрован, наружу не выносится.",
                       "Regional price series: IATA does not publish it (only the chart and the week), the full series is "
                       "licensed by Platts; the chart was digitised to check the multipliers and is not reproduced.",
                       "Regionale Preisreihe: Die IATA veröffentlicht sie nicht (nur Grafik und Woche), die volle Reihe gibt "
                       "es bei Platts unter Lizenz; die Grafik wurde zur Prüfung der Faktoren digitalisiert und wird nicht "
                       "wiedergegeben.") + "</li>"
    gaps += "<li>" + T("Сводная таблица цен ТЗК по аэропортам: Росавиация её больше не публикует.",
                       "Summary table of TZK prices by airport: Rosaviatsia no longer publishes it.",
                       "Übersicht der TZK-Preise nach Flughäfen: Die Rosawiazija veröffentlicht sie nicht mehr.") + "</li>"
    doubts = "".join(f"<li>{e(TR(x))}</li>" for x in D["doubts"] + RU["doubts"])
    fw = (n(sf['found']), n(sf.get('partial', 0)), n(sf.get('not_found', 0)))
    fr = (n(sr['found']), n(sr.get('partial', 0)), n(sr.get('not_found', 0)))
    report = f"""<section><h2>{T("Как проверялось", "How it was checked", "Wie geprüft wurde")}</h2>
<p>{T(
        f"Два исследователя вели журналы поиска с дословными цитатами (<code>trace/</code>); отдельные агенты открыли каждый\n"
        f"источник и сверили цитаты: мир — {fw[0]} найдено, {fw[1]} частично, {fw[2]} не найдено;\n"
        f"Россия — {fr[0]}, {fr[1]}, {fr[2]} (<code>verify/</code>). Проверка поправила:\n"
        f"множители Европы и Ближнего Востока (у исследователя ×1,12 и ×1,0 держались на допущениях) и российскую часть — биржевая\n"
        f"цена с НДС (позже подтверждено владельцем проекта по данным биржи), поэтому её сравнение с мировой и наценки ТЗК\n"
        f"пересчитаны.",
        f"Two researchers kept search logs with verbatim quotes (<code>trace/</code>); separate agents opened every source "
        f"and checked the quotes: world — {fw[0]} found, {fw[1]} partly, {fw[2]} not found; Russia — {fr[0]}, {fr[1]}, "
        f"{fr[2]} (<code>verify/</code>). The check corrected the multipliers for Europe and the Middle East (the "
        f"researcher's ×1.12 and ×1.0 rested on assumptions) and the Russian part: the exchange price includes VAT (later "
        f"confirmed by the project owner from exchange data), so its comparison with the world price and the TZK mark-ups "
        f"were recalculated.",
        f"Zwei Rechercheure führten Suchprotokolle mit wörtlichen Zitaten (<code>trace/</code>); separate Agenten öffneten "
        f"jede Quelle und glichen die Zitate ab: Welt — {fw[0]} gefunden, {fw[1]} teilweise, {fw[2]} nicht gefunden; "
        f"Russland — {fr[0]}, {fr[1]}, {fr[2]} (<code>verify/</code>). Die Prüfung korrigierte die Faktoren für Europa "
        f"und den Nahen Osten (beim Rechercheur beruhten ×1,12 und ×1,0 auf Annahmen) und den russischen Teil: Der "
        f"Börsenpreis enthält die MwSt. (später vom Projektinhaber anhand von Börsendaten bestätigt), daher wurden sein "
        f"Vergleich mit dem Weltpreis und die TZK-Aufschläge neu berechnet.")}</p>
<details><summary>{T("Чего не нашлось и в чём сомнения", "What was not found and what is in doubt",
                     "Was nicht gefunden wurde und was zweifelhaft ist")}</summary><h3>{T("Не найдено", "Not found",
                                                                                          "Nicht gefunden")}</h3><ul>{gaps}</ul>
<h3>{T("Сомнения", "Doubts", "Zweifel")}</h3><ul>{doubts}</ul></details>
<h3>{T("Что поднимет уверенность", "What would raise confidence", "Was die Verlässlichkeit erhöhen würde")}</h3>
<ul><li>{T("Ряд IATA Jet Fuel Price Monitor по регионам за 2023–2026 — проверит устойчивость множителей во времени.",
           "The IATA Jet Fuel Price Monitor series by region for 2023–2026 — would test how stable the multipliers are "
           "over time.",
           "Die Reihe des IATA Jet Fuel Price Monitor nach Regionen für 2023–2026 — würde prüfen, wie stabil die Faktoren "
           "über die Zeit sind.")}</li>
<li>{T("Прейскуранты ТЗК крупных аэропортов России (Домодедово, Внуково, Пулково, Сочи, Новосибирск, Хабаровск) — заменят\n"
       "наценки групп ценами аэропортов: сводную таблицу Росавиация больше не публикует.",
       "TZK price lists of major Russian airports (Domodedovo, Vnukovo, Pulkovo, Sochi, Novosibirsk, Khabarovsk) — would "
       "replace the group mark-ups with airport prices: Rosaviatsia no longer publishes the summary table.",
       "Preislisten der TZK großer russischer Flughäfen (Domodedowo, Wnukowo, Pulkowo, Sotschi, Nowosibirsk, Chabarowsk) "
       "— würden die Gruppenaufschläge durch Flughafenpreise ersetzen: Die Rosawiazija veröffentlicht die Übersicht nicht "
       "mehr.")}</li></ul>
{S.html()}</section>"""
    style = """<style>.chart .lab2{font:12.5px var(--sans);fill:var(--ink)}
sup.cite{font-size:10.5px;margin-left:1px}sup.cite a{color:var(--sky-t);text-decoration:none}
.chain{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin:14px 0 18px}
.chain div{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px 12px;position:relative}
.chain div:not(:last-child)::after{content:"→";position:absolute;right:-12px;top:40%;color:var(--dim)}
.chain b{display:block;color:var(--ink2);font-size:14px}.chain span{font-size:12.5px;color:var(--dim)}
ol.src{font-size:12.5px;color:var(--dim)}ol.src a{color:var(--dim);overflow-wrap:anywhere}
@media(max-width:760px){.chain{grid-template-columns:1fr}.chain div::after{display:none}}</style>"""
    return page(article_title("fuel-2026-10"), style + hook + theory + analytics + facts + concl + report)


# Множители — в данные калькулятора (решение 235): data/fuel/_regional.yaml. Регион аэропорта
# вылета — по префиксу ИКАО (сначала двухбуквенные); Россия — по группам ТЗК.
PREFIX = {"Северная Америка": ["K", "C", "PA", "PH", "PG", "TJ"],
          "Европа": ["GC", "LL", "B", "E", "L"],
          "Ближний Восток": ["O"],
          "Азия и Океания": ["VH", "VM", "VT", "VV", "VD", "VL", "VY", "VG", "VN", "VR", "VC", "R", "Z", "W", "Y", "N",
                             "A", "P"],
          "Африка": ["D", "F", "G", "H"],
          "Латинская Америка": ["M", "S", "T"],
          "Казахстан и СНГ": ["UA", "UT", "UB", "UG", "UK", "UM", "UC", "UD"],
          "Индия": ["VA", "VE", "VI", "VO"]}
RU_PREFIX = {"Центр": ["UU", "UL", "UW", "UR", "US"], "Сибирь": ["UN", "UI", "UO"], "Дальний Восток": ["UH", "UE"]}
CODE = {"Северная Америка": "north_america", "Европа": "europe", "Ближний Восток": "middle_east",
        "Азия и Океания": "asia_oceania", "Россия": "russia", "Африка": "africa", "Латинская Америка": "latam",
        "Казахстан и СНГ": "kz_cis", "Индия": "india"}


# Двухчастный множитель (решение 236): множитель снят на свою дату; региональный спот с тех пор
# сдвинулся. k(сейчас) = k(дата точки) × r(сейчас) / r(дата точки), r — спот региона Platts к
# Северной Америке. В данных — только надбавка addon = k / r(дата точки); сам ряд r — в локальном
# файле (данные Platts, не публикуются), без него калькулятор берёт статический k.
PLATTS = {"Северная Америка": None, "Европа": "europe", "Ближний Восток": "middle_east", "Азия и Океания": "asia",
          "Африка": "africa", "Латинская Америка": "latam", "Казахстан и СНГ": "europe", "Индия": "asia"}
REF = {"Европа": ("2026-01-01", "2026-01-31"), "Казахстан и СНГ": ("2026-01-01", "2026-01-31"),
       "Индия": ("2026-05-01", "2026-05-31"), "Латинская Америка": ("2025-01-01", "2025-12-31"),
       "Ближний Восток": ("2024-09-01", "2026-02-27"), "Азия и Океания": ("2024-09-01", "2026-02-27"),
       "Африка": ("2024-09-01", "2026-02-27")}
PLATTS_LOCAL = ROOT / "data" / "fuel" / "_platts.local.json"


def write_regional() -> None:
    import json as _json
    import statistics
    import yaml
    from datetime import date
    dst = ROOT / "data" / "fuel" / "_regional.yaml"
    old = (yaml.safe_load(dst.read_text(encoding="utf-8")) or {}).get("regions", {}) if dst.exists() else {}
    weekly = _json.loads(PLATTS_LOCAL.read_text(encoding="utf-8"))["weekly"] if PLATTS_LOCAL.exists() else None
    regions = {}
    for name, m, (lo, hi), conf, *_ in MODEL:
        if name == "Россия":
            continue
        r = {"name": name, "k": round(m, 3), "range": [lo, hi], "confidence": conf, "prefixes": PREFIX[name]}
        pl = PLATTS.get(name)
        if pl:
            a, b = REF[name]
            vals = [w[pl] for w in weekly or [] if a <= w["date"] <= b and pl in w]
            if vals:     # период точки ещё на графике (он скользит на два года назад)
                r["addon"] = round(m / statistics.mean(vals), 3)
            elif old.get(CODE[name], {}).get("addon"):     # иначе — посчитанная раньше надбавка
                r["addon"] = old[CODE[name]]["addon"]
            r.update(platts=pl, ref_period=[a, b])
        regions[CODE[name]] = r
    for g, (mk, fee) in RU_GROUPS.items():
        regions["russia_" + {"Центр": "centre", "Сибирь": "siberia", "Дальний Восток": "far_east"}[g]] = {
            "name": f"Россия — {g}", "k": round(ru_mult(mk, fee), 3), "range": [round(RU_LO, 3), round(RU_HI, 3)],
            "confidence": "низкая", "prefixes": RU_PREFIX[g],
            "note": f"биржа ТС-1 без НДС × (1 + {mk}) + {fee} руб/т сбора, сентябрь 2026; демпфер не вычтен"}
    doc = {"method": ("Цена топлива «в крыло» = спот USGC × множитель региона аэропорта вылета (research/fuel-2026-10). "
                      "Множители — по одной точке или допущению на регион; уверенность — confidence. Решение 235. addon — "
                      "надбавка к региональному споту Platts на дату точки (решение 236): при свежем соотношении спота "
                      "k = addon × r(сейчас)."),
           "built": str(date.today()), "unknown_k": 1.0, "regions": regions}
    dst.parent.mkdir(exist_ok=True)
    dst.write_text("# Сгенерировано research/fuel-2026-10/build_report.py — руками не править.\n"
                   + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")


# Демпфер для авиакеросина (решение 236): вычет эксплуатанту = акциз 2 800 руб/т × 2,08 + демпфер;
# сверх уплаченного в цене акциза — 2 800 × 1,08 = 3 024 руб/т плюс демпфер месяца. Месячные
# значения — расчёт Рейтер по формуле НК (вход формулы — экспортные котировки, их у нас нет).
DAMPER = {"2024-06": (13_949, "r1-077"), "2024-09": (7_819, "r1-080"), "2025-01": (15_615, "r1-083"),
          "2025-06": (618, "r1-073"), "2025-07": (1_981.2, "r1-073"), "2025-10": (2_049.45, "r1-039"),
          "2025-11": (4_386.2, "r1-039"), "2026-01": (0, "r1-044"), "2026-02": (1_779.7, "r1-044"),
          "2026-03": (52_097.5, "r1-044"), "2026-04": (47_833.5, "r1-051"), "2026-05": (27_986.4, "r1-054"),
          "2026-06": (15_100.8, "r1-057"), "2026-07": (27_639.95, "r1-061"), "2026-08": (38_297.35, "r1-064"),
          "2026-09": (58_421.35, "r1-067")}
EXCISE_REFUND = (3_024, ["r1-086", "r1-088", "r1-068"])


def write_damper() -> None:
    import yaml
    from datetime import date
    doc = {"method": ("Компенсация российскому эксплуатанту за тонну авиакеросина, заправленного в России: "
                      "демпфер месяца + возврат акциза сверх уплаченного (2 800 руб/т × 1,08 = 3 024). Демпфер — "
                      "расчёт Рейтер по формуле НК, публикуется в начале следующего месяца. Решение 236."),
           "built": str(date.today()), "excise_refund_rub_t": EXCISE_REFUND[0],
           "excise_evidence": [S.step[i][0] for i in EXCISE_REFUND[1] if i in S.step],
           "months": {m: {"damper_rub_t": v, "source": S.step[ev][0]} for m, (v, ev) in DAMPER.items()}}
    dst = ROOT / "data" / "fuel" / "_ru_damper.yaml"
    # Месяцы, дописанные агентом после сборки статьи, не теряются.
    if dst.exists():
        old = (yaml.safe_load(dst.read_text(encoding="utf-8")) or {}).get("months") or {}
        doc["months"] = dict(sorted({**old, **doc["months"]}.items()))
    dst.write_text("# Сгенерировано research/fuel-2026-10/build_report.py; новые месяцы дописывает месячный агент.\n"
                   + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")


# Индия, внутренние рейсы (решение 236): цена IOCL по Дели с налогами (акциз 11 % и VAT Дели),
# пересчёт на штат аэропорта вылета через VAT. Международные рейсы — множитель региона.
IN = json.loads((HERE / "out" / "india_atf.json").read_text(encoding="utf-8"))
TN_OTHER = ["VOCB", "VOMD", "VOTR", "VOTK", "VOSM"]       # аэропорты Тамилнада кроме Ченнаи
AP = ["VOVZ", "VOTP", "VORY", "VOBZ", "VOKU"]             # Андхра-Прадеш


def write_india() -> None:
    import yaml
    from datetime import date
    v = {x["state"]: x for x in IN["state_vat"]}
    src = lambda st: [S.step[i][0] for i in v[st]["evidence"] if i in S.step][:2]  # noqa: E731
    vat = {}
    for icao in ("VIDP",):
        vat[icao] = {"periods": [{"pct": 7, "from": "2026-05-16", "to": "2026-11-15"}, {"pct": 25}], "state": "Delhi"}
    for icao in ("VABB", "VAPO", "VANM"):
        vat[icao] = {"periods": [{"pct": 7, "from": "2026-05-15", "to": "2026-11-14"}, {"pct": 18}], "state": "Maharashtra"}
    vat["VOMM"] = {"periods": [{"pct": 29, "to": "2026-10-31"}, {"pct": 16, "from": "2026-11-01", "to": "2027-10-31"},
                               {"pct": 29}], "state": "Tamil Nadu"}
    for icao in TN_OTHER:
        vat[icao] = {"periods": [{"pct": 29, "to": "2026-10-31"}, {"pct": 1, "from": "2026-11-01", "to": "2027-10-31"},
                                 {"pct": 29}], "state": "Tamil Nadu"}
    simple = {"West Bengal": ["VECC"], "Karnataka": ["VOBL"], "Telangana": ["VOHS"], "Gujarat": ["VAAH"],
              "Kerala": ["VOCI", "VOTV", "VOCL"], "Goa": ["VOGO", "VOGA"], "Uttar Pradesh": ["VILK", "VIDX", "VEBN"],
              "Rajasthan": ["VIJP"], "Assam": ["VEGT"], "Andhra Pradesh": AP}
    for st, icaos in simple.items():
        for icao in icaos:
            vat[icao] = {"periods": [{"pct": v[st]["vat_pct"]}], "state": st}
    for x in vat.values():
        x["source"] = src(x["state"])
    dl = next(x for x in IN["iocl"] if x["icao"] == "VIDP")
    doc = {"method": ("Внутренние рейсы из Индии: цена IOCL для внутренних авиакомпаний в Дели (с акцизом 11 % и VAT "
                      "Дели) ÷ (1 + VAT Дели) × (1 + VAT штата аэропорта вылета). Международные рейсы — без VAT и "
                      "акциза, множитель региона. Решение 236."),
           "built": str(date.today()), "month": dl["month"], "delhi_domestic_inr_kl": dl["domestic_rs_per_kl"],
           "delhi_vat_pct_at_price": 7, "excise_pct": IN["excise"]["domestic_basic_excise_pct_ad_valorem"],
           "source": [S.step[i][0] for i in dl["evidence"] if i in S.step][:2],
           "default_vat_pct": 18, "vat": vat}
    dst = ROOT / "data" / "fuel" / "_india_atf.yaml"
    dst.write_text("# Сгенерировано research/fuel-2026-10/build_report.py; цену IOCL обновляет месячный агент.\n"
                   + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")


if __name__ == "__main__":
    write_regional()
    write_damper()
    write_india()
    write_all(HERE, "fuel-2026-10", build, TR)
    print(f"источников {len(S.num)}, Россия ×{RU_MID:.2f} ({RU_LO:.2f}–{RU_HI:.2f}), после демпфера ×{RU_NET:.2f}")
