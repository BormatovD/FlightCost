#!/usr/bin/env python3
"""Conservative *offline* interpretation of IATI location evidence.

Coordinates are evidence of a reported location, NOT proof of a building site.
IATI location-class=1 means admin region, 2 populated place, 3 structure;
location-reach=2 means beneficiaries.  A country centroid is never invented.
"""
from __future__ import annotations

import csv
import math
import re
import unicodedata
from pathlib import Path


def _norm(text: str | None) -> str:
    value = unicodedata.normalize('NFKC', str(text or '')).casefold()
    return ' '.join(re.sub(r'[^\w]+', ' ', value).split())


def load_gazetteer(path: str | Path) -> dict[tuple[str, str], list[dict]]:
    """Read a small, explicitly supplied, country-disambiguated CSV gazetteer.

    Required columns: country_iso2,name,lat,lon.  Duplicates are preserved as
    candidates; an ambiguous place is *not* resolved to the first match.
    """
    out: dict[tuple[str, str], list[dict]] = {}
    with open(path, encoding='utf-8', newline='') as handle:
        reader = csv.DictReader(handle)
        required = {'country_iso2', 'name', 'lat', 'lon'}
        if not reader.fieldnames or required - set(reader.fieldnames):
            raise ValueError(f'gazetteer missing columns: {sorted(required - set(reader.fieldnames or []))}')
        for row in reader:
            try:
                lat, lon = float(row['lat']), float(row['lon'])
            except (TypeError, ValueError):
                continue
            if not _valid_point(lat, lon):
                continue
            country = row['country_iso2'].upper().strip()
            key = (country, _norm(row['name']))
            if not country or not key[1]:
                continue
            out.setdefault(key, []).append({'lat': lat, 'lon': lon,
                                              'name': row['name'],
                                              'id': row.get('id') or None})
    return out


def _valid_point(lat, lon) -> bool:
    return (math.isfinite(lat) and math.isfinite(lon)
            and -90 <= lat <= 90 and -180 <= lon <= 180)


def resolve(location: dict | None, countries: list[dict] | None = None,
            gazetteer: dict | None = None) -> dict:
    """Classify one IATI *location*, keeping both uncertainty and original point.

    No returned candidate may be assigned to an airport without further review
    and airport catchment modelling.  In particular site_verified is NEVER
    asserted by this automatic classifier.
    """
    loc = location or {}
    class_code = str(loc.get('location_class_code') or '')
    reach = str(loc.get('reach_code') or '')
    exact = str(loc.get('exactness_code') or '')
    role = {'1': 'site_or_activity', '2': 'beneficiaries'}.get(reach, 'unspecified')
    name = loc.get('name')
    coords = loc.get('coordinates') or {}
    lat = lon = None
    if isinstance(coords, dict):
        try:
            llat, llon = float(coords['lat']), float(coords['lon'])
            if _valid_point(llat, llon):
                lat, lon = llat, llon
        except (TypeError, KeyError, ValueError):
            pass
    distinct = sorted({str(c['iso2']).upper() for c in (countries or [])
                       if isinstance(c, dict) and c.get('iso2')})
    candidates: list[dict] = []
    method = 'iati_point' if lat is not None else 'unresolved'
    # Local gazetteer only when unambiguous *and* one recipient country.
    if lat is None and name and gazetteer and len(distinct) == 1:
        candidates = gazetteer.get((distinct[0], _norm(name)), [])
        if len(candidates) == 1 and class_code in ('', '2'):
            lat, lon = candidates[0]['lat'], candidates[0]['lon']
            method = 'local_gazetteer_exact_name'
    if lat is not None:
        if class_code == '1':
            kind, quality = 'admin_region_reference', 'admin_region_unresolved'
            eligible = False
        elif class_code == '2' or method == 'local_gazetteer_exact_name':
            kind, quality = 'settlement_reference', 'settlement_resolved'
            eligible = False
        elif class_code == '3':
            kind, quality = 'reported_point', 'site_candidate_unverified'
            # Even 'exact' location could mean beneficiaries or a different
            # construction site; human verification is required in all cases.
            eligible = False
        else:
            kind, quality = 'reported_point', 'point_unclassified'
            eligible = False
    elif class_code == '1' or name:
        kind, quality = 'admin_or_named_area', 'unresolved'
        eligible = False
    elif len(distinct) == 1:
        kind, quality = 'country', 'country_only'
        eligible = False
    else:
        kind, quality = 'unknown', 'unknown'
        eligible = False
    return {'name': name, 'country_candidates': distinct,
            'latitude_reported_or_gazetteer': lat,
            'longitude_reported_or_gazetteer': lon,
            'geometry_type': kind, 'geo_quality': quality,
            'role': role, 'method': method, 'location_class_code': class_code or None,
            'location_reach_code': reach or None, 'exactness_code': exact or None,
            'airport_assignment_allowed': eligible,
            'candidate_count': len(candidates),
            'candidates': candidates[:20] if len(candidates) != 1 else [],
            'note': 'Reference location; no automatic airport assignment or financial allocation.'}


def country_fallback(countries: list[dict] | None) -> dict:
    """Synthetic country *scope*, never a point; call when no locations exist."""
    return resolve({}, countries, {})
