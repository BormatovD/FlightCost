"""Build the private owner dashboard snapshot outside the HTTP service."""

from __future__ import annotations

import grp
import json
import math
import os
import pwd
import re
import sqlite3
import stat
import subprocess
import sys
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from itertools import islice
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import monotonic

from .ticket_controls import TICKET_CONTROL, select_tickets, ticket_controls

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = Path("/var/lib/fca-admin-snapshot/status.json")
AGENT_HOME = Path("/srv/fca/agent")
MASTER_DB = Path("/srv/fca/master/flightcost.db")
FARE_DB = Path("/var/lib/fca-fo-ingest/staging.sqlite3")
TICKET_QUEUE = Path("/var/lib/fca-fo-tickets/queue.sqlite3")
LIMIT = 20
ICAO = re.compile(r"[A-Z0-9]{4}")
ROUTE = re.compile(r"[A-Z0-9]{3}-[A-Z0-9]{3}")
MODEL = re.compile(r"(?:openai/)?gpt-[0-9][a-z0-9.-]{0,30}")
PROPOSAL_SOURCES = {
    "airport_charges_tier1": "Тарифы аэропортов",
    "tkp_charges": "Аэропортовые сборы ТКП",
    "fas_ans_rates": "Ставки аэронавигации ФАС",
    "crco_enroute_rates": "Маршрутные ставки EUROCONTROL",
    "crco_terminal_rates": "Терминальные ставки EUROCONTROL",
}
PROPOSAL_STATUSES = {"pending": "Ждёт проверки", "accepted": "Принято", "rejected": "Отклонено",
                     "superseded": "Заменено"}
WORK_DOMAINS = {"airports": "airport_charge", "enroute": "enroute_rate", "terminal": "terminal_rate"}
CHARGE_LABELS = {"landing": "посадка", "parking": "стоянка", "passenger": "пассажиры",
                 "security": "безопасность", "pfc": "инфраструктура", "api": "данные пассажиров",
                 "gate": "гейт", "bridge": "телетрап", "fis": "пограничный контроль",
                 "ramp_tower": "диспетчеризация перрона"}


def _text(value, max_length=120):
    return " ".join(value[:max_length].split()) if isinstance(value, str) else ""


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        moment = datetime.fromisoformat(value)
        return moment.replace(tzinfo=moment.tzinfo or timezone.utc).astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _iso(moment):
    return moment.isoformat(timespec="seconds") if moment else None


def _amount(value):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) and 0 <= value <= 1_000_000 else None


def _read(path: Path, limit: int):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("snapshot source is not a small regular file")
        content = stream.read(limit + 1)
        if len(content) > limit:
            raise ValueError("snapshot source exceeds size limit")
        return content, info.st_mtime


def _document(path: Path, limit: int):
    try:
        content, mtime = _read(path, limit)
        value = json.loads(content)
        if isinstance(value, dict):
            return value, mtime
    except (OSError, ValueError, RecursionError):
        pass
    return {}, None


def _entries(path: Path, limit: int):
    try:
        with os.scandir(path) as entries:
            return [entry.name for entry in islice(entries, limit)]
    except OSError:
        return []


def _property(unit, prop):
    try:
        result = subprocess.run(
            ["/usr/bin/systemctl", "show", "--value", "-p", prop, unit],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=1.5, check=True,
            env={**os.environ, "LC_ALL": "C", "TZ": "UTC"},
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _next_timer(unit):
    timer = _property(unit, "NextElapseUSecRealtime")
    try:
        return _iso(datetime.strptime(timer, "%a %Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc))
    except ValueError:
        return None


def _agent(home, now):
    from .agent_run import JOBS, MONTH_USD

    budget = {"spent": None, "limit": _amount(MONTH_USD)}
    try:
        ledger, _ = _read(home / "ledger.jsonl", 2 * 1024 * 1024)
    except FileNotFoundError:
        ledger = b"" if home.is_dir() else None
    except (OSError, ValueError):
        ledger = None

    last_started = last_finished = None
    newest_model = None
    if ledger is not None:
        spent = 0.0
        for line in ledger.splitlines():
            if len(line) > 16 * 1024:
                continue
            try:
                row = json.loads(line)
            except (ValueError, RecursionError):
                continue
            at = _timestamp(row.get("ts")) if isinstance(row, dict) else None
            if at is None:
                continue
            if (at.year, at.month) == (now.year, now.month):
                spent += _amount(row.get("cost_usd")) or 0.0
            if row.get("job") != "charges":
                continue
            if row.get("status") != "running" and (last_finished is None or at >= last_finished):
                last_finished = at
            if last_started is None or at >= last_started:
                last_started = at
                model = _text(row.get("model"), 40)
                if MODEL.fullmatch(model):
                    newest_model = model
        budget["spent"] = round(spent, 6)

    state = _property("fca-agent@charges.service", "ActiveState")
    active = state in {"active", "activating", "reloading"} if state else None
    return budget, {"active": active, "last_finished": _iso(last_finished),
                    "next": _next_timer("fca-agent-charges.timer"), "model": JOBS["charges"]["model"],
                    "last_model": newest_model}


def _airport_queue(todo, have, state, directory):
    from .agent_run import manual_charge_candidate, pick_charges, region_of
    from .airport_queue import queue_airports

    regions = todo.get("regions") or {}
    direct = [code.strip().upper() for code in os.environ.get("FCA_AGENT_CHARGES_ONLY", "").split(",")]
    direct = list(dict.fromkeys(code for code in direct if ICAO.fullmatch(code)))
    airport_details = todo.get("airports") or {}

    def airport(icao, city, region, origin):
        name = (regions.get(region) or {}).get("name") or region
        return {"icao": icao, "city": _text(city), "region": _text(name), "origin": origin}

    manual, deferred = queue_airports(directory)
    manual_rows = []
    for row in manual:
        candidate, _ = manual_charge_candidate(todo, have, state, row)
        if candidate:
            icao, entry, region = candidate
            manual_rows.append(airport(icao, entry.get("city"), region, "manual"))

    deferred_rows = [airport(icao, (airport_details.get(icao) or {}).get("city"),
                             region_of(icao, regions), "deferred") for icao in deferred]
    queued = [] if direct else manual_rows[:LIMIT]
    excluded = set(deferred) | {row["icao"] for row in queued}

    # List eligible alternatives in the runner's order without changing how
    # existing tariffs and drafts count toward the regional quotas.
    while len(queued) < LIMIT:
        picked = pick_charges(todo, have, state, direct, excluded=excluded)
        if picked is None:
            break
        icao, row, region = picked
        excluded.add(icao)
        if ICAO.fullmatch(icao):
            queued.append(airport(icao, row.get("city"), region, "automatic"))
    return queued, manual_rows, deferred_rows

def _airports(home, charges_dir, master):
    import yaml

    state, _ = _document(home / "charges_state.json", 256 * 1024)
    state = {key: value for key, value in state.items() if ICAO.fullmatch(key) and isinstance(value, dict)}
    try:
        raw, _ = _read(charges_dir / "_todo.yaml", 256 * 1024)
        todo = yaml.safe_load(raw) or {}
        if not isinstance(todo, dict):
            todo = {}
    except (OSError, ValueError, yaml.YAMLError):
        todo = {}
    names = _entries(charges_dir, 4096)
    have = {name.split("-", 1)[0] for name in names if re.fullmatch(r"[A-Z0-9]{4}-.+\.json", name)}
    queued, manual, deferred = _airport_queue(todo, have, state, home / "queue" / "airport-admin")

    accepted = {}
    try:
        with _readonly(master, 1) as db:
            accepted = dict(db.execute("""
                SELECT substr(key,1,4),max(created_at) FROM facts
                WHERE domain='airport_charge' AND source_id='airport_charges_tier1'
                  AND value_text <> '' AND instr(key,'/_')=0
                GROUP BY 1
            """))
    except (OSError, sqlite3.Error):
        pass
    out = home / "out"
    candidates = defaultdict(list)
    for name in _entries(out, 4096):
        match = re.fullmatch(r"charges-([A-Z0-9]{4})-.+\.json", name)
        if not match or state.get(match[1], {}).get("status") != "draft" or name[8:] in names:
            continue
        try:
            meta = (out / name).lstat()
        except OSError:
            continue
        approved = _timestamp(accepted.get(match[1]))
        if stat.S_ISREG(meta.st_mode) and (not approved or meta.st_mtime > approved.timestamp()):
            candidates[match[1]].append((meta.st_mtime, name))

    latest = sorted((max(files), icao) for icao, files in candidates.items())
    drafts = []
    for (_, name), icao in reversed(latest[-128:]):
        draft, mtime = _document(out / name, 512 * 1024)
        rules = draft.get("rules")
        if isinstance(rules, list) and rules:
            drafts.append({"icao": icao, "updated_at": _iso(datetime.fromtimestamp(mtime, timezone.utc)),
                           "rules": len(rules)})
    return {"queued": queued, "manual": manual, "deferred": deferred, "drafts": drafts[:LIMIT],
            "waiting_review": len(drafts)}


@contextmanager
def _readonly(path, seconds):
    deadline = monotonic() + seconds
    connection = sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True, timeout=0.15)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA cache_size=-2048")
        connection.set_progress_handler(lambda: monotonic() > deadline, 1000)
        yield connection
    finally:
        connection.close()


def _updates(path, now):
    since = now - timedelta(days=30)
    since_db = since.strftime("%Y-%m-%dT%H:%M:%S")
    result = {"airport_rules": None, "enroute_rates": None, "terminal_rates": None,
              "recent": [], "since": _iso(since)}
    try:
        with _readonly(path, 2) as db:
            for domain, field, kind in (("airport_charge", "airport_rules", "airport"),
                                        ("enroute_rate", "enroute_rates", "enroute"),
                                        ("terminal_rate", "terminal_rates", "enroute")):
                rows = db.execute("""
                    SELECT created_at,
                           CASE WHEN instr(key,'/') THEN substr(key,1,instr(key,'/')-1) ELSE key END AS scope,
                           count(*), sum(count(*)) OVER (), group_concat(DISTINCT
                               CASE WHEN domain='airport_charge'
                                    THEN substr(substr(key,instr(key,'/')+1),1,instr(substr(key,instr(key,'/')+1),'/')-1)
                                    ELSE currency END)
                    FROM facts WHERE domain=? AND created_at>=? AND value IS NOT NULL
                      AND (? != 'airport_charge' OR (instr(key,'/_')=0 AND value_text <> ''))
                    GROUP BY created_at, scope
                    ORDER BY created_at DESC, scope LIMIT ?
                """, (domain, since_db, domain, LIMIT)).fetchall()
                result[field] = rows[0][3] if rows else 0
                for at, scope, count, _, units in rows:
                    if re.fullmatch(r"[A-Z0-9_-]{2,20}", scope):
                        label = f"{scope} · терминальные" if domain == "terminal_rate" else scope
                        detail = f"Записей: {count}"
                        if units:
                            if domain == "airport_charge":
                                labels = [CHARGE_LABELS.get(code, code) for code in units.split(",")
                                          if re.fullmatch(r"[a-z0-9_]{2,32}", code)][:8]
                                if labels:
                                    detail += " · " + ", ".join(labels)
                            else:
                                detail += " · " + _text(units, 45)
                        result["recent"].append({"at": _iso(_timestamp(at)), "label": label,
                                                 "details": detail, "kind": kind})
            sources = ",".join("?" for _ in PROPOSAL_SOURCES)
            for at, source, status in db.execute(f"""
                SELECT created_at,source_id,status FROM proposals
                WHERE created_at>=? AND source_id IN ({sources})
                ORDER BY id DESC LIMIT ?
            """, (since_db, *PROPOSAL_SOURCES, LIMIT)):
                if status in PROPOSAL_STATUSES:
                    result["recent"].append({"at": _iso(_timestamp(at)), "label": PROPOSAL_SOURCES[source],
                                             "details": PROPOSAL_STATUSES[status], "kind": "proposal"})
    except (OSError, sqlite3.Error):
        pass
    result["recent"] = sorted(result["recent"], key=lambda row: row["at"] or "", reverse=True)[:LIMIT]
    return result


def _work(master, agent, tickets, now):
    nav_next = _next_timer("fca-master-refresh.timer")
    next_at = {"airports": agent["next"], "enroute": nav_next, "terminal": nav_next,
               "tickets": _next_timer("fca-fo-tickets.timer")}
    work = {name: {"total": None, "last": None, "next_at": at} for name, at in next_at.items()}
    ticket_work = work["tickets"]
    ticket_work["total"] = tickets["observations"]
    if tickets["recent"]:
        latest = tickets["recent"][0]
        if latest["at"]:
            ticket_work["last"] = {"at": latest["at"], "label": latest["route"],
                                   "count": latest["observations"], "kind": "collection"}
    date = now.date().isoformat()
    cutoff = now.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        with _readonly(master, 2) as db:
            for name, domain in WORK_DOMAINS.items():
                # Match Store.current(): for overlapping intervals, count only
                # the winning row for each key at the snapshot date.
                work[name]["total"] = db.execute("""
                    SELECT count(*) FROM (
                        SELECT key, value, value_text,
                               row_number() OVER (
                                   PARTITION BY key ORDER BY valid_from DESC, created_at DESC
                               ) AS rank
                        FROM facts
                        WHERE domain=? AND valid_from<=? AND (valid_to IS NULL OR valid_to>?)
                    )
                    WHERE rank=1 AND value IS NOT NULL
                      AND (? != 'airport_charge' OR (instr(key,'/_')=0 AND value_text <> ''))
                """, (domain, date, date, domain)).fetchone()[0]
                row = db.execute("""
                    SELECT created_at, count(*), count(DISTINCT source_id), min(source_id),
                           count(DISTINCT scope), min(scope)
                    FROM (
                        SELECT created_at, source_id,
                               CASE WHEN instr(key,'/') THEN substr(key,1,instr(key,'/')-1)
                                    ELSE key END AS scope
                        FROM facts
                        WHERE domain=? AND created_at<=? AND value IS NOT NULL
                          AND (? != 'airport_charge' OR (instr(key,'/_')=0 AND value_text <> ''))
                    )
                    GROUP BY created_at ORDER BY created_at DESC LIMIT 1
                """, (domain, cutoff, domain)).fetchone()
                if row is not None:
                    at, count, sources, source, scopes, scope = row
                    moment = _timestamp(at)
                    if moment:
                        label = "Импорт в мастер-базу"
                        if sources == 1:
                            label = PROPOSAL_SOURCES.get(source, label)
                        if scopes == 1 and re.fullmatch(r"[A-Z0-9_-]{2,20}", scope):
                            label = scope
                        work[name]["last"] = {"at": _iso(moment), "label": label, "count": count}
    except (OSError, sqlite3.Error):
        pass
    return work


def _ticket_queue(queue):
    controls = ticket_controls(TICKET_CONTROL) if queue == TICKET_QUEUE else ([], [])
    prioritized, deferred = controls
    result = {"total": None, "unsupported": None, "planned": [],
              "prioritized": prioritized, "deferred": deferred}
    try:
        with _readonly(queue, 3) as db:
            now = int(datetime.now(timezone.utc).timestamp())
            result["planned"] = [
                {"route": route, "region": _text(region), "priority": route in prioritized, "ready": due <= now,
                 "due_at": _iso(datetime.fromtimestamp(due, timezone.utc)) if due > now else None}
                for route, region, due in select_tickets(db, LIMIT, now, controls, include_future=True)
                if ROUTE.fullmatch(route)
            ]
            result["total"] = db.execute("SELECT count(*) FROM targets").fetchone()[0]
            result["unsupported"] = db.execute("SELECT count(*) FROM targets WHERE status='unsupported_route'").fetchone()[0]
    except (OSError, sqlite3.Error):
        pass
    return result


def _ticket_evidence(staging):
    result = {"checked": None, "with_prices": None, "observations": None, "recent": []}
    try:
        with _readonly(staging, 4) as db:
            # SQLite can prefer the older status index and build a temporary
            # B-tree even when a serving index already provides every column.
            indexes = {row[1] for row in db.execute("PRAGMA index_list('handoff')")}
            recent_index = "INDEXED BY ix_handoff_ticket_recent" if "ix_handoff_ticket_recent" in indexes else ""
            totals_index = ("INDEXED BY ix_handoff_ticket_target_rows"
                            if "ix_handoff_ticket_target_rows" in indexes else "")
            result["recent"] = [{"route": route, "at": _iso(_timestamp(at)), "observations": rows}
                                for route, at, rows in db.execute(f"""
                                    SELECT target,checked_at,rows FROM handoff {recent_index}
                                    WHERE stream='tickets' AND phase='staged' AND rows>0
                                    ORDER BY checked_at DESC LIMIT ?
                                """, (LIMIT,)) if ROUTE.fullmatch(route)]
            result["checked"], result["with_prices"], result["observations"] = db.execute(f"""
                SELECT count(*), count(CASE WHEN observations>0 THEN 1 END), coalesce(sum(observations),0)
                FROM (SELECT target,sum(rows) AS observations FROM handoff {totals_index}
                      WHERE stream='tickets' AND phase='staged' GROUP BY target)
            """).fetchone()
    except (OSError, sqlite3.Error):
        pass
    return result


def _as_observer(user, section):
    # A read-only WAL connection may create sidecars. Let the database owner's
    # UID create them so that opening a dashboard snapshot cannot block a writer.
    account = pwd.getpwnam(user)
    return json.loads(subprocess.check_output(
        [sys.executable, "-m", "flightcostapp.admin_status", section], user=account.pw_uid, group=account.pw_gid,
        extra_groups=(), timeout=9, stderr=subprocess.DEVNULL,
    ))


def _tickets(queue, staging):
    if os.geteuid() != 0 or queue != TICKET_QUEUE or staging != FARE_DB:
        return {**_ticket_queue(queue), **_ticket_evidence(staging)}
    result = {"total": None, "unsupported": None, "planned": [], "checked": None,
              "with_prices": None, "observations": None, "recent": [], "prioritized": [], "deferred": []}
    for user, section in (("fca-fo-tickets", "queue"), ("fca-fo-ingest", "evidence")):
        try:
            result.update(_as_observer(user, section))
        except (OSError, KeyError, ValueError, subprocess.SubprocessError):
            continue
    return result


def build_snapshot(*, home=AGENT_HOME, charges_dir=ROOT / "data" / "charges", master=MASTER_DB,
                   ticket_queue=TICKET_QUEUE, fare_db=FARE_DB, now=None):
    now = now or datetime.now(timezone.utc)
    budget, agent = _agent(home, now)
    tickets = _tickets(ticket_queue, fare_db)
    return {"as_of": _iso(now), "budget": budget, "agent": agent, "airports": _airports(home, charges_dir, master),
            "updates": _updates(master, now), "tickets": tickets, "work": _work(master, agent, tickets, now)}


def write_snapshot(path, payload, gid):
    with NamedTemporaryFile(dir=path.parent, prefix=".status-", delete=False) as output:
        temp = Path(output.name)
        try:
            output.write(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode() + b"\n")
            output.flush()
            os.fchown(output.fileno(), -1, gid)
            os.fchmod(output.fileno(), 0o640)
            os.fsync(output.fileno())
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)


def main():
    if sys.argv[1:] == ["queue"]:
        print(json.dumps(_ticket_queue(TICKET_QUEUE)))
        return
    if sys.argv[1:] == ["evidence"]:
        print(json.dumps(_ticket_evidence(FARE_DB)))
        return
    write_snapshot(SNAPSHOT, build_snapshot(), grp.getgrnam("fcabot").gr_gid)


if __name__ == "__main__":
    main()
