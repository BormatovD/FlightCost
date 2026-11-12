#!/usr/bin/env python3
"""Research-only SQLite register for the normalized 0061/0063 IATI candidates.

It preserves variants and their distinct budgets/transactions.  A project is
not an accepted investment; no money is aggregated across source variants.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sqlite3

try:
    from . import georesolve
except ImportError:
    import georesolve

SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS project (
 project_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, iati_identifier TEXT NOT NULL,
 variant_conflict INTEGER NOT NULL DEFAULT 0 CHECK(variant_conflict IN (0,1)),
 review_state TEXT NOT NULL DEFAULT 'candidate' CHECK(review_state IN ('candidate','review','accepted','excluded')),
 UNIQUE(source_id,iati_identifier)
);
CREATE TABLE IF NOT EXISTS project_source (
 variant_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES project(project_id),
 source_id TEXT NOT NULL, source_variant_sha256 TEXT NOT NULL,
 reporting_org TEXT, title TEXT, description TEXT, source_url TEXT,
 reported_last_updated_at TEXT, observed_at TEXT NOT NULL,
 status_code TEXT, raw_candidate_json TEXT NOT NULL,
 UNIQUE(project_id,source_variant_sha256)
);
CREATE TABLE IF NOT EXISTS source_sighting (
 variant_id TEXT NOT NULL REFERENCES project_source(variant_id), snapshot_at TEXT NOT NULL,
 PRIMARY KEY(variant_id,snapshot_at)
);
CREATE TABLE IF NOT EXISTS project_sector (
 variant_id TEXT NOT NULL REFERENCES project_source(variant_id), ordinal INTEGER NOT NULL,
 code TEXT, vocabulary TEXT, share_pct TEXT, category TEXT,
 PRIMARY KEY(variant_id,ordinal)
);
CREATE TABLE IF NOT EXISTS project_country (
 variant_id TEXT NOT NULL REFERENCES project_source(variant_id), ordinal INTEGER NOT NULL,
 iso2 TEXT, share_pct TEXT,
 PRIMARY KEY(variant_id,ordinal)
);
CREATE TABLE IF NOT EXISTS project_event (
 variant_id TEXT NOT NULL REFERENCES project_source(variant_id), ordinal INTEGER NOT NULL,
 event_kind TEXT NOT NULL, event_date TEXT, known_as_of TEXT NOT NULL,
 source_event_code TEXT, PRIMARY KEY(variant_id,ordinal)
);
CREATE TABLE IF NOT EXISTS project_finance (
 variant_id TEXT NOT NULL REFERENCES project_source(variant_id), kind TEXT NOT NULL,
 ordinal INTEGER NOT NULL, finance_stage TEXT NOT NULL, source_stage_code TEXT,
 amount_decimal TEXT, currency TEXT, event_date TEXT, period_start TEXT,
 period_end TEXT, value_date TEXT, known_as_of TEXT NOT NULL,
 PRIMARY KEY(variant_id,kind,ordinal)
);
CREATE TABLE IF NOT EXISTS project_location (
 variant_id TEXT NOT NULL REFERENCES project_source(variant_id), ordinal INTEGER NOT NULL,
 role TEXT NOT NULL, geometry_type TEXT NOT NULL, geo_quality TEXT NOT NULL,
 method TEXT NOT NULL, name TEXT, country_candidates_json TEXT NOT NULL,
 latitude REAL, longitude REAL, exactness_code TEXT, location_class_code TEXT,
 location_reach_code TEXT, candidate_matches_json TEXT NOT NULL,
 known_as_of TEXT NOT NULL, airport_assignment_allowed INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(variant_id,ordinal)
);
-- These tables are intentionally empty until catchment and forecast evidence
-- exists. They cannot be populated just from an IATI geographic point.
CREATE TABLE IF NOT EXISTS project_airport_exposure (
 variant_id TEXT NOT NULL REFERENCES project_source(variant_id), airport_icao TEXT NOT NULL,
 method_version TEXT NOT NULL, verified_at TEXT NOT NULL, weight REAL,
 evidence TEXT NOT NULL,
 PRIMARY KEY(variant_id,airport_icao,method_version)
);
CREATE TABLE IF NOT EXISTS forecast_feature (
 feature_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES project(project_id),
 available_as_of TEXT NOT NULL, forecast_origin TEXT NOT NULL,
 target_year INTEGER NOT NULL, feature_type TEXT NOT NULL, scenario TEXT NOT NULL,
 value REAL, unit TEXT, source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_source_project ON project_source(project_id);
CREATE INDEX IF NOT EXISTS ix_event_known ON project_event(known_as_of);
CREATE INDEX IF NOT EXISTS ix_finance_known ON project_finance(known_as_of);
'''

ACTIVITY_DATES = {'1': 'planned_start', '2': 'actual_start',
                  '3': 'planned_end', '4': 'actual_end'}


def _amount(raw) -> str | None:
    if raw is None:
        return None
    try:
        d = Decimal(str(raw))
    except InvalidOperation:
        raise ValueError(f'Invalid numeric amount: {raw!r}') from None
    if not d.is_finite():
        raise ValueError('Non-finite investment amount')
    return str(d)


def _date(value) -> str | None:
    if not value:
        return None
    return str(value)


def init(db: sqlite3.Connection) -> None:
    db.executescript(SCHEMA)


def ingest(db: sqlite3.Connection, candidates: list[dict], *, gazetteer: dict | None = None) -> dict:
    """Atomic idempotent ingest: no version loss, no arithmetic over financial sums."""
    new_variants = new_sightings = 0
    with db:
        for cand in candidates:
            iid = str(cand.get('iati_identifier') or '')
            source = str(cand.get('source_id') or '')
            digest = str(cand.get('source_variant_sha256') or '')
            snapshot = str(cand.get('snapshot_at') or '')
            if not iid or not source or not snapshot or not re.fullmatch('[0-9a-f]{64}', digest):
                raise ValueError('Candidate lacks source_id, iati_identifier, snapshot or valid source SHA256')
            # The snapshot is acquisition time, not historical first-publication time.
            parsed_snapshot = datetime.fromisoformat(snapshot.replace('Z', '+00:00'))
            if parsed_snapshot.tzinfo is None or parsed_snapshot.utcoffset() is None:
                raise ValueError('snapshot_at must include a timezone')
            project_id = f'{source}:{iid}'
            variant_id = f'{project_id}:{digest}'
            db.execute('INSERT OR IGNORE INTO project (project_id,source_id,iati_identifier) VALUES (?,?,?)',
                       (project_id, source, iid))
            new = db.execute('SELECT 1 FROM project_source WHERE variant_id=?', (variant_id,)).fetchone() is None
            if new:
                db.execute('''INSERT INTO project_source
                        (variant_id,project_id,source_id,source_variant_sha256,reporting_org,title,
                         description,source_url,reported_last_updated_at,observed_at,status_code,raw_candidate_json)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                           (variant_id, project_id, source, digest, cand.get('reporting_org'),
                            cand.get('title'), cand.get('description'), cand.get('source_url'),
                            cand.get('reported_last_updated_at'), snapshot, cand.get('status_code'),
                            json.dumps(cand, sort_keys=True, ensure_ascii=False)))
                new_variants += 1
                for n, x in enumerate(cand.get('recipient_countries') or []):
                    db.execute('INSERT INTO project_country VALUES (?,?,?,?)',
                               (variant_id, n, x.get('iso2'), x.get('share_pct')))
                for n, x in enumerate(cand.get('sectors') or []):
                    db.execute('INSERT INTO project_sector VALUES (?,?,?,?,?,?)',
                               (variant_id, n, x.get('code'), x.get('vocabulary'),
                                x.get('share_pct'), x.get('category')))
                for n, ev in enumerate(cand.get('activity_dates') or []):
                    code = str(ev.get('type_code') or '')
                    db.execute('INSERT INTO project_event VALUES (?,?,?,?,?,?)',
                               (variant_id, n, ACTIVITY_DATES.get(code, 'other_activity_date'),
                                _date(ev.get('date')), snapshot, code))
                if cand.get('status_code') is not None:
                    # A reported status is a snapshot observation, NOT proof
                    # that cancellation/opening happened on snapshot day.
                    db.execute('INSERT INTO project_event VALUES (?,?,?,?,?,?)',
                               (variant_id, len(cand.get('activity_dates') or []),
                                'reported_activity_status', None, snapshot,
                                str(cand['status_code'])))
                for n, x in enumerate(cand.get('transactions') or []):
                    db.execute('INSERT INTO project_finance VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                               (variant_id, 'transaction', n, x.get('kind') or 'other',
                                x.get('kind_code'), _amount(x.get('amount')), x.get('currency'),
                                _date(x.get('date')), None, None, x.get('value_date'), snapshot))
                for n, x in enumerate(cand.get('budgets') or []):
                    db.execute('INSERT INTO project_finance VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                               (variant_id, 'budget', n, 'budget', x.get('type_code'),
                                _amount(x.get('amount')), x.get('currency'), None,
                                _date(x.get('start')), _date(x.get('end')), None, snapshot))
                places = cand.get('locations') or [{}]
                for n, loc in enumerate(places):
                    geo = georesolve.resolve(loc, cand.get('recipient_countries'), gazetteer)
                    db.execute('''INSERT INTO project_location VALUES
                                (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                               (variant_id, n, geo['role'], geo['geometry_type'], geo['geo_quality'],
                                geo['method'], geo['name'], json.dumps(geo['country_candidates']),
                                geo['latitude_reported_or_gazetteer'],
                                geo['longitude_reported_or_gazetteer'], geo['exactness_code'],
                                geo['location_class_code'], geo['location_reach_code'],
                                json.dumps(geo['candidates'], ensure_ascii=False), snapshot,
                                int(geo['airport_assignment_allowed'])))
            if db.execute('INSERT OR IGNORE INTO source_sighting VALUES (?,?)',
                          (variant_id, snapshot)).rowcount:
                new_sightings += 1
            if cand.get('identifier_conflict'):
                db.execute('UPDATE project SET variant_conflict=1,review_state=\'review\' WHERE project_id=?',
                           (project_id,))
        # Two or more different versions with the same identifier always block
        # financial aggregation; they may be distinct publisher-source records.
        db.execute('''UPDATE project SET variant_conflict=1, review_state='review'
                      WHERE project_id IN
                      (SELECT project_id FROM project_source GROUP BY project_id HAVING COUNT(*)>1)''')
    return {'input_rows': len(candidates), 'new_variants': new_variants,
            'new_sightings': new_sightings,
            'unique_projects': db.execute('SELECT COUNT(*) FROM project').fetchone()[0],
            'conflicted_identifiers': db.execute('SELECT COUNT(*) FROM project WHERE variant_conflict=1').fetchone()[0],
            'site_assignments': db.execute('SELECT COUNT(*) FROM project_location WHERE airport_assignment_allowed=1').fetchone()[0]}


def ingest_file(db: sqlite3.Connection, path: Path, *, gazetteer=None) -> dict:
    # Ingestion of the existing 0063 normalized file; original raw responses
    # remain separately archived in raw/*.json.gz, not inside this SQLite DB.
    entries = []
    with open(path, encoding='utf-8') as handle:
        for line in handle:
            if line.strip():
                entries.append(json.loads(line))
    return ingest(db, entries, gazetteer=gazetteer)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db', type=Path, required=True, help='research SQLite path (not production DB)')
    p.add_argument('--candidates', type=Path, required=True)
    p.add_argument('--gazetteer', type=Path)
    a = p.parse_args(argv)
    if a.db.name == 'flightcost.db' or a.db.resolve() == Path('data/flightcost.db').resolve():
        p.error('Refusing to write production FlightCost DB')
    a.db.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(a.db)
    try:
        init(db)
        g = georesolve.load_gazetteer(a.gazetteer) if a.gazetteer else None
        print(json.dumps(ingest_file(db, a.candidates, gazetteer=g), ensure_ascii=False, indent=2))
    finally:
        db.close()

if __name__ == '__main__':
    main()
