#!/usr/bin/env python3
"""Статья «ТОиР: сколько стоит и как быстро дорожает» — HTML в оформлении сайта, на трёх языках.

Структура — research/STYLE.md; ориентир — как ТОиР меняет расчёт рейса. Данные:
index.json (индексы цен), model2_ppi.json (ставки по типам, Form 41), oem/o1.json
(экономика производителей двигателей); ссылки — из журналов trace/*.jsonl.
Тексты — T(ru, en, de); строки из данных — i18n.yaml (Tr); деньги — money().

    python3 research/toir/build_report.py          # из корня репозитория → report.html, report.en.html, report.de.html
"""

from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
from _report import (ARTICLE_CSS, Sources, T, Tr, _fx, curname, article_title, calc_badge, chain, e,  # noqa: E402
                     line_chart, mark, money, n, page, whisker, write_all)

J = lambda name: json.loads((HERE / name).read_text(encoding="utf-8"))  # noqa: E731
IX, M2, OEM = J("index.json"), J("model2_ppi.json"), J("oem/o1.json")
S = Sources(HERE)
TR = Tr(HERE)
PPI, CPI = IX["wps5541_jun"], IX["cpiu_annual"]


def cagr(s, a, b):
    return (s[str(b)] / s[str(a)]) ** (1 / (b - a)) - 1


# Пример расчёта: A320 Франкфурт — Барселона, блок 2,12 ч. Заготовка ТОиР калькулятора
# на 30.10.2026 — 495 EUR за час и 729 EUR за цикл (параметрика от массы и кресел).
# Курс доллара — снимок research/_fx.json (ЕЦБ), тот же, что у переключателя валюты.
FX = _fx()
BLOCK, CALC_FH, CALC_FC, USD_EUR = 2.12, 495, 729, FX["rates"]["USD"]
CALC_FLIGHT = CALC_FH * BLOCK + CALC_FC
F41_A320 = M2["types"]["A320"]["mature"]                  # USD 2025 за блок-час, прямые
F41_FLIGHT = F41_A320 * BLOCK / USD_EUR

POPULAR = ["CRJ9", "E75L", "B38M", "AT76", "B737", "B738", "A319", "DH8D", "B789", "B763", "A321", "B739",
           "E190", "A320", "A359", "B752", "A332", "A21N", "B772"]
CLS = {"узкофюзеляжные": ("узкофюзеляжные", "narrow-body", "Schmalrumpf"),
       "широкофюзеляжные": ("широкофюзеляжные", "wide-body", "Großraum"),
       "региональные": ("региональные", "regional", "Regional")}


def build() -> str:
    g16, c16 = cagr(PPI, 2009, 2025), cagr(CPI, 2009, 2025)
    g10 = cagr(PPI, 2015, 2025)
    TY = M2["types"]
    gap = round(F41_FLIGHT - CALC_FLIGHT, -1)

    hook = f"""<h1>{T("ТОиР: сколько стоит и как быстро дорожает", "Aircraft maintenance: what it costs and how fast it gets dearer",
                    "Flugzeugwartung: was sie kostet und wie schnell sie teurer wird")}</h1>
<p class="meta">{T("Исследование FlightCostApp, октябрь 2026 · как техническое обслуживание меняет расчёт рейса",
                   "FlightCostApp research, October 2026 · how maintenance changes the cost of a flight",
                   "FlightCostApp-Recherche, Oktober 2026 · wie die Instandhaltung die Flugkosten verändert")}</p>
{calc_badge("toir")}
<div class="verdict">
<div><b>{money(F41_A320, "USD")} {T("за блок-час", "per block hour", "je Blockstunde")}</b><span>{T(
        "столько прямые затраты на ТОиР A320 у авиакомпаний США (Form 41, борт около 12 лет, доллары 2025)",
        "direct maintenance cost of an A320 at US airlines (Form 41, aircraft about 12 years old, 2025 dollars)",
        "direkte Instandhaltungskosten eines A320 bei US-Airlines (Form 41, Flugzeug etwa 12 Jahre alt, Dollar 2025)")
        }{S.cite('m1-007')}</span></div>
<div><b>+{n(g16 * 100, 1)} % {T("в год", "a year", "pro Jahr")}</b><span>{T(
        f"так дорожает ремонт и ТО самолётов (индекс цен США, 2009–2025) — инфляция +{n(c16 * 100, 1)} %; не «в 2–3 раза быстрее»",
        f"that is how fast aircraft repair and maintenance get dearer (US price index, 2009–2025) — inflation +{n(c16 * 100, 1)} %; "
        "not “two to three times faster”",
        f"so schnell verteuern sich Reparatur und Wartung von Flugzeugen (US-Preisindex, 2009–2025) — Inflation "
        f"+{n(c16 * 100, 1)} %; nicht „zwei- bis dreimal schneller“")}{S.cite('m1-007')}</span></div>
<div><b>{T("Каталог — 6–9 % в год", "Catalogue — 6–9 % a year", "Katalog — 6–9 % pro Jahr")}</b><span>{T(
        "быстро дорожают запчасти двигателей по прайсу производителя, но это лишь часть затрат",
        "engine parts at the manufacturer's list price rise fast, but they are only part of the cost",
        "Triebwerksteile nach Herstellerliste werden schnell teurer, sind aber nur ein Teil der Kosten")
        }{S.cite('l1-040', 'o1-094')}</span></div>
<div><b>{T("Новый борт — вдвое дешевле", "A new aircraft costs half", "Ein neues Flugzeug kostet die Hälfte")}</b><span>{T(
        "у узкофюзеляжных в первые годы ТОиР 0,4–0,6 от зрелой ставки, после 12 лет растёт",
        "for narrow-bodies maintenance is 0.4–0.6 of the mature rate in the first years and rises after 12 years",
        "bei Schmalrumpfflugzeugen liegt die Instandhaltung in den ersten Jahren bei 0,4–0,6 des reifen Satzes und "
        "steigt nach 12 Jahren")}</span></div></div>
<p class="lede">{T(
        f"В калькуляторе ТОиР считается двумя ставками — за час полёта и за цикл (взлёт-посадку). Для A320 на рейсе "
        f"Франкфурт — Барселона заготовка даёт {money(CALC_FLIGHT)}. По фактическим затратам американских авиакомпаний "
        f"тот же рейс стоил бы около {money(round(F41_FLIGHT, -1))} — на {money(gap)} больше. Ниже — откуда эти цифры, "
        f"как они меняются с возрастом самолёта и со временем.",
        f"The calculator prices maintenance with two rates — per flight hour and per cycle (one take-off and landing). "
        f"For an A320 on Frankfurt — Barcelona the default gives {money(CALC_FLIGHT)}. At the actual costs of US "
        f"airlines the same flight would cost about {money(round(F41_FLIGHT, -1))} — {money(gap)} more. Below: where "
        f"these numbers come from and how they change with aircraft age and over time.",
        f"Der Rechner bewertet die Instandhaltung mit zwei Sätzen — je Flugstunde und je Zyklus (ein Start und eine "
        f"Landung). Für einen A320 auf Frankfurt — Barcelona ergibt die Voreinstellung {money(CALC_FLIGHT)}. Zu den "
        f"tatsächlichen Kosten von US-Airlines würde derselbe Flug etwa {money(round(F41_FLIGHT, -1))} kosten — "
        f"{money(gap)} mehr. Unten: woher diese Zahlen kommen und wie sie sich mit dem Alter des Flugzeugs und über "
        f"die Zeit ändern.")}</p>"""

    theory = f"""<section><h2>{T("Из чего складывается ТОиР", "What maintenance is made of", "Woraus die Instandhaltung besteht")}</h2>
{chain([(T("Планер", "Airframe", "Zelle"), T("осмотры A–C, тяжёлые формы D раз в 6–12 лет: работа и материалы",
                                            "A–C checks, heavy D checks every 6–12 years: labour and materials",
                                            "A–C-Checks, schwere D-Checks alle 6–12 Jahre: Arbeit und Material")),
        (T("Двигатели", "Engines", "Triebwerke"), T("капремонт и ресурсные детали (LLP) — самая дорогая часть",
                                                    "shop visits and life-limited parts (LLP) — the most expensive part",
                                                    "Shop-Visits und lebensdauerbegrenzte Teile (LLP) — der teuerste Teil")),
        (T("Агрегаты", "Components", "Komponenten"), T("шасси, ВСУ, агрегаты по состоянию или по ресурсу",
                                                       "landing gear, APU, components on condition or by life limit",
                                                       "Fahrwerk, APU, Komponenten nach Zustand oder Lebensdauer")),
        (T("Линейное ТО", "Line maintenance", "Line Maintenance"), T("ежедневные проверки и мелкий ремонт в аэропорту",
                                                                     "daily checks and minor repairs at the airport",
                                                                     "tägliche Checks und kleine Reparaturen am Flughafen"))])}
<p>{T("Часть затрат зависит от <b>часов</b> полёта (двигатели, агрегаты), часть — от <b>циклов</b> (шасси, ресурсные детали, "
      "линейное ТО). Поэтому на коротких рейсах ТОиР за час выше: циклов на час больше. Калькулятор так и считает — две ставки.",
      "Part of the cost depends on flight <b>hours</b> (engines, components), part on <b>cycles</b> (landing gear, "
      "life-limited parts, line maintenance). That is why maintenance per hour is higher on short flights: there are more "
      "cycles per hour. The calculator works exactly this way — with two rates.",
      "Ein Teil der Kosten hängt von den Flug<b>stunden</b> ab (Triebwerke, Komponenten), ein Teil von den <b>Zyklen</b> "
      "(Fahrwerk, lebensdauerbegrenzte Teile, Line Maintenance). Deshalb ist die Instandhaltung je Stunde auf kurzen Flügen "
      "höher: Es gibt mehr Zyklen pro Stunde. Der Rechner arbeitet genau so — mit zwei Sätzen.")}</p>
<p>{T("<b>Почему каталог дороже факта.</b> Производители двигателей продают двигатели около нуля или в убыток и "
      "зарабатывают на запчастях и сервисе: сервис — 60–75 % выручки двигательных подразделений GE, Safran и Rolls-Royce",
      "<b>Why the catalogue is dearer than reality.</b> Engine makers sell engines at around zero or at a loss and earn on "
      "spare parts and service: service is 60–75 % of the revenue of the engine divisions of GE, Safran and Rolls-Royce",
      "<b>Warum der Katalog teurer ist als die Wirklichkeit.</b> Triebwerkshersteller verkaufen Triebwerke etwa zum "
      "Selbstkostenpreis oder mit Verlust und verdienen an Ersatzteilen und Service: Der Service macht 60–75 % des Umsatzes "
      "der Triebwerkssparten von GE, Safran und Rolls-Royce aus")}
{S.cite(*[x for c in OEM['companies'] for x in c['evidence']][:4])}; {T(
      "Rolls-Royce терял в 2019 в среднем £1,2 млн на каждом новом широкофюзеляжном двигателе",
      "in 2019 Rolls-Royce lost £1.2m on average on every new wide-body engine",
      "2019 verlor Rolls-Royce im Schnitt 1,2 Mio. £ an jedem neuen Großraum-Triebwerk")}{S.cite('o1-073')}. {T(
      "Отсюда быстрый рост прайса запчастей. Но авиакомпания платит не только за запчасти: есть работа, планер, агрегаты, "
      "скидки и ремонт вместо замены — поэтому её затраты растут медленнее каталога.",
      "Hence the fast rise of parts list prices. But an airline pays for more than parts: there is labour, the airframe, "
      "components, discounts and repair instead of replacement — so its costs rise more slowly than the catalogue.",
      "Daher steigen die Listenpreise für Teile schnell. Eine Airline zahlt aber nicht nur für Teile: Es gibt Arbeit, Zelle, "
      "Komponenten, Rabatte und Reparatur statt Austausch — deshalb steigen ihre Kosten langsamer als der Katalog.")}</p></section>"""

    rows = []
    for t in POPULAR:
        x = TY[t]
        col = "var(--orange)" if x.get("young_only") or x.get("weak") else "var(--sky)"
        rows.append((t, x["mature"], (max(x["lo"], 0), x["hi"]), col))
    pts = whisker(rows, lo=0, hi=2200, ticks=(0, 500, 1000, 1500, 2000), fmt=lambda v: n(v), label_w=80, cur="USD")
    base_p, base_c = PPI["2009"], CPI["2009"]
    chart = line_chart([(T("ТОиР (индекс цен)", "maintenance (price index)", "Instandhaltung (Preisindex)"), "var(--sky)",
                         {k: v / base_p * 100 for k, v in PPI.items()}, False),
                        (T("инфляция", "inflation", "Inflation"), "var(--dim)",
                         {k: v / base_c * 100 for k, v in CPI.items() if int(k) >= 2009}, True)],
                       ylab="2009 = 100")
    shape = M2["shape"]["узкофюзеляжные"]
    age = line_chart([(T(*CLS[c]), col, {int(k): v for k, v in M2["shape"][c].items() if int(k) <= 20}, False)
                      for c, col in (("узкофюзеляжные", "var(--sky)"), ("широкофюзеляжные", "var(--green)"),
                                     ("региональные", "var(--aqua)"))],
                     ylab=T("к ставке борта 12 лет", "relative to a 12-year-old aircraft", "relativ zu 12 Jahre altem Flugzeug"),
                     yfmt=lambda v: n(v, 1), x_every=4)
    analytics = f"""<section><h2>{T("Сколько стоит ТОиР по типам", "Maintenance cost by aircraft type",
                                     "Instandhaltungskosten nach Flugzeugtyp")}</h2>
<p>{T(f"Прямые затраты на ТОиР, {curname('USD')} за блок-час (цены 2025 года), борт около 12 лет; точка — оценка, линия — "
      f"разброс между авиакомпаниями. Оранжевым — только молодой парк или мало данных.",
      f"Direct maintenance cost, {curname('USD')} per block hour (2025 prices), aircraft about 12 years old; dot — estimate, "
      f"line — spread between airlines. Orange — young fleet only or little data.",
      f"Direkte Instandhaltungskosten, {curname('USD')} je Blockstunde (Preise 2025), Flugzeug etwa 12 Jahre alt; Punkt — "
      f"Schätzung, Linie — Streuung zwischen Airlines. Orange — nur junge Flotte oder wenig Daten.")}</p>
{pts}
<h3>{T("Как ставка меняется с возрастом борта", "How the rate changes with aircraft age",
       "Wie sich der Satz mit dem Flugzeugalter ändert")}</h3>
<p>{T(f"Новый узкофюзеляжный самолёт обходится в {n(shape['0'], 1)}–{n(shape['4'], 1)} от ставки 12-летнего: двигатели и "
      f"планер ещё не дошли до первых тяжёлых работ. За весь срок службы средняя ставка — ×{n(M2['life']['узкофюзеляжные'], 2)} "
      f"к зрелой у узкофюзеляжных, ×{n(M2['life']['региональные'], 2)} у региональных.",
      f"A new narrow-body costs {n(shape['0'], 1)}–{n(shape['4'], 1)} of the rate of a 12-year-old one: engines and airframe "
      f"have not yet reached their first heavy work. Over the whole service life the average rate is "
      f"×{n(M2['life']['узкофюзеляжные'], 2)} of the mature rate for narrow-bodies and ×{n(M2['life']['региональные'], 2)} "
      f"for regional aircraft.",
      f"Ein neues Schmalrumpfflugzeug kostet {n(shape['0'], 1)}–{n(shape['4'], 1)} des Satzes eines 12 Jahre alten: "
      f"Triebwerke und Zelle haben die ersten schweren Arbeiten noch nicht erreicht. Über die gesamte Nutzungsdauer liegt der "
      f"Durchschnitt bei ×{n(M2['life']['узкофюзеляжные'], 2)} des reifen Satzes bei Schmalrumpf- und "
      f"×{n(M2['life']['региональные'], 2)} bei Regionalflugzeugen.")}</p>
{age}
<h3>{T("Как ТОиР дорожает со временем", "How maintenance gets dearer over time", "Wie die Instandhaltung mit der Zeit teurer wird")}</h3>
<p>{T(f"Индекс цен на ремонт и ТО самолётов в США рос на {n(g16 * 100, 1)} % в год с 2009 по 2025 (инфляция "
      f"{n(c16 * 100, 1)} %), за последние 10 лет — {n(g10 * 100, 1)} %. Резкие повышения прайса доходят быстро: в 2023 индекс "
      f"вырос на 8,4 % декабрь к декабрю, сразу после повышения цен CFM",
      f"The US price index for aircraft repair and maintenance grew {n(g16 * 100, 1)} % a year from 2009 to 2025 "
      f"(inflation {n(c16 * 100, 1)} %), and {n(g10 * 100, 1)} % over the last 10 years. Sharp list-price increases pass "
      f"through quickly: in 2023 the index rose 8.4 % December on December, right after CFM raised its prices",
      f"Der US-Preisindex für Reparatur und Wartung von Flugzeugen stieg von 2009 bis 2025 um {n(g16 * 100, 1)} % pro Jahr "
      f"(Inflation {n(c16 * 100, 1)} %), in den letzten 10 Jahren um {n(g10 * 100, 1)} %. Sprunghafte Preiserhöhungen kommen "
      f"schnell an: 2023 stieg der Index um 8,4 % Dezember zu Dezember, direkt nach der Preiserhöhung von CFM")
      }{S.cite(*OEM['y2023'][1]['evidence'][:2])}.</p>
{chart}</section>"""

    young, weak = T("только молодой парк", "young fleet only", "nur junge Flotte"), T("мало данных", "little data", "wenig Daten")
    trows = []
    for cls in ("узкофюзеляжные", "широкофюзеляжные", "региональные"):
        for t in sorted((x for x in TY.values() if x["cls"] == cls), key=lambda x: x["icao"]):
            note = ", ".join(z for z, f in ((young, t.get("young_only")), (weak, t.get("weak"))) if f)
            trows.append(f"<tr{' class=dimrow' if t.get('weak') else ''}><td><b>{e(t['icao'])}</b></td><td>{e(T(*CLS[cls]))}</td>"
                         f"<td class=r>{n(t['mature'])}</td><td class=r>{n(t['life'])}</td>"
                         f"<td class=r>{money(t['mature'] * BLOCK / USD_EUR)}</td><td class=s>{e(note)}</td></tr>")
    facts = f"""<section><h2>{T("Таблица для расчёта", "Table for the calculation", "Tabelle für die Berechnung")}</h2>
<details open><summary>{T("Ставки по 53 типам — Form 41, 1991–2025", "Rates for 53 types — Form 41, 1991–2025",
                          "Sätze für 53 Typen — Form 41, 1991–2025")}</summary>
<div class="tw"><table><tr><th>{T("Тип", "Type", "Typ")}</th><th>{T("Класс", "Class", "Klasse")}</th>
<th class=r>{T("Зрелый борт, $/блок-ч", "Mature aircraft, $/block h", "Reifes Flugzeug, $/Blockstd.")}</th>
<th class=r>{T("За срок службы", "Over service life", "Über die Nutzungsdauer")}</th>
<th class=r>{T("Рейс 2,1 ч", "2.1 h flight", "Flug 2,1 h")}</th><th>{T("Оговорки", "Caveats", "Vorbehalte")}</th></tr>
{''.join(trows)}</table></div></details>
<p class="small">{T(
        f"Прямые затраты (работа, материалы, внешние подрядчики), без накладных. Колонка рейса — ставка × 2,12 ч по курсу "
        f"{n(USD_EUR, 3)} $/EUR (ЕЦБ, {FX['as_of']}), для сравнения с заготовкой калькулятора. Затраты американских "
        f"авиакомпаний: в Европе и Азии работа дешевле, материалы те же.",
        f"Direct costs (labour, materials, outside contractors), without overheads. The flight column is the rate × 2.12 h at "
        f"{n(USD_EUR, 3)} $/EUR (ECB, {FX['as_of']}), for comparison with the calculator's default. These are US airline "
        f"costs: in Europe and Asia labour is cheaper, materials are the same.",
        f"Direkte Kosten (Arbeit, Material, Fremdleistungen), ohne Gemeinkosten. Die Flugspalte ist der Satz × 2,12 h zu "
        f"{n(USD_EUR, 3)} $/EUR (EZB, {FX['as_of']}), zum Vergleich mit der Voreinstellung des Rechners. Es sind Kosten von "
        f"US-Airlines: In Europa und Asien ist die Arbeit billiger, das Material gleich teuer.")}</p></section>"""

    pct_gap = n(round((F41_FLIGHT / CALC_FLIGHT - 1) * 100))
    concl = f"""<section><h2>{T("Что меняем в калькуляторе", "What we change in the calculator", "Was wir im Rechner ändern")}</h2>
<ol><li>{mark('in_calc')}{T(
        f"<b>Полоса Form 41 рядом с заготовкой</b> — уже есть в экономике флота (перевозчики США, 2025): видно, что заготовка "
        f"A320 ниже фактических затрат на ~{pct_gap} %.",
        f"<b>The Form 41 band next to the default</b> — already in fleet economics (US carriers, 2025): it shows the A320 "
        f"default is ~{pct_gap} % below actual costs.",
        f"<b>Das Form-41-Band neben der Voreinstellung</b> — schon in der Flottenökonomie (US-Airlines, 2025): Es zeigt, dass "
        f"die Voreinstellung für den A320 ~{pct_gap} % unter den tatsächlichen Kosten liegt.")}</li>
<li>{mark('on_input')}{T(
        "<b>Своя ставка — двумя числами.</b> Ставки таблицы — в долларах 2025 за блок-час и уже включают цикловую часть; в "
        "карточке типа ТОиР вводится в евро отдельно за лётный час и за цикл: на коротких рейсах цикловая часть весомее. "
        "Ставки таблицы — прямые затраты, без накладных. Лизинг в калькуляторе — без резервов на ТОиР: резервы в ставке "
        "лизинга посчитают ТОиР дважды.",
        "<b>Your own rate — as two numbers.</b> The table rates are 2025 dollars per block hour and already include the cycle "
        "part; in the type card maintenance is entered in euros separately per flight hour and per cycle: on short flights the "
        "cycle part weighs more. Table rates are direct costs, without overheads. Lease in the calculator excludes maintenance "
        "reserves: reserves inside the lease rate would count maintenance twice.",
        "<b>Eigener Satz — als zwei Zahlen.</b> Die Tabellensätze sind Dollar 2025 je Blockstunde und enthalten den Zyklusanteil "
        "bereits; in der Typkarte wird die Instandhaltung in Euro getrennt je Flugstunde und je Zyklus eingegeben: Auf kurzen "
        "Flügen wiegt der Zyklusanteil mehr. Tabellensätze sind direkte Kosten, ohne Gemeinkosten. Das Leasing im Rechner ist "
        "ohne Instandhaltungsrücklagen: Rücklagen im Leasingsatz würden die Instandhaltung doppelt zählen.")}</li>
<li>{mark('planned')}{T("<b>Ставка зрелого борта по модели</b> из этой статьи — в полосу рядом с отчётностью 2025 года.",
                         "<b>The modelled mature-aircraft rate</b> from this article — into the band next to the 2025 reports.",
                         "<b>Der modellierte Satz des reifen Flugzeugs</b> aus diesem Artikel — ins Band neben den Berichten 2025.")}</li>
<li>{mark('planned')}{T("<b>Возраст борта.</b> Множитель кривой возраста: новый борт — 0,4–0,6 зрелой ставки, средний за срок "
                         "службы — ×0,9–1,15 по классу.",
                         "<b>Aircraft age.</b> An age-curve multiplier: a new aircraft — 0.4–0.6 of the mature rate, the "
                         "service-life average — ×0.9–1.15 by class.",
                         "<b>Flugzeugalter.</b> Ein Altersfaktor: neues Flugzeug — 0,4–0,6 des reifen Satzes, Durchschnitt über "
                         "die Nutzungsdauer — ×0,9–1,15 je nach Klasse.")}</li>
<li>{mark('planned')}{T("<b>Рост во времени.</b> Для расчёта на будущие годы — индекс ТОиР +3 % в год, а не каталог 6–9 %; "
                         "сценарий «дорогой каталог» — отдельная надбавка на двигательную часть.",
                         "<b>Growth over time.</b> For future years — the maintenance index +3 % a year, not the catalogue "
                         "6–9 %; an “expensive catalogue” scenario — a separate surcharge on the engine part.",
                         "<b>Anstieg über die Zeit.</b> Für künftige Jahre — der Instandhaltungsindex +3 % pro Jahr, nicht der "
                         "Katalog mit 6–9 %; ein Szenario „teurer Katalog“ — ein eigener Aufschlag auf den Triebwerksanteil.")}</li>
<li>{mark('planned')}{T("<b>Новые типы</b> без истории в США (LEAP, GTF, ПД-14) — расчёт «снизу» по каталогу с множителем "
                         "факт/каталог 0,55–0,67: каталог и резервы лизингодателей в 1,5–2,5 раза выше фактических затрат.",
                         "<b>New types</b> without US history (LEAP, GTF, PD-14) — a bottom-up estimate from the catalogue "
                         "with an actual/catalogue factor of 0.55–0.67: catalogue and lessor reserves are 1.5–2.5 times "
                         "actual costs.",
                         "<b>Neue Typen</b> ohne US-Historie (LEAP, GTF, PD-14) — eine Bottom-up-Schätzung aus dem Katalog "
                         "mit einem Faktor Ist/Katalog von 0,55–0,67: Katalog und Leasinggeber-Rücklagen liegen 1,5–2,5-mal "
                         "über den tatsächlichen Kosten.")}</li></ol></section>"""

    report = f"""<section><h2>{T("Как проверялось", "How it was checked", "Wie geprüft wurde")}</h2>
<p>{T("Ставки — модель по панели Form 41 (BTS) 1991–2025: тип + перевозчик + возраст + длина сектора + доработка перед "
      "списанием; строки не исключаются, выбросы объясняются (распределение затрат по типам формулой, капитализация тяжёлого "
      "ТО, доработка перед списанием). Экономика производителей — годовые отчёты GE, Safran, Rolls-Royce, RTX, MTU. Каждая "
      "цитата журналов (<code>trace/</code>) проверена отдельными агентами: из 948 найдено дословно 849, частично 5, не "
      "найдено 0, не проверено 94 (сайт не открылся).",
      "Rates come from a model on the Form 41 (BTS) panel 1991–2025: type + carrier + age + sector length + run-out before "
      "retirement; no rows are dropped, outliers are explained (formula allocation of costs to types, capitalised heavy "
      "maintenance, run-out before retirement). Manufacturer economics — annual reports of GE, Safran, Rolls-Royce, RTX, MTU. "
      "Every quote in the logs (<code>trace/</code>) was checked by separate agents: of 948, 849 found verbatim, 5 partly, "
      "0 not found, 94 not checked (site did not open).",
      "Die Sätze stammen aus einem Modell auf dem Form-41-Panel (BTS) 1991–2025: Typ + Airline + Alter + Streckenlänge + "
      "Auslauf vor der Ausmusterung; keine Zeile wird entfernt, Ausreißer werden erklärt (Kostenverteilung auf Typen per "
      "Formel, aktivierte schwere Wartung, Auslauf vor der Ausmusterung). Herstellerökonomie — Geschäftsberichte von GE, "
      "Safran, Rolls-Royce, RTX, MTU. Jedes Zitat in den Protokollen (<code>trace/</code>) wurde von separaten Agenten "
      "geprüft: von 948 wörtlich gefunden 849, teilweise 5, nicht gefunden 0, nicht geprüft 94 (Seite öffnete nicht).")}</p>
<details><summary>{T("Что осталось открытым", "What remains open", "Was offen bleibt")}</summary>
<ul>{''.join(f'<li>{e(TR(g))}</li>' for g in OEM['gaps'])}
<li>{T("Хвост кривой возраста после 20 лет, вероятно, занижен; B788 и DC10/MD11 — под вопросом.",
       "The age-curve tail after 20 years is probably understated; B788 and DC10/MD11 are in doubt.",
       "Das Ende der Alterskurve nach 20 Jahren ist wahrscheinlich zu niedrig; B788 und DC10/MD11 sind fraglich.")}</li></ul></details>
<p class="small">{T("Подробный журнал исследования — <code>README.md</code>, карта поиска — <code>map.html</code>.",
                    "Full research log — <code>README.md</code>, search map — <code>map.html</code> (in Russian).",
                    "Ausführliches Protokoll — <code>README.md</code>, Suchkarte — <code>map.html</code> (auf Russisch).")}</p>
{S.html()}</section>"""
    return page(article_title("toir"), ARTICLE_CSS + hook + theory + analytics + facts + concl + report)


if __name__ == "__main__":
    write_all(HERE, "toir", build, TR)
    print(f"источников {len(S.num)}; рейс A320: заготовка {CALC_FLIGHT:.0f} EUR, Form 41 {F41_FLIGHT:.0f} EUR")
