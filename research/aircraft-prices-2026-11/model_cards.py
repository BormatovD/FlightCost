"""Small formula cards and dated calibration marks for the history panels.

Historical axes remain nominal USD. A calibration mark uses its source period;
it is neither a second independent observation nor a historical backcast.
"""
from __future__ import annotations

from _report import T, e, n


DISPLAY_TYPES = {
    "turboprop": ("AT46", "AT76"),
    "regional": ("E75L", "E295"),
    "narrowbody": ("A20N", "A21N"),
    "widebody": ("A359", "B789"),
}


def range_label(low, high):
    return n(low / 1000) + ("–" + n(high / 1000) if low != high else "")


def midpoint_label(value):
    scaled = value / 1000
    return n(scaled, 1 if scaled % 1 else 0)


def period_label(period):
    if "Q" in period:
        year, quarter = period.split("-Q")
        return T(f"{quarter} кв. {year}", f"Q{quarter} {year}", f"Q{quarter} {year}")
    return period


def calibration_marks(aircraft, calibrations, colors, X, Y):
    parts = []
    for a in aircraft:
        record = calibrations.get(a["icao"], {})
        cal = record.get("calibration", {})
        if cal.get("multiplier_mid") is None:
            continue
        start, end = cal["display_span_x"]
        x1, x2 = X(start), X(end)
        low, high, mid = [Y(cal[k] / 1000) for k in ("amount_low_usd", "amount_high_usd", "amount_mid_usd")]
        col = colors[a["icao"]]
        title = T("После привязки к источнику", "After source anchoring", "Nach Quellenanpassung")
        unit = T("тыс. USD в месяц", "USD thousands per month", "Tsd. USD pro Monat")
        parts.append(f'<g class="model-correction" data-icao="{a["icao"]}" data-period="{e(cal["period"])}" '
                     f'data-model-age-years="{cal["age_years"]}" data-multiplier="{cal["multiplier_mid"]:.12g}" '
                     f'data-independent-validation="false"><title>{e(title)}: '
                     f'{range_label(cal["amount_low_usd"], cal["amount_high_usd"])} {unit}; '
                     f'k={cal["multiplier_mid"]:.6g}</title>')
        if high != low:
            parts.append(f'<rect x="{x1:.2f}" y="{high:.2f}" width="{x2-x1:.2f}" height="{low-high:.2f}" '
                         f'fill="{col}" opacity=".20"/>')
        parts.append(f'<path d="M {x1:.2f} {mid:.2f} H {x2:.2f}" fill="none" stroke="{col}" '
                     'stroke-width="4" stroke-linecap="round"/></g>')
    return ''.join(parts)


def formula_cards(aircraft, calibrations, colors, X, Y):
    parts = []
    ordered = sorted(aircraft, key=lambda a: a["nominal_usd_points"][-1]["lease_thousand_usd_month"], reverse=True)
    for index, a in enumerate(ordered):
        code = a["icao"]
        cal = calibrations.get(code, {}).get("calibration", {})
        last = a["nominal_usd_points"][-1]
        x, y, width, height = 728, 30 + 158 * index, 238, 145
        col = colors[code]
        before = last["lease_thousand_usd_month"]
        has_after = cal.get("multiplier_mid") is not None
        age = T("новый борт", "new aircraft", "Neuflugzeug") if a["model_age_years"] == 0 else T("борт ≈12 лет", "aircraft ≈12 years", "Flugzeug ≈12 Jahre")
        before_label = T("До", "Before", "Vorher") if has_after else T("Модель", "Model", "Modell")
        formula = f'{n(a["reference_lease_eur_month"]/1000)} × ({n(a["mtow_t"], 1)}/78)^1,10 × 1,16'
        # Keep decimal notation local without changing the stored equation.
        formula = formula.replace("^1,10", "^" + n(1.1, 2)).replace("× 1,16", "× " + n(1.16, 2))
        parts.append(f'<path class="model-card-link" data-icao="{code}" d="M {X(last["x"]):.2f} {Y(before):.2f} '
                     f'H {x-12} V {y+58} H {x}" fill="none" stroke="{col}" stroke-width="1" opacity=".5"/>')
        parts.append(f'<g class="model-card" data-icao="{code}" data-model-age-years="{a["model_age_years"]}">'
                     f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="7" '
                     'fill="var(--panel)" stroke="var(--line)"/>')
        lines = [
            (20, a["label"], col, "card-title"),
            (38, age + " · 2026", "var(--dim)", "card-note"),
            (60, f'{before_label}: {n(before)} ' + T("тыс. USD/мес.", "USD k/month", "Tsd. USD/Monat"), "var(--ink)", "card-value"),
            (79, formula, "var(--dim)", "card-formula"),
        ]
        if has_after:
            after = midpoint_label(cal["amount_mid_usd"])
            span = range_label(cal["amount_low_usd"], cal["amount_high_usd"])
            if cal["amount_low_usd"] != cal["amount_high_usd"]:
                after += " (" + span + ")"
            lines += [
                (104, T("После", "After", "Danach") + ": " + after, col, "card-value"),
                (124, "k = " + n(cal["multiplier_mid"], 3) + " · " + period_label(cal["period"]), "var(--dim)", "card-note"),
                (138, T("Ориентир; не проверка прогноза", "Anchor; not a forecast test", "Anker; kein Prognosetest"), "var(--dim)", "card-small"),
            ]
        else:
            lines += [
                (104, T("Поправка не определена", "Correction not established", "Korrektur nicht bestimmt"), "var(--ink)", "card-note"),
                (122, T("Точки относятся к новым ВС", "Points refer to new aircraft", "Punkte gelten für Neuflugzeuge"), "var(--dim)", "card-note"),
                (138, T("Разный возраст сравнивать нельзя", "Age bases are not comparable", "Altersbasis nicht vergleichbar"), "var(--dim)", "card-small"),
            ]
        for dy, value, fill, cls in lines:
            parts.append(f'<text x="{x+12}" y="{y+dy}" class="{cls}" fill="{fill}">{e(value)}</text>')
        parts.append('</g>')
    return ''.join(parts)


def correction_explanation(data, sources):
    parts = [f'<h3 id="lease-correction">{T("Что означает «после»", "What “after” means", "Was „danach“ bedeutet")}</h3>',
             f'<p>{T("Для пяти новых типов возраст совпадает с базой формулы. Их ставку можно привязать к датированному ориентиру: сохранить диапазон источника, а для одного сценария взять его середину. Получившийся коэффициент относится к конкретному типу, возрасту, периоду и условиям. Он не делает формулу универсальной и не подтверждает прогноз будущих ставок.", "For five new-aircraft types, the age matches the formula’s basis. Their rent can be anchored to a dated reference: retain the source range and use its midpoint for one scenario. The resulting factor belongs to a particular type, age, period and set of conditions. It neither makes the formula universal nor validates future rent forecasts.", "Bei fünf Neuflugzeugtypen stimmt das Alter mit der Formelbasis überein. Die Rate lässt sich an einen datierten Anker anpassen: Quellenspanne bewahren und für ein Szenario den Mittelpunkt verwenden. Der Faktor gilt für einen Typ, ein Alter, einen Zeitraum und bestimmte Bedingungen. Er macht die Formel weder universell noch validiert er zukünftige Leasingprognosen.")}</p>',
             '<p class="formula">L<sub>after,type,age,t₀</sub> = L<sub>model,type,age,t₀</sub> × k<br>'
             'k = [(L<sub>low,t₀</sub> + L<sub>high,t₀</sub>) / 2] / L<sub>model,type,age,t₀</sub></p>',
             f'<p class="small">{T("Короткая отметка занимает только период датировки источника. Совпадение с ним заложено в расчёт и не является независимой проверкой. За его пределами линия «после» не дорисована. У ATR и E175 поправки нет: нужны сопоставимые ставки для борта около 12 лет.", "The short mark spans only the source’s dating precision. Its agreement with that source is built into the calculation, not an independent test. The “after” line is not extended beyond it. ATR and E175 have no correction: comparable rents for aircraft around age twelve are needed.", "Die kurze Markierung umfasst nur die Datierungsgenauigkeit der Quelle. Die Übereinstimmung ist in die Rechnung eingebaut und kein unabhängiger Test. Die Linie wird darüber hinaus nicht fortgesetzt. Für ATR und E175 fehlt eine Korrektur: Benötigt werden vergleichbare Raten für etwa zwölfjährige Flugzeuge.")}</p>',
             f'<p class="small">{T("На графиках используется фиксированный курс 1,16 USD/EUR исходной линии. В примере рейса ниже — снимок 1,113 USD/EUR. Поэтому для A320neo поправка на шкале графика около +0,9%, а изменение суммы в EUR на рейс около +5,2%: разница включает валютный пересчёт.", "Charts use the original line’s fixed 1.16 USD/EUR convention. The flight example below uses the 1.113 USD/EUR snapshot. Thus the A320neo chart correction is about +0.9%, while EUR cost per flight changes about +5.2%; the difference includes FX conversion.", "Die Diagramme verwenden den festen Kurs der Ausgangslinie von 1,16 USD/EUR. Das Flugbeispiel unten nutzt den Stand 1,113 USD/EUR. Daher beträgt die A320neo-Korrektur im Diagramm etwa +0,9%, die Änderung des EUR-Betrags je Flug etwa +5,2%; die Differenz enthält die Währungsumrechnung.")}</p>',
             '<details><summary>' + T("Числа и границы применения поправки", "Correction values and limits", "Korrekturwerte und Anwendungsgrenzen") + '</summary>',
             '<div class="tw"><table id="lease-calibration"><thead><tr>']
    heads = [T("Тип и период", "Type and period", "Typ und Zeitraum"),
             T("До, тыс. USD/мес.", "Before, USD k/month", "Vorher, Tsd. USD/Monat"),
             T("После, середина (диапазон)", "After, midpoint (range)", "Danach, Mitte (Spanne)"),
             "k", T("Изменение", "Change", "Änderung")]
    parts += ["".join('<th>' + h + '</th>' for h in heads), '</tr></thead><tbody>']
    for a in data['aircraft']:
        c = a['calibration']
        if c['multiplier_mid'] is None:
            continue
        after = midpoint_label(c['amount_mid_usd'])
        if c['amount_high_usd'] != c['amount_low_usd']:
            after += ' (' + range_label(c['amount_low_usd'], c['amount_high_usd']) + ')'
        cells = [e(a['label']) + ' · ' + period_label(c['period']) + sources.cite(c['source_url']),
                 n(c['model_before_usd_month']/1000, 1), after, n(c['multiplier_mid'], 3), n(c['change_pct'], 1, sign=True) + '%']
        parts.append(f'<tr data-icao="{a["icao"]}">' + ''.join('<td>' + v + '</td>' for v in cells) + '</tr>')
    parts += ['</tbody></table></div>',
              f'<p>{T("В этой таблице все суммы приведены к той же шкале, что на графиках: 1,16 USD за EUR, как в исходной линии калькулятора. Это условие сравнения. Пример распределения лизинга на рейс ниже использует сохранённый курс 1,113; разницу валютных предпосылок нельзя приписывать рыночной поправке. При вводе ставки в калькулятор нужно использовать один выбранный курс для обеих сумм.", "This table uses the chart’s convention: 1.16 USD per EUR, matching the original calculator line. It is a comparison assumption. The flight-allocation example below uses the saved 1.113 rate; this FX difference must not be attributed to the market correction. When entering rent into the calculator, use one chosen FX rate for both amounts.", "Die Tabelle verwendet die Diagrammkonvention von 1,16 USD je EUR wie die ursprüngliche Rechnerlinie. Das ist eine Vergleichsannahme. Das Flugkostenbeispiel unten verwendet den gespeicherten Kurs 1,113; diese Wechselkursdifferenz gehört nicht zur Marktkorrektur. Bei der Eingabe im Rechner ist derselbe gewählte Kurs für beide Beträge zu verwenden.")}</p>',
              f'<p>{T("Коэффициенты не внесены в общую заготовку калькулятора. Это проверяемый вариант для ввода ставки по источнику. Для автоматического выбора по типу и возрасту ещё нужны правило свежести, технического состояния и приоритет ручных условий оператора. CPI здесь нужен для сравнения денежных шкал, а не как доказанный закон изменения арендной платы.", "These factors do not change the calculator’s general baseline. They are a reviewable way to enter a source-based rent. Automatic selection by type and age still needs freshness and condition rules, while preserving the operator’s manual terms. CPI aligns monetary scales here; it is not an established law of rent changes.", "Diese Faktoren ändern die allgemeine Rechner-Grundannahme nicht. Sie sind ein nachvollziehbarer Weg, eine quellengestützte Rate einzugeben. Automatische Auswahl nach Typ und Alter braucht noch Regeln zu Aktualität und Zustand sowie Vorrang manueller Betreiberkonditionen. Der CPI gleicht hier Geldmaßstäbe an und ist kein nachgewiesenes Gesetz der Ratenentwicklung.")}</p></details>']
    return ''.join(parts)
