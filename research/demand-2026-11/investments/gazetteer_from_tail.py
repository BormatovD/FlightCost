#!/usr/bin/env python3
"""Convert the owner's *public city facts only* to an offline country gazetteer.

No API calls. Does NOT geocode projects, infer project locations or copy
passenger traffic into the investment database.  Historical snapshots cannot
be reconstructed from this current city list.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path


def export_cities(inp: Path, dest: Path) -> dict:
    reader = gzip.open if inp.suffix == '.gz' else open
    best: dict[str, tuple[str, dict]] = {}
    scanned = accepted = 0
    with reader(inp, 'rt', encoding='utf-8') as fh:
        for line in fh:
            if not line.strip():
                continue
            data = json.loads(line)
            scanned += 1
            if (data.get('record') != 'fact' or data.get('domain') != 'city'
                    or data.get('source_id') != 'geonames_cities'
                    or data.get('valid_to') is not None):
                continue
            try:
                raw = data['value_text'].split('|', 2)
                pos, country, name = raw
                lat, lon = (float(v) for v in pos.split(','))
                if not name.strip() or len(country) != 2 or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            record = {'id': data['key'], 'country_iso2': country.upper(),
                      'name': name, 'lat': lat, 'lon': lon}
            stamp = str(data.get('valid_from') or '') + '|' + str(data.get('created_at') or '')
            if record['id'] not in best or stamp > best[record['id']][0]:
                best[record['id']] = (stamp, record)
                accepted += 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, 'w', newline='', encoding='utf-8') as fh:
        out = csv.DictWriter(fh, fieldnames=['id','country_iso2','name','lat','lon'])
        out.writeheader()
        out.writerows(v[1] for k,v in sorted(best.items()))
    return {'lines_scanned': scanned, 'unique_current_cities': len(best),
            'candidate_city_versions': accepted, 'output': str(dest)}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tail', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a=p.parse_args(argv)
    print(json.dumps(export_cities(a.tail, a.out), indent=2))

if __name__=='__main__':main()
