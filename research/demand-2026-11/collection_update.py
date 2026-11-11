"""Additional supply and birthplace data, with an explicit next modelling step."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

from _report import T, e, n

HERE = Path(__file__).resolve().parent
EUROSTAT_META = 'https://ec.europa.eu/eurostat/cache/metadata/en/avia_pa_esms.htm'


def _table(heads, rows, *, table_id=None, row_attribute=None, row_keys=()):
    identity = f' id="{e(table_id)}"' if table_id else ''
    rendered = []
    for index, row in enumerate(rows):
        attribute = f' {row_attribute}="{e(row_keys[index])}"' if row_attribute else ''
        rendered.append(f'<tr{attribute}>' + ''.join(f'<td>{x}</td>' for x in row) + '</tr>')
    return ('<div class="tw"><table' + identity + '><thead><tr>' + ''.join(f'<th>{e(x)}</th>' for x in heads)
            + '</tr></thead><tbody>' + ''.join(rendered) + '</tbody></table></div>')


def _count(value):
    return n(value, 0 if value is None or float(value).is_integer() else 1)


def collection_update(s):
    """Build a translated section using collected summaries, never forecasts."""
    d = json.loads((HERE / 'out/supply_summary.json').read_text())
    migrants = json.loads((HERE / 'out/migrant_stock_summary.json').read_text())
    migrant_panel = json.loads(gzip.decompress((HERE / 'out/migrant_stock.json.gz').read_bytes()))
    migrant_meta = migrant_panel['meta']
    archive_refs = []
    for cc in d['reporting_countries']:
        sources = [x for x in d['sources'] if '/avia_par_' + cc.lower() + '?' in x['url']]
        archive_refs.append(sources[0]['url'])
        for source in sources:
            s.url(source['url'], T(f'Eurostat: рейсы, кресла и пассажиры на борту, архив {cc}',
                                   f'Eurostat: flights, seats and passengers on board, {cc} archive',
                                   f'Eurostat: Flüge, Sitze und Passagiere an Bord, Archiv {cc}'))
    s.url(EUROSTAT_META, T('Eurostat: определения перевозок и границы публикации',
                           'Eurostat: traffic definitions and publication coverage',
                           'Eurostat: Verkehrsdefinitionen und Veröffentlichungsumfang'))
    primary_refs = {}
    for item in d['primary_comparisons']:
        if item.get('status') == 'matched_primary':
            s.url(item['url'], T(f'Eurostat: первичный ряд {item["pair"]}, {item["measure"]}',
                                 f'Eurostat: primary series {item["pair"]}, {item["measure"]}',
                                 f'Eurostat: Originalreihe {item["pair"]}, {item["measure"]}'))
            primary_refs.setdefault(item['pair'], []).append(item['url'])
    recent_refs = []
    for probe in d['primary_access_probes']:
        if 'sinceTimePeriod=2025-01' in probe['url']:
            recent_refs.append(probe['url'])
            s.url(probe['url'], T('Eurostat: проверка доступности рейсов с января 2025 года',
                                  'Eurostat: flight-data availability from January 2025',
                                  'Eurostat: Verfügbarkeit von Flugdaten ab Januar 2025'))

    pair_count, pair_months = d['pairs'], d['pair_months_any_measure']
    series = sum(d['series'].values())
    matched = d['pair_months_matched_triplet']
    joined = d['overlap_with_pas_crd_panel']['pairs_with_both_datasets']
    body = [f'<h2 id="supply-collected">{T("Рейсы и кресла: следующий слой уже собран", "Flights and seats: the next layer is available", "Flüge und Sitze: die nächste Datenschicht liegt vor")}</h2>',
        f'<p>{T("Теперь пассажирский поток можно сопоставить с тем, сколько рейсов выполнялось и сколько кресел предлагалось. Это позволит проверить, чем сопровождался рост перевозок: большей частотой, более вместительными самолётами или более высокой занятостью кресел. Сам по себе такой расчёт ещё не доказывает, что именно вызвало рост.",
                 "Passenger traffic can now be compared with the number of flights and seats offered. We can examine whether traffic growth coincided with more flights, larger aircraft or greater seat occupancy. This comparison alone does not establish what caused the growth.",
                 "Der Passagierverkehr lässt sich jetzt mit der Zahl der Flüge und angebotenen Sitze vergleichen. So wird prüfbar, ob Verkehrswachstum mit mehr Flügen, größeren Flugzeugen oder höherer Sitzplatzauslastung einherging. Der Vergleich allein belegt noch keine Ursache.")}</p>',
        f'<p>{T(f"Для пяти стран-отчётчиков — Германии, Испании, Франции, Италии и Нидерландов — собраны {n(series)} опубликованных месячных ряда за 2005–2024 годы. После отделения неоднозначных географических групп осталось {n(pair_count)} пар аэропортов и {n(pair_months)} наблюдений пары за месяц. Согласованная тройка «пассажиры на борту, кресла, рейсы» есть в {n(matched)} случаях. С прежней панелью пассажирского потока пересекаются {n(joined)} пары.",
                 f"For five reporting countries—Germany, Spain, France, Italy and the Netherlands—we collected {n(series)} published monthly series for 2005–2024. After separating ambiguous geographic groups, the panel contains {n(pair_count)} airport pairs and {n(pair_months)} pair-month observations. A matched set of passengers on board, seats and flights exists in {n(matched)} cases; {n(joined)} pairs also appear in the earlier passenger-flow panel.",
                 f"Für die fünf Meldeländer Deutschland, Spanien, Frankreich, Italien und die Niederlande wurden {n(series)} veröffentlichte Monatsreihen für 2005–2024 gesammelt. Nach Abtrennung mehrdeutiger geografischer Gruppen bleiben {n(pair_count)} Flughafenpaare und {n(pair_months)} Paarmonate. Für {n(matched)} Fälle liegt eine abgestimmte Kombination aus Passagieren an Bord, Sitzen und Flügen vor; {n(joined)} Paare sind auch im bisherigen Verkehrsdatensatz enthalten.")}{s.cite(*archive_refs)}</p>']

    examples = [
        ('EDDF-LEBL', T('Франкфурт — Барселона', 'Frankfurt–Barcelona', 'Frankfurt–Barcelona')),
        ('EDDL-LEPA', T('Дюссельдорф — Пальма', 'Düsseldorf–Palma', 'Düsseldorf–Palma')),
        ('EDDF-LIMC', T('Франкфурт — Милан-Мальпенса', 'Frankfurt–Milan Malpensa', 'Frankfurt–Mailand-Malpensa')),
        ('EDDF-VIDP', T('Франкфурт — Дели', 'Frankfurt–Delhi', 'Frankfurt–Delhi')),
        ('EHAM-LFRN', T('Амстердам — Ренн', 'Amsterdam–Rennes', 'Amsterdam–Rennes')),
    ]
    rows = []
    for code, label in examples:
        a = d['diagnostic_annual'][code]['2024']
        rows.append([e(label) + s.cite(*primary_refs.get(code, [])), _count(a['seats']), _count(a['flights']),
                     n(a['seat_load_factor'] * 100, 1) + '%', n(a['seats_per_flight'], 1)])
    body.append(_table([T('Пара, 2024 год', 'Pair, 2024', 'Paar, 2024'), T('Кресел за год', 'Seats per year', 'Sitze pro Jahr'),
                        T('Рейсов за год', 'Flights per year', 'Flüge pro Jahr'), T('Занятость кресел', 'Seat occupancy', 'Sitzplatzauslastung'),
                        T('Кресел на рейс', 'Seats per flight', 'Sitze je Flug')], rows,
                       table_id='supply-diagnostics', row_attribute='data-pair', row_keys=[code for code, _ in examples]))
    body.append(f'<p class="small">{T("Оба направления и все перевозчики вместе; у каждого примера есть 12 согласованных месяцев. Две стороны сообщают о тех же полётах: их отчёты усредняются, поэтому возможны дробные кресла и рейсы в итогах. Это не рекомендации по типу ВС: средняя вместимость смешивает разные самолёты и компоновки. Полный сбор включает всю заданную когорту, а не только эти пять примеров.",
        "Both directions and all airlines combined; each example has twelve matched months. The two airports report the same flights, so their reports are averaged and totals may contain fractional seats or flights. These are not aircraft-type recommendations: average capacity combines different aircraft and configurations. The collection covers the whole predefined cohort, not just these five examples.",
        "Beide Richtungen und alle Airlines zusammen; jedes Beispiel hat zwölf abgestimmte Monate. Beide Flughäfen melden dieselben Flüge. Ihre Meldungen werden gemittelt, weshalb Summen Bruchteile von Sitzen oder Flügen enthalten können. Dies sind keine Empfehlungen für Flugzeugtypen: Die mittlere Kapazität umfasst unterschiedliche Flugzeuge und Kabinen. Die Sammlung deckt die gesamte vorab festgelegte Kohorte ab.")}</p>')

    body.append(f'<h3>{T("Как сопоставляем поток и вместимость", "Matching traffic and capacity", "Verkehr und Kapazität richtig zuordnen")}</h3>')
    body.append(f'<p class="formula">{T("Занятость кресел = пассажиры на борту / предложенные кресла<br>Средняя вместимость рейса = предложенные кресла / рейсы", "Seat occupancy = passengers on board / seats offered<br>Average flight capacity = seats offered / flights", "Sitzplatzauslastung = Passagiere an Bord / angebotene Sitze<br>Mittlere Flugkapazität = angebotene Sitze / Flüge")}</p>')
    body.append(f'<p>{T("Пассажиры на борту, PAS_BRD, относятся к участку от взлёта до следующей посадки и включают прямой транзит. Прежний PAS_CRD считает поездку в пределах одного номера рейса по посадке и высадке, исключая прямой транзит. Для занятости кресел используем PAS_BRD вместе с креслами ST_PAS и рейсами CAF_PAS. В каждом месяце все три значения усредняются по одному и тому же набору аэропортов-отчётчиков; годовые отношения считаются по годовым суммам. Высокая занятость не измеряет скрытый спрос и не задаёт долю будущего перевозчика.",
        "Passengers on board, PAS_BRD, refer to a flight stage from take-off to the next landing and include direct transit. The earlier PAS_CRD series records embarkation and disembarkation within one flight number and excludes direct transit. Seat occupancy therefore uses PAS_BRD with seats ST_PAS and flights CAF_PAS. Every month, all three values are averaged over the identical set of reporting airports; annual ratios use annual sums. High occupancy does not measure hidden demand or determine a future airline's share.",
        "Passagiere an Bord, PAS_BRD, beziehen sich auf den Flugabschnitt vom Start bis zur nächsten Landung und schließen direkten Transit ein. Die bisherige Reihe PAS_CRD erfasst Ein- und Ausstieg innerhalb einer Flugnummer ohne direkten Transit. Für die Auslastung verwenden wir daher PAS_BRD mit Sitzen ST_PAS und Flügen CAF_PAS. Alle drei Monatswerte werden über dieselben meldenden Flughäfen gemittelt; Jahresquoten beruhen auf Jahressummen. Hohe Auslastung misst weder verborgene Nachfrage noch den Anteil einer künftigen Airline.")}{s.cite(EUROSTAT_META)}</p>')
    q = d['quality']
    incomplete = q['no_complete_common_reporter']
    disagree = q['reporter_disagreement_above_10pct']
    excess = q['passengers_exceed_available_seats']
    checked = sum(x.get('checked_values', 0) for x in d['primary_comparisons'])
    body.append(f'<details><summary>{T("Покрытие, качество и свежесть", "Coverage, quality and recency", "Abdeckung, Qualität und Aktualität")}</summary>')
    body.append(f'<p>{T(f"У {n(incomplete)} пар-месяцев нет полной согласованной тройки. В {n(disagree)} случаях отчёты сторон расходятся больше чем на 10% их среднего хотя бы по одной величине; в {n(excess)} пассажиров больше кресел. Значения и флаги сохранены для разбора причин. Пропуски не заменяются нулями, неполные годы не достраиваются. Пороги публикации самого Eurostat также могут скрывать небольшие маршруты.",
        f"There is no complete matched triplet in {n(incomplete)} pair-months. In {n(disagree)} cases, reports differ by more than 10% of their mean for at least one measure; {n(excess)} have more passengers than seats. Values and flags remain available for investigation. Missing values are not zero-filled and incomplete years are not extrapolated. Eurostat's own publication thresholds can also hide small routes.",
        f"In {n(incomplete)} Paarmonaten fehlt eine vollständige abgestimmte Kombination. In {n(disagree)} Fällen weichen Meldungen bei mindestens einer Größe um mehr als 10% ihres Mittels ab; in {n(excess)} Fällen übersteigen Passagiere die Sitzzahl. Werte und Kennzeichen bleiben zur Ursachenprüfung erhalten. Fehlwerte werden nicht durch null ersetzt und unvollständige Jahre nicht hochgerechnet. Auch Eurostats Veröffentlichungsschwellen können kleine Strecken ausblenden.")}{s.cite(EUROSTAT_META)}</p>')
    body.append(f'<p>{T(f"Длинная история получена через обозначенный архив DBnomics, а {n(checked)} опубликованных значений контрольных рядов сверены с официальным API и совпали. Архив заканчивается декабрём 2024 года. Отдельные запросы рейсов с января 2025 года по всем пяти странам не вернули опубликованных значений; это результат этих запросов, а не нулевой трафик. У французского первичного ответа дата обновления уже 2026 год, но проверенный ряд Ренн также заканчивается 2024-м. Дата обновления источника и последний наблюдаемый месяц — разные вещи.",
        f"The long history comes through the identified DBnomics archive; {n(checked)} published diagnostic values matched the official API. The archive ends in December 2024. Separate requests for flights from January 2025 returned no published values for any of the five countries; this is an availability result, not zero traffic. The French primary response has a 2026 update date, yet the checked Rennes series also ends in 2024. A source update date and the last observed month are different things.",
        f"Die lange Historie stammt aus dem gekennzeichneten DBnomics-Archiv; {n(checked)} veröffentlichte Kontrollwerte stimmen mit der offiziellen API überein. Das Archiv endet im Dezember 2024. Separate Flugabfragen ab Januar 2025 lieferten für keines der fünf Länder veröffentlichte Werte; das ist ein Verfügbarkeitsergebnis, kein Nullverkehr. Die französische Originalantwort wurde 2026 aktualisiert, doch auch die geprüfte Rennes-Reihe endet 2024. Aktualisierungsdatum und letzter beobachteter Monat sind verschieden.")}{s.cite(*recent_refs, *primary_refs.get('EHAM-LFRN', [])[:1])}</p></details>')

    body.append(f'<h3>{T("Место рождения: первый вход для проверки диаспор", "Birthplace: an initial input for diaspora analysis", "Geburtsland: ein erster Eingang für die Diaspora-Analyse")}</h3>')
    migrant_urls = {}
    for cc in migrants['reporters']:
        source = migrant_meta['sources']['eurostat-migr-pop3ctb-' + cc.lower()]
        migrant_urls[cc] = source['url']
        s.url(source['url'], T(f'Eurostat migr_pop3ctb: место рождения населения {cc}',
                              f'Eurostat migr_pop3ctb: country of birth of residents in {cc}',
                              f'Eurostat migr_pop3ctb: Geburtsland der Wohnbevölkerung in {cc}'))
    s.url(migrant_meta['metadata_url'], T('Eurostat: определения статистики населения',
                                        'Eurostat: population statistics definitions',
                                        'Eurostat: Definitionen der Bevölkerungsstatistik'))
    country = {
        'DE': T('Германия', 'Germany', 'Deutschland'), 'ES': T('Испания', 'Spain', 'Spanien'),
        'FR': T('Франция', 'France', 'Frankreich'), 'IT': T('Италия', 'Italy', 'Italien'),
        'NL': T('Нидерланды', 'Netherlands', 'Niederlande'),
    }
    body.append(f'<p>{T("Из официального API Eurostat получена численность жителей по стране рождения на 1 января за 2005–2025 годы. Покрытие неоднородно: для Германии в этом срезе нет значений по отдельным странам рождения, хотя агрегаты присутствуют; у Франции много пробелов и меняется детализация. Таблица показывает число зарубежных стран и территорий рождения с данными, а не число людей.",
        "The official Eurostat API supplied resident-population stocks by country of birth on 1 January for 2005–2025. Coverage is uneven: this German extract has no values for individual birth countries, although aggregates exist; France has substantial gaps and changing detail. The table counts foreign birth countries and territories with data, not people.",
        "Aus der offiziellen Eurostat-API liegen Bevölkerungsbestände nach Geburtsland zum 1. Januar für 2005–2025 vor. Die Abdeckung ist uneinheitlich: Im deutschen Auszug fehlen Werte für einzelne Geburtsländer trotz vorhandener Aggregate; Frankreich hat große Lücken und wechselnde Detailtiefe. Die Tabelle zählt ausländische Geburtsländer und -gebiete mit Daten, keine Personen.")}</p>')
    rows = []
    for cc, data in migrants['reporters'].items():
        last = data['annual_coverage'][-1]
        available = data['bilateral_country_input_available']
        rows.append([e(country[cc]) + s.cite(migrant_urls[cc]),
                     n(last['cross_border_origins_numeric']) if available else T('Нет детализации', 'No country detail', 'Keine Länderdetails'),
                     n(data['cross_border_country_pairs']['series_with_all_21_numeric_values']) if available else '—'])
    body.append(_table([T('Страна проживания', 'Country of residence', 'Wohnsitzland'),
                        T('Есть значение на 1 января 2025', 'Value on 1 January 2025', 'Wert zum 1. Januar 2025'),
                        T('Полная история 2005–2025', 'Complete history 2005–2025', 'Vollständige Reihe 2005–2025')], rows,
                       table_id='migrant-coverage', row_attribute='data-residence', row_keys=list(migrants['reporters'])))
    body.append(f'<p class="small">{T("Это национальный запас населения по месту рождения, не годовая миграция, число поездок или распределение жителей по городам и аэропортам. Пропуски не заполняются агрегатом «родившиеся за рубежом», гражданством или нулями. Для маршрутной модели нужны обе стороны связи, зоны охвата аэропортов и оценённая по данным связь с поездками; коэффициент диаспоры ещё не обучен.",
        "This is a national population stock by birthplace, not annual migration, trips or a distribution across cities and airports. Missing values are not filled with foreign-born aggregates, citizenship or zeros. A route model needs both sides of the relationship, airport catchments and an empirically estimated link to travel; no diaspora coefficient has yet been fitted.",
        "Dies ist ein nationaler Bevölkerungsbestand nach Geburtsland, keine jährliche Migration, Reisezahlen oder Verteilung auf Städte und Flughäfen. Fehlwerte werden weder durch Gesamtzahlen im Ausland Geborener noch durch Staatsangehörigkeit oder null ersetzt. Ein Streckenmodell benötigt beide Seiten der Beziehung, Flughafeneinzugsgebiete und einen empirisch geschätzten Reisebezug; ein Diasporakoeffizient ist noch nicht angepasst.")}{s.cite(migrant_meta['metadata_url'])}</p>')

    body.append(f'<h3>{T("Ближайший шаг: проверить базовые модели", "Next: evaluate the baseline models", "Als Nächstes: die Basismodelle prüfen")}</h3>')
    body.append(f'<p>{T("Собранного уже достаточно, чтобы начать согласование потоков и вместимости и проверить простые ориентиры: последний полный год, прежний месячный профиль и тренд, обученный только на прошлом. На одинаковых временных выборках с ними сравним действующую модель калькулятора, заново обученную без информации из будущего, затем добавим факторы. Будущую фактическую ёмкость нельзя подставлять как заранее известный вход: она должна быть отдельным прогнозом или условием сценария. Именно эта проверка сейчас важнее расширения списка источников.",
        "Enough data is now available to harmonise traffic and capacity and evaluate simple references: the last complete year, the previous monthly profile and a trend trained only on past data. On identical time splits, these will be compared with the production calculator model refitted without future information before adding factors. Realised future capacity cannot be used as an already-known input; it must be separately forecast or specified as a scenario. This evaluation is now more important than extending the source list.",
        "Die vorhandenen Daten reichen aus, um Verkehr und Kapazität abzugleichen und einfache Referenzen zu prüfen: letztes vollständiges Jahr, bisheriges Monatsprofil und einen nur aus vergangenen Daten geschätzten Trend. Auf identischen Zeitaufteilungen vergleichen wir damit das ohne Zukunftsinformationen neu angepasste Rechnermodell und ergänzen anschließend Faktoren. Tatsächliche künftige Kapazität darf kein vorab bekannter Eingang sein; sie muss separat prognostiziert oder als Szenario vorgegeben werden. Diese Prüfung ist nun wichtiger als eine längere Quellenliste.")}</p>')
    queue = [
        [T('Свежий хвост 2025–2026', 'Recent observations for 2025–2026', 'Aktuelle Beobachtungen 2025–2026'),
         T('Те же пары, месяцы, пассажиры, кресла и рейсы; сверка перекрытия с архивом. Это приблизит наблюдаемый якорь к дате решения.',
           'The same pairs, months, passengers, seats and flights, with overlap checked against the archive, to bring the observed anchor closer to the decision date.',
           'Dieselben Paare, Monate, Passagiere, Sitze und Flüge mit Archivabgleich, um den beobachteten Ausgangspunkt näher an die Entscheidung zu rücken.')],
        [T('Тарифы и конкуренция', 'Fares and competition', 'Tarife und Wettbewerb'),
         T('Реализованный средний тариф, перевозчики, доли и частоты. Это позволит разделить рост рынка, изменение цены и перераспределение между компаниями.',
           'Realised average fares, airlines, shares and frequencies, to separate market growth, price changes and redistribution between carriers.',
           'Realisierte Durchschnittstarife, Airlines, Anteile und Frequenzen, um Marktwachstum, Preiseffekte und Verschiebungen zwischen Anbietern zu trennen.')],
        [T('Полная поездка с пересадками', 'Complete connecting journeys', 'Vollständige Umsteigereisen'),
         T('Истинные начало и конец поездки, пересадочные узлы и наземные альтернативы. Без них поток прямого рейса не раскрывает весь рынок новой пары.',
           'True journey origins and destinations, connecting hubs and surface alternatives. Nonstop traffic alone does not reveal the whole market for a new pair.',
           'Tatsächliche Reiseursprünge und -ziele, Umsteigeknoten und Bodenalternativen. Direktverkehr allein zeigt nicht den gesamten Markt eines neuen Paars.')],
        [T('Диаспоры и зоны охвата', 'Diasporas and airport catchments', 'Diaspora und Flughafeneinzugsgebiete'),
         T('Недостающие двусторонние запасы населения и их городская география. Нельзя распределить страновую диаспору по аэропортам только пропорционально населению без проверки.',
           'Missing bilateral population stocks and their urban geography. Allocating national diaspora stocks to airports purely in proportion to population requires validation.',
           'Fehlende bilaterale Bevölkerungsbestände und ihre städtische Verteilung. Eine rein proportionale Zuordnung nationaler Bestände nach Einwohnerzahl zu Flughäfen muss geprüft werden.')],
        [T('Типы ВС и ограничения', 'Aircraft and operating constraints', 'Flugzeuge und Betriebsgrenzen'),
         T('Исторические типы и компоновки, дальность с нагрузкой, ВПП, слоты, права полёта. Этот слой превратит сценарий пассажиров в допустимые сочетания самолёта и частоты.',
           'Historical aircraft and layouts, range with payload, runways, slots and traffic rights. These convert passenger scenarios into feasible combinations of aircraft and frequency.',
           'Historische Flugzeugtypen und Kabinen, Nutzlast-Reichweite, Pisten, Slots und Verkehrsrechte. Daraus werden technisch zulässige Kombinationen aus Flugzeug und Frequenz.')],
    ]
    body.append(_table([T('Параллельный поиск', 'Parallel data search', 'Parallele Datensuche'),
                        T('Что даст расчёту', 'Contribution to the model', 'Beitrag zur Berechnung')], queue))
    next_sources = {
        'aena': ('https://www.aena.es/es/estadisticas/informes-mensuales.html', 'Aena: monthly airport reports'),
        'caa': ('https://www.caa.co.uk/data-and-analysis/uk-aviation-market/consumer-research/departing-passenger-survey/passenger-survey-report-2025/', 'UK CAA: departing passenger survey 2025'),
        'bts': ('https://www.bts.gov/topics/airlines-and-airports/origin-and-destination-survey-data', 'US BTS: Origin and Destination Survey'),
    }
    for url, title in next_sources.values():
        s.url(url, title)
    body.append(f'<p class="small">{T("Следующие конкретные источники ещё не загружены в модель: месячные отчёты Aena за 2026 год — для оценки текущих итогов аэропортов, без подмены ими маршрутного потока; британский опрос CAA 2025 — для места проживания, цели и полной поездки пассажира в охваченных аэропортах; американские BTS DB1B/DB1C — отдельная выборка тарифов и маршрутов билетов. Переход от DB1B к DB1C в июле 2025 года требует проверки сопоставимости. Коэффициенты американского рынка нельзя автоматически переносить на Европу.",
        "Specific next sources have not yet been loaded into the model: Aena's 2026 monthly reports for current airport totals, without substituting them for route traffic; the UK CAA 2025 survey for residence, purpose and complete journeys at covered airports; and US BTS DB1B/DB1C as a separate fare-and-itinerary sample. The July 2025 transition from DB1B to DB1C requires a comparability check. US-market coefficients cannot automatically be transferred to Europe.",
        "Konkrete nächste Quellen sind noch nicht ins Modell geladen: Aenas Monatsberichte 2026 für aktuelle Flughafensummen, nicht als Ersatz für Streckenverkehr; die britische CAA-Erhebung 2025 für Wohnort, Reisezweck und vollständige Reisen an erfassten Flughäfen; US BTS DB1B/DB1C als separate Tarif- und Reiseroutenstichprobe. Der Übergang von DB1B zu DB1C im Juli 2025 erfordert eine Vergleichbarkeitsprüfung. US-Koeffizienten sind nicht automatisch auf Europa übertragbar.")}{s.cite(*(url for url, _ in next_sources.values()))}</p>')
    return ''.join(body)
