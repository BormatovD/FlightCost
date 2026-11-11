"""Route archetypes and aircraft scenarios, grounded in dated primary evidence."""
from __future__ import annotations

import json
from pathlib import Path

import _report
from _report import T, e, n

HERE = Path(__file__).resolve().parent


def table(heads, rows, ident):
    return (f'<div class="tw"><table id="{ident}"><thead><tr>'
            + ''.join('<th>' + e(h) + '</th>' for h in heads) + '</tr></thead><tbody>'
            + ''.join('<tr>' + ''.join('<td>' + v + '</td>' for v in row) + '</tr>' for row in rows)
            + '</tbody></table></div>')


def aircraft_demand_section(sources):
    copy = json.loads((HERE / 'out/route_aircraft_copy.json').read_text())
    evidence = json.loads((HERE / 'out/route_aircraft_evidence.json').read_text())
    for source in evidence['sources']:
        sources.url(source['url'], source['title'])
    lang = _report.LANG
    body = [f'<h2 id="route-aircraft">{e(copy["title"][lang])}</h2>',
            f'<p>{e(copy["intro"][lang])}</p>']
    body.append(table(copy['archetype_columns'][lang],
                      [[e(text) + (sources.cite(*row['sources']) if i == 2 else '')
                        for i, text in enumerate(row[lang])] for row in copy['archetypes']], 'route-archetypes'))
    for paragraph in copy['paragraphs']:
        body.append('<p>' + e(paragraph[lang]) + sources.cite(*paragraph['sources']) + '</p>')
    body += [f'<h3>{T("Как перевести прогноз потока в частоту и тип", "From traffic forecasts to frequency and aircraft", "Von Verkehrsprognosen zu Frequenz und Flugzeug")}</h3>',
             '<p class="formula">P<sub>airline,year</sub> = 2 × 52 × f<sub>week,direction</sub> × S × LF<br>'
             'f<sub>week,direction</sub> = P<sub>airline,year</sub> / (104 × S × LF)</p>',
             f'<p>{T("P — годовой поток выбранного перевозчика в обе стороны, f — число вылетов в неделю в каждом направлении, S — кресла в конкретном салоне, LF — занятость кресел. Формула использует условный год из 52 недель, одинаковое предложение в обе стороны и усреднение сезона. Это равенство предложения и перевезённых пассажиров, а не модель появления спроса. Поток всего рынка сначала нужно разделить между конкурентами и отделить местных пассажиров от стыковочных.", "P is one airline’s annual passengers in both directions, f weekly departures in each direction, S seats in the actual cabin, and LF load factor. The formula assumes a 52-week year, symmetric service and a season average. It is a capacity–passenger identity, not a model of demand creation. Market traffic must first be allocated among competitors and local passengers separated from connecting passengers.", "P ist der jährliche Verkehr einer Airline in beiden Richtungen, f sind wöchentliche Abflüge je Richtung, S Sitze der konkreten Kabine und LF die Auslastung. Angenommen werden 52 Wochen, symmetrisches Angebot und ein Saisonmittel. Dies ist eine Kapazitätsidentität, kein Modell der Nachfrageentstehung. Der Marktverkehr muss zunächst auf Wettbewerber verteilt und Lokalverkehr von Umsteigeverkehr getrennt werden.")}</p>']
    flow, load = 100000, .82
    rows = [[n(seats), n(flow / (104 * seats * load), 1)] for seats in (145, 182, 220)]
    body += ['<div class="aircraft-scenario" style="border-left:3px solid var(--guess);padding-left:12px">',
             f'<p>{T(f"Условный пример: {n(flow)} пассажиров перевозчика в год в обе стороны и занятость {n(load*100)}%. Размеры салона ниже — сценарии для сравнения частоты, не характеристики всех A220, A321 или широкофюзеляжных ВС.", f"Illustration: {n(flow)} airline passengers per year in both directions at {n(load*100)}% load factor. Cabin sizes below are frequency scenarios, not specifications shared by every A220, A321 or widebody.", f"Rechenbeispiel: {n(flow)} Airline-Passagiere pro Jahr in beiden Richtungen bei {n(load*100)}% Auslastung. Die Kabinengrößen sind Frequenzszenarien, keine gemeinsamen Eigenschaften sämtlicher A220, A321 oder Großraumflugzeuge.")}</p>',
             table([T("Кресел в сценарии", "Seats in scenario", "Sitze im Szenario"),
                    T("Вылетов в неделю в каждую сторону", "Weekly departures in each direction", "Wöchentliche Abflüge je Richtung")], rows, 'frequency-scenarios'), '</div>',
             f'<p>{T("Больший самолёт при том же потоке требует меньшей частоты. Это помогает при дефиците слотов, но может ухудшить расписание и долю рынка. Меньший тип позволяет летать чаще, однако требует больше рейсов и экипажей. Выбор нужно проверять по месяцам, доходу на пассажира, стоимости рейса, доступности самолётов и ограничениям дальности с полезной нагрузкой; годовой средний поток сам по себе не выбирает победителя.", "A larger aircraft needs fewer departures for the same traffic. That helps with slot scarcity but can weaken schedules and market share. A smaller aircraft permits higher frequency while requiring more flights and crews. The choice needs monthly demand, passenger revenue, flight cost, aircraft availability and payload–range checks; annual average traffic alone cannot select a winner.", "Ein größeres Flugzeug benötigt für denselben Verkehr weniger Abflüge. Das hilft bei Slotknappheit, kann aber Flugplan und Marktanteil schwächen. Ein kleinerer Typ erlaubt höhere Frequenz, benötigt jedoch mehr Flüge und Besatzungen. Monatsnachfrage, Passagiererlös, Flugkosten, Flottenverfügbarkeit und Nutzlast-Reichweite müssen gemeinsam geprüft werden; ein Jahresmittel bestimmt keinen Sieger.")}</p>',
             f'<p>{e(copy["conclusion"][lang])}</p>']
    return ''.join(body)
