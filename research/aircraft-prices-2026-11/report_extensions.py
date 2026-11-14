"""Historical segment panels and the lease cash-flow chapter for the draft."""
from __future__ import annotations

from collections import defaultdict
import json
import math
from pathlib import Path

from _report import T, e, money, n
from deal_flow import deal_flow_section
from model_cards import DISPLAY_TYPES, calibration_marks, correction_explanation, formula_cards

HERE = Path(__file__).resolve().parent
COLORS = ("var(--blue-t)", "var(--sky-t)", "var(--aqua-t)", "var(--green-t)")


def table(heads, rows):
    return ('<div class="tw"><table><thead><tr>' + ''.join(f'<th>{x}</th>' for x in heads)
            + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{x}</td>' for x in row)
                                                + '</tr>' for row in rows) + '</tbody></table></div>')


def segment_name(segment):
    return {"turboprop": T("Турбовинтовые", "Turboprops", "Turboprops"),
            "regional": T("Региональные реактивные", "Regional jets", "Regionaljets"),
            "narrowbody": T("Узкофюзеляжные", "Narrowbodies", "Schmalrumpfflugzeuge"),
            "widebody": T("Широкофюзеляжные", "Widebodies", "Großraumflugzeuge")}[segment]


def period_x(period):
    """Display coarse periods at their centres without changing source dates."""
    year = int(period[:4])
    if len(period) == 4:
        return year + 0.5
    if "Q" in period:
        return year + (int(period[-1]) - 1) / 4 + 0.125
    return year + (int(period[5:7]) - 0.5) / 12


def years_text(years):
    years = sorted(set(years))
    if not years:
        return "—"
    runs = [[years[0]]]
    for year in years[1:]:
        if year == runs[-1][-1] + 1:
            runs[-1].append(year)
        else:
            runs.append([year])
    return ", ".join(str(r[0]) if len(r) == 1 else f"{r[0]}–{r[-1]}" for r in runs)


def amount_text(obs):
    divisor = 1e6 if obs["kind"] == "value" else 1000
    digits = 1 if obs["kind"] == "value" else 0
    lo, hi = obs["amount_low_usd"] / divisor, obs["amount_high_usd"] / divisor
    prefix = "≈ " if obs.get("quality") == "chart_digitized" or obs.get("estimate_type") in {"approximate_point", "approximate"} else ""
    return prefix + n(lo, digits) + ("–" + n(hi, digits) if lo != hi else "")


def history_chart(data, segment, kind):
    rows = [o for o in data["observations"] if o["icao"] in segment["types"] and o["kind"] == kind
            and o["age"]["category"] == "new"]
    labels = {a["icao"]: a["label"] for a in data["aircraft"]}
    colors = dict(zip(segment["types"], COLORS))
    divisor = 1e6 if kind == "value" else 1000
    references = json.loads((HERE / 'out/model_reference.json').read_text())
    calibration = json.loads((HERE / 'out/lease_calibration.json').read_text())
    calibrations = {a['icao']: a for a in calibration['aircraft']}
    by_code = {a['icao']: a for a in references['aircraft']}
    model_rows = [by_code[code] for code in segment['types']] if kind == 'lease' else []
    largest = max([o["amount_high_usd"] / divisor for o in rows]
                  + [p['lease_thousand_usd_month'] for a in model_rows for p in a['nominal_usd_points']])
    raw_step = largest / 4
    base = 10 ** math.floor(math.log10(raw_step))
    step = next(x * base for x in (1, 2, 2.5, 5, 10) if x * base >= raw_step)
    ymax = math.ceil(largest / step) * step
    W, H, L, R, TOP, BOT = (980, 360, 64, 274, 30, 40) if kind == 'lease' else (760, 250, 64, 24, 26, 38)
    xmin, xmax = 2016.0, 2027.0
    X = lambda v: L + (v - xmin) / (xmax - xmin) * (W - L - R)
    Y = lambda v: H - BOT - v / ymax * (H - BOT - TOP)
    unit = T("млн USD за ВС", "USD million per aircraft", "Mio. USD je Flugzeug") if kind == "value" else T("тыс. USD в месяц", "USD thousands per month", "Tsd. USD pro Monat")
    title = (T("Цена ВС (оценка рынка)", "Aircraft price (market appraisal)", "Flugzeugpreis (Marktwertschätzung)") if kind == "value"
             else T("Лизинговые ставки", "Lease rates", "Leasingraten"))
    ident = f"history-{segment['id']}-{kind}"
    svg = [f'<svg class="chart segment-history" data-kind="{kind}" data-segment="{segment["id"]}" '
           f'viewBox="0 0 {W} {H}" role="img" aria-labelledby="{ident}">',
           f'<title id="{ident}">{e(title + " — " + segment_name(segment["id"]) + "; " + unit)}</title>',
           f'<text class="ax" x="{L}" y="15">{e(unit)}</text>']
    for k in range(int(round(ymax / step)) + 1):
        val = step * k
        yy = Y(val)
        svg.append(f'<line x1="{L}" x2="{W-R}" y1="{yy:.2f}" y2="{yy:.2f}" stroke="var(--line)"/>'
                   f'<text class="ax" x="{L-10}" y="{yy+4:.2f}" text-anchor="end">{n(val, 1 if step % 1 else 0)}</text>')
    for year in range(2016, 2027, 2):
        xx = X(year)
        svg.append(f'<text class="ax" x="{xx:.2f}" y="{H-12}" text-anchor="middle">{year}</text>')
    for a in model_rows:
        points = ' '.join(f'{X(p["x"]):.2f},{Y(p["lease_thousand_usd_month"]):.2f}' for p in a['nominal_usd_points'])
        age_label = T('новый', 'new', 'neu') if a['model_age_years'] == 0 else T('около 12 лет', 'approximately 12 years', 'etwa 12 Jahre')
        tip = T('Базовая заготовка калькулятора', 'Calculator baseline', 'Rechner-Grundannahme') + f' · {a["label"]} · {age_label}'
        svg.append(f'<polyline class="model-reference" data-icao="{a["icao"]}" data-model-age-years="{a["model_age_years"]}" '
                   f'data-reference-role="raw_parametric" data-model-lease-eur-month="{a["raw_parametric_lease_eur_month"]:.12g}" '
                   f'points="{points}" fill="none" stroke="{colors[a["icao"]]}" stroke-width="1.8" stroke-dasharray="10 4 2 4" opacity=".65">'
                   f'<title>{e(tip)}</title></polyline>')
    by_series = defaultdict(list)
    for o in rows:
        by_series[o["series_key"]].append(o)
    for series in by_series.values():
        ordered = sorted(series, key=lambda o: (period_x(o["period"]), o["id"]))
        for a, b in zip(ordered, ordered[1:]):
            xa, xb = period_x(a["period"]), period_x(b["period"])
            if not 0 < xb - xa <= 1.5:
                continue
            av = (a["amount_low_usd"] + a["amount_high_usd"]) / 2 / divisor
            bv = (b["amount_low_usd"] + b["amount_high_usd"]) / 2 / divisor
            dash = ' stroke-dasharray="5 4"' if a.get("quality") == "chart_digitized" else ""
            svg.append(f'<line data-series="{e(a["series_key"])}" x1="{X(xa):.2f}" x2="{X(xb):.2f}" '
                       f'y1="{Y(av):.2f}" y2="{Y(bv):.2f}" stroke="{colors[a["icao"]]}" stroke-width="1.8"{dash} opacity=".8"/>')
    for o in rows:
        xx = X(period_x(o["period"]))
        low, high = o["amount_low_usd"] / divisor, o["amount_high_usd"] / divisor
        yy = Y((low + high) / 2)
        col = colors[o["icao"]]
        approx = o.get("quality") == "chart_digitized"
        explanation = T("оцифровка графика", "chart digitization", "Diagrammdigitalisierung") if approx else T("опубликованное число", "published number", "veröffentlichte Zahl")
        tip = f'{labels[o["icao"]]} · {o["period"]} · {amount_text(o)} {unit} · {o["source_family"]} · {explanation} · {o["valuation_basis"]}'
        svg.append(f'<a href="{e(o["source_url"])}" rel="nofollow"><g data-observation-id="{e(o["id"])}" '
                   f'data-period="{e(o["period"])}" data-icao="{o["icao"]}" data-age-category="new" '
                   f'data-quality="{e(o.get("quality", ""))}"><title>{e(tip)}</title>')
        if high != low:
            svg.append(f'<path d="M {xx:.2f} {Y(high):.2f} V {Y(low):.2f} M {xx-4:.2f} {Y(high):.2f} h 8 M {xx-4:.2f} {Y(low):.2f} h 8" '
                       f'fill="none" stroke="{col}" stroke-width="2"/>')
        svg.append(f'<circle cx="{xx:.2f}" cy="{yy:.2f}" r="3.6" fill="{"var(--bg)" if approx else col}" stroke="{col}" stroke-width="1.6"/></g></a>')
    if kind == 'lease':
        svg.append(calibration_marks(model_rows, calibrations, colors, X, Y))
        svg.append(formula_cards(model_rows, calibrations, {o["id"]: o for o in rows}, colors, X, Y))
    svg.append('</svg>')
    age_note = ''
    if kind == 'lease':
        new_names = ', '.join(a['label'] for a in model_rows if a['model_age_years'] == 0)
        aged_names = ', '.join(a['label'] for a in model_rows if a['model_age_years'] > 0)
        age_note = '<div class="model-cohort" data-model-segment="' + segment['id'] + '"><p class="small">' + T('Точки — ставки новых ВС. Штрихпунктир — исходная формула; короткий сплошной отрезок и полоса — привязка к выбранному источнику на его дату.', 'Points show new-aircraft rents. Dash-dot lines are the original formula; a short solid mark and band show anchoring to the selected source at its date.', 'Punkte zeigen Neuflugzeugraten. Strichpunktlinien sind die Ausgangsformel; eine kurze durchgezogene Markierung mit Band zeigt die Anpassung an die gewählte Quelle zu deren Datum.') + '</p>'
        if new_names:
            age_note += '<p class="small">' + T('Модель нового борта: ', 'New-aircraft model: ', 'Modell für neue Flugzeuge: ') + e(new_names) + '.</p>'
        if aged_names:
            age_note += '<p class="small model-age-mismatch">' + T('Модель борта около 12 лет: ', 'Model for aircraft around age 12: ', 'Modell für etwa zwölfjährige Flugzeuge: ') + e(aged_names) + '. ' + T('Её разрыв с точками новых ВС включает различие возраста и не измеряет ошибку модели.', 'Its gap from new-aircraft points includes an age difference and does not measure model error.', 'Ihr Abstand zu Neuflugzeugpunkten enthält einen Altersunterschied und misst keinen Modellfehler.') + '</p>'
        age_note += '</div>'
    return f'<h4>{title}</h4>' + age_note + '<div class="segment-scroll">' + ''.join(svg) + '</div>'


def history_section(s):
    data = json.loads((HERE / "out/segments_history.json").read_text())
    for source in data["sources"]:
        s.url(source["url"], source["title"])
    ac = {a["icao"]: a for a in data["aircraft"]}
    body = [f'<h2 id="segment-history">{T("История по сегментам: цена и лизинг", "History by segment: value and rent", "Historie nach Segmenten: Wert und Leasing")}</h2>',
            '<style>.segment-legend{margin:10px 0}.segment-legend span{display:inline-block;white-space:nowrap;margin:0 20px 6px 0;font-weight:400}.segment-legend i{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;background:currentColor}.segment-panel{margin:24px 0 34px}.segment-panel h3{font-size:18px;font-weight:500}.segment-panel h4{font-size:15px;font-weight:500;margin-bottom:5px}.segment-history{margin-top:0;min-width:620px}.segment-history[data-kind="lease"]{min-width:900px}.model-card text{font:11px var(--sans);font-weight:400}.model-card .card-title{font-size:13px;font-weight:500}.model-card .card-value{font-size:13px}.model-card .card-formula{font:10.5px var(--mono)}.model-card .card-small{font-size:9.5px}.purchase-history{margin:16px 0;padding:12px 14px;border:1px solid var(--line);border-radius:8px}.purchase-history>summary{font-weight:400}.segment-source{margin-top:10px}.model-key{line-height:1.6}.segment-scroll{max-width:100%;overflow-x:auto}.lease-assumptions{border-left:3px solid var(--guess);padding-left:12px}.model-cohort{border-left:2px solid var(--line);padding-left:10px;margin:8px 0}.model-cohort p{margin:4px 0}.model-key{display:flex;flex-wrap:wrap;gap:8px 20px;align-items:center;font-size:12.5px;color:var(--dim)}.model-key i{display:inline-block;width:36px;height:0;border-top:2px dashed var(--dim);vertical-align:middle;margin-right:6px}</style>',
            f'<p>{T("Четыре сегмента, по два типа в каждом. Открыто показан лизинг; графики цены покупки можно раскрыть отдельно. Цвет самолёта одинаков на обоих графиках. Все значения — номинальные доллары указанного периода; каталог в эти ряды не включён.", "Four segments, two types each. Lease charts are visible; purchase-price charts can be expanded separately. Each type keeps its colour across both charts. Values are nominal dollars of the stated period; catalogue prices are excluded.", "Vier Segmente mit je zwei Typen. Leasingdiagramme sind sichtbar; Kaufpreisdiagramme lassen sich separat öffnen. Jeder Typ behält seine Farbe. Die Werte sind nominale Dollar des genannten Zeitraums; Listenpreise gehören nicht zu diesen Reihen.")}</p>',
            f'<p class="small">{T("Полая точка и пунктир означают приблизительное снятие с опубликованного графика; это не новая рыночная оценка. Вертикальный отрезок показывает опубликованный диапазон ставки. Даты кварталов и годов сохраняют исходную точность и размещены в центре периода. Линии соединяют только сопоставимые наблюдения одного ряда; пробел больше полутора лет остаётся разрывом. Нажатие на точку открывает источник.", "Hollow points and dashed lines indicate approximate readings from a published chart, not new appraisals. Vertical bars show published rent ranges. Quarterly and annual dates retain their precision and are displayed at the period centre. Lines only join comparable observations within one series; gaps exceeding eighteen months remain open. Click a point to open its source.", "Hohle Punkte und gestrichelte Linien kennzeichnen ungefähre Ablesungen veröffentlichter Diagramme, keine neuen Bewertungen. Senkrechte Balken zeigen veröffentlichte Ratenspannen. Quartals- und Jahresdaten behalten ihre Genauigkeit und stehen in der Periodenmitte. Linien verbinden nur vergleichbare Beobachtungen einer Reihe; Lücken über achtzehn Monate bleiben offen. Ein Klick öffnet die Quelle.")}</p>']
    notes = {
        "turboprop": T("Исторические кривые ATR из обзора TrueNoord доступны до 2023 года. Полые точки сняты с опубликованных графиков нескольких оценщиков. Датированные оценки не продлены до 2026 года.", "TrueNoord ATR history runs through 2023. Hollow points were digitized from published charts aggregating several appraisers. These dated appraisals are not extended to 2026.", "Die ATR-Historie von TrueNoord reicht bis 2023. Hohle Punkte stammen aus veröffentlichten Diagrammen mehrerer Gutachter. Die datierten Bewertungen werden nicht bis 2026 verlängert."),
        "regional": T("У E175 более длинный ряд TrueNoord показан отдельно от AVAC: оценщики и база различаются. Ориентир E195-E2 от Oriel относится к 2026 году, новому борту и двигателю PW1923G; его нельзя переносить на любой E-Jet.", "The longer E175 TrueNoord series remains separate from AVAC because appraisers and bases differ. Oriel’s E195-E2 anchor refers to a new aircraft with PW1923G engines in 2026; it cannot be transferred to every E-Jet.", "Die längere E175-Reihe von TrueNoord bleibt wegen anderer Gutachter und Bewertungsgrundlagen von AVAC getrennt. Oriels E195-E2-Anker gilt 2026 für ein Neuflugzeug mit PW1923G-Triebwerken, nicht für jeden E-Jet."),
        "narrowbody": T("Разрыв между AVAC 2020 и свежими оценками оставлен видимым. A321neo здесь соответствует выбранному варианту A321NX: ставки XLR к нему не приписаны. Диапазоны IBA сохраняют различия условий арендатора.", "The gap between AVAC 2020 and recent appraisals remains visible. The selected A321neo reference is the A321NX variant; XLR rates are not assigned to it. IBA ranges retain differences in lessee conditions.", "Die Lücke zwischen AVAC 2020 und jüngeren Bewertungen bleibt sichtbar. Der gewählte A321neo-Anker gilt für die A321NX-Variante; XLR-Raten werden ihr nicht zugeordnet. IBA-Spannen bewahren Unterschiede der Leasingnehmerkonditionen."),
        "widebody": T("Для новых A350-900 и 787-9 есть диапазоны IBA за I квартал 2026 года. Оба ориентира ниже исходной формулы; разницу можно использовать для сценария лизинга, сохранив дату и весь диапазон.", "New A350-900 and 787-9 have IBA ranges for Q1 2026. Both anchors are below the original formula; the difference can inform a lease scenario while retaining its date and full range.", "Für neue A350-900 und 787-9 liegen IBA-Spannen für das erste Quartal 2026 vor. Beide Anker liegen unter der Ausgangsformel; die Differenz kann in ein Leasingszenario einfließen, mit Datum und vollständiger Spanne."),
    }
    body.append(f'<p class="small">{T("Кружок внутри диапазона стоит на арифметической середине его границ. Это удобная отметка сценария, а не опубликованная средняя цена сделок.", "A point inside a range marks the arithmetic midpoint of its bounds. It is a scenario marker, not a published average transaction price.", "Ein Punkt innerhalb einer Spanne markiert den arithmetischen Mittelpunkt ihrer Grenzen. Er ist eine Szenariomarkierung, kein veröffentlichter durchschnittlicher Transaktionspreis.")}</p>')
    body.append(f'<p class="small">{T("На узком экране графики прокручиваются по горизонтали.", "On a narrow screen, charts scroll horizontally.", "Auf schmalen Bildschirmen lassen sich die Diagramme horizontal verschieben.")}</p>')
    body.append(f'<p class="small">{T("На графиках лизинга добавлена сегодняшняя базовая заготовка, приведённая к долларам каждого года. Это пересчёт нынешней формулы, а не история фактически заключённых договоров. Возраст заготовки указан у каждого графика. Покупную цену калькулятор пока не моделирует, поэтому на графиках стоимости соответствующей расчётной линии нет.", "Lease charts include today's baseline expressed in each year's dollars. This translates the current formula, not actual historical contracts. Each chart states the model's age basis. The calculator does not yet model aircraft acquisition prices, so value charts have no corresponding model line.", "Leasingdiagramme enthalten die heutige Grundannahme in Dollar des jeweiligen Jahres. Dies rechnet die aktuelle Formel um und bildet keine historischen Verträge ab. Jedes Diagramm nennt die Altersbasis. Der Rechner modelliert bislang keinen Flugzeugkaufpreis; Wertdiagramme haben daher keine entsprechende Modelllinie.")}</p>')
    for original_seg in data["segments"]:
        seg = {**original_seg, "types": list(DISPLAY_TYPES[original_seg["id"]])}
        body.append(f'<section class="segment-panel"><h3>{segment_name(seg["id"])}</h3><div class="segment-legend">')
        for code, color in zip(seg["types"], COLORS):
            body.append(f'<span style="color:{color}"><i aria-hidden="true"></i>{e(ac[code]["label"])}</span>')
        body.append('</div>')
        body.append(history_chart(data, seg, "lease"))
        body.append('<details class="purchase-history"><summary>' + T("Цена ВС (оценка рынка) — раскрыть график", "Aircraft price (market appraisal) — show chart", "Flugzeugpreis (Marktwertschätzung) — Diagramm öffnen") + '</summary>')
        body.append(history_chart(data, seg, "value"))
        body.append('</details>')
        urls = sorted({o["source_url"] for o in data["observations"] if o["icao"] in seg["types"] and o["age"]["category"] == "new"})
        body.append(f'<p class="small">{notes[seg["id"]]}{s.cite(*urls)}</p>')
        rows = []
        for code in seg["types"]:
            v, l = ac[code]["coverage"]["new"]["value"], ac[code]["coverage"]["new"]["lease"]
            color = COLORS[seg["types"].index(code)]
            rows.append([f'<span style="color:{color};font-weight:400">{e(ac[code]["label"])}</span>', years_text(v["years"]), years_text(l["years"])])
        body.append('<details><summary>' + T("Периоды наблюдений", "Observation periods", "Beobachtungszeiträume") + '</summary>')
        body.append(table([T("Тип", "Type", "Typ"), T("Годы оценки нового ВС", "New-aircraft value years", "Jahre: Wert neuer Flugzeuge"),
                           T("Годы лизинга нового ВС", "New-aircraft rent years", "Jahre: Rate neuer Flugzeuge")], rows))
        body.append('</details></section>')
    aged_all = [o for o in data["observations"] if o["age"]["category"] == "aged"]
    last_aged_year = {code: max(int(o["period"][:4]) for o in aged_all if o["icao"] == code)
                     for code in {o["icao"] for o in aged_all}}
    aged = [o for o in aged_all if int(o["period"][:4]) == last_aged_year[o["icao"]]]
    body.append(f'<details><summary>{T("Возрастные ориентиры и точность исходных данных", "Aged-aircraft anchors and source precision", "Altersbezogene Anker und Quellengenauigkeit")}</summary>')
    if aged:
        body.append(f'<p class="small">{T("Последний доступный год для каждого типа. Дата видна в каждой строке: старые оценки не названы текущим рынком.", "The latest available year for each type. Each row shows its date; older appraisals are not presented as today's market.", "Das letzte verfügbare Jahr je Typ. Jede Zeile zeigt ihr Datum; ältere Bewertungen werden nicht als heutiger Markt dargestellt.")}</p>')
        rows = [[e(ac[o["icao"]]["label"]), e(o["period"]), e(str(o["age"].get("years", "—"))),
                 T("Цена, млн USD", "Value, USD m", "Wert, Mio. USD") if o["kind"] == "value" else T("Лизинг, тыс. USD/мес.", "Rent, USD k/month", "Rate, Tsd. USD/Monat"),
                 amount_text(o) + s.cite(o["source_url"])] for o in sorted(aged, key=lambda o: (o["icao"], o["period"], o["kind"]))]
        body.append(table([T("Тип", "Type", "Typ"), T("Период", "Period", "Zeitraum"), T("Возраст, лет", "Age, years", "Alter, Jahre"),
                           T("Величина", "Quantity", "Größe"), T("Значение", "Value", "Wert")], rows))
    body.append(f'<p>{T("В полном наборе отдельно сохранены точность периода, вариант, техническая база, источник, исходная ячейка или координаты снятия с графика. Допуск оцифровки описывает точность извлечения, а не рыночную неопределённость. Пустые годы остаются пустыми; прогнозы из документов не становятся историей рынка.", "The complete set retains period precision, variant, valuation condition, source, source cell or chart-reading coordinates. Digitization tolerance describes extraction precision, not market uncertainty. Missing years stay missing; forecasts in source documents are not market history.", "Der vollständige Bestand bewahrt Periodengenauigkeit, Variante, Bewertungszustand, Quelle sowie Tabellenzelle oder Ablesekoordinaten. Die Digitalisierungstoleranz beschreibt die Extraktionsgenauigkeit, nicht Marktunsicherheit. Fehlende Jahre bleiben leer; Dokumentprognosen werden nicht zur Markthistorie.")}</p></details>')
    body.append(f'<p class="small">{T("Панели показывают выбранные первичные ряды. Отдельные принятые новости за 2022–2024 годы остаются в справочнике типов, но не включены в эти линии. Пробел здесь означает отсутствие сопоставимой точки в выбранном наборе, а не отсутствие любых публикаций за год.", "Panels show selected primary-source series. Individual accepted news reports from 2022–2024 remain in the type catalogue but are not included in these lines. A gap means no comparable observation in this selection, not that no publication exists for that year.", "Die Diagramme zeigen ausgewählte Primärquellenreihen. Einzelne angenommene Nachrichtenwerte 2022–2024 bleiben im Typenkatalog, gehören aber nicht zu diesen Linien. Eine Lücke bedeutet keine vergleichbare Beobachtung in dieser Auswahl, nicht das Fehlen aller Veröffentlichungen eines Jahres.")}</p>')
    body.append(correction_explanation(json.loads((HERE/'out/lease_calibration.json').read_text()), s))
    body.append(model_description(s))
    return ''.join(body)


def model_description(s):
    data=json.loads((HERE/'out/model_reference.json').read_text())
    m=data['meta'];h=m['historical_display']
    fleet_url='https://github.com/BormatovD/FlightCost/blob/'+m['base_commit']+'/flightcostapp/fleet.py'
    seo_url='https://github.com/BormatovD/FlightCost/blob/'+m['base_commit']+'/flightcostapp/seo.py'
    s.url(fleet_url,'FlightCost: generation/MTOW lease baseline and overrides')
    s.url(seo_url,'FlightCost: nominal-USD/CPI comparison for aircraft pages')
    body=[f'<details><summary>{T("Как считается линия калькулятора", "How the calculator line is calculated", "Wie die Rechnerlinie berechnet wird")}</summary>',
          '<p class="formula">L<sub>EUR/month</sub> = L₀(generation) × (MTOW / 78 t)<sup>1.10</sup><br>L₀(new) = 345 000 EUR/month; L₀(current) = 200 000 EUR/month</p>',
          f'<p>{T("Тип выбирает одну из двух групп поколения, а максимальная взлётная масса масштабирует базовую ставку. Отдельного коэффициента сегмента, числа кресел и плавной возрастной кривой в этой формуле нет. Параметр возраста в рабочем загрузчике сейчас влияет на обслуживание. Для лизинга сохраняется условный возраст группы: новый борт или около 12 лет. Даже ATR 42-600 и ATR 72-600 текущий код относит ко второй группе — это ограничение заготовки, которое исследование должно проверить.", "The type selects one of two generation groups, and maximum take-off weight scales its base rate. This formula has no separate segment coefficient, seat-count term or continuous age curve. The production loader currently uses the age input for maintenance. Leasing retains the group's assumed age: new or around twelve years. Even ATR 42-600 and ATR 72-600 fall in the latter group in current code; that baseline limitation requires research.", "Der Typ wählt eine von zwei Generationsgruppen, die maximale Startmasse skaliert deren Grundrate. Die Formel enthält keinen separaten Segmentfaktor, keine Sitzanzahl und keine kontinuierliche Alterskurve. Der produktive Lader nutzt die Alterseingabe derzeit für Wartung. Beim Leasing bleibt das angenommene Gruppenalter: neu oder etwa zwölf Jahre. Selbst ATR 42-600 und ATR 72-600 gehören im aktuellen Code zur zweiten Gruppe; diese Grenze der Grundannahme ist zu untersuchen.")}{s.cite(fleet_url)}</p>',
          '<p class="formula">L<sub>USD,y</sub> = L<sub>EUR,2026</sub> × 1.16 × CPI<sub>y</sub> / CPI<sub>2026</sub></p>',
          f'<p>{T(f"Для графиков воспроизведён существующий пересчёт страниц типов: база — октябрь 2026 года в EUR, фиксированный якорь {n(h['usd_per_eur'],2)} USD/EUR и годовой CPI-U США. Ряд CPI заканчивается {h['cpi_last_observed_year']} годом; 2026 продлён последним годовым ростом. Это способ сопоставить номинальные доллары, а не индексация реального договора. Он не исправляет различия возраста и состояния.", f"Charts reproduce the existing aircraft-page conversion: October 2026 EUR, a fixed {n(h['usd_per_eur'],2)} USD/EUR anchor and annual US CPI-U. CPI observations end in {h['cpi_last_observed_year']}; 2026 extends the last annual growth rate. This compares nominal dollars; it is not a contract indexation rule and does not correct age or condition differences.", f"Die Diagramme übernehmen die Umrechnung der Typenseiten: EUR vom Oktober 2026, fester Anker {n(h['usd_per_eur'],2)} USD/EUR und jährlicher US-CPI-U. Der beobachtete CPI endet {h['cpi_last_observed_year']}; 2026 verlängert dessen letzte Jahreswachstumsrate. Dies vergleicht nominale Dollar, ist keine Vertragsindexierung und gleicht Alter oder Zustand nicht aus.")}{s.cite(seo_url)}</p>',
          f'<p class="small">{T(f"Общий переключатель валют и пример рейса используют другой сохранённый снимок: {n(h['research_currency_widget_usd_per_eur'],3)} USD/EUR на {h['research_currency_widget_as_of']}. Подписи графиков остаются в явно указанных USD; якорь модельной линии — часть существующего производственного метода.", f"The general currency control and flight example use a different saved snapshot: {n(h['research_currency_widget_usd_per_eur'],3)} USD/EUR on {h['research_currency_widget_as_of']}. Chart labels remain in the stated USD; the model-line anchor belongs to the existing production method.", f"Der allgemeine Währungsschalter und das Flugbeispiel verwenden einen anderen gespeicherten Stand: {n(h['research_currency_widget_usd_per_eur'],3)} USD/EUR am {h['research_currency_widget_as_of']}. Diagramme bleiben in den angegebenen USD; der Modellanker gehört zur bestehenden Produktivmethode.")}</p>']
    rows=[]
    for a in data['aircraft']:
        rows.append([e(a['label']),n(a['mtow_t'],1),T('новый','new','neu') if not a['model_age_years'] else T('около 12 лет','around age 12','etwa 12 Jahre'),money(a['raw_parametric_lease_eur_month'],'EUR'),n(a['nominal_usd_points'][-1]['lease_thousand_usd_month'],1)])
    body.append(table([T('Тип','Type','Typ'),'MTOW, t',T('Возраст модели','Model age','Modellalter'),T('База в месяц','Monthly baseline','Monatliche Basis'),T('Линия 2026, тыс. USD/мес.','2026 line, USD k/month','Linie 2026, Tsd. USD/Monat')],rows))
    body.append(f'<p>{T("Здесь показана независимая базовая заготовка. Выбранная пользователем рыночная середина и ручная ставка могут заменить её в расчёте, но не становятся независимой моделью рядом с тем же источником. Публичный снимок не показывает частные настройки оператора и сервера.", "This is the independent baseline. A user-selected market midpoint or manual rate can replace it in a calculation but cannot become an independent comparator against the same source. The public snapshot does not reveal private operator or server settings.", "Gezeigt wird die unabhängige Grundannahme. Ein gewählter Marktmittelpunkt oder manueller Satz kann sie im Rechner ersetzen, wird dadurch aber nicht zum unabhängigen Vergleich desselben Quellenwerts. Der öffentliche Stand zeigt keine privaten Betreiber- oder Servereinstellungen.")}</p></details>')
    return ''.join(body)


def leasing_section(s):
    data = json.loads((HERE / "out/lease_economics.json").read_text())
    p, b, f = data["inputs"], data["base"], data["financing"]
    fy = f["first_year"]
    body = [f'<h2 id="lease-economics">{T("Как из цены самолёта получается лизинговая ставка", "How aircraft price becomes a lease rate", "Wie aus dem Flugzeugpreis eine Leasingrate wird")}</h2>',
            f'<p>{T("Лизингодатель оплачивает самолёт сейчас, получает арендные платежи во времени и в конце сохраняет актив, который можно снова сдать или продать. Ему нужно покрыть падение стоимости, расходы и требуемую доходность вложенных денег. Поэтому ставку нельзя получить одним постоянным процентом от каталога: важны фактическая цена покупки, срок, будущая стоимость, условия договора и рынок.", "The lessor pays for an aircraft now, receives rent over time and retains an asset to re-lease or sell. Rent must cover value loss, expenses and the required return on capital. A constant percentage of catalogue price cannot determine it: actual acquisition cost, term, future value, contract conditions and the market matter.", "Der Leasinggeber bezahlt das Flugzeug heute, erhält laufende Raten und behält einen Vermögenswert zur erneuten Vermietung oder zum Verkauf. Die Rate muss Wertverlust, Kosten und die erforderliche Kapitalrendite decken. Ein fester Prozentsatz des Listenpreises genügt nicht; Kaufpreis, Laufzeit, Restwert, Vertragsbedingungen und Markt sind entscheidend.")}{s.cite('lease-002')}</p>',
            f'<p>{T("Формула ниже считает ставку, необходимую при заданных допущениях. Согласованная рыночная ставка возникает в переговорах и может отличаться. Air Lease в отчётности за 2025 год прямо описывает фиксированные ставки действующих договоров и отдельные корректировки будущих поставок по процентам или удорожанию производителя. Изменение ставки банка не переписывает автоматически уже подписанный лизинг.", "The formula below calculates required rent under stated assumptions. A negotiated market rate can differ. Air Lease's 2025 filing describes fixed rates on existing leases and separate interest or manufacturer-escalation adjustments for future deliveries. A change in borrowing rates does not automatically rewrite an existing lease.", "Die folgende Formel berechnet die notwendige Rate unter vorgegebenen Annahmen. Eine ausgehandelte Marktrate kann davon abweichen. Air Lease beschreibt im Bericht 2025 feste Raten laufender Verträge und separate Zins- oder Herstellerpreisanpassungen künftiger Lieferungen. Eine Änderung des Kreditzinses ändert einen bestehenden Leasingvertrag nicht automatisch.")}{s.cite('lease-003')}</p>',
            '<p class="formula">P + C₀ = Σ<sub>t=1…N</sub> (L − C)/(1+i)<sup>t</sup> + (S − C<sub>sale</sub>)/(1+i)<sup>N</sup><br>'
            'i = (1+r)<sup>1/12</sup> − 1; a<sub>N</sub> = [1 − (1+i)<sup>−N</sup>]/i<br>'
            'L = C + [P + C₀ − (S − C<sub>sale</sub>)/(1+i)<sup>N</sup>] / a<sub>N</sub></p>',
            f'<p>{T("Сначала все будущие суммы приводятся к сегодняшнему дню: доллар через десять лет имеет другой вес, чем доллар сейчас. P — уплаченная цена, C₀ — первоначальные издержки, C — месячные расходы владельца, S — предполагаемая цена продажи, Csale — расходы продажи. r — требуемая годовая эффективная доходность самого актива до налогов; это не процент по банковскому кредиту. N — число месяцев договора. В этой записи платежи приходят в конце месяца.", "Future amounts are first discounted to today: a dollar in ten years has a different weight from a dollar now. P is acquisition price, C₀ upfront costs, C monthly owner expenses, S assumed resale and Csale selling costs. r is the required effective annual pre-tax asset return, not the bank-loan interest rate. N is lease months. This version assumes month-end payments.", "Zukünftige Beträge werden zuerst auf heute abgezinst: Ein Dollar in zehn Jahren hat ein anderes Gewicht als ein Dollar heute. P ist der Kaufpreis, C₀ sind Anfangskosten, C monatliche Eigentümerkosten, S der angenommene Verkaufspreis und Csale Verkaufskosten. r ist die erforderliche effektive jährliche Anlagenrendite vor Steuern, nicht der Kreditzins. N bezeichnet Vertragsmonate. Diese Fassung nimmt Monatsendzahlungen an.")}</p>']
    body[3:3]=[deal_flow_section(data,s),f'<details><summary>{T("Как получены платежи: формулы, условия договора и учёт", "How the payments were derived: formulae, terms and accounting", "Wie die Zahlungen entstehen: Formeln, Bedingungen und Bilanzierung")}</summary>']
    body.append(f'<div class="lease-assumptions"><p>{T("Учебный пример: все входы ниже — наши допущения, а не раскрытая сделка и не калибровка рынка. Самолёт куплен за 50 млн USD, договор длится десять лет, затем борт продаётся. Налоги, дефолт арендатора и простой здесь ещё не моделируются.", "Illustrative example: every input below is an assumption, not a disclosed transaction or market calibration. An aircraft is bought for USD 50m, leased for ten years and then sold. Taxes, lessee default and downtime are not simulated here.", "Rechenbeispiel: Alle folgenden Eingaben sind Annahmen, keine offengelegte Transaktion oder Marktkalibrierung. Ein Flugzeug wird für 50 Mio. USD gekauft, zehn Jahre verleast und danach verkauft. Steuern, Mieterausfall und Stillstand sind hier nicht modelliert.")}</p></div>')
    body.append(table([T("Вход", "Input", "Eingabe"), T("Значение", "Value", "Wert"), T("Смысл", "Meaning", "Bedeutung")], [
        ["P", money(p["purchase_usd"], "USD"), T("цена приобретения", "acquisition price", "Anschaffungspreis")],
        ["C₀", money(p["upfront_cost_usd"], "USD"), T("издержки приобретения", "acquisition costs", "Anschaffungsnebenkosten")],
        ["N", n(p["lease_months"]), T("месяцы", "months", "Monate")],
        ["S / Csale", money(p["resale_usd"], "USD") + " / " + money(p["sale_cost_usd"], "USD"), T("продажа / расходы продажи в конце срока", "resale / selling costs at lease end", "Verkauf / Verkaufskosten am Laufzeitende")],
        ["C", money(p["owner_cost_usd_month"], "USD"), T("расходы владельца в месяц; обычное ТОиР оператора сюда не входит", "monthly owner costs; ordinary operator maintenance is excluded", "monatliche Eigentümerkosten; normale Betreiberwartung ist ausgeschlossen")],
        ["r", n(p["asset_return_annual_effective"] * 100, 1) + " %", T("годовая эффективная доходность актива", "effective annual asset return", "effektive jährliche Anlagenrendite")],
    ]))
    body.append(f'<p>{T(
        f"Получается {money(b['rent_usd_month_end'], 'USD')} в месяц. Отношение платежа к цене — {n(100*b['gross_monthly_rent_purchase_ratio'], 3)} % в месяц, или {n(100*b['gross_annual_rent_purchase_ratio'], 2)} % годовой выручки от первоначальной цены. Но доходность актива в этом примере равна выбранным {n(100*p['asset_return_annual_effective'], 1)} %, потому что учтены время, расходы и остаточная стоимость. Эти три процента отвечают на разные вопросы.",
        f"The result is {money(b['rent_usd_month_end'], 'USD')} per month. Rent is {n(100*b['gross_monthly_rent_purchase_ratio'], 3)}% of acquisition price monthly, or {n(100*b['gross_annual_rent_purchase_ratio'], 2)}% annual gross rent relative to initial price. Asset return is nevertheless the assumed {n(100*p['asset_return_annual_effective'], 1)}%, after timing, costs and residual value. These three percentages answer different questions.",
        f"Das Ergebnis beträgt {money(b['rent_usd_month_end'], 'USD')} pro Monat. Die Rate entspricht monatlich {n(100*b['gross_monthly_rent_purchase_ratio'], 3)} % des Kaufpreises beziehungsweise jährlich {n(100*b['gross_annual_rent_purchase_ratio'], 2)} % Bruttomiete bezogen auf den Anfangspreis. Die Anlagenrendite beträgt dennoch die angenommenen {n(100*p['asset_return_annual_effective'], 1)} %, nach Berücksichtigung von Zeit, Kosten und Restwert. Diese drei Prozentsätze beantworten verschiedene Fragen.")}</p>')
    body.append(f'<p class="small">{T(f"В реальных договорах месячная оплата часто авансовая. При переносе только аренды на начало месяца и сохранении расходов в конце требуемая ставка этого же примера составляет {money(b['rent_usd_month_advance'], 'USD')}. Дата платежа тоже часть экономики сделки.", f"Actual contracts often require monthly payment in advance. Moving rent alone to the start of the month, with costs still at month end, changes this example's required rent to {money(b['rent_usd_month_advance'], 'USD')}. Payment timing is part of the economics.", f"Verträge sehen häufig monatliche Vorauszahlung vor. Wird nur die Rate an den Monatsanfang verschoben, während Kosten am Monatsende bleiben, beträgt die erforderliche Rate dieses Beispiels {money(b['rent_usd_month_advance'], 'USD')}. Auch der Zahlungszeitpunkt beeinflusst die Wirtschaftlichkeit.")}{s.cite('lease-001')}</p>')
    selected = [x for x in data["sensitivity"] if x["changed_input"] in ("asset_return_annual_effective", "resale_usd") and x["value"] != p[x["changed_input"]]]
    rows = [[T("Базовый пример", "Base example", "Basisbeispiel"), money(b["rent_usd_month_end"], "USD")]]
    for x in selected:
        label = (T("Требуемая доходность", "Required return", "Erforderliche Rendite") + f' {n(x["value"]*100, 0)} %') if x["changed_input"] == "asset_return_annual_effective" else T("Продажа через 10 лет: ", "Resale in 10 years: ", "Verkauf nach 10 Jahren: ") + money(x["value"], "USD")
        rows.append([label, money(x["rent_usd_month_end"], "USD")])
    body.append(table([T("Меняем один вход, остальные фиксированы", "One input changes; others stay fixed", "Eine Eingabe ändert sich, übrige bleiben konstant"), T("Необходимая ставка в месяц", "Required monthly rent", "Erforderliche Monatsrate")], rows))
    body.append(f'<p>{T("Эта таблица пересчитывает ставку до подписания договора. После подписания фиксированный платёж сохраняется: если будущая продажа окажется дешевле, снизится фактическая доходность владельца. При продаже за 15 млн вместо 25 млн USD тот же денежный поток даёт около 6,1 % годовых по активу вместо 8 %. Остаточная стоимость — риск, а не гарантированный возврат денег.", "This table recalculates rent before signing. Once a fixed-rate lease is signed, lower realized resale reduces the owner's return instead. Selling for USD 15m rather than USD 25m makes the same rent stream yield about 6.1% annually on the asset instead of 8%. Residual value is a risk, not guaranteed capital recovery.", "Die Tabelle berechnet die Rate vor Vertragsabschluss neu. Nach Unterzeichnung bleibt eine feste Rate bestehen; ein niedrigerer Verkaufspreis senkt die tatsächliche Rendite. Ein Verkauf für 15 statt 25 Mio. USD ergibt bei gleichen Raten rund 6,1 % jährliche Anlagenrendite statt 8 %. Der Restwert ist ein Risiko, keine garantierte Kapitalrückzahlung.")}</p>')

    body.append(f'<h3>{T("Кто получает деньги и что здесь является прибылью", "Who receives cash, and what counts as profit", "Wer erhält Geld, und was ist Gewinn?")}</h3>')
    body.append(f'<p>{T("Теперь добавим финансирование отдельно. Банк выдаёт 70 % цены покупки под 6 % годовых эффективных. Платёж рассчитан как для погашения за 15 лет, но кредит заканчивается через десять: оставшийся долг нужно вернуть при продаже. Собственник вкладывает остальную цену и первоначальные расходы. Это учебная структура финансирования, не условия конкретного банка.", "Now add financing separately. A bank lends 70% of purchase price at a 6% effective annual rate. Payments amortize over fifteen years, but the loan matures in ten; outstanding principal must be repaid at sale. Equity funds the remaining price and upfront costs. This is an illustrative financing structure, not a bank quote.", "Nun wird die Finanzierung separat ergänzt. Eine Bank finanziert 70 % des Kaufpreises zu 6 % effektiv pro Jahr. Die Raten entsprechen fünfzehnjähriger Tilgung, die Laufzeit endet jedoch nach zehn Jahren; die Restschuld wird beim Verkauf zurückgezahlt. Eigenkapital deckt den übrigen Preis und die Anfangskosten. Dies ist eine Beispielstruktur, kein Bankangebot.")}</p>')
    body.append(table([T("Денежный поток", "Cash flow", "Zahlungsstrom"), T("Сумма", "Amount", "Betrag"), T("Что означает", "Meaning", "Bedeutung")], [
        [T("В начале: банк", "At inception: bank", "Zu Beginn: Bank"), money(f["opening_debt_usd"], "USD"), T("заём, который надо вернуть", "borrowing that must be repaid", "zurückzuzahlender Kredit")],
        [T("В начале: собственник", "At inception: equity", "Zu Beginn: Eigenkapital"), money(f["initial_equity_usd"], "USD"), T("капитал под риском", "capital at risk", "Risikokapital")],
        [T("Авиакомпания → владелец, в месяц", "Airline → owner, monthly", "Airline → Eigentümer, monatlich"), money(b["rent_usd_month_end"], "USD"), T("базовая арендная выручка", "basic rental revenue", "Grundleasingerlös")],
        [T("Владелец → банк, в месяц", "Owner → bank, monthly", "Eigentümer → Bank, monatlich"), money(f["scheduled_debt_payment_usd_month"], "USD"), T("проценты и погашение долга вместе", "interest and principal together", "Zins und Tilgung zusammen")],
        [T("Остаток после расходов и банка, в месяц", "After costs and bank payment, monthly", "Nach Kosten und Bankrate, monatlich"), money(f["regular_equity_cash_usd_month"], "USD"), T("денежный поток собственнику до налогов", "equity cash flow before tax", "Eigenkapital-Cashflow vor Steuern")],
        [T("Непогашенный кредит через 10 лет", "Loan outstanding after 10 years", "Restschuld nach 10 Jahren"), money(f["remaining_debt_at_sale_usd"], "USD"), T("вычитается из продажи", "deducted from sale proceeds", "vom Verkaufserlös abzuziehen")],
        [T("Продажа: остаток собственнику", "Sale: net cash to equity", "Verkauf: Nettozufluss an Eigenkapital"), money(f["net_sale_cash_to_equity_usd"], "USD"), T("после расходов продажи и остатка кредита", "after sale costs and remaining debt", "nach Verkaufskosten und Restschuld")],
    ]))
    body.append(f'<p>{T(f"При выполнении всех этих допущений доходность собственного капитала получается {n(f['equity_irr_annual_effective_pre_tax']*100, 1)} % годовых до налогов. Заём увеличивает её здесь, потому что финансирование дешевле доходности актива. Но он также оставляет обязательные платежи и усиливает риск потери собственного капитала. Полученные {money(f['regular_equity_cash_usd_month'], 'USD')} в месяц нельзя назвать чистой прибылью.", f"If all assumptions hold, equity earns {n(f['equity_irr_annual_effective_pre_tax']*100, 1)}% annually before tax. Borrowing raises the return here because financing costs less than the asset earns. It also creates mandatory payments and greater equity-loss exposure. The monthly {money(f['regular_equity_cash_usd_month'], 'USD')} is not net accounting profit.", f"Wenn alle Annahmen eintreten, ergibt sich eine Eigenkapitalrendite von {n(f['equity_irr_annual_effective_pre_tax']*100, 1)} % pro Jahr vor Steuern. Der Kredit erhöht sie hier, weil Finanzierung günstiger als die Anlagenrendite ist. Er schafft zugleich feste Zahlungsverpflichtungen und verstärkt das Eigenkapitalrisiko. Die monatlichen {money(f['regular_equity_cash_usd_month'], 'USD')} sind kein bilanzieller Nettogewinn.")}</p>')
    body.append('<p class="formula">' + T("Прибыль", "Profit", "Gewinn") + ' ≈ ' + T("арендная выручка − расходы − амортизация − проценты − налоги", "rental revenue − costs − depreciation − interest − taxes", "Leasingerlös − Kosten − Abschreibung − Zinsen − Steuern") + '<br>'
                + T("Денежный поток собственнику", "Equity cash flow", "Eigenkapital-Cashflow") + ' = ' + T("аренда − денежные расходы − проценты − погашение долга", "rent − cash costs − interest − principal repayment", "Leasingzahlungen − zahlungswirksame Kosten − Zinsen − Tilgung") + '</p>')
    body.append(f'<p>{T(f"Для учётной иллюстрации принимаем срок службы 25 лет и остаток в конце службы 7,5 млн USD. Это отдельное допущение: оно не равно продаже за 25 млн через десять лет. Первоначальные издержки капитализированы. За первый год амортизация составит {money(fy['depreciation_usd'], 'USD')}, проценты — {money(fy['interest_usd'], 'USD')}. Тогда прибыль до налогов и прочих статей — {money(fy['accounting_profit_usd_before_tax_and_other_items'], 'USD')}, а денежный поток собственнику после платежей банку — {money(fy['equity_cash_usd_before_tax_and_terminal_sale'], 'USD')}. Погашение тела кредита уменьшает деньги, но не является расходом прибыли; амортизация действует наоборот.", f"For an accounting illustration, assume a 25-year useful life and USD 7.5m residual at the end of that life. This differs from a USD 25m resale after ten years. Upfront acquisition costs are capitalized. First-year depreciation is {money(fy['depreciation_usd'], 'USD')} and interest {money(fy['interest_usd'], 'USD')}. Profit before tax and other items is {money(fy['accounting_profit_usd_before_tax_and_other_items'], 'USD')}, while equity cash after bank payments is {money(fy['equity_cash_usd_before_tax_and_terminal_sale'], 'USD')}. Principal repayment reduces cash, not accounting profit; depreciation does the reverse.", f"Für die Bilanzillustration gelten 25 Jahre Nutzungsdauer und 7,5 Mio. USD Restwert am Lebensende. Dies unterscheidet sich vom Verkauf für 25 Mio. USD nach zehn Jahren. Anfangskosten werden aktiviert. Im ersten Jahr betragen Abschreibung {money(fy['depreciation_usd'], 'USD')} und Zinsen {money(fy['interest_usd'], 'USD')}. Gewinn vor Steuern und sonstigen Posten: {money(fy['accounting_profit_usd_before_tax_and_other_items'], 'USD')}; Eigenkapital-Cashflow nach Bankzahlungen: {money(fy['equity_cash_usd_before_tax_and_terminal_sale'], 'USD')}. Tilgung vermindert Geld, nicht den bilanziellen Gewinn; Abschreibung wirkt umgekehrt.")}</p>')
    body.append(table([T("Участник", "Participant", "Beteiligter"), T("Источник заработка", "Source of earnings", "Ertragsquelle"), T("Чем рискует", "Exposure", "Risiko")], [
        [T("Производитель / продавец", "Manufacturer / seller", "Hersteller / Verkäufer"), T("маржа продажи, отдельно — согласованные услуги и запчасти", "sale margin; separately contracted services and parts", "Verkaufsmarge; separat vereinbarte Leistungen und Teile"), T("затраты, сроки поставки, гарантии", "costs, delivery timing, warranties", "Kosten, Liefertermine, Gewährleistung")],
        [T("Лизингодатель", "Lessor", "Leasinggeber"), T("арендный поток и последующая продажа за вычетом затрат и финансирования", "rent and later resale less costs and financing", "Raten und späterer Verkauf abzüglich Kosten und Finanzierung"), T("неплатежи, простой, возврат и будущая цена", "default, downtime, return condition and future price", "Ausfall, Stillstand, Rückgabezustand und künftiger Preis")],
        [T("Банк / держатель облигации", "Bank / bondholder", "Bank / Anleihegläubiger"), T("проценты и комиссии; возврат тела долга — не заработок", "interest and fees; returned principal is not earnings", "Zinsen und Gebühren; Tilgungsrückfluss ist kein Ertrag"), T("кредитный риск, стоимость собственного фондирования", "credit risk and its own funding cost", "Kreditrisiko und eigene Refinanzierungskosten")],
        [T("Авиакомпания", "Airline", "Fluggesellschaft"), T("выручка от перевозок за вычетом лизинга и всех расходов рейсов", "transport revenue less leasing and all flight costs", "Verkehrserlös abzüglich Leasing und sämtlicher Flugkosten"), T("спрос, тариф, топливо, исполнение условий договора", "demand, fares, fuel and contractual performance", "Nachfrage, Tarife, Treibstoff und Vertragserfüllung")],
        [T("Посредники и сервис", "Intermediaries and services", "Vermittler und Dienstleister"), T("согласованные комиссии, юридические и технические услуги, обслуживание", "agreed fees, legal and technical services, maintenance", "vereinbarte Gebühren, rechtliche und technische Leistungen, Wartung"), T("стоимость и качество работ, договорная ответственность", "service cost, quality and contractual liability", "Kosten, Qualität und vertragliche Haftung")],
    ]))
    body.append(f'<h3>{T("Как заключается сделка", "How a transaction is arranged", "Wie eine Transaktion zustande kommt")}</h3>')
    body.append(f'<p>{T("Самолёт может прийти из заказа лизингодателя производителю, с вторичного рынка или через sale-and-leaseback — авиакомпания продаёт борт и сразу арендует его обратно. Например, Lufthansa в 2025 году раскрыла такую сделку для 15 самолётов семейства A320 на 72 месяца и четырёх A350 на 144 месяца. Срок и будущая стоимость зависят от конкретного контракта.", "An aircraft may come from a lessor's manufacturer order, the secondary market, or a sale-and-leaseback: an airline sells it and leases it back. Lufthansa disclosed such 2025 transactions for fifteen A320-family aircraft over 72 months and four A350s over 144 months. Term and residual exposure are contract-specific.", "Ein Flugzeug kann aus einer Herstellerbestellung des Leasinggebers, vom Sekundärmarkt oder aus Sale-and-Leaseback stammen: Die Airline verkauft es und least es zurück. Lufthansa meldete für 2025 solche Transaktionen mit fünfzehn A320-Familienflugzeugen über 72 Monate und vier A350 über 144 Monate. Laufzeit und Restwertrisiko hängen vom Vertrag ab.")}{s.cite('lease-004')}</p>')
    body.append(table([T("Шаг", "Step", "Schritt"), T("Что согласуют и проверяют", "What is agreed and checked", "Was vereinbart und geprüft wird")], [
        [T("1. Самолёт и контрагент", "1. Aircraft and counterparty", "1. Flugzeug und Vertragspartner"), T("модификация, срок поставки, состояние и документы; платёжеспособность и способность оператора обслуживать борт", "variant, delivery date, condition and records; airline credit and maintenance capability", "Variante, Liefertermin, Zustand und Unterlagen; Bonität und Wartungsfähigkeit")],
        [T("2. Основные условия", "2. Heads of terms", "2. Eckpunkte"), T("письмо о намерениях: срок, ставка, депозит, резервирование борта и ключевые условия возврата", "letter of intent: term, rent, deposit, aircraft reservation and key return conditions", "Absichtserklärung: Laufzeit, Rate, Kaution, Reservierung und wesentliche Rückgabebedingungen")],
        [T("3. Договор и финансирование", "3. Contract and financing", "3. Vertrag und Finanzierung"), T("подробный договор, страхование, обеспечение, допустимая эксплуатация, события дефолта, проверки до закрытия", "detailed contract, insurance, security, permitted operation, defaults and closing conditions", "Detailvertrag, Versicherung, Sicherheiten, zulässiger Betrieb, Ausfallereignisse und Vollzugsbedingungen")],
        [T("4. Приёмка и начало аренды", "4. Acceptance and lease start", "4. Abnahme und Leasingbeginn"), T("осмотр самолёта и записей, выполнение условий поставки, оплата покупки и документированная передача", "aircraft and records inspection, delivery conditions, purchase payment and documented handover", "Prüfung von Flugzeug und Unterlagen, Lieferbedingungen, Kaufzahlung und dokumentierte Übergabe")],
        [T("5. Эксплуатация и возврат", "5. Operation and return", "5. Betrieb und Rückgabe"), T("платежи, технические резервы и контроль состояния; затем продление, возврат, новый арендатор или продажа", "payments, maintenance reserves and condition monitoring; then extension, return, re-lease or sale", "Zahlungen, Wartungsrücklagen und Zustandskontrolle; danach Verlängerung, Rückgabe, Neuvermietung oder Verkauf")],
    ]))
    body.append(f'<p class="small">{T("Это общая последовательность, а конкретные обязательства определяет подписанный договор. Продажа самолёта между владельцами может сопровождаться передачей действующего договора аренды — самолёт при этом не обязан уходить из парка авиакомпании.", "This is a general sequence; the signed contract sets specific obligations. An aircraft sale between owners can transfer the existing lease without requiring the aircraft to leave its airline's fleet.", "Dies ist ein allgemeiner Ablauf; konkrete Pflichten ergeben sich aus dem unterzeichneten Vertrag. Beim Eigentümerwechsel kann der bestehende Leasingvertrag übertragen werden, ohne dass das Flugzeug die Airline-Flotte verlässt.")}{s.cite('lease-001', 'lease-002', 'lease-006')}</p>')
    body.append(f'<h3>{T("Какие платежи нельзя смешивать", "Payments that must be separated", "Welche Zahlungen getrennt bleiben müssen")}</h3>')
    body.append(f'<p>{T("Базовая аренда оплачивает пользование самолётом. Обеспечительный депозит защищает исполнение обязательств; условия его возврата зависят от договора. Технические резервы накапливаются под согласованные события обслуживания, а возмещение из них требует выполнения условий. При возврате могут возникнуть компенсации за состояние. Поэтому поступивший резерв или депозит нельзя целиком записать в свободную прибыль владельца.", "Basic rent pays for use of the aircraft. A security deposit supports performance, with repayment governed by the contract. Maintenance reserves accumulate for agreed events and reimbursements depend on eligibility. Return-condition compensation can also arise. A received deposit or reserve is therefore not entirely free owner profit.", "Die Grundrate bezahlt die Nutzung. Eine Kaution sichert Verpflichtungen; ihre Rückzahlung folgt dem Vertrag. Wartungsrücklagen dienen vereinbarten Ereignissen, Erstattungen sind an Bedingungen gebunden. Hinzu können Ausgleichszahlungen für den Rückgabezustand kommen. Eingegangene Kautionen oder Rücklagen sind daher nicht vollständig freier Eigentümergewinn.")}{s.cite('lease-001', 'lease-002')}</p>')
    body.append(f'<p>{T("Для калькулятора нужно отдельно вести стоимость рейса и потребность в деньгах. Если резерв перечислен, а ремонт затем возмещён из этого же резерва, нельзя посчитать и весь резерв, и тот же ремонт вторым расходом. При покупке собственным капиталом и при аренде нужны разные модели владения. Для авиакомпании аренда также не означает отсутствия балансового обязательства: IFRS 16 предусматривает актив права пользования и обязательство по аренде с оговорёнными стандартом исключениями.", "The calculator needs separate views of flight cost and cash requirements. If reserves are paid and later reimburse the same maintenance, counting both in full duplicates that cost. Ownership and leasing need different capital models. Leasing also does not imply no balance-sheet obligation for the airline: IFRS 16 provides for right-of-use assets and lease liabilities, with the standard's exceptions.", "Der Rechner braucht getrennte Sichten auf Flugkosten und Liquiditätsbedarf. Werden Rücklagen später für dieselbe Wartung erstattet, würde die vollständige Erfassung beider Beträge Kosten doppelt zählen. Eigentum und Leasing erfordern unterschiedliche Kapitalmodelle. Leasing bedeutet zudem keine fehlende Bilanzverpflichtung: IFRS 16 sieht Nutzungsrechte und Leasingverbindlichkeiten mit den Ausnahmen des Standards vor.")}{s.cite('lease-005')}</p>')
    body.append('</details>')
    return ''.join(body)
