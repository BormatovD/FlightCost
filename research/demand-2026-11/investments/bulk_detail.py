#!/usr/bin/env python3
"""0064-D: offline, bounded enrichment of already-cached IATI Bulk XML.

Reads exact, locally verified XML datasets and their existing .scan.json files.
Emits normalized *source evidence* for registry.py, not accepted projects,
financial aggregates, airport allocations, or flight demand estimates.
No HTTP, model, credentials, production DB access or third-party packages.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import xml.etree.ElementTree as ET

try:
    from . import bulk_seed
except ImportError:
    import bulk_seed

MAX_DATASETS = 3
MAX_FILE_BYTES = 25_000_000
MAX_ACTIVITY_COUNT = 5000
ACTIVITY_STATUSES = {'1', '2', '3', '4', '5', '6'}
FINANCE = {'1': 'incoming_funds', '2': 'commitment', '3': 'disbursement',
           '4': 'expenditure', '5': 'interest_payment', '6': 'loan_repayment',
           '7': 'reimbursement', '8': 'purchase_of_equity', '9': 'sale_of_equity',
           '10': 'credit_guarantee', '11': 'incoming_commitment',
           '12': 'outgoing_pledge', '13': 'incoming_pledge'}
SHA256 = re.compile(r'^[0-9a-f]{64}$')
HEX = re.compile(r'^[a-fA-F0-9]{32,64}$')


def canon(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _private(path: Path):
    if path.is_symlink():
        raise PermissionError(f'Unsafe symlink: {path}')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.stat().st_mode & 0o077:
        raise PermissionError(f'Research output directory must be private (0700): {path}')


def _atomic_write(path: Path, data: bytes):
    _private(path.parent)
    if path.is_symlink():
        raise PermissionError(f'Unsafe output symlink: {path}')
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        path.chmod(0o600)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _decimal(value):
    if value is None or not str(value).strip():
        return None
    try:
        num = Decimal(str(value).strip())
    except InvalidOperation:
        raise ValueError(f'Invalid amount (do not guess): {value!r}') from None
    if not num.is_finite():
        raise ValueError('Non-finite IATI amount')
    return str(num)


def _first(el, tag):
    return bulk_seed.direct(el, tag)


def _attr(el, attr):
    return el.get(attr) if el is not None else None


def _date(el):
    return _attr(el, 'iso-date')


def _value(block, *, fallback_currency=None):
    v = _first(block, 'value')
    return {'amount': _decimal(''.join(v.itertext()).strip()) if v is not None else None,
            'currency': (_attr(v, 'currency') or fallback_currency) if v is not None else None,
            'value_date': _attr(v, 'value-date') if v is not None else None}


def _point(loc):
    """Preserve only recognized WGS84 lat/lon. No facility-location inference."""
    point = _first(loc, 'point')
    if point is None:
        return None
    if point.get('srsName') != 'http://www.opengis.net/def/crs/EPSG/0/4326':
        return None
    pos = _first(point, 'pos')
    if pos is None or not pos.text:
        return None
    parts = pos.text.split()
    if len(parts) != 2:
        return None
    try:
        lat, lon = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    from math import isfinite
    if not all(map(isfinite, (lat, lon))) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return {'lat': lat, 'lon': lon}


def _locations(el):
    locations = []
    for l in bulk_seed.children(el, 'location'):
        ids = [{'vocabulary': _attr(i, 'vocabulary'), 'code': _attr(i, 'code')}
               for i in bulk_seed.children(l, 'location-id')]
        adm = [{'vocabulary': _attr(i, 'vocabulary'), 'code': _attr(i, 'code'),
                'level': _attr(i, 'level')} for i in bulk_seed.children(l, 'administrative')]
        locations.append({
            'name': bulk_seed.narratives(l, 'name') or None,
            'coordinates': _point(l),
            'location_class_code': _attr(_first(l, 'location-class'), 'code'),
            'exactness_code': _attr(_first(l, 'exactness'), 'code'),
            'reach_code': _attr(_first(l, 'location-reach'), 'code'),
            'location_ids': ids, 'administrative_ids': adm,
            'description': bulk_seed.narratives(l, 'description') or None,
        })
    return locations


def _transactions(el, default_currency):
    rows = []
    for tr in bulk_seed.children(el, 'transaction'):
        type_code = _attr(_first(tr, 'transaction-type'), 'code')
        d = _value(tr, fallback_currency=default_currency)
        rows.append({'kind': FINANCE.get(type_code, 'other'), 'kind_code': type_code,
                     'date': _date(_first(tr, 'transaction-date')),
                     **d})
    return rows


def _budgets(el, default_currency):
    rows = []
    for b in bulk_seed.children(el, 'budget'):
        d = _value(b, fallback_currency=default_currency)
        rows.append({'type_code': b.get('type'), 'status_code': b.get('status'),
                     'start': _date(_first(b, 'period-start')),
                     'end': _date(_first(b, 'period-end')),
                     **d})
    return rows


def extract_activity(el, *, dataset: dict, observed_at: str):
    scan = bulk_seed.activity_row(el, dataset)
    ident = scan['iati_identifier']
    if not ident:
        raise ValueError('IATI activity missing identifier: cannot merge or track variants')
    currency = el.get('default-currency')
    source_xml_sha = sha256(ET.tostring(el, encoding='utf-8'))
    # Retain structured original values; never aggregate or switch currency.
    return {
        'iati_identifier': ident,
        'source_id': 'iati_bulk:' + dataset['name'],
        'source_variant_sha256': source_xml_sha,
        'source_occurrences': 1,
        'identifier_conflict': False,
        'financial_aggregation_blocked_reason': None,
        'snapshot_at': observed_at,
        'historically_available_before_snapshot': 'unverified',
        'source_url': dataset['url'],
        'dataset_name': dataset['name'],
        'dataset_id': dataset['dataset_id'],
        'source_xml_hash': dataset['upstream_content_hash'],
        'reporting_org': scan['reporting_org'],
        'reported_last_updated_at': el.get('last-updated-datetime'),
        'title': scan['title'],
        'description': bulk_seed.narratives(el, 'description'),
        'status_code': scan['status'],
        'recipient_countries': [{'iso2': r['code'], 'share_pct': r['percentage']}
                                for r in scan['recipient_countries']],
        'sectors': [{'code': r['code'], 'vocabulary': r['vocabulary'],
                     'share_pct': r['percentage'], 'category': None}
                    for r in scan['sectors']],
        'activity_dates': [{'type_code': r['type'], 'date': r['iso_date']}
                           for r in scan['activity_dates']],
        'locations': _locations(el),
        'related_activities': scan['related_activities'],
        'transactions': _transactions(el, currency),
        'budgets': _budgets(el, currency),
        'matched_query_countries': list(scan.get('country_matches') or []),
        'notes': ['Raw IATI Bulk source; compare against original XML, not just scan JSON.',
                  'An IATI identifier is not necessarily a distinct physical project.',
                  'Commitment, disbursement, expenditure and budget are separate stages: do not add them.',
                  'A future IATI actual end date is not evidence of completed works.',
                  'Location coordinates do not necessarily identify the project site.'],
    }


def read_dataset(scanfile: Path, rawdir: Path, *, now: str, max_bytes=MAX_FILE_BYTES):
    if scanfile.is_symlink():
        raise PermissionError('Scan must not be symlinked')
    scan = json.loads(scanfile.read_text(encoding='utf-8'))
    dataset = scan['dataset']
    name = dataset['name']
    if not bulk_seed.MAX_NAME.fullmatch(name):
        raise ValueError(f'Invalid dataset name: {name!r}')
    link = bulk_seed.canonical_url(dataset['url'])
    if not HEX.fullmatch(dataset['upstream_content_hash']):
        raise ValueError('No upstream index hash')
    if not re.fullmatch(r'[a-zA-Z0-9-]{36}', dataset['dataset_id']):
        raise ValueError('Missing valid dataset UUID')
    raw = rawdir / (name + '.xml')
    cache = rawdir / (name + '.cache.json')
    for path in (raw, cache):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Required locally cached source unavailable: {path}')
    if raw.stat().st_size > max_bytes or raw.stat().st_size < 32:
        raise ValueError(f'Raw XML size outside allowed bound: {raw}')
    marker = json.loads(cache.read_text(encoding='utf-8'))
    if (marker.get('upstream_content_hash') != dataset['upstream_content_hash']
            or marker.get('url') != link
            or marker.get('dataset_id') != dataset['dataset_id']):
        raise ValueError('Cache source metadata differs from scanned source; abort')
    rawbytes = raw.read_bytes()
    if sha256(rawbytes) != marker.get('sha256'):
        raise ValueError('Raw XML hash differs from trusted local cache manifest; abort')
    if b'<!DOCTYPE' in rawbytes.upper() or b'<!ENTITY' in rawbytes.upper():
        raise ValueError('XML DTD/entities prohibited')
    rows = []
    try:
        root = ET.fromstring(rawbytes)
        for el in root.iter():
            if bulk_seed.local(el.tag) != 'iati-activity':
                continue
            rows.append(extract_activity(el, dataset=dataset, observed_at=now))
            if len(rows) > MAX_ACTIVITY_COUNT:
                raise ValueError('Too many activities in XML')
    except ET.ParseError as exc:
        raise ValueError(f'Malformed cached XML: {exc}') from exc
    if len(rows) != scan['counts']['activities']:
        raise ValueError(f'Activity count changed: {name}, {len(rows)} vs {scan["counts"]["activities"]}')
    # Validate all retained rows against scan metadata (same source revision).
    scanned = defaultdict(list)
    for row in scan['rows']:
        scanned[row['iati_identifier']].append(row)
    confirmed = set()
    for row in rows:
        country_matches = sorted(set(scan['country_filter']) & {r['iso2'] for r in row['recipient_countries']
                                                               if r['iso2']})
        if not country_matches:
            continue
        originals = scanned[row['iati_identifier']]
        if not originals:
            raise ValueError(f'{name}: {row["iati_identifier"]} missing in existing scan')
        match = any((v['title'] == row['title'] and v['status'] == row['status_code']
                     and v['reporting_org'] == row['reporting_org']) for v in originals)
        if not match:
            raise ValueError(f'{name}: metadata disagrees with scan for {row["iati_identifier"]}')
        row['matched_query_countries'] = country_matches
        confirmed.add(row['iati_identifier'])
    if confirmed != set(scanned):
        raise ValueError(f'{name}: scan/structured XML ID coverage mismatch')
    result = [r for r in rows if r['matched_query_countries']]
    return result, {'dataset': name, 'xml_activities': len(rows), 'selected_activities': len(result),
                    'source_xml_sha256': marker['sha256'], 'upstream_content_hash': dataset['upstream_content_hash'],
                    'transactions': sum(len(r['transactions']) for r in result),
                    'budgets': sum(len(r['budgets']) for r in result),
                    'reported_locations': sum(len(r['locations']) for r in result),
                    'locations_with_points': sum(x['coordinates'] is not None for r in result for x in r['locations'])}


def run(scans: list[Path], rawdir: Path, out: Path, *, observed_at: str | None = None):
    if not 1 <= len(scans) <= MAX_DATASETS:
        raise ValueError('Only 1–3 explicitly selected scan files per run')
    if out.resolve().name == 'flightcost.db':
        raise ValueError('Never write the production DB')
    if not rawdir.is_dir() or rawdir.is_symlink():
        raise ValueError('Raw directory not found or symlink')
    if len({x.name for x in scans}) != len(scans):
        raise ValueError('Repeated scan paths')
    stamp = observed_at or datetime.now(timezone.utc).isoformat(timespec='seconds')
    parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('Observation time requires timezone')
    if out.exists() and any(out.iterdir()):
        raise ValueError('Output directory already contains results; use a new run directory')
    allrows, per_source = [], []
    for scan in scans:
        rows, summary = read_dataset(scan, rawdir, now=stamp)
        allrows += rows
        per_source.append(summary)
    # Preserve distinct same-ID variants within Bulk. Do not resolve parent-child here.
    versions = defaultdict(set)
    occurrences = Counter()
    for row in allrows:
        versions[row['iati_identifier']].add(row['source_variant_sha256'])
        occurrences[(row['dataset_id'], row['iati_identifier'], row['source_variant_sha256'])] += 1
    conflicts = sorted(k for k, v in versions.items() if len(v) > 1)
    for r in allrows:
        r['identifier_conflict'] = r['iati_identifier'] in conflicts
        if r['identifier_conflict']:
            r['financial_aggregation_blocked_reason'] = 'conflicting_iati_identifier'
        r['source_occurrences'] = occurrences[(r['dataset_id'], r['iati_identifier'], r['source_variant_sha256'])]
    # Keep one row per *identical* variant; complete sightings remain in manifest.
    distinct = {(r['dataset_id'], r['iati_identifier'], r['source_variant_sha256']):r for r in allrows}
    # Note: all computed before writing output, failures leave no result files.
    _private(out)
    rows = sorted(distinct.values(), key=lambda x:(x['dataset_name'], x['iati_identifier'],x['source_variant_sha256']))
    _atomic_write(out / 'candidates.jsonl', ''.join(canon(r)+'\n' for r in rows).encode('utf-8'))
    relation_lines = [{'dataset_name': r['dataset_name'], 'source_id': r['iati_identifier'],
                       'target_id': edge.get('ref'), 'type_code': edge.get('type')}
                      for r in rows for edge in r['related_activities']]
    _atomic_write(out / 'relations.json', json.dumps(relation_lines, ensure_ascii=False, indent=2).encode('utf-8'))
    result = {'source': 'iati_bulk_by_dataset', 'observed_at': stamp, 'datasets': per_source,
              'original_records': len(allrows), 'distinct_variants': len(rows),
              'unique_identifiers': len(versions), 'conflict_identifiers': conflicts,
              'relations': len(relation_lines), 'datastore_api_calls': 0,
              'financial_aggregation_performed': False,
              'airport_assignment_performed': False,
              'note': 'Different source schemas must be linked by IATI ID, not treated as independent real-world projects.'}
    _atomic_write(out / 'manifest.json', json.dumps(result, ensure_ascii=False, indent=2).encode('utf-8'))
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--raw-dir', type=Path, required=True)
    p.add_argument('--scans', type=Path, nargs='+', required=True)
    p.add_argument('--out', type=Path, required=True)
    a=p.parse_args(argv)
    print(json.dumps(run(a.scans, a.raw_dir, a.out), ensure_ascii=False, indent=2))

if __name__=='__main__':
    main()
