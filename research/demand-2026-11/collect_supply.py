#!/usr/bin/env python3
"""Collect aircraft capacity and flight-stage traffic, separate from PAS_CRD.

Raw HTTP responses stay in an explicitly supplied directory outside the repo.
The five-country historical cohort is fixed before observing successful routes.
DBnomics is an identified archive access channel for Eurostat, not a fresh feed.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import urlencode, urlsplit, parse_qs
from urllib.request import urlopen
from urllib.error import HTTPError

HERE = Path(__file__).resolve().parent
CHECKED_ON = '2026-11-11'
REPORTERS = ('de', 'es', 'fr', 'it', 'nl')
MEASURES = {'PAS_BRD': ('pax', 'PAS'), 'ST_PAS': ('seats', 'SEAT'), 'CAF_PAS': ('flights', 'FLIGHT')}
FIELDS = ('pax', 'seats', 'flights')
MAX_BYTES = 50_000_000
PER_PAGE = 1000
DIAGNOSTICS = ('EDDF-LEBL', 'EDDL-LEPA', 'EDDF-LIMC', 'EDDF-VIDP', 'EHAM-LFRN')
PRIMARY_CASES = ('DE_EDDF_ES_LEBL', 'ES_LEBL_DE_EDDF', 'DE_EDDL_ES_LEPA',
                 'DE_EDDF_IT_LIMC', 'DE_EDDF_IN_VIDP', 'NL_EHAM_FR_LFRN', 'FR_LFRN_NL_EHAM')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    compact = path.suffix == '.gz'
    blob = (json.dumps(obj, ensure_ascii=False, allow_nan=False,
                       **({'separators': (',', ':')} if compact else {'indent': 2})) + '\n').encode()
    path.write_bytes(gzip.compress(blob, mtime=0) if compact else blob)


def fetch(raw, name, url, refresh=False):
    path = raw / (name + '.raw')
    if path.exists() and not refresh:
        return path
    try:
        response = urlopen(url, timeout=50)
    except HTTPError as err:
        response = err
    blob = response.read(MAX_BYTES + 1)
    if len(blob) > MAX_BYTES:
        raise ValueError('Response exceeds the bounded per-file budget: ' + name)
    path.write_bytes(blob)
    dump(raw / (name + '.meta.json'), {
        'url': response.url, 'status': response.status, 'retrieved_on': CHECKED_ON,
        'retrieved_at': datetime.now(timezone.utc).isoformat(),
        'content_type': response.headers.get('Content-Type'),
        'bytes': len(blob), 'sha256': hashlib.sha256(blob).hexdigest(),
    })
    if response.status != 200:
        raise ValueError(f'{name}: HTTP {response.status}; saved as an access result, not data')
    return path


def download_country(raw, cc, refresh=False):
    offset, total = 0, None
    while total is None or offset < total:
        query = {'limit': PER_PAGE, 'offset': offset, 'observations': 1,
                 'dimensions': json.dumps({'freq': ['M'], 'tra_meas': list(MEASURES)}, separators=(',', ':'))}
        url = 'https://api.db.nomics.world/v22/series/Eurostat/avia_par_' + cc + '?' + urlencode(query)
        name = f'supply_{cc}_{offset:05d}'
        d = json.loads(fetch(raw, name, url, refresh).read_bytes())
        series = d.get('series', {})
        found, docs = series.get('num_found'), series.get('docs', [])
        if found is None or not docs or (total is not None and found != total):
            raise ValueError(name + ': changed or incomplete pagination')
        total = found
        if total > 20_000:
            raise ValueError(name + ': series budget exceeded; review scope before extending')
        offset += len(docs)
        print(f'{cc}: {offset}/{total}', flush=True)


def download_primary_checks(raw, refresh=False):
    """Bounded source comparisons and recent-period availability probes."""
    requests = []
    for code in PRIMARY_CASES:
        for measure, (_, unit) in MEASURES.items():
            query = {'lang': 'EN', 'freq': 'M', 'unit': unit, 'tra_meas': measure,
                     'airp_pr': code, 'sinceTimePeriod': '2005-01'}
            requests.append((f'supply_primary_{code}_{measure}', code[:2].lower(), query))
    for cc in REPORTERS:
        requests.append((f'supply_recent_{cc}_CAF_PAS', cc,
                         {'lang': 'EN', 'freq': 'M', 'unit': 'FLIGHT', 'tra_meas': 'CAF_PAS',
                          'sinceTimePeriod': '2025-01'}))
    def check(item):
        name, cc, query = item
        url = 'https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/avia_par_' + cc + '?' + urlencode(query)
        try:
            fetch(raw, name, url, refresh)
        except (ValueError, OSError) as err:
            # HTTP failures are persisted; do not turn them into empty traffic.
            print(f'{name}: {type(err).__name__}; diagnostic access incomplete', flush=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(check, requests))


def pages(raw, cc):
    paths = sorted(raw.glob(f'supply_{cc}_[0-9][0-9][0-9][0-9][0-9].raw'))
    if not paths:
        raise ValueError('No saved pages for ' + cc)
    docs, sources, seen, expected = [], [], set(), None
    for path in paths:
        d = json.loads(path.read_bytes())
        series, dataset = d['series'], d['dataset']
        if expected is not None and series['num_found'] != expected:
            raise ValueError(cc + ': inconsistent page totals')
        expected = series['num_found']
        for s in series['docs']:
            if s['series_code'] in seen:
                raise ValueError('Duplicate series ' + s['series_code'])
            seen.add(s['series_code'])
            docs.append((s, dataset))
        meta = json.loads(path.with_suffix('.meta.json').read_text())
        sources.append({'cache_name': path.stem, 'url': meta['url'], 'http_status': meta['status'],
                        'retrieved_on': meta['retrieved_on'], 'bytes': path.stat().st_size,
                        'sha256': sha(path), 'provider': 'Eurostat', 'access_channel': 'DBnomics archive',
                        'source_updated_at': dataset.get('updated_at'),
                        'mirror_indexed_at': dataset.get('indexed_at')})
    if len(docs) != expected:
        raise ValueError(f'{cc}: got {len(docs)} series, expected {expected}')
    return docs, sources


def exclusion(pair, label, previous):
    codes = set(pair.split('-'))
    reasons = set(previous.get(pair, {}).get('reasons', []))
    if len(codes) == 1:
        reasons.add('self_pair')
    if re.search(r'\bunknown\b', label, re.I) or 'ZZZZ' in codes:
        reasons.add('unknown_airport')
    if re.search(r'\bairport system\b', label, re.I):
        reasons.add('airport_system')
    if codes & {'ENOS', 'ESMM', 'SKED', 'EDVV', 'LMMM', 'HKNA', 'LECP'}:
        reasons.add('airspace_control_area')
    if codes & {'ENCA', 'SABA', 'SCSC'}:
        reasons.add('administrative_location')
    if 'ZSSA' in codes:
        reasons.add('city_location_needs_airport_identity')
    return reasons


def number(value):
    if value in (None, 'NA', '', ':'):
        return None
    val = float(value)
    if not math.isfinite(val) or val < 0:
        raise ValueError('Unexpected negative or nonfinite observation')
    return int(val) if val.is_integer() else val


def build(raw, out):
    previous_path = HERE / 'out/eu_excluded_groups.json.gz'
    previous_obj = json.loads(gzip.decompress(previous_path.read_bytes()))
    previous = previous_obj.get('pairs', previous_obj.get('groups', {}))
    target_path = HERE / 'out/eu_monthly_panel.json.gz'
    target = json.loads(gzip.decompress(target_path.read_bytes()))
    baseline_pairs = set(target['pairs'])
    cells = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    reasons, labels = defaultdict(set), defaultdict(set)
    sources, country_info, missing = [], {}, Counter()
    geography = defaultdict(lambda: defaultdict(set))
    measurement_series = Counter()
    for cc in REPORTERS:
        docs, src = pages(raw, cc)
        sources.extend(src)
        country_info[cc.upper()] = {'series': len(docs), 'source_updated_at': src[0]['source_updated_at'],
                                   'mirror_indexed_at': src[0]['mirror_indexed_at']}
        for s, ds in docs:
            dims = s['dimensions']
            measure = dims['tra_meas']
            if dims['freq'] != 'M' or measure not in MEASURES or dims['unit'] != MEASURES[measure][1]:
                raise ValueError('Unexpected dimension/measure/unit combination')
            field = MEASURES[measure][0]
            measurement_series[measure] += 1
            m = re.fullmatch(r'([A-Z]{2})_([A-Z0-9]{4})_([A-Z]{2})_([A-Z0-9]{4})', dims['airp_pr'])
            if not m:
                raise ValueError('Unknown airport-pair coding')
            reporter, other = m.group(2), m.group(4)
            pair = '-'.join(sorted((reporter, other)))
            label = ds['dimensions_values_labels']['airp_pr'][dims['airp_pr']]
            labels[pair].add(label)
            reasons[pair].update(exclusion(pair, label, previous))
            geography[pair][reporter].add(m.group(1))
            geography[pair][other].add(m.group(3))
            flags = {}
            for key, values in s.get('observations_attributes', []):
                if key == 'OBS_FLAG':
                    values = values if isinstance(values, list) else [values] * len(s['period'])
                    if len(values) != len(s['period']):
                        raise ValueError('Flag count mismatch')
                    flags = dict(zip(s['period'], values))
            if len(s['period']) != len(s['value']):
                raise ValueError('Period count mismatch')
            for month, val in zip(s['period'], s['value']):
                if month < '2005-01' or month > CHECKED_ON[:7]:
                    continue
                val = number(val)
                if val is None:
                    missing[measure] += 1
                    continue
                row = cells[pair][month][reporter]
                if field in row and row[field] != val:
                    raise ValueError(f'Conflicting reporter metric: {pair} {month} {reporter} {field}')
                row[field] = val
                if flags.get(month):
                    row.setdefault('flags', set()).add(field + ':' + str(flags[month]))

    reporter_panel, pair_panel, excluded = {}, {}, {}
    totals, quality, year_counts = Counter(), Counter(), defaultdict(Counter)
    excluded_reasons = Counter()
    paired_years = defaultdict(lambda: defaultdict(list))
    diagnostic_reporters = {}
    for pair, months in sorted(cells.items()):
        reports, derived = [], []
        for month, by_reporter in sorted(months.items()):
            flags = set()
            for reporter, fields in sorted(by_reporter.items()):
                flags.update(fields.get('flags', set()))
                reports.append([month, reporter, *[fields.get(f) for f in FIELDS],
                                ';'.join(sorted(fields.get('flags', set()))) or None])
            complete = sorted(r for r, fs in by_reporter.items() if all(f in fs for f in FIELDS))
            # All three numerator/denominator means use exactly the same reporters.
            means = [sum(by_reporter[r][f] for r in complete) / len(complete) for f in FIELDS] if complete else [None] * 3
            pax, seats, flights = means
            lf = pax / seats if seats and pax is not None else None
            gauge = seats / flights if flights and seats is not None else None
            consistency = []
            if complete and (seats == 0 and pax > 0 or flights == 0 and (seats > 0 or pax > 0)):
                consistency.append('positive_activity_with_zero_capacity_or_flights')
            if lf is not None and lf > 1:
                consistency.append('passengers_exceed_available_seats')
            spreads = []
            for field in FIELDS:
                vals = [fields[field] for fields in by_reporter.values() if field in fields]
                avg = sum(vals) / len(vals) if vals else 0
                spreads.append((max(vals) - min(vals)) / avg if vals and avg else 0.0)
            if any(spread > .1 for spread in spreads):
                consistency.append('reporter_disagreement_above_10pct')
            derived.append([month, *means, round(lf, 6) if lf is not None else None,
                            round(gauge, 6) if gauge is not None else None,
                            ';'.join(complete) or None, ';'.join(sorted(flags)) or None,
                            ';'.join(consistency) or None])
            if not reasons[pair]:
                totals['pair_months_any_measure'] += 1
                year_counts[month[:4]]['pair_months_any_measure'] += 1
                if complete:
                    totals['pair_months_matched_triplet'] += 1
                    year_counts[month[:4]]['pair_months_matched_triplet'] += 1
                    paired_years[pair][month[:4]].append(means)
                    quality['one_common_reporter' if len(complete) == 1 else 'two_common_reporters'] += 1
                else:
                    quality['no_complete_common_reporter'] += 1
                for flag in consistency:
                    quality[flag] += 1
                if flags:
                    quality['source_quality_flag_present'] += 1
        if reasons[pair]:
            excluded[pair] = {'reasons': sorted(reasons[pair]), 'source_labels': sorted(labels[pair]), 'reporter_rows': reports}
            excluded_reasons.update(reasons[pair])
        else:
            reporter_panel[pair] = reports
            pair_panel[pair] = derived
            totals['reporter_month_rows'] += len(reports)
            for row in reports:
                for i, field in enumerate(FIELDS, 2):
                    if row[i] is not None:
                        totals[field + '_reporter_values'] += 1
            if pair in DIAGNOSTICS:
                diagnostic_reporters[pair] = sorted({r[1] for r in reports})

    annual_examples = {}
    for pair in DIAGNOSTICS:
        annual_examples[pair] = {}
        for year, rows in sorted(paired_years.get(pair, {}).items()):
            if len(rows) == 12:
                p, s, f = [sum(row[k] for row in rows) for k in range(3)]
                annual_examples[pair][year] = {'months': 12, 'pax_brd': p, 'seats': s, 'flights': f,
                    'seat_load_factor': p / s if s else None,
                    'seats_per_flight': s / f if f else None,
                    'definition': 'flight-stage, all three metrics from common reporters per month'}

    full_year_counts = Counter()
    for pair, years in paired_years.items():
        for year, rows in years.items():
            if len(rows) == 12:
                full_year_counts[year] += 1
    for year, count in full_year_counts.items():
        year_counts[year]['pairs_with_12_matched_months'] = count
    valid_pairs = set(pair_panel)
    months = [r[0] for rows in pair_panel.values() for r in rows]
    baseline_months = {pair: {row[0] for row in target['pairs'][pair]} for pair in valid_pairs & baseline_pairs}
    joined = sum(row[0] in baseline_months[pair] for pair in baseline_months for row in pair_panel[pair])
    common_meta = {'schema_version': 1, 'checked_on': CHECKED_ON, 'source_family': 'Eurostat avia_par_*',
                  'access_channel': 'DBnomics historical archive', 'reporting_country_cohort': list(REPORTERS),
                  'period_filter': ['2005-01', CHECKED_ON[:7]], 'sources': sources,
                  'directions': 'arrival plus departure at each reporting airport; counterpart reports never summed',
                  'missing_policy': 'missing remains missing; explicit source zero retained; no interpolation',
                  'excluded': 'administrative, unknown, system and unresolved airport identities are stored separately'}
    dump(out / 'supply_reporter_panel.json.gz', {**common_meta,
        'columns': ['month', 'reporting_airport', 'passengers_on_board', 'seats_available', 'commercial_passenger_flights', 'source_flags'],
        'units': {'passengers_on_board': 'persons', 'seats_available': 'seats', 'commercial_passenger_flights': 'flights'},
        'measurement_codes': {'passengers_on_board': 'PAS_BRD', 'seats_available': 'ST_PAS', 'commercial_passenger_flights': 'CAF_PAS'},
        'pairs': reporter_panel})
    dump(out / 'supply_pair_panel.json.gz', {**common_meta,
        'columns': ['month', 'pax_brd_mean_common_reporters', 'seats_mean_common_reporters', 'flights_mean_common_reporters',
                    'seat_load_factor_matched', 'seats_per_flight_matched', 'common_reporters', 'source_flags_union', 'consistency_flags'],
        'aggregation': 'arithmetic means over the identical intersection of reporters with all three measures',
        'ratio_policy': 'ratio of matched means; zero denominator gives null; suspect ratios retained with flags',
        'not_a_demand_measure': 'PAS_BRD/ST_PAS is realized seat occupancy, not latent demand or airline market share',
        'pairs': pair_panel})
    dump(out / 'supply_excluded_groups.json.gz', {**common_meta, 'groups': excluded})
    access_probes = []
    for name in ('supply_probe_direct_de', 'supply_direct_de_flights',
                 *(f'supply_recent_{cc}_CAF_PAS' for cc in REPORTERS)):
        file = raw / (name + '.raw')
        meta = raw / (name + '.meta.json')
        if file.exists() and meta.exists():
            d = json.loads(meta.read_text())
            try:
                response = json.loads(file.read_bytes())
                state = 'valid_primary_json_stat' if response.get('class') == 'dataset' else 'not_dataset'
                last = max(response.get('dimension', {}).get('time', {}).get('category', {}).get('index', {}), default=None)
                error = response.get('error')
            except ValueError:
                state, last, error = 'non_json_response', None, None
            access_probes.append({**d, 'classification': state, 'last_time_axis_period': last,
                                  'published_values': len(response.get('value', {})) if state == 'valid_primary_json_stat' else None,
                                  'source_updated_at': response.get('updated') if state == 'valid_primary_json_stat' else None,
                                  'error': error})
    primary_comparisons = []
    for file in sorted(raw.glob('supply_primary_*.raw')):
        meta = json.loads(file.with_suffix('.meta.json').read_text())
        response = json.loads(file.read_bytes())
        if response.get('class') != 'dataset':
            primary_comparisons.append({**meta, 'status': 'not_a_dataset', 'error': response.get('error')})
            continue
        dims = response['dimension']
        measure = next(iter(dims['tra_meas']['category']['index']))
        unit = next(iter(dims['unit']['category']['index']))
        if measure not in MEASURES or unit != MEASURES[measure][1]:
            raise ValueError('Primary diagnostic dimension mismatch')
        field = MEASURES[measure][0]
        code = parse_qs(urlsplit(meta['url']).query)['airp_pr'][0]
        source_codes = dims['airp_pr']['category']['index']
        if source_codes and list(source_codes) != [code]:
            raise ValueError('Primary diagnostic airport mismatch')
        cc1, reporter, cc2, other = code.split('_')
        pair = '-'.join(sorted((reporter, other)))
        times = {idx: period for period, idx in dims['time']['category']['index'].items()}
        if response.get('value') and (response['id'][-1] != 'time' or any(size != 1 for size in response['size'][:-1])):
            raise ValueError('Primary diagnostic is not a singleton airport/metric series')
        checked, errors, published_months = 0, [], []
        for index, value in response.get('value', {}).items():
            month = times[int(index)]
            if month < '2005-01' or month > CHECKED_ON[:7]:
                continue
            actual = cells.get(pair, {}).get(month, {}).get(reporter, {}).get(field)
            if actual != value:
                errors.append({'month': month, 'primary': value, 'archive': actual})
            checked += 1
            published_months.append(month)
        if errors:
            raise ValueError(f'Primary/archived disagreement: {pair} {measure} {errors[:3]}')
        primary_comparisons.append({**meta, 'status': 'matched_primary' if checked else 'no_published_values', 'pair': pair,
            'reporting_airport': reporter, 'measure': measure, 'checked_values': checked,
            'source_updated_at': response.get('updated'), 'first_month': min(published_months, default=None),
            'last_month': max(published_months, default=None), 'disagreements': errors})
    summary = {'schema_version': 1, 'checked_on': CHECKED_ON, 'status': 'collected_archive',
        'scope': 'All monthly flight-stage series in five fixed reporting countries; no survivor or minimum-traffic filtering',
        'series': dict(measurement_series), 'reporting_countries': country_info,
        'pairs': len(valid_pairs), 'first_month': min(months), 'last_month': max(months), **dict(totals),
        'overlap_with_pas_crd_panel': {'baseline_pairs': len(baseline_pairs), 'pairs_with_both_datasets': len(valid_pairs & baseline_pairs),
                                     'supply_pairs_not_in_baseline': len(valid_pairs - baseline_pairs),
                                     'baseline_pairs_without_supply': len(baseline_pairs - valid_pairs), 'matching_pair_month_keys': joined,
                                     'meaning': 'key alignment only; PAS_CRD and PAS_BRD are different quantities'},
        'excluded_groups': len(excluded), 'excluded_reason_counts': dict(excluded_reasons),
        'source_missing_values': dict(missing), 'quality': dict(quality),
        'year_coverage': dict(sorted((year, dict(counts)) for year, counts in year_counts.items())),
        'diagnostic_annual': annual_examples, 'diagnostic_reporting_airports': diagnostic_reporters,
        'sources': sources, 'primary_access_probes': access_probes,
        'primary_comparisons': primary_comparisons,
        'inputs_sha256': {'baseline_pas_crd_panel': sha(target_path), 'baseline_excluded_groups': sha(previous_path)},
        'limitations': [
            'Historical archive ends at its source horizon; retrieval in 2026 is not 2026 traffic.',
            'PAS_BRD includes direct transit on a flight stage; it does not equal PAS_CRD on-flight origin/destination.',
            'Seat load factor uses only matched flight-stage passenger, seat and flight reports, never PAS_CRD divided by seats.',
            'Common-reporting sets may change by month. Reporter differences and statistical breaks are preserved for modelling.',
            'Realized occupancy does not identify suppressed demand or causal effects of capacity and frequency.',
            'Aircraft type, operator identity, fares, actual departures by direction and timetable timings are absent from this aggregate panel.',
            'Historical airport and country codes still require longitudinal reconciliation.',
        ]}
    artifacts = []
    for path in sorted(out.glob('supply*.json.gz')):
        artifacts.append({'file': path.name, 'bytes': path.stat().st_size, 'sha256': sha(path)})
    summary['artifacts'] = artifacts
    dump(out / 'supply_summary.json', summary)
    print(json.dumps({k: summary[k] for k in ('pairs', 'pair_months_any_measure', 'pair_months_matched_triplet', 'reporter_month_rows', 'first_month', 'last_month', 'overlap_with_pas_crd_panel')}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-dir', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=HERE / 'out')
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    if args.raw_dir.resolve().is_relative_to(HERE.parents[1]):
        raise SystemExit('Raw downloads must stay outside the repository')
    args.raw_dir.mkdir(parents=True, exist_ok=True)
    if args.fetch:
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda cc: download_country(args.raw_dir, cc, args.refresh), REPORTERS))
        download_primary_checks(args.raw_dir, args.refresh)
    build(args.raw_dir, args.out)


if __name__ == '__main__':
    main()
