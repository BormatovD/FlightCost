"""Bounded queue overrides shared by the dashboard snapshot and fare collector."""

import json
import os
import re
import stat
from pathlib import Path

TICKET_CONTROL = Path("/var/spool/fca-fare-observer/ticket-admin/overrides.json")
ROUTE = re.compile(r"[A-Z0-9]{3}-[A-Z0-9]{3}")
MAX_OVERRIDES = 64
MAX_BYTES = 2048


def read_ticket_controls(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return [], []
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Некорректный файл очереди билетов.")
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Некорректный файл очереди билетов.")
    try:
        document = json.loads(data)
        prioritized, deferred = document["prioritized"], document["deferred"]
        for rows in (prioritized, deferred):
            if not isinstance(rows, list) or any(
                not isinstance(route, str) or not ROUTE.fullmatch(route) for route in rows
            ):
                raise ValueError
        combined = prioritized + deferred
        if len(combined) > MAX_OVERRIDES or len(set(combined)) != len(combined):
            raise ValueError
    except (KeyError, TypeError, ValueError, RecursionError):
        raise ValueError("Некорректный файл очереди билетов.") from None
    return prioritized, deferred


def ticket_controls(path):
    try:
        return read_ticket_controls(path)
    except (OSError, ValueError):
        return [], []


def select_tickets(db, limit, now, controls, *, include_future=False):
    prioritized, deferred = controls
    front = []
    status = "status IS NOT 'unsupported_route'"
    if prioritized:
        slots = ",".join("?" for _ in prioritized)
        rows = db.execute(f"""
            SELECT target,metadata,due FROM targets
            WHERE target IN ({slots}) AND due<=? AND {status}
        """, (*prioritized, now))
        eligible = {row[0]: row for row in rows}
        front = [eligible[route] for route in prioritized if route in eligible][:limit]
    if len(front) == limit:
        return front

    excluded = deferred + [row[0] for row in front]
    filter_sql = ""
    if excluded:
        filter_sql = "AND target NOT IN (" + ",".join("?" for _ in excluded) + ")"
    due = "due IS NOT NULL" if include_future else "due<=?"
    due_args = () if include_future else (now,)
    regular = db.execute(f"""
        SELECT target,metadata,due FROM targets
        WHERE {due} AND {status} {filter_sql}
        ORDER BY due,priority,seq LIMIT ?
    """, (*due_args, *excluded, limit - len(front)))
    return front + regular.fetchall()
