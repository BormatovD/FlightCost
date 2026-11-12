#!/usr/bin/env python3
"""Offline-first IATI Bulk Data *index* cache and inspection.

Does NOT download the massive ZIP or individual publisher datasets.  Explicit
--refresh-index fetches a capped, publicly accessible JSON index, no API key.
A dataset index may lack project sectors: do not silently equate publisher
metadata with an investment project or exclude unknown-sector datasets.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

MINIMAL_INDEX = 'https://bulk-data.iatistandard.org/datasets-minimal'
FULL_INDEX = 'https://bulk-data.iatistandard.org/datasets-full'
MAX_INDEX_BYTES = 40_000_000


def download_index(*, url=MINIMAL_INDEX, opener=urlopen) -> bytes:
    if url not in {MINIMAL_INDEX, FULL_INDEX}:
        raise ValueError('Only the official IATI Bulk Data index URL is allowed')
    req = Request(url, headers={'Accept': 'application/json',
                                'User-Agent': 'FlightCost/0064-Research (+https://flightcost.app)'})
    with opener(req, timeout=60) as response:
        data = response.read(MAX_INDEX_BYTES + 1)
    if len(data) > MAX_INDEX_BYTES:
        raise ValueError('IATI index exceeds safety cap')
    json.loads(data)
    return data


def entries(doc):
    """Preserve raw shape; never pretend to know a missing country or sector."""
    if isinstance(doc, list):
        return doc
    if not isinstance(doc, dict):
        raise ValueError('Unknown IATI index top-level format')
    for field in ('datasets', 'results', 'data'):
        if field in doc:
            got = doc[field]
            if isinstance(got, list):
                return got
            if isinstance(got, dict):
                return list(got.values())
            raise ValueError(f'IATI index {field} has unsupported type')
    # A mapping keyed by dataset IDs is also common in registry exports.
    if doc and all(isinstance(v, dict) for v in doc.values()):
        return list(doc.values())
    raise ValueError('IATI index structure not yet recognized; keep raw snapshot')


def inspect_index(blob: bytes) -> dict:
    raw = json.loads(blob)
    rows = entries(raw)
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError('IATI index contains non-object dataset entries')
    known_countries = sum(bool(x.get('recipient_countries') or x.get('countries')) for x in rows)
    known_sectors = sum(bool(x.get('sectors') or x.get('sector_codes')) for x in rows)
    return {'datasets': len(rows), 'with_country_metadata': known_countries,
            'with_sector_metadata': known_sectors,
            'cannot_filter_projects_from_index_alone': known_sectors < len(rows),
            'sha256': hashlib.sha256(blob).hexdigest(), 'bytes': len(blob)}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cache', type=Path, required=True)
    p.add_argument('--refresh-index', action='store_true', help='Explicit opt-in HTTP GET (no Datastore API key)')
    p.add_argument('--full', action='store_true', help='Fetch official full metadata index instead of minimal')
    a = p.parse_args(argv)
    if a.refresh_index:
        data = download_index(url=FULL_INDEX if a.full else MINIMAL_INDEX)
        a.cache.parent.mkdir(parents=True, exist_ok=True)
        # Write only after the whole JSON body was downloaded and validated.
        tmp = a.cache.with_name(a.cache.name + '.tmp')
        tmp.write_bytes(data)
        tmp.replace(a.cache)
        meta = {'fetched_at': datetime.now(timezone.utc).isoformat(),
                'url': FULL_INDEX if a.full else MINIMAL_INDEX,
                **inspect_index(data)}
        a.cache.with_suffix(a.cache.suffix + '.meta.json').write_text(
            json.dumps(meta, indent=2), encoding='utf-8')
    if not a.cache.exists():
        p.error('No cached index; --refresh-index is required for an explicit network fetch')
    print(json.dumps(inspect_index(a.cache.read_bytes()), indent=2))

if __name__ == '__main__':
    main()
