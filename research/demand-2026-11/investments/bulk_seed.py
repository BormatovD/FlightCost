#!/usr/bin/env python3
"""0064-C: bounded, explicit IATI Bulk XML seeds with offline XML activity indexes.

No Datastore calls, keys, geocoding, financial aggregation or production changes.
Nothing is downloaded unless --download is explicitly supplied; exact dataset names
are mandatory because the minimal global index lacks country/sector metadata.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
import xml.etree.ElementTree as ET

try:
    from .catalogue import entries
except ImportError:
    from catalogue import entries

BULK_HOST = 'bulk-data.iatistandard.org'
MAX_NAME = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}$')
# DAC 5-digit vocabulary=1. This is an *analysis lens*, not a global IATI filter.
WATCH_SECTORS = frozenset({'21010', '21020', '21030', '21040', '21050', '21061',
                           '23030', '32110', '32120', '32210', '33210', '33220'})


def canonical_url(raw: str) -> str:
    """Only official cached XML, never arbitrary source/publisher URLs."""
    p = urlsplit(raw or '')
    if (p.scheme != 'https' or p.hostname != BULK_HOST or p.port not in (None, 443)
            or p.username or p.password or p.query or p.fragment
            or not p.path.endswith('.xml') or '..' in p.path or '\\' in p.path):
        raise ValueError(f'Non-canonical IATI Bulk XML URL (not fetched): {raw!r}')
    return raw


def name_list(text: str) -> list[str]:
    names = [x.strip() for x in text.split(',') if x.strip()]
    if not names or len(set(names)) != len(names):
        raise ValueError('Pass unique exact dataset short_names using --names')
    if any(not MAX_NAME.fullmatch(n) for n in names):
        raise ValueError('Dataset names must be plain safe identifiers')
    return names


def select(index: dict, names: list[str]) -> list[dict]:
    catalogue = {}
    for row in entries(index):
        short = row.get('short_name')
        if short in catalogue:
            raise ValueError(f'Duplicate short_name in IATI index: {short}')
        if short:
            catalogue[short] = row
    missing = sorted(set(names) - catalogue.keys())
    if missing:
        raise ValueError(f'Unknown exact dataset short_names: {missing}; no guessing')
    result = []
    for name in names:
        row = catalogue[name]
        meta = row.get('last_known_good_dataset') or {}
        link = canonical_url(meta.get('cached_dataset_url_xml') or meta.get('cached_dataset_xml_url'))
        version = meta.get('hash_excluding_generated_timestamp') or meta.get('hash')
        if not isinstance(version, str) or not re.fullmatch(r'[a-fA-F0-9]{32,64}', version):
            raise ValueError(f'{name}: missing structured content hash')
        result.append({'name': name, 'dataset_id': row['id'],
                       'publisher': row.get('reporting_org_short_name'),
                       'url': link, 'upstream_content_hash': version,
                       'verified_on_server': meta.get('verified_on_server')})
    return result


def _private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise PermissionError(f'Research directory must be private (0700): {path}')


def _atomic_bytes(path: Path, content: bytes) -> None:
    _private_dir(path.parent)
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _read_cache(path: Path) -> dict:
    if path.is_symlink():
        raise PermissionError(f'Unsafe symlink cache file: {path}')
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


class BulkOnlyRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        canonical_url(newurl)  # refuse redirects outside the official cache host
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def stream_download(url: str, dst: Path, *, max_bytes: int, opener=None) -> dict:
    """Read at most max_bytes+1 over network; never publish truncated XML."""
    canonical_url(url)
    if max_bytes < 1024:
        raise ValueError('max_bytes too small for a useful IATI XML dataset')
    _private_dir(dst.parent)
    if dst.is_symlink():
        raise PermissionError('Refusing to overwrite a symlink')
    opener = opener or build_opener(BulkOnlyRedirect()).open
    req = Request(url, headers={'Accept': 'application/xml, text/xml',
                                'User-Agent': 'FlightCost/0064-C (https://flightcost.app)'})
    fd, temporary = tempfile.mkstemp(prefix='.bulk-', suffix='.part', dir=dst.parent)
    total = 0
    digest = hashlib.sha256()
    try:
        with os.fdopen(fd, 'wb') as out, opener(req, timeout=60) as resp:
            canonical_url(resp.geturl())
            declared = resp.headers.get('Content-Length') if resp.headers else None
            if declared is not None and int(declared) > max_bytes:
                raise ValueError(f'IATI XML exceeds per-file cap (declared {declared} bytes)')
            while True:
                buf = resp.read(min(256 * 1024, max_bytes + 1 - total))
                if not buf:
                    break
                total += len(buf)
                if total > max_bytes:
                    raise ValueError('IATI XML exceeds per-file cap (stream); source not saved')
                digest.update(buf)
                out.write(buf)
            out.flush()
            os.fsync(out.fileno())
        if total == 0:
            raise ValueError('IATI XML is empty')
        # Quick gate before replacing cached data; complete XML validated during scan.
        with open(temporary, 'rb') as test:
            head = test.read(4096)
        if b'<!DOCTYPE' in head.upper() or b'<!ENTITY' in head.upper():
            raise ValueError('XML DTD/entities prohibited in 0064-C research scanner')
        os.replace(temporary, dst)
        os.chmod(dst, 0o600)
        return {'bytes': total, 'sha256': digest.hexdigest()}
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def local(tag: str) -> str:
    return tag.rsplit('}', 1)[-1]


def children(el, wanted):
    return [x for x in el if local(x.tag) == wanted]


def direct(el, wanted):
    return next((x for x in el if local(x.tag) == wanted), None)


def narratives(parent, wanted) -> str:
    obj = direct(parent, wanted)
    if obj is None:
        return ''
    parts = [''.join(x.itertext()).strip() for x in obj if local(x.tag) == 'narrative']
    return next((s for s in parts if s), '') or ''.join(obj.itertext()).strip()


def activity_row(el: ET.Element, dataset: dict) -> dict:
    identity = direct(el, 'iati-identifier')
    status = direct(el, 'activity-status')
    org = direct(el, 'reporting-org')
    sectors = [{'vocabulary': s.get('vocabulary'), 'code': s.get('code'),
                'percentage': s.get('percentage')} for s in children(el, 'sector')]
    countries = [{'code': c.get('code'), 'percentage': c.get('percentage')}
                 for c in children(el, 'recipient-country')]
    dates = [{'type': d.get('type'), 'iso_date': d.get('iso-date')}
             for d in children(el, 'activity-date')]
    related = [{'ref': s.get('ref'), 'type': s.get('type')}
               for s in children(el, 'related-activity')]
    locations = []
    for l in children(el, 'location'):
        cl = direct(l, 'location-class')
        reach = direct(l, 'location-reach')
        exact = direct(l, 'exactness')
        locations.append({'name': narratives(l, 'name'),
                          'class': cl.get('code') if cl is not None else None,
                          'reach': reach.get('code') if reach is not None else None,
                          'exactness': exact.get('code') if exact is not None else None})
    return {'iati_identifier': (identity.text or '').strip() if identity is not None else '',
            'dataset_name': dataset['name'], 'dataset_id': dataset['dataset_id'],
            'reporting_org': org.get('ref') if org is not None else None,
            'title': narratives(el, 'title'), 'status': status.get('code') if status is not None else None,
            'recipient_countries': countries, 'sectors': sectors,
            'activity_dates': dates, 'locations': locations, 'related_activities': related}


def scan_file(path: Path, dataset: dict, *, countries: set[str], max_rows: int = 2_000_000) -> dict:
    """IATI XML iterparse. Keep matching summaries; never guess a missing country."""
    if path.is_symlink():
        raise PermissionError('Refuse to parse a symlinked XML file')
    counts = Counter()
    selected: list[dict] = []
    seen_ids = set()
    try:
        iterator = ET.iterparse(path, events=('start', 'end'))
        root = None
        for event, el in iterator:
            if event == 'start' and root is None:
                root = el
            if event == 'end' and local(el.tag) == 'iati-activity':
                counts['activities'] += 1
                if counts['activities'] > max_rows:
                    raise ValueError('XML has too many activity rows for capped research scan')
                row = activity_row(el, dataset)
                if not row['iati_identifier']:
                    counts['missing_iati_identifier'] += 1
                if row['iati_identifier'] in seen_ids:
                    counts['repeated_iati_identifier'] += 1
                seen_ids.add(row['iati_identifier'])
                hits = countries & {c['code'] for c in row['recipient_countries'] if c.get('code')}
                if not row['recipient_countries']:
                    counts['missing_recipient_country'] += 1
                if hits:
                    counts['matching_country'] += 1
                    row['country_matches'] = sorted(hits)
                    row['watch_sector_match'] = any(
                        s['vocabulary'] == '1' and s['code'] in WATCH_SECTORS
                        for s in row['sectors'])
                    if row['watch_sector_match']:
                        counts['matching_watch_sector'] += 1
                    selected.append(row)
                el.clear()
                if root is not None:
                    root.clear()
        return {'dataset': dataset, 'counts': dict(counts), 'country_filter': sorted(countries),
                'rows': selected, 'scanned_at': datetime.now(timezone.utc).isoformat()}
    except ET.ParseError as exc:
        raise ValueError(f'Malformed IATI source XML, not accepted: {exc}') from exc


def run(index_path: Path, out: Path, names: list[str], *,
        download: bool = False, countries: set[str] | None = None,
        max_files: int = 3, max_file_bytes: int = 25_000_000,
        max_total_bytes: int = 60_000_000, opener=None) -> dict:
    # Absolute path, explicit allowlist and small hard caps; no automatic world crawl.
    if not 1 <= len(names) <= max_files <= 8:
        raise ValueError(f'Choose 1–{min(max_files, 8)} exact dataset names for this run')
    if not 100_000 <= max_file_bytes <= 50_000_000:
        raise ValueError('Per-file maximum must be between 100 KB and 50 MB')
    if not max_file_bytes <= max_total_bytes <= 150_000_000:
        raise ValueError('Total transfer cap must be between per-file cap and 150 MB')
    if out.name == 'flightcost.db' or out.resolve() == Path('data/flightcost.db').resolve():
        raise ValueError('Cannot write production data')
    index = json.loads(index_path.read_text(encoding='utf-8'))
    chosen = select(index, names)
    plan = {'index': str(index_path), 'explicit_datasets': chosen,
            'network_requested': download, 'datastore_calls': 0,
            'guaranteed_country_coverage': False,
            'note': 'Publisher file names are selection hints, not authoritative recipient countries.'}
    if not download:
        return plan
    _private_dir(out)
    raw = out / 'raw'
    _private_dir(raw)
    consumed = 0
    results = []
    for d in chosen:
        name = d['name']
        file = raw / (name + '.xml')
        marker = raw / (name + '.cache.json')
        prev = _read_cache(marker)
        if (file.exists() and not file.is_symlink() and file.stat().st_size
                and prev.get('upstream_content_hash') == d['upstream_content_hash']
                and hashlib.sha256(file.read_bytes()).hexdigest() == prev.get('sha256')):
            download_status = 'unchanged_cache'
            used = {'bytes': file.stat().st_size, 'sha256': prev['sha256']}
        else:
            quota = min(max_file_bytes, max_total_bytes - consumed)
            if quota < 100_000:
                raise ValueError('Total byte budget reached; remaining datasets not requested')
            used = stream_download(d['url'], file, max_bytes=quota, opener=opener)
            consumed += used['bytes']
            download_status = 'downloaded'
            _atomic_bytes(marker, json.dumps({**d, **used}, indent=2).encode('utf-8'))
        summary = scan_file(file, d, countries=countries or {'KE', 'TZ', 'MA', 'CV'})
        rec = {'dataset_name': name, 'status': download_status, 'local_sha256': used['sha256'],
               'local_bytes': used['bytes'], 'activities': summary['counts'].get('activities', 0),
               'matching_country': summary['counts'].get('matching_country', 0),
               'matching_watch_sector': summary['counts'].get('matching_watch_sector', 0)}
        # Only write after complete and verified XML scan.
        _atomic_bytes(out / (name + '.scan.json'), json.dumps(summary, ensure_ascii=False).encode('utf-8'))
        results.append(rec)
    return {**plan, 'downloads_this_run': len([x for x in results if x['status'] == 'downloaded']),
            'bytes_transferred': consumed, 'results': results}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--index', type=Path, required=True, help='locally cached datasets-minimal.json')
    ap.add_argument('--out', type=Path, required=True, help='private research output folder')
    ap.add_argument('--names', required=True, help='comma-separated, EXACT index short_name values')
    ap.add_argument('--countries', default='KE,TZ,MA,CV', help='recipient-country codes; NOT publisher filename')
    ap.add_argument('--download', action='store_true', help='explicit opt-in to at most 3 bounded public XML downloads')
    ap.add_argument('--max-files', type=int, default=3)
    ap.add_argument('--max-file-bytes', type=int, default=25_000_000)
    ap.add_argument('--max-total-bytes', type=int, default=60_000_000)
    a = ap.parse_args(argv)
    cc = {c.strip().upper() for c in a.countries.split(',') if c.strip()}
    if not cc or not all(re.fullmatch('[A-Z]{2}', c) for c in cc):
        ap.error('--countries must contain ISO2 codes')
    try:
        result = run(a.index, a.out, name_list(a.names), download=a.download,
                     countries=cc, max_files=a.max_files,
                     max_file_bytes=a.max_file_bytes, max_total_bytes=a.max_total_bytes)
    except (ValueError, OSError, PermissionError) as exc:
        ap.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
