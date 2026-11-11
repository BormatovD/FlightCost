#!/usr/bin/env python3
"""Build the first demand-research draft from the reproducible benchmark.

This is a research experiment, not a replacement for the production model.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from _report import (ARTICLE_CSS, Sources, T, article_title, calc_badge, e,
                     mark, n, page, whisker, write_all)

SLUG = HERE.name
DATA = json.loads((HERE / "out/summary.json").read_text())
EUROSTAT = "https://ec.europa.eu/eurostat/cache/metadata/en/avia_pa_esms.htm"
WB = "https://data.worldbank.org/indicator/NY.GDP.PCAP.PP.KD"
TOUR = "https://ec.europa.eu/eurostat/cache/metadata/en/tour_occ_esms.htm"
DUAN = "https://doi.org/10.1080/01621459.1983.10478017"
REPO = "https://github.com/BormatovD/FlightCost/blob/e5429af890018ec54ffce82731ae2ea56cd0ea3e/"


def table(heads, rows):
    return ('<div class="tw"><table><thead><tr>' + ''.join(f'<th>{e(x)}</th>' for x in heads)
            + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{x}</td>' for x in row)
                                                + '</tr>' for row in rows) + '</tbody></table></div>')


def model_name(key):
    return {
        "last_year": T("Повторить прошлый год", "Repeat last year", "Vorjahr übernehmen"),
        "distance": T("Расстояние + граница", "Distance + border", "Distanz + Grenze"),
        "gravity": T("Базовая гравитация", "Baseline gravity", "Basis-Gravitation"),
        "gravity_smearing": T("Гравитация + поправка", "Gravity + correction", "Gravitation + Korrektur"),
        "gravity_income": T("Гравитация + ВВП", "Gravity + GDP", "Gravitation + BIP"),
        "gravity_tourism": T("Гравитация + ночёвки", "Gravity + nights", "Gravitation + Nächte"),
    }[key]


def metric_table(experiment):
    rows = [[model_name(k), n(v["median_factor"], 3), n(v["wape_pct"], 2),
             n(v["mae_pax_year"]), n(v["bias_pct"], 2, sign=True)]
            for k, v in experiment["models"].items()]
    return table([T("Способ", "Method", "Methode"), T("Медианный множитель", "Median factor", "Medianer Faktor"),
                  "WAPE, %", T("MAE, пасс./год", "MAE, passengers/year", "MAE, Passagiere/Jahr"),
                  T("Смещение, %", "Bias, %", "Verzerrung, %")], rows)


def build():
    s = Sources(HERE)
    d = DATA
    fc, ho = d["experiments"]["forecast_2023_2024"], d["experiments"]["heldout_pairs_2024"]
    for url, title in [(EUROSTAT, "Eurostat: air passenger transport metadata"),
                       (WB, "World Bank: GDP per capita, PPP (constant 2021 international dollars)"),
                       (TOUR, "Eurostat: occupancy of tourist accommodation establishments"),
                       (d["macro"]["tourism"]["geography_source"], "GISCO: NUTS 2024 regional polygons"),
                       (REPO + "research/routes-2026-11/out/pairs_eu.json", "FlightCost: dated Eurostat route aggregates"),
                       (REPO + "flightcostapp/traffic_model.py", "FlightCost: production P/T/F demand model"),
                       (DUAN, "Naihua Duan (1983): Smearing Estimate — retransformation method")]:
        s.url(url, title)
    body = [ARTICLE_CSS,
            f'<h1>{T("Спрос между городами: что дают доход и туризм в первом тесте", "Demand between cities: a first test of income and tourism", "Nachfrage zwischen Städten: ein erster Test von Einkommen und Tourismus")}</h1>',
            f'<p class="meta">{T("Черновик исследования · 11 ноября 2026 · первый этап; перед публикацией требуется моделирование владельцем", "Research draft · 11 November 2026 · first stage; owner modelling required before publication", "Forschungsentwurf · 11. November 2026 · erste Stufe; Modellprüfung vor Veröffentlichung erforderlich")}</p>',
            calc_badge(SLUG)]
    cards = [
        (n(fc["n"]), T("известных пар: прогноз 2024 года по 2023-му", "known pairs: predict 2024 from 2023", "bekannte Paare: Prognose 2024 aus 2023")),
        (n(ho["n"]), T("пар, исключённых из обучения, в отдельном тесте", "pairs held out of training in a separate test", "im separaten Test vom Training ausgeschlossene Paare")),
        (n(ho["models"]["gravity"]["median_factor"], 2) + "×", T("медианная кратность ошибки базовой гравитации на исключённых парах", "median error factor of baseline gravity on held-out pairs", "medianer Fehlerfaktor der Basis-Gravitation bei ausgeschlossenen Paaren")),
        (T("2 фактора", "2 factors", "2 Faktoren"), T("ВВП и ночёвки проверены отдельно; явного выигрыша пока нет", "GDP and nights tested separately; no clear gain yet", "BIP und Übernachtungen separat geprüft; bisher kein klarer Gewinn")),
    ]
    body.append('<div class="verdict">' + ''.join(f'<div><b>{x}</b><span>{y}</span></div>' for x, y in cards) + '</div>')
    body.append(f'<p class="lede">{T(
        "Доход, туризм и деловые связи выглядят естественными объяснениями пассажирского потока. Но полезность фактора для калькулятора нужно измерить: улучшает ли он прогноз на данных, которых модель не видела? В первом воспроизводимом тесте национальный ВВП и региональные ночёвки почти не изменили ошибку. Для известного направления простое повторение прошлогоднего потока оказалось заметно точнее нашей упрощённой гравитации. Это определяет следующий шаг исследования, а не отменяет возможную роль этих факторов.",
        "Income, tourism and business links are plausible explanations of passenger traffic. Their value to a calculator still needs a test: do they improve predictions on data the model has not seen? In this first reproducible experiment, national GDP and regional accommodation nights barely changed the error. For an established route, repeating last year's flow was much more accurate than our simplified gravity model. This guides the next research step; it does not rule out these factors in other specifications.",
        "Einkommen, Tourismus und Geschäftsbeziehungen können Passagierströme erklären. Für einen Rechner zählt aber ein Test: Verbessert ein Faktor die Vorhersage unbekannter Daten? Im ersten reproduzierbaren Experiment änderten nationales BIP und regionale Übernachtungen den Fehler kaum. Bei bestehenden Verbindungen war die Übernahme des Vorjahres deutlich genauer als unser vereinfachtes Gravitationsmodell. Das bestimmt den nächsten Forschungsschritt und schließt eine Wirkung anderer Spezifikationen nicht aus.")}</p>')

    body.append(f'<h2>{T("Что именно мы предсказываем", "What is being predicted", "Was wird vorhergesagt?")}</h2>')
    body.append(f'<p>{T(
        "На этом этапе единица наблюдения — опубликованный годовой поток пары аэропортов в обе стороны. Eurostat PAS_CRD описывает on-flight origin/destination: отправление и прибытие в пределах одного номера рейса. Это не строго показатель отдельного лётного участка PAS_BRD и не вся поездка человека через пересадки. Поэтому результат ещё нельзя назвать спросом жителей двух городов на новый прямой маршрут.",
        "The observation here is the published annual flow of an airport pair in both directions. Eurostat PAS_CRD measures on-flight origin/destination within one flight number. It is neither strictly the flight-stage measure PAS_BRD nor the traveller's full connecting journey. The result therefore does not yet measure residents' demand for a new nonstop city connection.",
        "Beobachtet wird der veröffentlichte jährliche Verkehr eines Flughafenpaars in beiden Richtungen. Eurostat PAS_CRD beschreibt On-flight Origin/Destination innerhalb einer Flugnummer. Dies ist weder strikt der Flugabschnittsindikator PAS_BRD noch die gesamte Reise mit Umstiegen. Daraus folgt noch keine Nachfrage der Stadtbevölkerung nach einer neuen Direktverbindung.")}{s.cite(EUROSTAT)}</p>')
    body.append(f'<p>{T(
        f"В исходном снимке {n(d['coverage']['pairs_in_source'])} пар; последний месяц — декабрь 2024 года. Для годового теста оставлены пары с 12 положительными месячными значениями, координатами и расстоянием не менее 100 км. Пары с сезонными перерывами или неполным годом положительных наблюдений не входят в проверку. Отсутствующая пара не превращается в нулевой спрос.",
        f"The input snapshot contains {n(d['coverage']['pairs_in_source'])} pairs and ends in December 2024. The annual test keeps pairs with 12 positive monthly values, coordinates and at least 100 km distance. Pairs with seasonal gaps or an incomplete year of positive observations are excluded. A missing pair is not treated as zero demand.",
        f"Der Datensnapshot enthält {n(d['coverage']['pairs_in_source'])} Paare und endet im Dezember 2024. Der Jahrestest berücksichtigt nur Paare mit zwölf positiven Monatswerten, Koordinaten und mindestens 100 km Distanz. Paare mit saisonalen Unterbrechungen oder unvollständigem Jahr positiver Beobachtungen sind ausgeschlossen. Fehlende Paare werden nicht als Nullnachfrage behandelt.")}{s.cite(REPO + 'research/routes-2026-11/out/pairs_eu.json')}</p>')
    body.append(f'<h2>{T("Модель и входы: один простой проверяемый шаг", "Model and inputs: one testable step", "Modell und Eingaben: ein überprüfbarer Schritt")}</h2>')
    body.append('<p class="formula">ln Q = β₀ + βₘ ln(M<sub>A</sub>M<sub>B</sub>) + β₁ x + β₂ x² + βₛ I<sub>same country</sub><br>'
                '+ β<sub>z</sub> ln(Z<sub>A</sub>Z<sub>B</sub>)<br>'
                'x = ln(distance<sub>km</sub> / 1000)</p>')
    body.append(f'<p class="small">{T("Член с Z есть только в расширенной модели; при его добавлении все коэффициенты оцениваются заново.", "The Z term appears only in the augmented model; adding it refits all coefficients.", "Der Z-Term gehört nur zum erweiterten Modell; dabei werden alle Koeffizienten neu geschätzt.")}</p>')
    body.append(table([T("Вход", "Input", "Eingabe"), T("Что означает", "Meaning", "Bedeutung")], [
        ["Q", T("годовой поток пары в обе стороны, пассажиры", "annual pair flow in both directions, passengers", "jährlicher Verkehr des Paars in beiden Richtungen, Passagiere")],
        ["M", T("сумма доступных потоков других пар аэропорта только в обучающей части", "sum of available flows on other airport pairs in training only", "Summe verfügbarer Ströme anderer Flughafenpaare ausschließlich im Training")],
        ["distance", T("расстояние по координатам аэропортов", "distance from airport coordinates", "Distanz aus Flughafenkoordinaten")],
        ["I", T("1 для одной страны, иначе 0", "1 within one country, otherwise 0", "1 innerhalb eines Landes, sonst 0")],
        ["Z", T("добавляется отдельно: ВВП на человека или региональные ночёвки за предыдущий год", "added separately: GDP per person or regional nights in the previous year", "separate Ergänzung: BIP je Einwohner oder regionale Übernachtungen des Vorjahres")],
    ]))
    body.append(f'<p>{T(
        "Коэффициенты оцениваются по логарифму потока. Масса узла — сумма нашей выборки, а не полный официальный пассажиропоток аэропорта. У обучающей строки её собственный поток вычитается из обеих масс; при проверке исключаются все пары тестовой группы. Так модель не получает ответ через агрегированный признак.",
        "Coefficients are fitted to log traffic. Node mass is a sum within our sample, not certified total airport throughput. Each training row's own traffic is subtracted from both node masses; evaluation removes every pair in its test fold. This prevents the target from entering through an aggregate feature.",
        "Die Koeffizienten werden am logarithmierten Verkehr geschätzt. Die Knotenmasse ist eine Stichprobensumme, kein amtlicher Gesamtverkehr des Flughafens. Der eigene Verkehr jeder Trainingszeile wird von beiden Massen abgezogen; bei der Prüfung werden sämtliche Paare der Testgruppe ausgeschlossen. So gelangt die Zielgröße nicht über ein Aggregat in das Modell.")}</p>')
    body.append(f'<p class="small">{T(
        "Это упрощённый исследовательский benchmark. Рабочая модель калькулятора уже использует население зон притяжения, потоки узлов, сглаженные эффекты аэропортов и региональные поправки P/T/F. Здесь нет зон населения и эффектов аэропортов; полученные ошибки нельзя переносить на рабочую модель как её оценку качества.",
        "This is a simplified research benchmark. The production P/T/F model already uses population catchments, node traffic, shrunk airport effects and regional terms. Catchments and airport effects are absent here; these errors do not evaluate the production model.",
        "Dies ist ein vereinfachter Forschungsbenchmark. Das produktive P/T/F-Modell nutzt bereits Bevölkerungseinzugsgebiete, Knotenverkehr, geglättete Flughafeneffekte und regionale Terme. Einzugsgebiete und Flughafeneffekte fehlen hier; die Fehler bewerten daher nicht das produktive Modell.")}{s.cite(REPO + 'flightcostapp/traffic_model.py')}</p>')

    body.append(f'<h2>{T("Две задачи — две проверки", "Two questions, two tests", "Zwei Fragen, zwei Tests")}</h2>')
    body.append(table([T("Задача", "Question", "Aufgabe"), T("Что доступно модели", "Information available", "Verfügbare Information"), T("Проверка", "Evaluation", "Prüfung")], [
        [T("Известная пара: следующий год", "Known pair: next year", "Bekanntes Paar: Folgejahr"), T("потоки и массы 2023 года", "2023 traffic and masses", "Verkehr und Massen von 2023"), f'{n(fc["n"])} ' + T("пар в 2024 году", "pairs in 2024", "Paare im Jahr 2024")],
        [T("Пара исключена из обучения", "Pair held out of training", "Paar vom Training ausgeschlossen"), T("другие пары тех же аэропортов в 2024 году", "other pairs of the same airports in 2024", "andere Paare derselben Flughäfen im Jahr 2024"), f'{n(ho["n"])} ' + T("пар, 5 фиксированных групп", "pairs, 5 fixed folds", "Paare, 5 feste Gruppen")],
    ]))
    body.append(f'<p>{T(
        "Для известной пары есть сильный контроль: предсказать ровно прошлогодний поток. Для пары без истории его нет. Вторая проверка скрывает целую неориентированную пару, включая обе стороны, и заново считает массы внутри обучения. Она проверяет перенос между наблюдаемыми парами уже работающих аэропортов; открытие нового аэропорта или обнаружение скрытого спроса ею не проверены.",
        "A known pair has a strong reference: predict exactly last year's flow. A pair without history lacks that reference. The second test hides an entire unordered pair, including both directions, and recomputes training masses. It tests transfer across observed pairs of established airports, not a new airport or latent demand.",
        "Bei bekannten Paaren gibt es einen starken Vergleich: exakt den Vorjahresverkehr prognostizieren. Bei Paaren ohne Historie fehlt dieser Vergleich. Der zweite Test verbirgt das gesamte ungeordnete Paar in beiden Richtungen und berechnet Trainingsmassen neu. Er prüft die Übertragung zwischen beobachteten Paaren bestehender Flughäfen, nicht neue Flughäfen oder latente Nachfrage.")}</p>')
    body.append(f'<p class="formula">{T("Медианный множитель", "Median factor", "Medianer Faktor")} = exp(median(|ln(Q̂/Q)|))<br>'
                'WAPE = 100 × Σ|Q̂ − Q| / ΣQ<br>MAE = Σ|Q̂ − Q| / N<br>'
                f'{T("Смещение", "Bias", "Verzerrung")} = 100 × (ΣQ̂ − ΣQ) / ΣQ</p>')
    body.append(f'<p class="small">{T(
        "Множитель 1 означает точное совпадение; 1,6 — медианную кратность расхождения 1,6. Это не доверительный интервал для следующей пары. WAPE считает суммарную абсолютную ошибку относительно общего потока, MAE — ошибку в пассажирах на пару. Отрицательное смещение означает занижение общей суммы.",
        "A factor of 1 is exact; 1.6 means a median discrepancy factor of 1.6. It is not a confidence interval for the next pair. WAPE scales total absolute error by total traffic; MAE is the average passenger error per pair. Negative bias means underpredicting the aggregate.",
        "Ein Faktor von 1 ist exakt; 1,6 bedeutet eine mediane Abweichung um den Faktor 1,6. Dies ist kein Konfidenzintervall für das nächste Paar. WAPE setzt den gesamten absoluten Fehler zum Gesamtverkehr ins Verhältnis; MAE ist der mittlere Passagierfehler je Paar. Negative Verzerrung bedeutet eine zu niedrige Gesamtsumme.")}</p>')
    body.append(f'<h3>{T("Прогноз 2024 года по 2023-му", "Forecast 2024 using 2023", "Prognose 2024 anhand von 2023")}: {n(fc["n"])} {T("пар", "pairs", "Paare")}</h3>' + metric_table(fc))
    body.append(f'<h3>{T("Исключённые пары 2024 года", "Held-out pairs in 2024", "Ausgeschlossene Paare 2024")}: {n(ho["n"])} {T("пар", "pairs", "Paare")}</h3>' + metric_table(ho))
    chart_rows = []
    for k, color in [("distance", "var(--guess)"), ("gravity", "var(--sky-t)"), ("gravity_smearing", "var(--aqua-t)")]:
        values = [r["metrics"][k]["median_factor"] for r in ho["fold_results"]]
        chart_rows.append((model_name(k), ho["models"][k]["median_factor"], (min(values), max(values)), color))
    body.append(whisker(chart_rows, lo=1.4, hi=2.1, ticks=[1.4, 1.6, 1.8, 2.0], fmt=lambda v: n(v, 2), label_w=230))
    body.append(f'<p class="small">{T(
        "Точка — медианный множитель по всем проверочным парам; полоса — минимум и максимум пяти групп. Это разброс данного разбиения, не статистический интервал неопределённости. Таблицы и график — наш расчёт из сохранённых входов.",
        "Dots show the median factor across all evaluated pairs; bars span the minimum and maximum of the five folds. This is variation within one split, not a statistical uncertainty interval. Tables and chart are our calculations from saved inputs.",
        "Punkte zeigen den medianen Faktor aller geprüften Paare, Balken das Minimum und Maximum der fünf Gruppen. Dies ist die Streuung dieser Aufteilung, kein statistisches Unsicherheitsintervall. Tabellen und Grafik sind eigene Berechnungen aus gespeicherten Eingaben.")}</p>')

    body.append(f'<h2>{T("Почему поправить общую сумму недостаточно", "Why fixing the total is not enough", "Warum eine korrekte Gesamtsumme nicht genügt")}</h2>')
    body.append(f'<p>{T(
        "Обратное преобразование логарифмической регрессии может давать слишком низкую общую сумму. Отдельно проверена поправка Duan smearing: прогноз умножается на среднее exp(остаток), вычисленное только по обучающим строкам. Для прогноза следующего года множитель равен 1,286; в каждой из пяти групп он считается заново.",
        "Exponentiating a log regression can underpredict the total. We separately test Duan smearing: multiply predictions by the mean exp(residual), calculated from training rows only. The next-year multiplier is 1.286; each of the five folds gets its own estimate.",
        "Die Rücktransformation einer Log-Regression kann die Gesamtsumme unterschätzen. Separat prüfen wir Duan Smearing: Prognosen werden mit dem Mittelwert von exp(Residuum) ausschließlich aus Trainingszeilen multipliziert. Für das Folgejahr beträgt der Faktor 1,286; jede der fünf Gruppen erhält einen eigenen Wert.")}{s.cite(DUAN)}</p>')
    body.append(f'<p>{T(
        f"На исключённых парах смещение улучшается с {n(ho['models']['gravity']['bias_pct'], 2)} % до {n(ho['models']['gravity_smearing']['bias_pct'], 2)} %, но медианный множитель ухудшается с {n(ho['models']['gravity']['median_factor'], 3)} до {n(ho['models']['gravity_smearing']['median_factor'], 3)}, а WAPE растёт. Поэтому поправка полезна как диагностика, но не объявлена общим улучшением модели.",
        f"On held-out pairs, bias improves from {n(ho['models']['gravity']['bias_pct'], 2)}% to {n(ho['models']['gravity_smearing']['bias_pct'], 2)}%, but the median factor worsens from {n(ho['models']['gravity']['median_factor'], 3)} to {n(ho['models']['gravity_smearing']['median_factor'], 3)} and WAPE rises. This is a useful diagnostic, not an overall model improvement.",
        f"Bei ausgeschlossenen Paaren verbessert sich die Verzerrung von {n(ho['models']['gravity']['bias_pct'], 2)} % auf {n(ho['models']['gravity_smearing']['bias_pct'], 2)} %. Der mediane Faktor verschlechtert sich jedoch von {n(ho['models']['gravity']['median_factor'], 3)} auf {n(ho['models']['gravity_smearing']['median_factor'], 3)}, und WAPE steigt. Das ist eine nützliche Diagnose, keine allgemeine Modellverbesserung.")}</p>')

    body.append(f'<h2>{T("Сколько добавили ВВП и ночёвки", "What GDP and nights added", "Was BIP und Übernachtungen beitragen")}</h2>')
    body.append(f'<p>{T(
        "ВВП на человека взят по паритету покупательной способности в постоянных международных долларах 2021 года. Это показатель страны, не доход пассажира или населения зоны аэропорта. Туристический фактор — все ночёвки в средствах размещения региона NUTS2: включая резидентов и посетителей, приехавших любым транспортом. Он не равен числу авиаприбытий.",
        "GDP per person uses purchasing-power parity in constant 2021 international dollars. It describes a country, not a passenger's or airport catchment's income. The tourism feature counts all accommodation nights in a NUTS2 region, including residents and visitors using any mode of transport. It is not an air-arrival count.",
        "Das BIP je Einwohner wird in Kaufkraftparitäten und konstanten internationalen Dollar von 2021 verwendet. Es beschreibt ein Land, nicht das Einkommen eines Passagiers oder Flughafeneinzugsgebiets. Der Tourismusfaktor zählt sämtliche Übernachtungen in einer NUTS2-Region, einschließlich Inländern und Gästen aller Verkehrsmittel. Er entspricht nicht den Fluggastankünften.")}{s.cite(WB, TOUR)}</p>')
    body.append(f'<p>{T(
        "Оба фактора берутся за предыдущий год и добавляются по одному. Аэропорт сопоставлен с полигоном NUTS2 по координатам; годовая сумма требует всех 12 месяцев. Внутри каждого сравнения базовая и расширенная модели получают одинаковые строки обучения и проверки. Сами группы ВВП и туризма различаются по покрытию, поэтому сравнивать их абсолютные ошибки между собой нельзя.",
        "Both features use the previous year and are added one at a time. Airports are mapped into NUTS2 polygons by coordinates; annual totals require all 12 months. Each comparison gives the baseline and augmented models identical training and evaluation rows. GDP and tourism cohorts have different coverage, so their absolute errors are not directly comparable.",
        "Beide Faktoren stammen aus dem Vorjahr und werden einzeln ergänzt. Flughafenkoordinaten werden NUTS2-Polygonen zugeordnet; Jahressummen erfordern alle zwölf Monate. Innerhalb jedes Vergleichs erhalten Basis- und erweitertes Modell identische Trainings- und Prüfzeilen. BIP- und Tourismusgruppen unterscheiden sich in ihrer Abdeckung; ihre absoluten Fehler sind nicht direkt vergleichbar.")}{s.cite(d['macro']['tourism']['geography_source'])}</p>')
    rows = []
    for factor, key in [("income", "gravity_income"), ("tourism", "gravity_tourism")]:
        for exp, label in [("forecast_2023_2024", T("Следующий год", "Next year", "Folgejahr")),
                           ("heldout_pairs_2024", T("Исключённые пары", "Held-out pairs", "Ausgeschlossene Paare"))]:
            x = d["macro"][factor][exp]
            base, aug = x["models"]["gravity"], x["models"][key]
            rows.append([T("ВВП страны", "National GDP", "Nationales BIP") if factor == "income" else T("Ночёвки региона", "Regional nights", "Regionale Nächte"),
                         label, n(x["n"]), f'{n(base["median_factor"], 3)} → {n(aug["median_factor"], 3)}',
                         f'{n(base["wape_pct"], 2)} → {n(aug["wape_pct"], 2)}'])
    body.append(table([T("Добавленный фактор", "Added feature", "Ergänzter Faktor"), T("Проверка", "Test", "Test"), "N",
                       T("Медианный множитель: до → после", "Median factor: before → after", "Medianer Faktor: vorher → nachher"),
                       "WAPE, %"], rows))
    body.append(f'<p>{T(
        "Практического выигрыша в этой спецификации пока не видно: изменения малы, а разные метрики иногда движутся в разные стороны. Это не проверка причинного влияния дохода или туризма. Масса аэропорта уже может отражать часть этих связей; агрегаты страны и региона могут быть слишком грубыми. Эти объяснения — гипотезы для следующего теста. Формальная статистическая значимость здесь не оценивалась.",
        "This specification shows no clear practical gain: changes are small and metrics sometimes move in opposite directions. It is not a causal test of income or tourism. Airport mass may already capture part of these associations, and country or regional aggregates may be too coarse. Those explanations are hypotheses for the next test. Formal statistical significance has not been estimated.",
        "Diese Spezifikation zeigt bisher keinen klaren praktischen Gewinn: Änderungen sind klein, und Kennzahlen bewegen sich teils in entgegengesetzte Richtungen. Dies ist kein kausaler Test von Einkommen oder Tourismus. Die Flughafenmasse könnte Zusammenhänge bereits abbilden; Länder- und Regionalaggregate könnten zu grob sein. Das sind Hypothesen für den nächsten Test. Formale statistische Signifikanz wurde nicht geschätzt.")}</p>')
    body.append(f'<p class="small">{T(
        "Данные скачаны в 2026 году; исторические даты публикаций и последующие пересмотры не восстановлены. Используются границы NUTS 2024. Поэтому это ретроспективная исследовательская проверка с лагом показателей, а не демонстрация прогноза, который можно было получить в реальном времени в 2023 году.",
        "Data were downloaded in 2026; historical publication dates and later revisions were not reconstructed. NUTS 2024 boundaries are used. This is a retrospective research comparison with lagged indicators, not a demonstration of a forecast available in real time in 2023.",
        "Die Daten wurden 2026 heruntergeladen; historische Veröffentlichungsstände und spätere Revisionen wurden nicht rekonstruiert. Verwendet werden NUTS-2024-Grenzen. Dies ist ein retrospektiver Vergleich mit verzögerten Indikatoren, kein Nachweis einer bereits 2023 in Echtzeit verfügbaren Prognose.")}</p>')

    body.append(f'<h2>{T("Пример: Франкфурт — Барселона", "Example: Frankfurt–Barcelona", "Beispiel: Frankfurt–Barcelona")}</h2>')
    ex = fc["example"]
    scenario = {"share": 0.15, "seats": 180, "load": 0.8, "days": 365, "directions": 2}
    flights = lambda q: scenario["share"] * q / (scenario["days"] * scenario["directions"] * scenario["seats"] * scenario["load"])
    example_rows = [(T("Опубликовано за 2024", "Published for 2024", "Für 2024 veröffentlicht"), ex["actual"])]
    example_rows += [(model_name(k), ex["predictions"][k]) for k in ("last_year", "gravity", "gravity_smearing")]
    body.append(table([T("Поток EDDF–LEBL", "EDDF–LEBL flow", "Verkehr EDDF–LEBL"), T("Пасс./год, обе стороны", "Passengers/year, both ways", "Passagiere/Jahr, beide Richtungen"),
                       T("Условных рейсов/день в одну сторону", "Illustrative flights/day per direction", "Beispielflüge/Tag je Richtung")],
                      [[label, n(value), n(flights(value), 2)] for label, value in example_rows]))
    body.append('<p class="formula">f<sub>one-way/day</sub> = share × Q / (365 × 2 × seats × load)<br>'
                'share = 15 %; seats = 180; load = 80 %</p>')
    body.append(f'<p>{T(
        "Все модельные значения в этой таблице относятся к одной проверке следующего года, а не к разным подвыборкам ВВП и туризма. Доля 15 %, 180 кресел, загрузка 80 %, равный поток по направлениям и равномерный год — наши условия примера. Они показывают, как ошибка годового потока переносится в частоту. Это не рекомендация открыть рейс: конкуренция, пересадки, частота, тариф и сезонность здесь не смоделированы.",
        "All model values in this table belong to the same next-year experiment, not to different GDP and tourism cohorts. A 15% share, 180 seats, 80% load, equal directional traffic and an even year are illustrative assumptions. They show how an annual-flow error carries into frequency. This is not a route-launch recommendation: competition, connections, frequency response, fare and seasonality are not modelled here.",
        "Alle Modellwerte dieser Tabelle stammen aus demselben Folgejahrestest, nicht aus unterschiedlichen BIP- und Tourismusgruppen. 15 % Marktanteil, 180 Sitze, 80 % Auslastung, gleiche Richtungsströme und ein gleichmäßiges Jahr sind Beispielannahmen. Sie zeigen die Übertragung eines Verkehrsfehlers auf die Frequenz. Dies ist keine Streckeneröffnungsempfehlung; Wettbewerb, Umstiege, Frequenzwirkung, Preis und Saisonalität sind nicht modelliert.")}</p>')

    body.append(f'<h2>{T("Что требуется для следующего этапа", "What the next stage needs", "Was die nächste Stufe benötigt")}</h2>')
    body.append(table([T("Фактор", "Factor", "Faktor"), T("Следующая проверка", "Next test", "Nächster Test")], [
        [T("Доход", "Income", "Einkommen"), T("региональный показатель в зоне притяжения вместо страны; проверка на полной P/T/F-базе", "regional catchment measure instead of country data; test against the full P/T/F baseline", "regionales Einzugsgebietsmaß statt Landeswert; Test gegen vollständige P/T/F-Basis")],
        [T("Туризм и сезонность", "Tourism and seasonality", "Tourismus und Saisonalität"), T("связать месячные ночёвки с месячными потоками; годы обучения и проверки разделить", "link monthly nights to monthly traffic; separate training and test years", "monatliche Nächte und Verkehre verknüpfen; Trainings- und Testjahre trennen")],
        [T("Деловая активность", "Business activity", "Geschäftsaktivität"), T("региональная занятость и отраслевая структура; отдельная добавка на той же выборке", "regional employment and sector mix; a separate addition on the same sample", "regionale Beschäftigung und Branchenstruktur; separate Ergänzung derselben Stichprobe")],
        [T("Диаспоры", "Diasporas", "Diaspora"), T("двусторонний миграционный запас на известную дату; направление и масштаб географии", "bilateral migrant stock at a known date; direction and geographic scale", "bilateraler Migrantenbestand zu bekanntem Datum; Richtung und räumliche Ebene")],
        [T("Визы", "Visas", "Visa"), T("направленные визовые условия по гражданству и времени, не общий рейтинг паспорта", "directional visa rules by citizenship and time, not an aggregate passport rank", "gerichtete Visaregeln nach Staatsangehörigkeit und Zeit, kein allgemeiner Passrang")],
    ]))
    body.append(f'<p>{T(
        "Диаспоры, визы и отдельный деловой фактор ещё не оценены. Годовые агрегаты не позволяют проверить профиль сезона. Для нового направления дополнительно нужны проверка открытия маршрутов и явное различение отсутствующей статистики, отсутствующего предложения и низкого спроса. Коридор цен потребует также связи потока с тарифом и конкуренцией: нынешний тест её не оценивает.",
        "Diaspora, visa and separate business effects have not yet been estimated. Annual aggregates cannot validate a seasonal profile. New-route work also requires route-opening evaluation and a distinction between missing statistics, absent service and low demand. A fare corridor needs a relationship with fares and competition, which this experiment does not estimate.",
        "Diaspora-, Visa- und separate Geschäftseffekte sind noch nicht geschätzt. Jahresaggregate prüfen kein Saisonprofil. Neue Verbindungen erfordern zusätzlich Tests an Streckeneröffnungen sowie die Trennung von fehlender Statistik, fehlendem Angebot und geringer Nachfrage. Ein Preiskorridor braucht außerdem den Zusammenhang mit Tarifen und Wettbewerb; dieser wird hier nicht geschätzt.")}</p>')
    body.append(f'<h2>{T("Что это меняет в калькуляторе", "What this means for the calculator", "Was dies für den Rechner bedeutet")}</h2><ul>')
    body.append(f'<li>{mark("planned")}{T("Сначала воспроизвести рабочую P/T/F-модель на том же протоколе. Ошибки упрощённого теста не подменяют её проверку.", "First reproduce the production P/T/F model under the same protocol. Simplified benchmark errors do not replace that evaluation.", "Zuerst das produktive P/T/F-Modell im selben Prüfprotokoll reproduzieren. Fehler des vereinfachten Benchmarks ersetzen diese Prüfung nicht.")}</li>')
    body.append(f'<li>{mark("planned")}{T("Каждый фактор сравнивать с базой на одинаковых строках, годах и географии; сохранять несколько метрик.", "Compare each factor with the baseline on identical rows, years and geography; retain several metrics.", "Jeden Faktor auf identischen Zeilen, Jahren und Gebieten mit der Basis vergleichen; mehrere Kennzahlen erhalten.")}</li>')
    body.append(f'<li>{mark("planned")}{T("Диапазон спроса калибровать на отдельных проверочных данных. Медианный множитель 1,6 не превращать автоматически в полосу прогноза.", "Calibrate a demand interval on separate evaluation data. Do not turn the median factor of 1.6 directly into a prediction band.", "Eine Nachfragespanne an separaten Prüfdaten kalibrieren. Den medianen Faktor 1,6 nicht direkt in ein Prognoseband umwandeln.")}</li></ul>')
    body.append(f'<details><summary>{T("Проверка, воспроизводимость и что нужно от владельца", "Verification, reproducibility and owner inputs", "Prüfung, Reproduzierbarkeit und Eingaben des Eigentümers")}</summary>')
    body.append(f'<p>{T(
        "Все коэффициенты, метрики, прогнозы по парам, хеши входов и правила исключения сохранены в out/. Отдельный проверяющий заново считает регрессию и признаки, сверяет значения Всемирного банка, геопривязку и суммы Eurostat; результаты и код находятся в verify/. Сборщики и проверяющий не один и тот же агент. HTML на трёх языках собирается из summary.json, а не из вручную набранных итоговых таблиц.",
        "Coefficients, metrics, pair predictions, input hashes and exclusions are saved under out/. An independent verifier recomputes regression and features and checks World Bank values, geographic mapping and Eurostat totals; results and code are under verify/. Collection and verification are handled by different agents. The three-language HTML is built from summary.json rather than manually entered result tables.",
        "Koeffizienten, Kennzahlen, Paarprognosen, Eingabe-Hashes und Ausschlüsse liegen in out/. Eine unabhängige Prüfung berechnet Regression und Merkmale neu und kontrolliert Weltbankwerte, Geozuordnung und Eurostat-Summen; Ergebnisse und Code liegen in verify/. Sammlung und Prüfung erfolgen durch verschiedene Agenten. Das dreisprachige HTML entsteht aus summary.json statt aus manuell erfassten Ergebnistabellen.")}</p>')
    body.append(f'<p>{T(
        "Для этого этапа дополнительных файлов от владельца не требуется. Для проверки сезонности подготовлен export_panel.py: он читает только разрешённые таблицы справочника в режиме read-only и создаёт отдельный сжатый файл. Нужность серверной выгрузки уточняется после проверки месячных открытых данных. До публикации владелец проверяет выводы на своей модели; статьи остаются draft: true.",
        "No additional owner files are needed for this stage. For seasonality, export_panel.py can read only allowed reference-data tables in read-only mode and create a separate compressed file. A server export will be requested only after assessing public monthly data. Before publication, the owner checks the conclusions against their model; articles remain draft: true.",
        "Für diese Stufe werden keine weiteren Dateien des Eigentümers benötigt. Für Saisonalität kann export_panel.py nur freigegebene Referenztabellen im Nur-Lese-Modus auslesen und eine separate komprimierte Datei erzeugen. Ein Serverexport wird erst nach Prüfung öffentlicher Monatsdaten angefordert. Vor Veröffentlichung prüft der Eigentümer die Schlussfolgerungen an seinem Modell; die Artikel bleiben draft: true.")}</p></details>')
    body.append(s.html())
    return page(article_title(SLUG), "\n".join(body))


if __name__ == "__main__":
    write_all(HERE, SLUG, build)
