#!/usr/bin/env python3
"""Shared, fail-closed IATI API budget ledger (not an HTTP client).

0064-B: the Datastore client reserves an attempt BEFORE each HTTP call.
Failures and probes count. SQLite serializes concurrent reservations.
All callers must use the SAME private budget path; the ledger cannot account
for calls made outside it (such as pre-existing runs or other clients).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3

DDL = '''
CREATE TABLE IF NOT EXISTS request_attempt (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 service TEXT NOT NULL, at TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('reserved','completed','failed','rate_limited')),
 http_status INTEGER, note TEXT
);
CREATE INDEX IF NOT EXISTS ix_attempt_time ON request_attempt(service,at);
CREATE TABLE IF NOT EXISTS embargo (
 service TEXT PRIMARY KEY, until TEXT NOT NULL, reason TEXT NOT NULL
);
'''


def open_private(path):
    """Open a single private, persistent quota ledger shared by all IATI jobs.

    The file must live outside Git. Fail rather than continue with a
    world-/group-readable or symlinked ledger.
    """
    path = Path(path).expanduser()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink():
        raise RuntimeError('IATI budget ledger cannot be a symlink')
    if path.exists():
        if not path.is_file() or path.stat().st_mode & 0o077:
            raise RuntimeError('IATI budget ledger must be a private regular file (0600)')
    else:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    db = sqlite3.connect(path, timeout=30, isolation_level=None)
    try:
        init(db)
    except BaseException:
        db.close()
        raise
    return db


def _utc(now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('now must be timezone-aware')
    return now.astimezone(timezone.utc)


def _fmt(now):
    return _utc(now).isoformat(timespec='microseconds')


def init(db):
    db.executescript(DDL)


def snapshot(db, *, service='iati_datastore', now=None, minute_limit=5,
             week_limit=100, day_limit=100):
    now = _utc(now)
    minute = _fmt(now - timedelta(seconds=60))
    day = _fmt(now - timedelta(hours=24))
    week = _fmt(now - timedelta(days=7))
    counts = []
    for low in (minute, day, week):
        counts.append(db.execute('SELECT COUNT(*) FROM request_attempt WHERE service=? AND at>=? AND at<=?',
                                 (service, low, _fmt(now))).fetchone()[0])
    emb = db.execute('SELECT until,reason FROM embargo WHERE service=?', (service,)).fetchone()
    blocked = bool(emb and emb[0] > _fmt(now))
    return {'service': service, 'minute_used': counts[0], 'day_used': counts[1],
            'seven_days_used': counts[2], 'minute_limit': minute_limit,
            'day_limit': day_limit, 'seven_days_limit': week_limit,
            'blocked_until': emb[0] if blocked else None,
            'allowed': not blocked and counts[0] < minute_limit
                       and counts[1] < day_limit and counts[2] < week_limit}


def reserve(db, *, service='iati_datastore', now=None, **limits):
    now = _utc(now)
    # An explicit exclusive transaction prevents concurrent callers exceeding
    # the quota. Reservation persists even if the HTTP request fails later.
    db.execute('BEGIN IMMEDIATE')
    try:
        state = snapshot(db, service=service, now=now, **limits)
        if not state['allowed']:
            raise RuntimeError(f'IATI budget exhausted or cooling down: {state}')
        rid = db.execute('INSERT INTO request_attempt(service,at,state) VALUES (?,?,?)',
                         (service, _fmt(now), 'reserved')).lastrowid
        db.commit()
        return rid
    except BaseException:
        db.rollback()
        raise


def finish(db, request_id: int, *, http_status=None, note=None,
           retry_after_seconds=None, now=None):
    """Mark an attempt (never delete it) and optionally honor Retry-After."""
    now = _utc(now)
    # The completion and embargo must commit together: a parallel reserve
    # may not slip between the HTTP-429 record and its Retry-After embargo.
    db.execute('BEGIN IMMEDIATE')
    try:
        row = db.execute('SELECT service,state FROM request_attempt WHERE id=?', (request_id,)).fetchone()
        if not row:
            raise KeyError(f'Unknown budget reservation {request_id}')
        if row[1] != 'reserved':
            raise ValueError('Reservation already finished')
        status = int(http_status) if http_status is not None else None
        state = 'rate_limited' if status == 429 else 'failed' if status is None or status >= 400 else 'completed'
        db.execute('UPDATE request_attempt SET state=?,http_status=?,note=? WHERE id=?',
                   (state, status, str(note or '')[:200], request_id))
        if status == 429 and retry_after_seconds is not None:
            seconds = max(0.0, min(float(retry_after_seconds), 7*24*3600))
            until = _fmt(now + timedelta(seconds=seconds))
            db.execute('''INSERT INTO embargo(service,until,reason) VALUES (?,?,?)
                          ON CONFLICT(service) DO UPDATE SET until=excluded.until, reason=excluded.reason''',
                       (row[0], until, 'HTTP 429 Retry-After'))
        db.commit()
    except BaseException:
        db.rollback()
        raise


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db', type=Path, required=True)
    p.add_argument('--service', default='iati_datastore')
    p.add_argument('--minute-limit', type=int, default=5)
    p.add_argument('--day-limit', type=int, default=100)
    p.add_argument('--week-limit', type=int, default=100)
    p.add_argument('--reserve', action='store_true', help='Explicitly reserve a future HTTP attempt')
    a = p.parse_args(argv)
    if min(a.minute_limit, a.day_limit, a.week_limit) < 1:
        p.error('All limits must be positive')
    db = open_private(a.db)
    try:
        limits = dict(minute_limit=a.minute_limit, day_limit=a.day_limit,
                      week_limit=a.week_limit)
        if a.reserve:
            print('request_id', reserve(db, service=a.service, **limits))
        print(json.dumps(snapshot(db, service=a.service, **limits), indent=2))
    finally:
        db.close()

if __name__ == '__main__':
    main()
