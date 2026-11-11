"""Translated, data-backed results of the first long-horizon demand experiments."""
from __future__ import annotations

import json
from pathlib import Path

from _report import T, e, n

HERE = Path(__file__).resolve().parent
EUROSTAT_META = "https://ec.europa.eu/eurostat/cache/metadata/en/avia_pa_esms.htm"

CSS = """<style>
.modelling-update .evolution-scroll{max-width:100%;overflow-x:auto;margin:12px 0}
.modelling-update .evolution-chart{display:block;min-width:620px}
.modelling-update .evolution-legend{display:flex;flex-wrap:wrap;gap:8px 24px;margin:8px 0;font-size:13px}
.modelling-update .evolution-legend span{display:inline-flex;align-items:center;gap:7px;white-space:nowrap;flex:0 0 auto}
.modelling-update .evolution-legend i{display:inline-block;width:14px;height:7px;border-radius:2px}
.modelling-update .chart .evolution-label{font:12px var(--sans);fill:var(--ink);font-weight:400}
.modelling-update .chart .evolution-value{font:12px var(--sans);font-weight:400}
.modelling-update .chart .evolution-count{font:10.5px var(--sans);fill:var(--dim)}
.modelling-update .evolution-figure{margin:18px 0 22px}
.modelling-update .evolution-figure figcaption{font-size:13px;color:var(--dim);margin:8px 0}
.modelling-update .method-note{border-left:2px solid var(--line);padding-left:14px;color:var(--dim)}
</style>"""


def _percent(value, *, sign=False):
    return "—" if value is None else n(value * 100, 1, sign=sign) + "%"


def _table(heads, rows, table_id, row_attrs=None):
    rendered = []
    for index, row in enumerate(rows):
        attrs = "" if row_attrs is None else " " + row_attrs[index]
        rendered.append(f'<tr{attrs}>' + "".join(f"<td>{x}</td>" for x in row) + "</tr>")
    return (f'<div class="tw"><table id="{e(table_id)}"><thead><tr>'
            + "".join(f"<th>{e(h)}</th>" for h in heads)
            + "</tr></thead><tbody>" + "".join(rendered) + "</tbody></table></div>")


def _distance_label(key):
    return {
        "under1500km": T(f"До {n(1500)} км", f"Under {n(1500)} km", f"Unter {n(1500)} km"),
        "1500to4000km": T(f"{n(1500)}–{n(4000)} км", f"{n(1500)}–{n(4000)} km", f"{n(1500)}–{n(4000)} km"),
        "4000to6500km": T(f"{n(4000)}–{n(6500)} км", f"{n(4000)}–{n(6500)} km", f"{n(4000)}–{n(6500)} km"),
        "6500pluskm": T(f"От {n(6500)} км", f"{n(6500)} km and over", f"Ab {n(6500)} km"),
    }[key]


def _capacity_chart(evolution):
    """Two signed bars per distance bin; values come directly from saved results."""
    width, height = 760, 320
    left, right, top = 175, 58, 38
    lo, hi = -10.0, 15.0
    plot_width = width - left - right
    X = lambda value: left + (value - lo) / (hi - lo) * plot_width
    zero = X(0)
    title = T("Рейсы и средняя вместимость: изменение с 2019 по 2024 год",
              "Flights and average capacity: change from 2019 to 2024",
              "Flüge und mittlere Kapazität: Veränderung von 2019 bis 2024")
    metrics = [
        ("flights", "var(--blue-t)", T("Рейсы", "Flights", "Flüge")),
        ("seats_per_flight", "var(--aqua-t)", T("Кресел на рейс", "Seats per flight", "Sitze je Flug")),
    ]
    g = [f'<title id="evolution-chart-title">{e(title)}</title>']
    descriptions = []
    for value in (-10, -5, 0, 5, 10, 15):
        x = X(value)
        g.append(f'<line x1="{x:.2f}" x2="{x:.2f}" y1="{top - 8}" y2="{height - 38}" '
                 f'stroke="{"var(--dim)" if value == 0 else "var(--line)"}" stroke-width="1"/>')
        g.append(f'<text x="{x:.2f}" y="{height - 15}" text-anchor="middle" class="ax">{n(value, 0, sign=True)}%</text>')
    for index, group in enumerate(evolution["by_distance"]):
        period = next(p for p in group["periods"] if p.get("start") == 2019 and p.get("end") == 2024)
        label = _distance_label(group["group"])
        y = top + index * 61
        g.append(f'<g data-distance-group="{e(group["group"])}" data-pairs="{period["pairs"]}">')
        g.append(f'<text x="12" y="{y + 15}" class="evolution-label">{e(label)}</text>')
        count = T(f'пар: {n(period["pairs"])}', f'{n(period["pairs"])} pairs', f'{n(period["pairs"])} Paare')
        g.append(f'<text x="12" y="{y + 32}" class="evolution-count">{e(count)}</text>')
        for offset, (metric, color, metric_label) in enumerate(metrics):
            fraction = period["aggregate_decomposition"]["factor_change_fraction"][metric]
            value = fraction * 100
            if not lo <= value <= hi:
                raise ValueError("Evolution chart domain must be updated for the new snapshot")
            end = X(value)
            bar_y = y + offset * 20
            change = _percent(fraction, sign=True)
            g.append(f'<rect data-metric="{metric}" data-change-fraction="{fraction:.12g}" '
                     f'x="{min(end, zero):.2f}" y="{bar_y}" width="{abs(end - zero):.2f}" height="12" '
                     f'rx="2" fill="{color}"><title>{e(label + ": " + metric_label + " " + change)}</title></rect>')
            text_x, anchor = (end - 6, "end") if value < 0 else (end + 6, "start")
            g.append(f'<text x="{text_x:.2f}" y="{bar_y + 10}" text-anchor="{anchor}" '
                     f'class="evolution-value" fill="{color}">{change}</text>')
            descriptions.append(label + ": " + metric_label + " " + change)
        g.append("</g>")
    desc = " · ".join(descriptions)
    g.insert(1, f'<desc id="evolution-chart-desc">{e(desc)}</desc>')
    legend = '<div class="evolution-legend">' + "".join(
        f'<span><i style="background:{color}" aria-hidden="true"></i>{e(label)}</span>'
        for _, color, label in metrics) + "</div>"
    return (legend + '<div class="evolution-scroll">'
            + f'<svg id="route-capacity-change-0057" class="chart evolution-chart" viewBox="0 0 {width} {height}" '
            + 'role="img" aria-labelledby="evolution-chart-title evolution-chart-desc">'
            + "".join(g) + "</svg></div>")


def modelling_update(sources):
    """Return a self-contained article chapter; the caller owns page/source lists."""
    benchmark = json.loads((HERE / "out/forecast_benchmark.json").read_text())
    evolution = json.loads((HERE / "out/route_evolution.json").read_text())
    supply = json.loads((HERE / "out/supply_summary.json").read_text())
    collection = json.loads((HERE / "out/collection_summary.json").read_text())
    sources.url(EUROSTAT_META, T("Eurostat: определения пассажирских перевозок и охват",
                               "Eurostat: passenger-traffic definitions and coverage",
                               "Eurostat: Definitionen und Abdeckung des Passagierverkehrs"))
    archives, traffic_archives = [], []
    for cc in ("de", "es", "fr", "it", "nl"):
        url = next(u for u in evolution["source_urls"] if f"/avia_par_{cc}?" in u)
        archives.append(url)
        sources.url(url, T(f"Eurostat: исторические ряды {cc.upper()}, архив DBnomics",
                           f"Eurostat: historical {cc.upper()} series, DBnomics archive",
                           f"Eurostat: historische Reihen {cc.upper()}, DBnomics-Archiv"))
        traffic_url = next(x["url"] for x in collection["eu_routes"]["sources"]
                           if f"/avia_par_{cc}?" in x["url"])
        traffic_archives.append(traffic_url)
        sources.url(traffic_url, T(f"Eurostat: история PAS_CRD, {cc.upper()}, архив DBnomics",
                                   f"Eurostat: PAS_CRD history, {cc.upper()}, DBnomics archive",
                                   f"Eurostat: PAS_CRD-Historie, {cc.upper()}, DBnomics-Archiv"))
    primary = {}
    for item in supply["primary_comparisons"]:
        if item.get("status") == "matched_primary":
            sources.url(item["url"], T(f'Eurostat: {item["pair"]}, {item["measure"]}',
                                       f'Eurostat: {item["pair"]}, {item["measure"]}',
                                       f'Eurostat: {item["pair"]}, {item["measure"]}'))
            primary.setdefault(item["pair"], []).append(item["url"])
    citation = sources.cite(EUROSTAT_META, *archives)
    traffic_citation = sources.cite(EUROSTAT_META, *traffic_archives)
    tested = sorted((x for x in benchmark["experiments"] if x["availability_lag_years"] == 1),
                    key=lambda x: x["horizon_years_from_decision"])
    main = next(p for p in evolution["periods"] if p["start"] == 2019 and p["end"] == 2024)
    count = evolution["main_pairs"]
    body = [CSS, '<section class="modelling-update" id="demand-model-results">',
        f'<h2>{T("Прогноз: первые проверки на длинной истории", "Forecasts: first tests on a long history", "Prognosen: erste Tests mit langen Zeitreihen")}</h2>',
        f'<p>{T("История уже позволяет проверить самое простое предположение: продолжится ли прежний темп маршрута. Наш первый расчёт показывает, что для этой выборки повторение последнего известного годового потока пока надёжнее его механического продления по тренду. Значит, доход, туризм и другие факторы должны доказать добавочную точность, прежде чем из них получится прогноз для выбора самолёта.",
            "The history now lets us test a basic assumption: will a route continue growing at its previous rate? In our first calculation, repeating the last known annual flow outperforms mechanical trend extrapolation on this sample. Income, tourism and other factors therefore need to demonstrate incremental predictive value before they can support aircraft-choice forecasts.",
            "Die Historie erlaubt jetzt den Test einer einfachen Annahme: Wächst eine Strecke mit ihrem bisherigen Tempo weiter? In unserer ersten Berechnung schneidet die Übernahme des zuletzt bekannten Jahresverkehrs in dieser Stichprobe besser ab als die mechanische Trendfortschreibung. Einkommen, Tourismus und weitere Faktoren müssen deshalb einen zusätzlichen Prognosenutzen belegen, bevor sie die Flugzeugwahl stützen können.")}</p>',
        f'<p class="small">{T("Наш расчёт по сохранённому снимку Eurostat: Германия, Испания, Франция, Италия и Нидерланды как страны-отчётчики; месячная история 2005–2024. Прогнозная цель — годовой поток пары аэропортов в обоих направлениях, PAS_CRD, внутри одного номера рейса. Это ещё не весь рынок поездок между городами с пересадками.",
            "Our calculation uses the saved Eurostat snapshot for Germany, Spain, France, Italy and the Netherlands as reporting countries, with monthly history for 2005–2024. The forecast target is annual traffic in both directions for an airport pair, PAS_CRD, within one flight number. It does not yet capture the whole city-to-city travel market including connections.",
            "Unsere Berechnung nutzt den gespeicherten Eurostat-Stand mit Deutschland, Spanien, Frankreich, Italien und den Niederlanden als Meldeländern und Monatsdaten für 2005–2024. Prognoseziel ist der jährliche Verkehr eines Flughafenpaars in beiden Richtungen, PAS_CRD, innerhalb einer Flugnummer. Der gesamte Städtereisemarkt einschließlich Umsteigeverbindungen ist damit noch nicht erfasst.")}{traffic_citation}</p>']

    rows = []
    attrs = []
    for x in tested:
        m = x["metrics"]["all"]
        rows.append([n(x["horizon_years_from_decision"]),
                     f'{n(x["scored_cases"])} / {n(x["eligible_origin_pair_cases"])}',
                     _percent(m["last_year"]["wape"]), _percent(m["damped_log_trend"]["wape"]),
                     _percent(m["log_trend"]["wape"])])
        attrs.append(f'data-horizon="{x["horizon_years_from_decision"]}" data-availability-lag="1"')
    body.append(_table([T("Горизонт, лет", "Horizon, years", "Horizont, Jahre"),
                        T("Оценено / подходило", "Scored / eligible", "Bewertet / geeignet"),
                        T("Последний год", "Last known year", "Letztes bekanntes Jahr"),
                        T("Затухающий тренд", "Damped trend", "Gedämpfter Trend"),
                        T("Обычный тренд", "Undamped trend", "Ungedämpfter Trend")], rows,
                       "demand-temporal-benchmark", attrs))
    pre = tested[0]["metrics"]["pre2020"]
    body.append(f'<p>{T(f"В таблице WAPE: сумма абсолютных ошибок, делённая на сумму фактических пассажиров. Меньше — лучше; это не доля верных прогнозов. Пары выбирались по пяти полным прошлым годам. В год решения использованы данные только до предыдущего года — условный годовой лаг публикации. Даже до пандемии трёхлетняя ошибка составляла {_percent(pre["last_year"]["wape"])} у последнего года против {_percent(pre["damped_log_trend"]["wape"])} у затухающего тренда.",
        f"The table shows WAPE: summed absolute errors divided by total observed passengers. Lower is better; this is not the proportion of correct forecasts. Pairs were selected using five complete past years. A decision year only uses observations through the preceding year, assuming a one-year publication lag. Even before the pandemic, the three-year error was {_percent(pre["last_year"]["wape"])} for the last known year versus {_percent(pre["damped_log_trend"]["wape"])} for the damped trend.",
        f"Die Tabelle zeigt WAPE: die Summe absoluter Fehler geteilt durch die Summe beobachteter Passagiere. Niedriger ist besser; dies ist nicht der Anteil richtiger Prognosen. Paare wurden anhand von fünf vollständigen Vorjahren ausgewählt. Im Entscheidungsjahr werden nur Beobachtungen bis zum Vorjahr genutzt, bei angenommener einjähriger Veröffentlichungsverzögerung. Schon vor der Pandemie betrug der Dreijahresfehler {_percent(pre["last_year"]["wape"])} für das letzte bekannte Jahr gegenüber {_percent(pre["damped_log_trend"]["wape"])} für den gedämpften Trend.")}</p>')
    body.append(f'<p class="method-note">{T("Отсутствующие и неполные цели не стали нулями: они не оценены и показаны разницей чисел во второй колонке. Использован последний пересмотренный снимок, поэтому историческая дата доступности каждой публикации ещё не восстановлена. Десятилетний тест с этим лагом попадает только в 2020–2024 годы: его ошибку нельзя считать типичной для спокойного десятилетия. Новые маршруты и исчезновение старых требуют отдельного теста.",
        "Missing and incomplete targets were not turned into zeros: they remain unscored, shown by the gap between the two counts. We use the latest revised snapshot, so the historical availability date of each release has not been reconstructed. With this lag, the ten-year test only targets 2020–2024: its error is not representative of an ordinary decade. New routes and the disappearance of existing ones need a separate test.",
        "Fehlende und unvollständige Ziele wurden nicht zu Nullen: Sie bleiben unbewertet, erkennbar an der Differenz der beiden Fallzahlen. Verwendet wird der zuletzt revidierte Stand; die historische Verfügbarkeit jeder Veröffentlichung ist noch nicht rekonstruiert. Der Zehnjahrestest mit diesem Lag hat ausschließlich Ziele in 2020–2024: Sein Fehler steht nicht für ein gewöhnliches Jahrzehnt. Neue Strecken und das Verschwinden bestehender Strecken benötigen einen eigenen Test.")}</p>')

    body.append(f'<details><summary>{T("Как проверяли: ошибки, интервалы и пропуски", "Evaluation details: errors, intervals and missing targets", "Prüfdetails: Fehler, Intervalle und fehlende Ziele")}</summary>')
    detail_rows = []
    for x in tested:
        m = x["metrics"]["all"]["last_year"]
        interval = m["empirical_80pct_interval"]
        detail_rows.append([n(x["horizon_years_from_decision"]), n(m["mae_passengers"]),
                            _percent(m["signed_bias"], sign=True), n(m["median_error_factor_positive"], 2) + "×",
                            _percent(interval["coverage"]), n(interval["n"])])
    body.append(_table([T("Лет", "Years", "Jahre"), T("MAE, пассажиров/год", "MAE, passengers/year", "MAE, Passagiere/Jahr"),
                        T("Смещение", "Bias", "Verzerrung"), T("Медианная ошибка в разах", "Median error factor", "Medianer Fehlerfaktor"),
                        T("Покрытие 80%-интервала", "80% interval coverage", "Abdeckung des 80%-Intervalls"),
                        T("Интервалов проверено", "Intervals evaluated", "Geprüfte Intervalle")], detail_rows,
                       "demand-benchmark-uncertainty"))
    body.append(f'<p>{T("Здесь дополнительные показатели ориентира «последний год». MAE — средняя абсолютная ошибка отдельной пары; смещение — суммарное превышение или недобор относительно факта. Небольшое суммарное смещение может скрывать взаимное погашение крупных ошибок. Интервал строился по прошлым ошибкам того же метода и горизонта, только когда исходы уже могли быть известны. На десять лет таких завершённых ранних эпизодов ещё недостаточно. Пары и даты начала повторяются, поэтому формальной гарантии покрытия у этих эмпирических интервалов нет.",
        "These are additional metrics for the last-known-year baseline. MAE is the average absolute error for a pair; bias is total over- or underprediction relative to observations. A small aggregate bias can conceal large errors cancelling one another. Intervals use past errors of the same method and horizon, only after those outcomes could already be known. There are not enough completed earlier episodes for ten-year calibration. Repeated pairs and overlapping origins mean these empirical intervals have no formal coverage guarantee.",
        "Dies sind zusätzliche Kennzahlen des Vergleichs mit dem letzten bekannten Jahr. MAE ist der mittlere absolute Fehler je Paar; die Verzerrung misst die gesamte Über- oder Unterschätzung relativ zum Istwert. Eine geringe Gesamtverzerrung kann große, sich aufhebende Fehler verdecken. Intervalle beruhen auf früheren Fehlern derselben Methode und desselben Horizonts, deren Ergebnisse bereits bekannt sein konnten. Für zehn Jahre fehlen genügend abgeschlossene frühere Fälle. Wiederholte Paare und überlappende Startjahre erlauben keine formale Abdeckungsgarantie.")}</p>')
    body.append(f'<p>{T("Год считается полным при двенадцати опубликованных месяцах без флагов источника и расхождения отчётчиков больше 10%. Пропуски не заполнялись, а целевые нули не исключались правилом положительного потока; в прошедшей строгий отбор оценённой когорте полных годовых нулей не оказалось. Тренд оценён по логарифму «один плюс поток» пяти прошлых лет; затухание 0,8 задано заранее. Производственная P/T/F, доход, туризм и диаспоры в этом временном эксперименте ещё не сравнивались.",
        "A complete year requires twelve published months without source flags or reporter disagreement above 10%. Missing values were not filled; target zeros were not rejected by a positive-flow rule, although no complete annual zero survived into the strictly scored cohort. Trends use the logarithm of one plus traffic over five past years; damping of 0.8 was specified in advance. Production P/T/F, income, tourism and diaspora factors have not yet been compared in this temporal experiment.",
        "Ein vollständiges Jahr verlangt zwölf veröffentlichte Monate ohne Quellenkennzeichen oder Meldeabweichungen über 10%. Fehlwerte wurden nicht ergänzt; Zielnullen wurden nicht durch eine Positivitätsregel ausgeschlossen, doch in der streng bewerteten Kohorte blieb kein vollständiges Nulljahr. Trends nutzen den Logarithmus von eins plus Verkehr über fünf Vorjahre; die Dämpfung 0,8 war vorgegeben. Produktions-P/T/F, Einkommen, Tourismus und Diaspora-Faktoren wurden in diesem zeitlichen Experiment noch nicht verglichen.")}</p></details>')

    body.append(f'<h2>{T("Чем обеспечивался рост: рейсы, кресла и занятость", "What supported growth: flights, seats and occupancy", "Wodurch Verkehr wuchs: Flüge, Sitze und Auslastung")}</h2>')
    body.append(f'<p>{T(f"Для выбора самолёта важно разделить три изменения. Мы пересчитали предложение на одной группе из {n(count)} пар: у каждой есть полные чистые 2015, 2019 и 2024 годы, а состав аэропортов-отчётчиков одинаков во всех трёх годах. Это отдельный расчёт по пассажирам на борту участка PAS_BRD, креслам ST_PAS и рейсам CAF_PAS; две стороны не складываются, а усредняются.",
        f"Aircraft choice requires separating three changes. We recalculated supply for one group of {n(count)} pairs, each with complete clean years in 2015, 2019 and 2024 and the same reporting airports throughout all three years. This is a separate calculation using flight-stage passengers PAS_BRD, seats ST_PAS and flights CAF_PAS; counterpart reports are averaged, not added.",
        f"Für die Flugzeugwahl müssen drei Veränderungen getrennt werden. Wir berechneten das Angebot für eine feste Gruppe von {n(count)} Paaren mit vollständigen sauberen Jahren 2015, 2019 und 2024 sowie denselben meldenden Flughäfen in allen drei Jahren. Diese separate Rechnung nutzt Flugabschnittspassagiere PAS_BRD, Sitze ST_PAS und Flüge CAF_PAS; Gegenmeldungen werden gemittelt, nicht addiert.")}{citation}</p>')
    body.append('<p class="formula">P = F × S̄ × LF</p>')
    body.append(f'<p>{T("P — пассажиры за год, F — рейсы за год, S̄ — среднее число кресел на рейс, LF — занятая доля предложенных кресел. Годовые отношения считаются из сумм. Это арифметическое разложение фактических перевозок, а не модель причинного влияния частоты на спрос.",
        "P is annual passengers, F annual flights, S̄ mean seats per flight and LF the occupied share of offered seats. Annual ratios use annual sums. This is an arithmetic decomposition of realized traffic, not a causal model of frequency's effect on demand.",
        "P sind jährliche Passagiere, F jährliche Flüge, S̄ mittlere Sitze je Flug und LF der belegte Anteil angebotener Sitze. Jahresquoten beruhen auf Jahressummen. Dies zerlegt den tatsächlichen Verkehr arithmetisch und modelliert keinen kausalen Frequenzeffekt auf die Nachfrage.")}{sources.cite(EUROSTAT_META)}</p>')
    annual = {**evolution["periods"][0]["aggregates"], **main["aggregates"]}
    annual_rows = []
    for key, divisor, decimals, label in [
        ("passengers", 1e6, 1, T("P · млн пассажиров", "P · million passengers", "P · Mio. Passagiere")),
        ("flights", 1e6, 3, T("F · млн рейсов", "F · million flights", "F · Mio. Flüge")),
        ("seats_per_flight", 1, 1, T("S̄ · кресел на рейс", "S̄ · seats per flight", "S̄ · Sitze je Flug")),
        ("load_factor", 0.01, 1, T("LF · занятость, %", "LF · occupancy, %", "LF · Auslastung, %")),
    ]:
        annual_rows.append([e(label)] + [n(annual[str(y)][key] / divisor, decimals) for y in (2015, 2019, 2024)])
    body.append(_table([T("Наш расчёт: одна когорта", "Our calculation: one cohort", "Eigene Berechnung: eine Kohorte"), "2015", "2019", "2024"],
                       annual_rows, "demand-same-cohort-years"))
    within = main["within_pair"]
    body.append(f'<p>{T(f"Средняя вместимость выросла с {n(annual["2019"]["seats_per_flight"], 1)} до {n(annual["2024"]["seats_per_flight"], 1)} кресла. Однако внутри отдельной пары медианное изменение — лишь {_percent(within["median_seats_per_flight_change"], sign=True)}; увеличение было у {n(within["seats_per_flight_increased"])} из {n(count)} пар. Средняя цифра всей группы дополнительно меняется вместе с весом крупных и малых маршрутов.",
        f"Average capacity rose from {n(annual["2019"]["seats_per_flight"], 1)} to {n(annual["2024"]["seats_per_flight"], 1)} seats. Within individual pairs, however, the median change was only {_percent(within["median_seats_per_flight_change"], sign=True)}; {n(within["seats_per_flight_increased"])} of {n(count)} pairs increased. The whole-group average also changes as larger and smaller routes gain or lose weight.",
        f"Die mittlere Kapazität stieg von {n(annual["2019"]["seats_per_flight"], 1)} auf {n(annual["2024"]["seats_per_flight"], 1)} Sitze. Innerhalb einzelner Paare betrug die mediane Änderung jedoch nur {_percent(within["median_seats_per_flight_change"], sign=True)}; bei {n(within["seats_per_flight_increased"])} von {n(count)} Paaren gab es einen Anstieg. Der Gruppenmittelwert verändert sich zusätzlich mit den Gewichten größerer und kleinerer Strecken.")}</p>')

    body.append(f'<h3>{T("Разная дальность — разные изменения", "Different distances, different changes", "Unterschiedliche Distanzen, unterschiedliche Veränderungen")}</h3>')
    body.append('<figure class="evolution-figure">' + _capacity_chart(evolution))
    body.append(f'<figcaption>{T(f"Наш расчёт: 2019 → 2024, одна сопоставимая когорта; координаты есть для {n(evolution["main_pairs_with_coordinates"])} из {n(count)} пар. Расстояние по большой окружности служит группировкой и не проверяет допустимую дальность ВС с нагрузкой.",
        f"Our calculation: 2019 → 2024, one matched cohort; coordinates are available for {n(evolution["main_pairs_with_coordinates"])} of {n(count)} pairs. Great-circle distance defines the groups; it does not establish aircraft payload-range feasibility.",
        f"Eigene Berechnung: 2019 → 2024, eine vergleichbare Kohorte; Koordinaten liegen für {n(evolution["main_pairs_with_coordinates"])} von {n(count)} Paaren vor. Großkreisdistanz dient der Gruppierung und prüft keine Nutzlast-Reichweiten-Eignung.")}{sources.cite(*archives)}</figcaption></figure>')
    middle = next(g["periods"][1] for g in evolution["by_distance"] if g["group"] == "1500to4000km")
    body.append(f'<p>{T(f"На коротких направлениях вместимость увеличивалась при сокращении числа рейсов. В группе {n(1500)}–{n(4000)} км пассажирский поток вырос на {_percent(middle["aggregate_decomposition"]["passenger_change_fraction"])} главным образом вместе с числом рейсов; средняя вместимость прибавила лишь {_percent(middle["aggregate_decomposition"]["factor_change_fraction"]["seats_per_flight"])}. В более дальних группах вместимость снижалась. История поддерживает несколько способов развития сети, а не один общий переход к более крупному самолёту.",
        f"On short routes, capacity increased while flight counts fell. In the {n(1500)}–{n(4000)} km group, passenger traffic rose {_percent(middle["aggregate_decomposition"]["passenger_change_fraction"])} mainly alongside more flights; average capacity added only {_percent(middle["aggregate_decomposition"]["factor_change_fraction"]["seats_per_flight"])}. In the longer-distance groups it declined. The history supports several network-development mechanisms rather than one universal move to larger aircraft.",
        f"Auf kurzen Strecken nahm die Kapazität bei sinkender Flugzahl zu. In der Gruppe {n(1500)}–{n(4000)} km wuchs der Passagierverkehr um {_percent(middle["aggregate_decomposition"]["passenger_change_fraction"])} vor allem zusammen mit mehr Flügen; die mittlere Kapazität legte nur um {_percent(middle["aggregate_decomposition"]["factor_change_fraction"]["seats_per_flight"])} zu. In den längeren Distanzgruppen ging sie zurück. Die Historie zeigt mehrere Mechanismen der Netzentwicklung statt eines allgemeinen Übergangs zu größeren Flugzeugen.")}</p>')

    examples = {
        "EDDF-LEBL": T("Франкфурт — Барселона", "Frankfurt–Barcelona", "Frankfurt–Barcelona"),
        "EDDL-LEPA": T("Дюссельдорф — Пальма", "Düsseldorf–Palma", "Düsseldorf–Palma"),
        "EDDF-LIMC": T("Франкфурт — Милан-Мальпенса", "Frankfurt–Milan Malpensa", "Frankfurt–Mailand-Malpensa"),
        "EDDF-VIDP": T("Франкфурт — Дели", "Frankfurt–Delhi", "Frankfurt–Delhi"),
        "EHAM-LFRN": T("Амстердам — Ренн", "Amsterdam–Rennes", "Amsterdam–Rennes"),
    }
    body.append(f'<details><summary>{T("Пять маршрутов: как различаются изменения", "Five routes: how their changes differ", "Fünf Strecken: unterschiedliche Entwicklungen")}</summary>')
    example_rows, example_attrs = [], []
    for item in evolution["examples"]:
        years = item.get("years", {})
        if "2019" not in years or "2024" not in years:
            continue
        d = item["decomposition"]["2019_2024"]
        cohort = (T("Основная когорта", "Main cohort", "Hauptkohorte") if item["in_main_balanced_cohort"] else
                  T("Отдельно: 2019/2024", "Separate: 2019/2024", "Separat: 2019/2024"))
        example_rows.append([e(examples[item["pair"]]) + sources.cite(*primary.get(item["pair"], [])),
                             n(years["2019"]["seats_per_flight"], 1) + " → " + n(years["2024"]["seats_per_flight"], 1),
                             _percent(d["factor_change_fraction"]["flights"], sign=True),
                             _percent(d["passenger_change_fraction"], sign=True), e(cohort)])
        example_attrs.append(f'data-pair="{e(item["pair"])}" data-main-cohort="{str(item["in_main_balanced_cohort"]).lower()}"')
    body.append(_table([T("Пара", "Pair", "Paar"), T("Кресел/рейс, 2019 → 2024", "Seats/flight, 2019 → 2024", "Sitze/Flug, 2019 → 2024"),
                        T("Рейсы", "Flights", "Flüge"), T("Пассажиры", "Passengers", "Passagiere"),
                        T("Выборка", "Sample", "Stichprobe")], example_rows, "demand-evolution-examples", example_attrs))
    body.append(f'<p>{T("Наш расчёт на опубликованных годовых суммах. Милан и Ренн не входят в основную когорту трёх лет: у них нет полного чистого 2015 года. Среднее число кресел объединяет типы, компоновки, перевозчиков и сезоны; восстановить из него конкретный парк нельзя. Высокая занятость также не доказывает неудовлетворённый спрос.",
        "Our calculation uses published annual sums. Milan and Rennes are outside the main three-year cohort because they lack a complete clean 2015. Mean seats combine types, configurations, carriers and seasons; they cannot reconstruct a particular fleet. High occupancy likewise does not establish unmet demand.",
        "Eigene Berechnung aus veröffentlichten Jahressummen. Mailand und Rennes gehören wegen eines fehlenden vollständigen sauberen Jahres 2015 nicht zur dreijährigen Hauptkohorte. Mittlere Sitzzahlen vermischen Typen, Kabinen, Airlines und Saisons und rekonstruieren keine konkrete Flotte. Auch hohe Auslastung belegt keine ungedeckte Nachfrage.")}</p></details>')
    relaxed = main["same_cohort_relaxed_reporter_disagreement"]
    sensitivity = main["pairwise_endpoint_cohort_sensitivity"]
    body.append(f'<p class="method-note">{T(f"Сопоставимая группа отобрана ретроспективно: она не описывает открывшиеся, закрывшиеся и неполностью опубликованные направления. Сигнал умеренного укрупнения сохраняется при изменении фильтра: без исключения расхождений отчётчиков — {n(relaxed["pairs"])} пар и {_percent(relaxed["aggregate_decomposition"]["factor_change_fraction"]["seats_per_flight"], sign=True)} кресел на рейс; при требовании только полных концов 2019/2024 — {n(sensitivity["pairs"])} пар и {_percent(sensitivity["aggregate_decomposition"]["factor_change_fraction"]["seats_per_flight"], sign=True)}. Это проверка чувствительности исторического результата, а не прогноз всего рынка.",
        f"The matched group is selected retrospectively: it does not describe openings, closures or incompletely published routes. Moderate upgauging remains under different filters: retaining reporter disagreements gives {n(relaxed["pairs"])} pairs and {_percent(relaxed["aggregate_decomposition"]["factor_change_fraction"]["seats_per_flight"], sign=True)} seats per flight; requiring only complete 2019/2024 endpoints gives {n(sensitivity["pairs"])} pairs and {_percent(sensitivity["aggregate_decomposition"]["factor_change_fraction"]["seats_per_flight"], sign=True)}. This tests a historical result's sensitivity, not a forecast of the whole market.",
        f"Die vergleichbare Gruppe ist rückblickend ausgewählt: Sie beschreibt keine Neueröffnungen, Schließungen oder unvollständig veröffentlichten Strecken. Der moderate Kapazitätsanstieg bleibt bei anderen Filtern bestehen: Mit abweichenden Gegenmeldungen ergeben sich {n(relaxed["pairs"])} Paare und {_percent(relaxed["aggregate_decomposition"]["factor_change_fraction"]["seats_per_flight"], sign=True)} Sitze je Flug; nur mit vollständigen Endjahren 2019/2024 sind es {n(sensitivity["pairs"])} Paare und {_percent(sensitivity["aggregate_decomposition"]["factor_change_fraction"]["seats_per_flight"], sign=True)}. Dies prüft die Sensitivität eines historischen Ergebnisses und prognostiziert nicht den Gesamtmarkt.")}</p>')

    body.append(f'<h3>{T("Следующий расчёт: от проверенной базы к маршруту и самолёту", "Next calculation: from a tested baseline to routes and aircraft", "Nächste Berechnung: von der geprüften Basis zu Strecke und Flugzeug")}</h3>')
    steps = [
        T("Воспроизвести действующую P/T/F на этих же временных разбиениях, с историческими зонами охвата и только доступными в прошлом входами. Тогда появится честное сравнение с сегодняшним калькулятором.",
          "Reproduce production P/T/F on these same time splits, using historical catchments and inputs available in the past. This will enable a fair comparison with today's calculator.",
          "Die produktive P/T/F auf denselben Zeitaufteilungen mit historischen Einzugsgebieten und damals verfügbaren Eingaben reproduzieren. Erst dann ist ein fairer Vergleich mit dem heutigen Rechner möglich."),
        T("На одной когорте добавлять и убирать доход, туризм, деловую активность, диаспоры и визы. Сохранять фактор, только если он улучшает отложенные годы и проверку интервалов.",
          "Add and remove income, tourism, business activity, diaspora and visa factors on the same cohort. Retain a factor only when it improves held-out years and interval evaluation.",
          "Einkommen, Tourismus, Geschäftstätigkeit, Diaspora und Visa auf derselben Kohorte einzeln ergänzen und weglassen. Ein Faktor bleibt nur, wenn er zurückgehaltene Jahre und die Intervallprüfung verbessert."),
        T("Отдельно проверить новые пары, смену аэропорта и исчезновение маршрутов из публикации. Продление существующего ряда не оценивает рынок новой прямой линии.",
          "Test new pairs, airport changes and routes disappearing from publication separately. Extrapolating an existing series does not estimate the market for a new nonstop service.",
          "Neue Paare, Flughafenwechsel und aus Veröffentlichungen verschwindende Strecken separat prüfen. Die Fortschreibung einer bestehenden Reihe schätzt nicht den Markt einer neuen Direktverbindung."),
        T("Достроить наблюдения 2025–2026 либо отдельно оценить текущий год от якоря 2024. Эту дополнительную неопределённость показывать до выдачи прогноза на три года.",
          "Extend observations through 2025–2026 or separately estimate the current year from the 2024 anchor. Show this extra uncertainty before issuing a three-year forecast.",
          "Beobachtungen für 2025–2026 ergänzen oder das laufende Jahr separat vom Anker 2024 aus schätzen. Diese zusätzliche Unsicherheit vor einer Dreijahresprognose ausweisen."),
        T("Для 2029, 2031 и 2036 связать сценарии потока с месячными пиками, долей перевозчика, ценой билета, частотой и ограничениями аэропортов. После этого сравнить допустимые ВС и экономику рейса; преимущество бизнес-модели должно выдержать несколько сценариев.",
          "For 2029, 2031 and 2036, connect traffic scenarios to monthly peaks, airline share, fares, frequency and airport constraints. Then compare feasible aircraft and flight economics; a business-model advantage must survive several scenarios.",
          "Für 2029, 2031 und 2036 Verkehrsszenarien mit Monatsspitzen, Airline-Anteil, Ticketpreisen, Frequenz und Flughafenbeschränkungen verbinden. Danach geeignete Flugzeuge und Flugwirtschaft vergleichen; ein Geschäftsmodellvorteil muss mehrere Szenarien überstehen."),
    ]
    body.append("<ol>" + "".join(f"<li>{x}</li>" for x in steps) + "</ol>")
    body.append("</section>")
    return "".join(body)
