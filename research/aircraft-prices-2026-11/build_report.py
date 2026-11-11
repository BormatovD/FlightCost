#!/usr/bin/env python3
"""Build the aircraft-price research draft in RU/EN/DE from analyzed inputs.

Run analyze.py first. The article remains draft:true until owner modelling.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from _report import (ARTICLE_CSS, Sources, T, article_title, calc_badge, chain, e,
                     line_chart, mark, money, n, page, whisker, write_all)
from report_extensions import history_section, leasing_section
from model_cards import DISPLAY_TYPES

SLUG = HERE.name
DATA = json.loads((HERE / "out/summary.json").read_text())
HISTORY = json.loads((HERE / "out/segments_history.json").read_text())
AIRBUS = "https://www.airbus.com/sites/g/files/jlcbta136/files/2021-07/new-airbus-list-prices-2018.pdf"
AVAC18 = "https://aviationstrategy.aero/newsletter/Nov-2018/5/Jet-values-and-lease-rates"
IBA = DATA["example"]["anchor"]["source"]
NAMES = {"A20N": "A320neo", "A21N": "A321neo", "B38M": "737 MAX 8", "A359": "A350-900",
         "A320": "A320", "A321": "A321", "A332": "A330-200", "A339": "A330-900", "B738": "737-800",
         "B77W": "777-300ER", "B788": "787-8", "B789": "787-9"}


def table(heads, rows):
    return ('<div class="tw"><table><thead><tr>' + ''.join(f'<th>{e(x)}</th>' for x in heads)
            + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{x}</td>' for x in row)
                                                + '</tr>' for row in rows) + '</tbody></table></div>')


def build():
    s = Sources(HERE)
    s.url(AIRBUS, "Airbus: 2018 average list prices")
    s.url(AVAC18, "AVAC / Aviation Strategy: October 2018")
    s.url(IBA, "IBA / Jon Whaley: Q1 2026 values and lease rates, ICLG")
    d, ex = DATA, DATA["example"]
    anchor, inp = ex["anchor"], ex["inputs"]
    current = ex["default_ownership_eur_flight"]
    mid = ex["research_ownership_eur_flight_midpoint"]
    lo, hi = ex["research_ownership_eur_flight_low"], ex["research_ownership_eur_flight_high"]
    delta = ex["midpoint_delta_eur_flight"]
    body = [ARTICLE_CSS, f'<h1>{T("Сколько стоит самолёт: история цен и экономика лизинга", "What an aircraft costs: price history and lease economics", "Was ein Flugzeug kostet: Preisentwicklung und Leasingwirtschaft")}</h1>',
            f'<p class="meta">{T("Исследование · 11 ноября 2026", "Research · 11 November 2026", "Recherche · 11. November 2026")}</p>',
            calc_badge(SLUG)]
    cards = [
        (money(mid), T("лизинг на условный рейс A320neo при середине выбранного диапазона", "lease cost allocated to an illustrative A320neo flight at the selected midpoint", "Leasinganteil eines A320neo-Beispielflugs beim gewählten Mittelpunkt")),
        (money(delta, sign=True), T("к заготовке на том же рейсе; меняется только владение", "versus the default for the same flight; only ownership changes", "gegenüber der Voreinstellung beim selben Flug; nur der Besitzkostenanteil ändert sich")),
        (f'{n(sum(map(len, DISPLAY_TYPES.values())))} / {n(len(HISTORY["segments"]))}', T("типов ВС / сегмента в исторических панелях", "aircraft types / segments in the history panels", "Flugzeugtypen / Segmente in den historischen Diagrammen")),
        (n(len(HISTORY["segments"])), T("графика лизинга открыто; история цены покупки — по нажатию", "lease charts visible; purchase-price history expands on demand", "Leasingdiagramme sichtbar; Kaufpreishistorie aufklappbar")),
    ]
    body.append('<div class="verdict">' + ''.join(f'<div><b>{a}</b><span>{b}</span></div>' for a, b in cards) + '</div>')
    body.append(f'<p>{T("Сначала — история стоимости и ставок по четырём сегментам. Затем — численный пример сделки: как цена покупки, остаточная стоимость и стоимость денег превращаются в аренду; кому достаются платежи и какой риск остаётся у каждого участника.", "First comes value and rent history for four segments. A numerical transaction example then connects acquisition price, residual value and the cost of capital to rent, showing who receives each payment and who retains each risk.", "Zuerst folgt die Entwicklung von Werten und Raten in vier Segmenten. Ein Zahlenbeispiel verbindet danach Kaufpreis, Restwert und Kapitalkosten mit der Rate und zeigt Zahlungsströme und Risiken der Beteiligten.")}</p>')
    body.append('<p class="small"><a href="#segment-history">' + T("История по сегментам", "History by segment", "Historie nach Segmenten") + '</a> · <a href="#lease-economics">' + T("Экономика сделки", "Transaction economics", "Transaktionswirtschaft") + '</a> · <a href="#flight-allocation">' + T("Стоимость на рейс", "Cost per flight", "Kosten je Flug") + '</a></p>')
    body.append(f'<p class="lede">{T(
        f"В нашем примере A320neo Франкфурт — Барселона заготовка отводит на лизинг {money(current)} за рейс. Выбранная оценка даёт {money(lo)}–{money(hi)}, а её середина — {money(mid)}. Разница относится к владению: топливо, обслуживание и экипаж в этом сравнении не пересчитываются. Ниже можно проверить каждый множитель и увидеть, почему ни каталог, ни возраст сами по себе не определяют месячный платёж.",
        f"In our Frankfurt–Barcelona A320neo example, the default allocates {money(current)} per flight to leasing. The selected estimate gives {money(lo)}–{money(hi)}, with a midpoint of {money(mid)}. This difference concerns ownership: fuel, maintenance and crew are held fixed. Each multiplier is shown below, explaining why neither the catalogue nor age alone determines a monthly payment.",
        f"Im A320neo-Beispiel Frankfurt–Barcelona entfallen laut Voreinstellung {money(current)} je Flug auf Leasing. Die gewählte Schätzung ergibt {money(lo)}–{money(hi)}, mit {money(mid)} als Mittelpunkt. Die Differenz betrifft den Besitzkostenanteil; Treibstoff, Wartung und Besatzung bleiben unverändert. Unten sind alle Faktoren nachvollziehbar dargestellt.")}</p>')
    body.append(f'<h2>{T("Четыре разных числа", "Four different quantities", "Vier unterschiedliche Größen")}</h2>')
    body.append(chain([
        (T("Каталог", "List price", "Listenpreis"), T("опубликованный ориентир производителя", "the manufacturer's published reference", "veröffentlichter Richtwert des Herstellers")),
        (T("Цена сделки", "Transaction price", "Transaktionspreis"), T("сумма за конкретный самолёт и условия", "amount for a particular aircraft and terms", "Betrag für ein bestimmtes Flugzeug und seine Konditionen")),
        (T("Цена ВС (оценка рынка)", "Aircraft price (market appraisal)", "Flugzeugpreis (Marktwertschätzung)"), T("мнение оценщика на дату и при заданных условиях", "an appraiser's opinion for a date and stated conditions", "Bewertung für einen Zeitpunkt und bestimmte Annahmen")),
        (T("Лизинг", "Lease rate", "Leasingrate"), T("периодический платёж за пользование", "a recurring payment for use", "regelmäßige Zahlung für die Nutzung")),
    ]))
    body.append(f'<p>{T(
        "Покупка превращает деньги в актив, а лизинг задаёт регулярный платёж. В расчёте рейса нужен способ распределить владение по работе самолёта. Если самолёт взят в аренду, месячную ставку делим на месячный налёт и умножаем на длительность рейса. Если борт куплен, требуется отдельная модель капитала и остаточной стоимости: подставлять цену покупки вместо месячного лизинга нельзя.",
        "Buying converts money into an asset; leasing creates a recurring payment. Flight economics needs an allocation of ownership to aircraft use. For a leased aircraft, divide monthly rent by monthly block hours, then multiply by the flight's block time. A purchased aircraft needs a separate capital and residual-value model; its purchase price cannot replace monthly rent.",
        "Ein Kauf verwandelt Geld in einen Vermögenswert, Leasing erzeugt eine regelmäßige Zahlung. Für Flugkosten wird der Besitzkostenanteil auf die Nutzung verteilt: Monatsrate geteilt durch monatliche Blockstunden, multipliziert mit der Blockzeit des Flugs. Ein gekauftes Flugzeug braucht ein eigenes Modell für Kapital und Restwert.")}</p>')
    body.append(history_section(s))
    body.append(f'<h2>{T("Свежая опора: I квартал 2026 года", "A recent anchor: Q1 2026", "Aktueller Anker: erstes Quartal 2026")}</h2>')
    body.append(f'<p>{T("IBA публикует следующие месячные диапазоны. Период сохранён как квартал; точный месяц не придуман.", "IBA reports these monthly ranges. The reference period remains a quarter; no exact month is invented.", "IBA nennt diese monatlichen Spannen. Der Bezugszeitraum bleibt ein Quartal; ein genauer Monat wird nicht unterstellt.")}{s.cite(IBA)}</p>')
    fresh = [o for o in d["recent_observations"] if o["source_id"] == "iba-iclg-2026" and o["kind"] == "lease"
             and o["icao"] in ("A20N", "A21N", "A320", "B738")]
    fresh_rows = []
    for o in fresh:
        value = next(r for r in d["recent_observations"] if r["kind"] == "value"
                     and r["source_id"] == o["source_id"] and r["variant"] == o["variant"]
                     and r["age"] == o["age"] and r["period"] == o["period"])
        fresh_rows.append([e(NAMES.get(o["icao"], o["icao"])) + (" (NX)" if o["icao"] == "A21N" else ""),
                           T("новый", "new", "neu") if o["age"] == "new" else str(o["age"]),
                           n(value["amount_low_usd"] / 1e6, 1),
                           f'{n(o["amount_low_usd"] / 1000)}–{n(o["amount_high_usd"] / 1000)}'])
    body.append(table([T("Тип", "Type", "Typ"), T("Возраст", "Age", "Alter"),
                       T("Оценка, млн USD", "Appraisal, USD m", "Bewertung, Mio. USD"),
                       T("Лизинг, тыс. USD/месяц", "Lease, USD thousands/month", "Leasing, Tsd. USD/Monat")], fresh_rows))
    body.append(f'<p class="small">{T("Это оценки, а середины — наш расчёт. Возраст и модификацию сохраняем; A321NX и XLR не объединяем. Для диапазона A321NX источник прямо указывает зависимость от кредитного качества лизингополучателя. Его оценка 65 млн USD дана как half-life market value (HLMV): эту базу оценки технического состояния нужно сохранять отдельно от возраста борта.", "These are appraisals; midpoints are our calculation. Age and variant are retained; A321NX and XLR are kept separate. The source explicitly links the A321NX rent range to lessee credit strength. Its USD 65m appraisal is a half-life market value (HLMV); this maintenance-condition basis must be retained separately from aircraft age.", "Dies sind Schätzungen; Mittelpunkte berechnen wir. Alter und Variante bleiben erhalten; A321NX und XLR werden getrennt. Die Quelle nennt für die A321NX-Ratenspanne ausdrücklich die Bonität des Leasingnehmers. Die Bewertung von 65 Mio. USD ist ein Half-Life Market Value (HLMV); diese Zustandsbasis ist vom Flugzeugalter zu trennen.")}</p>')
    body.append(leasing_section(s))
    body.append(f'<h2 id="flight-allocation">{T("Формула: от месячной ставки к рейсу", "From monthly rent to one flight", "Von der Monatsrate zu einem Flug")}</h2>')
    body.append('<p class="formula">L = (L<sub>min</sub> + L<sub>max</sub>) / 2<br>'
                'C<sub>flight,EUR</sub> = (L<sub>USD/month</sub> / FX<sub>USD/EUR</sub>) × t<sub>block,h</sub> / H<sub>month,h</sub><br>'
                'ΔC<sub>passenger</sub> = (C<sub>scenario</sub> − C<sub>default</sub>) / (seats × load)</p>')
    model_url = "https://github.com/BormatovD/FlightCost/blob/e5429af890018ec54ffce82731ae2ea56cd0ea3e/flightcostapp/fleet.py"
    fx_url = "https://github.com/BormatovD/FlightCost/blob/e5429af890018ec54ffce82731ae2ea56cd0ea3e/research/_fx.json"
    s.url(model_url, "FlightCost: fleet ownership formula and default coefficients")
    s.url(fx_url, "FlightCost: dated exchange-rate snapshot")
    body.append(table([T("Множитель", "Input", "Eingabe"), T("Значение", "Value", "Wert"), T("Основание", "Basis", "Grundlage")], [
        ["L", f'{n(anchor["midpoint_usd_month"])} USD / ' + T("месяц", "month", "Monat"), T("арифметическая середина границ", "arithmetic midpoint of the bounds", "arithmetischer Mittelpunkt der Grenzen")],
        ["FX", f'{n(ex["fx"]["usd_per_eur"], 3)} USD/EUR · {e(ex["fx"]["as_of"])}', T("снимок для воспроизводимости", "snapshot for reproducibility", "Snapshot für Reproduzierbarkeit") + s.cite(fx_url)],
        ["t", f'{n(inp["block_hours"], 2)} ' + T("ч", "h", "h"), T("условный пример Франкфурт — Барселона", "illustrative Frankfurt–Barcelona example", "Beispiel Frankfurt–Barcelona")],
        ["H", f'{n(inp["monthly_hours"])} ' + T("ч/месяц", "h/month", "h/Monat"), T("фиксированное допущение сценария", "fixed scenario assumption", "feste Szenarioannahme")],
        [T("Заготовка", "Default", "Voreinstellung") + s.cite(model_url), money(ex["default_lease_eur_month"]) + ' / ' + T("месяц", "month", "Monat"), '345 000 × (79 / 78)<sup>1.1</sup>'],
        [T("Пассажиры", "Passengers", "Passagiere"), f'{n(inp["seats"])} × {n(inp["load_factor"] * 100)} % = {n(inp["passengers"])}', T("для оценки изменения чека", "for the change per passenger", "für die Änderung je Passagier")],
    ]))
    body.append(f'<p>{T(
        f"Результат по середине — {money(mid)} за рейс. Это на {money(delta)} больше заготовки, или {money(ex['midpoint_delta_eur_passenger'], d=2)} на пассажира при выбранной загрузке. Курс относится к {ex['fx']['as_of']}, а ставка — к I кварталу: это явно заданный сценарий пересчёта, а не наблюдавшийся евро-договор того квартала.",
        f"The midpoint gives {money(mid)} per flight: {money(delta)} above the default, or {money(ex['midpoint_delta_eur_passenger'], d=2)} per passenger at the assumed load. FX is dated {ex['fx']['as_of']}, while rent refers to Q1. This is a stated conversion scenario, not an observed Q1 euro contract.",
        f"Der Mittelpunkt ergibt {money(mid)} je Flug: {money(delta)} über der Voreinstellung beziehungsweise {money(ex['midpoint_delta_eur_passenger'], d=2)} je Passagier bei angenommener Auslastung. Der Wechselkurs gilt für {ex['fx']['as_of']}, die Rate für das erste Quartal. Dies ist ein Umrechnungsszenario, kein beobachteter Eurovertrag dieses Quartals.")}</p>')
    rows = [(f'{n(r["monthly_hours"])} ' + T("ч/месяц", "h/month", "h/Monat"), r["midpoint_eur_flight"],
             (r["low_eur_flight"], r["high_eur_flight"]), "var(--sky-t)") for r in ex["utilisation_sensitivity"]]
    rows.append((T("Заготовка, 300 ч", "Default, 300 h", "Voreinstellung, 300 h"), current, (current, current), "var(--guess)"))
    body.append(whisker(rows, lo=1800, hi=3500, ticks=[2000, 2500, 3000, 3500], fmt=lambda v: n(v), cur="EUR", label_w=205))
    body.append(f'<p class="small">{T("Лизинг на один и тот же условный рейс; меняется месячный налёт. Полосы получены из границ сценария, а не из статистического доверительного интервала.", "Leasing allocated to the same illustrative flight at different monthly utilisation. Bars propagate scenario bounds; they are not statistical confidence intervals.", "Leasinganteil desselben Beispielflugs bei unterschiedlicher Monatsnutzung. Die Balken übertragen Szenariogrenzen; sie sind keine statistischen Konfidenzintervalle.")}</p>')
    body.append(f'<p>{T(
        "Один и тот же месячный платёж делится на большее или меньшее число рабочих часов. Поэтому изменение налёта может повлиять на рейс сильнее, чем выбор точки внутри узкого диапазона ставки. Для собственного маршрута следует менять оба входа: договорную ставку и достижимый налёт с учётом расписания.",
        "The same monthly payment is spread over more or fewer working hours. Utilisation can therefore change flight cost more than choosing a point inside a narrow rent range. For a real route, adjust both inputs: the contractual rent and achievable utilisation under the schedule.",
        "Dieselbe Monatszahlung verteilt sich auf mehr oder weniger Arbeitsstunden. Die Nutzung kann Flugkosten deshalb stärker verändern als die Wahl eines Punkts innerhalb einer engen Ratenspanne. Für eine reale Strecke sind Vertragsrate und erreichbare Nutzung gemeinsam anzupassen.")}</p>')
    body.append(f'<h2>{T("Почему каталог не заменяет оценку стоимости", "Why a catalogue does not replace an appraisal", "Warum ein Katalog keine Bewertung ersetzt")}</h2>')
    body.append(table([T("Тип", "Type", "Typ"), T("Каталог 01/2018, млн USD", "List 01/2018, USD m", "Liste 01/2018, Mio. USD"),
                       T("Оценка 10/2018, млн USD", "Appraisal 10/2018, USD m", "Bewertung 10/2018, Mio. USD"), T("Отношение", "Ratio", "Verhältnis")],
                      [[e(NAMES.get(r["icao"], r["icao"])), n(r["list_usd"] / 1e6, 1), n(r["market_usd"] / 1e6, 1), n(r["ratio"], 2)] for r in d["catalog_comparisons"]]))
    body.append(f'<p class="small">{T("Airbus и AVAC; новый борт, разные месяцы одного года. Это отношение двух оценочных величин, а не измеренная скидка сделки.", "Airbus and AVAC; new aircraft, different months of one year. This compares two price concepts, not an observed transaction discount.", "Airbus und AVAC; neue Flugzeuge, unterschiedliche Monate desselben Jahres. Verglichen werden zwei Preisbegriffe, kein beobachteter Transaktionsrabatt.")}{s.cite(AIRBUS, AVAC18)}</p>')
    body.append(f'<h2>{T("Возраст и год рынка нужно разделять", "Separate aircraft age from the market year", "Flugzeugalter und Marktjahr trennen")}</h2>')
    body.append(f'<p>{T(
        "Если десятилетний самолёт дешевле нового, разницу ещё нельзя назвать чистой амортизацией. Нужно удержать одинаковыми дату оценки, модификацию, комплектацию и оценщика. Сравнение старого борта в кризис с новым в период дефицита смешивает возраст и рынок. Мы формируем пары внутри одного типа, периода и источника.",
        "A ten-year-old aircraft being cheaper than a new one does not isolate depreciation. Valuation date, variant, specification and appraiser must be held comparable. Comparing an older aircraft in a crisis with a new one in a shortage mixes age and market conditions. We form comparisons within type, period and source.",
        "Ein günstigeres zehnjähriges Flugzeug beweist noch keine reine Abschreibung. Bewertungsdatum, Variante, Ausstattung und Gutachter müssen vergleichbar sein. Ein altes Flugzeug in der Krise mit einem neuen bei Kapazitätsmangel zu vergleichen, vermischt Alter und Markt. Wir vergleichen innerhalb von Typ, Zeitraum und Quelle.")}</p>')
    ages = []
    for code, period in (("A320", "2020-10"), ("A332", "2018-10"), ("B77W", "2017-10")):
        match = next((r for r in d["expanded_age_comparisons"] if r["icao"] == code and r["kind"] == "lease" and r["period"] == period and r["age"] == 5), None)
        if match:
            ages.append([e(NAMES[code]), e(period), '5', f'{n(match["fraction_of_new"] * 100, 1)} %' + s.cite(match["source"])])
    body.append(table([T("Тип", "Type", "Typ"), T("Период", "Period", "Zeitraum"), T("Колонка возраста, лет", "Age column, years", "Altersspalte, Jahre"),
                       T("Лизинг к новому борту", "Lease / new-aircraft lease", "Rate / Neuflugzeugrate")], ages))
    body.append(f'<p class="small">{T("AVAC оговаривает, что колонка «5 лет» может охватывать 4–6 лет. Это срез оценок, не история старения одного борта.", "AVAC notes that the five-year column may cover ages four to six. This is an appraisal cross-section, not one aircraft aging.", "AVAC weist darauf hin, dass die Fünfjahresspalte vier bis sechs Jahre abdecken kann. Dies ist ein Bewertungsquerschnitt, kein einzelnes alterndes Flugzeug.")}{s.cite("https://aviationstrategy.aero/newsletter/Oct-2020/4/Jet-Values-and-Lease-Rates")}</p>')
    body.append(f'<p>{T(
        f"В исходной выборке есть {n(len(d['lease_value_pairs']))} точные пары «оценка стоимости — лизинг» одного типа, месяца, возраста и источника. Их отношение L/V удобно для сравнения, но не является доходностью инвестиции: оно не вычитает расходы и не учитывает остаточную стоимость. Общий коэффициент для всех типов преждевременен; сначала нужна проверка модели на отложенных годах и типах.",
        f"The input contains {n(len(d['lease_value_pairs']))} matched value-and-lease pairs with the same type, month, age and source. Their L/V ratio is useful for comparison but is not investment return: it omits expenses and residual value. A universal factor is premature; validation on held-out years and types comes first.",
        f"Der Ausgangsbestand enthält {n(len(d['lease_value_pairs']))} passende Wert- und Ratenpaare desselben Typs, Monats, Alters und derselben Quelle. L/V hilft beim Vergleich, ist aber keine Investitionsrendite: Kosten und Restwert fehlen. Ein allgemeiner Faktor setzt zuerst eine Prüfung an zurückgehaltenen Jahren und Typen voraus.")}</p>')
    body.append(f'<h2>{T("Что это меняет в калькуляторе", "What this changes in the calculator", "Was sich daraus für den Rechner ergibt")}</h2><ol>')
    for badge, text in [
        ("on_input", T("Использовать выбранный диапазон как сценарий: середину ввести месячной ставкой, границы — проверить отдельными расчётами.", "Use the chosen range as a scenario: enter the midpoint as monthly rent and test the bounds in separate calculations.", "Die gewählte Spanne als Szenario nutzen: Mittelpunkt als Monatsrate eingeben und Grenzen separat rechnen.")),
        ("in_calc", T("Сохранять опубликованные границы и отличать их от вычисленной середины; ручная ставка имеет приоритет.", "Keep published bounds distinct from the computed midpoint; an explicit manual rate has priority.", "Veröffentlichte Grenzen vom berechneten Mittelpunkt unterscheiden; eine manuelle Rate hat Vorrang.")),
        ("planned", T("Обучить ставку по типу, возрасту и периоду после проверки расширенных данных, сохраняя точность дат источника.", "Fit rates by type, age and period after checking the expanded data, retaining the source's date precision.", "Raten nach Typ, Alter und Zeitraum erst nach Prüfung der erweiterten Daten modellieren; die Datumsgenauigkeit der Quelle bleibt erhalten.")),
        ("planned", T("Разделить сценарии аренды и покупки: для покупки задавать цену, срок владения, остаточную стоимость и стоимость капитала; для аренды — ставку, срок и состав платежей. Условия кредита показывать отдельно от стоимости самого актива.", "Separate leasing and purchase scenarios: for a purchase, specify price, holding period, residual value and capital return; for a lease, specify rent, term and payment scope. Show loan terms separately from asset economics.", "Miet- und Kaufszenarien trennen: beim Kauf Preis, Haltedauer, Restwert und Kapitalrendite; bei Leasing Rate, Laufzeit und Zahlungsumfang angeben. Kreditbedingungen getrennt von der Anlagenwirtschaft zeigen.")),
        ("planned", T("Показывать отдельно экономическую себестоимость рейса и потребность в деньгах: депозит, технический резерв и погашение кредита имеют другой смысл, чем расход периода. Проверять, чтобы ТОиР не учитывалось дважды.", "Show flight economics separately from cash requirements: deposits, maintenance reserves and principal repayment differ from period expenses. Check that maintenance is not counted twice.", "Flugkosten und Liquiditätsbedarf getrennt zeigen: Kautionen, Wartungsrücklagen und Tilgung unterscheiden sich von Periodenaufwendungen. Wartung darf nicht doppelt erfasst werden.")),
    ]:
        body.append(f'<li>{mark(badge)}{text}</li>')
    body.append('</ol>')
    body.append(f'<details><summary>{T("Проверка, ограничения и следующие данные", "Verification, limits and next data", "Prüfung, Grenzen und weitere Daten")}</summary>')
    body.append(f'<p>{T(
        f"Исторические панели содержат {n(HISTORY['meta']['observation_count'])} наблюдение по 15 типам, включая {n(HISTORY['quality_counts']['chart_digitized'])} приблизительных значений, снятых с опубликованных графиков. Этот набор частично пересекается с прежней выпиской: количества нельзя складывать как новые уникальные наблюдения. history.py воспроизводит панели, lease_economics.py — денежные потоки и чувствительность сделки. Независимая проверка арифметики заново дисконтирует все потоки и пересчитывает кредит, не импортируя расчёт автора.",
        f"History panels contain {n(HISTORY['meta']['observation_count'])} observations across 15 types, including {n(HISTORY['quality_counts']['chart_digitized'])} approximate readings from published charts. This set overlaps the earlier extraction; counts must not be added as unique new observations. history.py reproduces the panels, and lease_economics.py reproduces transaction cash flows and sensitivities. An independent arithmetic check discounts each cash flow and recalculates the loan without importing the author's calculation.",
        f"Die historischen Diagramme verwenden {n(HISTORY['meta']['observation_count'])} Beobachtungen zu 15 Typen, darunter {n(HISTORY['quality_counts']['chart_digitized'])} ungefähre Ablesungen veröffentlichter Diagramme. Der Bestand überschneidet sich mit der früheren Erhebung; die Zahlen dürfen nicht als neue eindeutige Beobachtungen addiert werden. history.py erzeugt die Diagrammdaten, lease_economics.py Zahlungsströme und Sensitivitäten. Eine unabhängige Prüfung diskontiert jeden Zahlungsstrom und berechnet den Kredit ohne Import der Autorenberechnung neu.")}</p>')
    body.append(f'<p>{T(
        f"Анализ читает исходный YAML и отдельную исследовательскую выписку; контрольные суммы записаны в out/summary.json. В справочнике {n(d['coverage']['total'])} принятых строк. Дополнительно собраны {n(d['additional_coverage']['total'])} исследовательских строк, которые пока не меняют справочник. Независимая сверка и её охват находятся в verify/. Команды analyze.py и build_report.py воспроизводят расчёт и три языковые версии.",
        f"Analysis reads the original YAML and a separate research extraction; checksums are in out/summary.json. The accepted catalogue has {n(d['coverage']['total'])} rows. Another {n(d['additional_coverage']['total'])} research rows do not yet change that catalogue. Independent checks and their scope are in verify/. analyze.py and build_report.py reproduce the calculation and all three language versions.",
        f"Die Analyse liest das ursprüngliche YAML und eine getrennte Forschungsabschrift; Prüfsummen stehen in out/summary.json. Der angenommene Bestand hat {n(d['coverage']['total'])} Zeilen. Weitere {n(d['additional_coverage']['total'])} Forschungszeilen verändern ihn noch nicht. Unabhängige Prüfungen und ihr Umfang stehen in verify/. analyze.py und build_report.py erzeugen Ergebnisse und drei Sprachfassungen.")}</p>')
    body.append(f'<p>{T(
        "Отдельно исключаем из точной возрастной подгонки верхние оценки «до», точки с неизвестным возрастом и неуточнённые модификации. Пустые годы не заполнены интерполяцией. Цен раскрытых сделок за один борт в исходной выборке нет. Для текущего этапа документы от владельца не требуются; следующим подтверждением могли бы стать реальные условия лизинга с датой, возрастом и составом платежа, если их допустимо раскрыть.",
        "Exact age fitting excludes upper-bound estimates, unknown ages and unspecified variants. Missing years are not interpolated. The input contains no disclosed per-aircraft transaction prices. No owner documents are needed for this stage; a useful later check would be shareable lease terms with date, age and payment scope.",
        "Obergrenzen, unbekannte Alter und unklare Varianten bleiben aus der genauen Alterskalibrierung ausgeschlossen. Fehlende Jahre werden nicht interpoliert. Der Ausgangsbestand enthält keine offengelegten Einzeltransaktionspreise. Für diese Stufe sind keine Unterlagen des Eigentümers nötig; später wären teilbare Vertragsbedingungen mit Datum, Alter und Zahlungsumfang hilfreich.")}</p></details>')
    body.append(s.html())
    return page(article_title(SLUG), ''.join(body))


if __name__ == "__main__":
    write_all(HERE, SLUG, build)
    # Keep metadata and the cited answer box after every HTML rebuild.
    from seo_article import process_three
    process_three(HERE)
