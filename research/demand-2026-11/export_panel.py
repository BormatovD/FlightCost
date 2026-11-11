#!/usr/bin/env python3
"""Export only public research inputs from an existing FlightCost SQLite DB.

The source DB is opened with mode=ro and query_only. No application code, API
credentials, bot settings, user workspaces, raw documents or artifact paths
are read. The output is a gzip JSONL panel suitable for local research, not
a file to commit to the public repository.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit, urlunsplit


SOURCES = {
    "traffic": ("eurostat_par", "t100", "dgca_domestic", "dgca_international", "ru_pairs"),
    "airport": ("ourairports",),
    "city": ("geonames_cities",),
    "macro": ("wb_wdi", "eurostat_gdp_nuts3", "eurostat_pop_nuts3", "eurostat_nights_nuts2",
              "eurostat_emp_nuts2", "gisco_nuts2", "gisco_nuts3", "migrant_stock", "visa_index"),
}
FACT_FIELDS = ("domain", "key", "value", "value_text", "unit", "currency", "valid_from", "valid_to",
               "source_id", "artifact_sha", "confidence", "certainty", "created_at")
STATE_FIELDS = ("source_id", "status", "last_checked", "last_changed", "last_ok")
ARTIFACT_FIELDS = ("sha", "source_id", "url", "fetched_at", "n_bytes", "media_type")
PUBLIC_HOSTS = {
    "api.worldbank.org", "ec.europa.eu", "gisco-services.ec.europa.eu", "download.geonames.org",
    "raw.githubusercontent.com", "github.com", "davidmegginson.github.io", "transtats.bts.gov",
    "www.transtats.bts.gov", "www.bts.gov", "data.transportation.gov", "un.org", "www.un.org",
    "population.un.org", "unstats.un.org", "dgca.gov.in", "www.dgca.gov.in",
}


def public_url(value):
    """Keep a recognisable public source path, dropping credentials and queries."""
    try:
        u = urlsplit(value or "")
        if u.scheme not in ("https", "http") or u.hostname not in PUBLIC_HOSTS:
            return None
        if u.username is not None or u.password is not None:
            return None
        return urlunsplit((u.scheme, u.hostname, u.path, "", ""))
    except ValueError:
        return None


@contextmanager
def read_only_db(path):
    if not path.is_file():
        raise ValueError("source database does not exist")
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
        conn.row_factory = sqlite3.Row
        # A consistent SQLite read transaction, including with a live WAL DB.
        conn.execute("BEGIN")
        yield conn
    finally:
        conn.close()


def columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def selected_rows(conn, table, fields, where, params=(), order=""):
    have = columns(conn, table)
    selected = [f for f in fields if f in have]
    if not selected:
        return
    sql = f"SELECT {','.join(selected)} FROM {table} WHERE {where}"
    if order:
        sql += " ORDER BY " + order
    for r in conn.execute(sql, params):
        yield dict(r)


def export(db_path, out_path, traffic_since="2019-01-01"):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", traffic_since):
        raise ValueError("--traffic-since must be YYYY-MM-DD")
    if db_path.resolve() == out_path.resolve():
        raise ValueError("output must be different from the source database")
    if out_path.exists():
        raise ValueError("output already exists; choose another filename")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    source_ids = sorted({s for values in SOURCES.values() for s in values})
    source_counts, domain_counts, periods, artifact_shas = Counter(), Counter(), defaultdict(set), set()
    opener = gzip.open if out_path.suffix == ".gz" else open
    with read_only_db(db_path) as conn, opener(out_path, "xt", encoding="utf-8") as output:
        if not {"domain", "key", "source_id", "valid_from"} <= columns(conn, "facts"):
            raise ValueError("database has no supported facts schema")

        def emit(obj):
            output.write(json.dumps(obj, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")

        emit({"record": "metadata", "schema_version": 1, "exported_at": datetime.now(timezone.utc).isoformat(),
              "purpose": "flightcost_demand_research", "source_database_mode": "ro",
              "query_only": True, "traffic_since": traffic_since, "sources": SOURCES,
              "facts_policy": "all retained fact versions from whitelisted public source/domain combinations",
              "omitted": ["workspace tables", "observations", "proposals", "settings", "raw artifacts",
                          "artifact paths", "source_state.message", "fact notes", "URL queries and credentials"]})
        for domain, ids in SOURCES.items():
            marks = ",".join("?" for _ in ids)
            where, params = f"domain=? AND source_id IN ({marks})", [domain, *ids]
            if domain == "traffic":
                where += " AND valid_from>=?"
                params.append(traffic_since)
            for fact in selected_rows(conn, "facts", FACT_FIELDS, where, params,
                                      "source_id,key,valid_from,id"):
                emit({"record": "fact", **fact})
                source_counts[fact["source_id"]] += 1
                domain_counts[domain] += 1
                periods[fact["source_id"]].add(str(fact.get("valid_from") or "")[:4])
                if fact.get("artifact_sha"):
                    artifact_shas.add(fact["artifact_sha"])
        marks = ",".join("?" for _ in source_ids)
        states = []
        if {"source_id", "status"} <= columns(conn, "source_state"):
            for state in selected_rows(conn, "source_state", STATE_FIELDS, f"source_id IN ({marks})", source_ids,
                                       "source_id"):
                states.append(state)
                emit({"record": "source_state", **state})
        artifact_count = 0
        if {"sha", "source_id"} <= columns(conn, "artifacts"):
            for meta in selected_rows(conn, "artifacts", ARTIFACT_FIELDS, f"source_id IN ({marks})", source_ids,
                                      "source_id,sha"):
                if meta["sha"] not in artifact_shas:
                    continue
                if "url" in meta:
                    meta["url"] = public_url(meta["url"])
                emit({"record": "artifact", **meta})
                artifact_count += 1
        summary = {"record": "summary", "fact_count": sum(source_counts.values()),
                   "by_domain": dict(domain_counts), "by_source": dict(sorted(source_counts.items())),
                   "years_by_source": {s: sorted(ys) for s, ys in sorted(periods.items())},
                   "missing_sources": [s for s in source_ids if not source_counts[s]],
                   "source_states": len(states), "artifacts": artifact_count}
        emit(summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="existing SQLite database, opened read-only")
    parser.add_argument("--out", required=True, type=Path, help="new .jsonl.gz or .jsonl file")
    parser.add_argument("--traffic-since", default="2019-01-01")
    args = parser.parse_args()
    result = export(args.db, args.out, args.traffic_since)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
