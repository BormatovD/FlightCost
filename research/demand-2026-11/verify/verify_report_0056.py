#!/usr/bin/env python3
"""Independent numerical/content audit of the extended multilingual report.

Only lxml is required. This does not claim a browser or screenshot layout check.
The source-data audit is separately recorded in demand_collection_0056.json.
"""
from collections import Counter
import copy
import gzip
import hashlib
import json
from pathlib import Path
from lxml import html

HERE = Path(__file__).resolve().parent


def read(path):
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == '.gz' else data)


def plain(node):
    node = copy.deepcopy(node)
    for sup in node.xpath('.//sup'):
        sup.getparent().remove(sup)
    return ' '.join(node.text_content().split())


def fmt(value, lang):
    return f'{value:,.0f}'.replace(',', ' ' if lang == 'ru' else '.' if lang == 'de' else ',')


def main():
    summary = read(HERE.parent / 'out/collection_summary.json')
    panel = read(HERE.parent / 'out/eu_monthly_panel.json.gz')['pairs']
    eu = summary['eu_routes']
    annual = {}
    for year in range(2005, 2025):
        rows = [r for r in panel['EDDF-LEBL'] if r[0].startswith(str(year) + '-')]
        if len(rows) == 12:
            annual[year] = sum(r[1] for r in rows) / 1000
    examples = ('EDDF-LEBL', 'EDDL-LEPA', 'EDDF-LIMC', 'EDDF-VIDP', 'EHAM-LFRN')
    failures = []
    checks = []
    for lang, name in [('ru', 'report.html'), ('en', 'report.en.html'), ('de', 'report.de.html')]:
        path = HERE.parent / name
        doc = html.fromstring(path.read_text())
        tables = [[[plain(c) for c in r.xpath('./td|./th')] for r in t.xpath('.//tr')]
                  for t in doc.xpath('//table')]
        datasets = [('eu_routes', 'first_month', 'last_month', 'pair_months'),
                    ('india_domestic', 'first_period', 'last_period', 'usable_pair_periods'),
                    ('india_international', 'first_period', 'last_period', 'usable_pair_periods')]
        for row, (key, first, last, count) in zip(tables[0][1:], datasets):
            source = summary[key]
            if row[1] != source[first] + '–' + source[last]:
                failures.append({'language': lang, 'problem': 'dataset period', 'dataset': key})
            if not all(fmt(v, lang) in row[2] for v in (source['pairs'], source[count])):
                failures.append({'language': lang, 'problem': 'dataset counts', 'dataset': key})
        for row, key in zip(tables[1][1:], ('gdp', 'pop', 'emp', 'nights')):
            source = summary['regional'][key]
            wanted = [source['first_period'] + '–' + source['last_period'],
                      fmt(source['regions'], lang), fmt(source['observations'], lang)]
            if row[1:] != wanted:
                failures.append({'language': lang, 'problem': 'regional coverage table', 'feature': key, 'actual': row})
        for row, h in zip(tables[2][1:], ('3', '5', '10')):
            source = eu['readiness']['horizons'][h]
            years = [r['origin_year'] for r in source['origins']]
            wanted = [h, str(2026 + int(h)), f'{min(years)}–{max(years)}',
                      str(len(years)), fmt(source['sum_complete_pair_targets'], lang)]
            if row != wanted:
                failures.append({'language': lang, 'problem': 'horizon readiness', 'horizon': h})
        coverage = summary['scenario_inputs']['coverage_by_source_variant_year']
        for row, year in zip(tables[3][1:], ('2029', '2031', '2036')):
            if row[0] != year or str(coverage['WPP_Medium'][year]) not in row[1]:
                failures.append({'language': lang, 'problem': 'external scenario population coverage', 'year': year})
            if year != '2036' and str(coverage['WEO_NGDP_RPCH'][year]) not in row[2]:
                failures.append({'language': lang, 'problem': 'external scenario GDP coverage', 'year': year})
        route_totals = {}
        for row, code in zip(tables[4][1:], examples):
            months = [r for r in panel[code] if r[0].startswith('2024-')]
            total = sum(r[1] for r in months)
            route_totals[code] = total
            if len(months) != 12 or code not in row[0] or row[1] != fmt(total, lang):
                failures.append({'language': lang, 'problem': 'diagnostic route total', 'pair': code})

        # Recover affine axes from the rendered coordinates independently of
        # _report.line_chart. Tick labels must agree within their whole-unit rounding.
        svg = doc.xpath('//svg')[0]
        points = [tuple(map(float, p.split(','))) for p in svg.xpath('.//polyline')[0].get('points').split()]
        values = list(annual.values())
        years = list(annual)
        if len(points) != len(values):
            failures.append({'language': lang, 'problem': 'historical chart point count'})
        else:
            mv = sum(values) / len(values)
            my = sum(y for x, y in points) / len(points)
            slope = sum((v-mv)*(y-my) for v,(x,y) in zip(values,points)) / sum((v-mv)**2 for v in values)
            intercept = my - slope * mv
            y_error = max(abs(y - (intercept + slope*v)) for v,(x,y) in zip(values, points))
            x_ticks = [(int(plain(t)), float(t.get('x'))) for t in svg.xpath('.//text[@text-anchor="middle"]') if plain(t).isdigit()]
            first_year, first_x = min(x_ticks)
            last_year, last_x = max(x_ticks)
            x_error = max(abs(x - (first_x + (year-first_year)/(last_year-first_year)*(last_x-first_x))) for year,(x,y) in zip(years,points))
            for tick in svg.xpath('.//text[@text-anchor="end"]'):
                label = plain(tick).replace(' ', '').replace('\u00a0', '')
                label = label.replace('.', '').replace(',', '.') if lang == 'de' else label.replace(',', '') if lang == 'en' else label.replace(',', '.')
                implied = (float(tick.get('y')) - 4 - intercept) / slope
                if abs(float(label) - implied) > .7:
                    failures.append({'language': lang, 'problem': 'historical chart axis disagrees with observed values'})
            if y_error > .08 or x_error > .051 or slope >= 0:
                failures.append({'language': lang, 'problem': 'historical chart geometry', 'max_x_px': x_error, 'max_y_px': y_error})
        ids = doc.xpath('//*[@id]/@id')
        duplicates = [key for key,value in Counter(ids).items() if value > 1]
        broken = [u for u in doc.xpath('//a[starts-with(@href,"#")]/@href') if u[1:] not in ids]
        if duplicates or broken:
            failures.append({'language': lang, 'problem': 'internal links', 'duplicates': duplicates, 'broken': broken})
        details = doc.xpath('//details')[0]
        if details.get('open') is not None or len(details.xpath('.//table')) != 6:
            failures.append({'language': lang, 'problem': 'initial experiment disclosure not retained/collapsed'})
        checks.append({'language': lang, 'file': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                       'new_data_tables_checked': 5, 'route_2024_totals': route_totals,
                       'historical_chart_years': years, 'historical_chart_points': len(points),
                       'maximum_chart_fit_error_px': y_error, 'broken_internal_links': broken,
                       'initial_experiment_preserved_in_closed_details': True})
    report = {'stage': '0056', 'status': 'pass' if not failures else 'fail',
              'scope': 'Multilingual content, table and SVG data verification; not a browser screenshot layout audit.',
              'summary_sha256': hashlib.sha256((HERE.parent / 'out/collection_summary.json').read_bytes()).hexdigest(),
              'checks': checks, 'failures': failures,
              'manual_semantic_review': [
                  'Eurostat remains the statistical provider and DBnomics the dated access channel; five reporters do not cover all Europe.',
                  'PAS_CRD is observed on-flight origin/destination, not unconstrained city demand or complete transfer journeys.',
                  'The source is city-pair data for India; quarterly observations are not interpolated into months.',
                  'The coverage table is not a fitted 3/5/10-year accuracy result; five training years and overlapping origins are stated.',
                  'Pair eligibility precedes target availability checks; missing rows are not treated as zero.',
                  'Current revisions are distinguished from historical publication vintages and the 2024-to-2026 nowcast gap is explicit.',
                  'WPP Low/High are demographic variants rather than passenger confidence bounds; IMF data are not extrapolated to 2036.',
                  'Regional PPS, NUTS boundaries, M_N aggregation and incomplete current-year coverage remain qualifications.',
                  'Visa snapshot date is not legal effective date and departure country does not identify passport citizenship.',
                  'Market profiles and aircraft candidates are hypotheses, not route-opening recommendations or fitted future passenger forecasts.',
                  'Monthly symmetric two-way passenger-to-frequency and block-hour identities are dimensionally correct; scheduling and asymmetry constraints are stated.'
              ],
              'limits': ['DGCA original publication tables were not independently matched; the Vonter public transcription and its complete normalization were checked.',
                         'Historical airport IDs and geographic boundary harmonization remain work for modelling; these are collected data, not production-ready forecast inputs.']}
    (HERE / 'review_0056.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(report['status'], json.dumps(failures, ensure_ascii=False))


if __name__ == '__main__':
    main()
