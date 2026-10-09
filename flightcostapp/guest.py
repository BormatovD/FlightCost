"""Слой гостя: анонимное рабочее место по секретной ссылке (решение 148).

Что это. Вторая база, `data/user.db`, того же устройства, что справочник:
таблица фактов с теми же колонками плюс рабочее место. При чтении она
накладывается поверх справочника (`GuestStore`): своё значение главнее
общего, остальное — как у всех. `econ.py` об этом не знает.

Что хранится. Свои типы ВС — фактами, через тот же разбор и гейт, что
файл каталога (решение 146). Ставки флота, сети и сценарии — документами
(JSON): ставки применяются слоем сценария при расчёте, в факты не пишутся
(решение 10).

Кто владелец. Никто. Ключ — 128 бит случайности в ссылке `/w#<ключ>` и в
cookie; на сервере лежит только его хеш, так что утечка базы не отдаёт
ссылок. Ключ стоит после «#»: эту часть браузер серверу не посылает, и в
журналах запросов его нет. Почты и имени нет: потеря ссылки и браузера —
потеря места, поэтому есть экспорт и импорт одним файлом и выпуск новой
ссылки.

Адреса. Полный IP-адрес на диск не пишется — политика конфиденциальности
это обещает. Для суточного предела мест и для разбора злоупотреблений
хранится адрес без хвоста, как в журнале Caddy (IPv4 без последних 8 бит,
IPv6 — первые 48), а счётчики суток удаляются через двое суток.

Ограничения названы числами, а не прилагательными: размер места, число
документов, число мест с одного адреса в сутки, срок жизни без открытия.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import secrets
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

DEFAULT_PATH = Path("data/user.db")
KEY_BYTES = 16                      # 128 бит → 32 символа hex
MAX_BYTES = 512 * 1024              # на одно место: документы + факты
MAX_DOCS = 200
MAX_NEW_PER_DAY = 20                # мест с одной сети (/24, /48) в сутки
IDLE_DAYS = 365                     # не открывали год — удаляется
COUNTER_DAYS = 2                    # счётчики суток с адресами живут не дольше
DOC_KINDS = ("network", "scenario", "settings", "aircraft")
# Домены, которые гость может переопределять фактами. Только свои типы:
# всё остальное — слой сценария, документом `settings` (решение 10).
FACT_DOMAINS = ("aircraft", "aircraft_layout")

SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces (
    ws          TEXT PRIMARY KEY,          -- sha256 ключа
    created_at  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    created_ip  TEXT,
    note        TEXT
);
CREATE TABLE IF NOT EXISTS gfacts (
    id           INTEGER PRIMARY KEY,
    ws           TEXT NOT NULL,
    domain       TEXT NOT NULL,
    key          TEXT NOT NULL,
    value        REAL,
    value_text   TEXT,
    unit         TEXT,
    currency     TEXT,
    valid_from   TEXT NOT NULL,
    valid_to     TEXT,
    source_id    TEXT NOT NULL,
    artifact_sha TEXT,
    extracted_by TEXT NOT NULL,
    confidence   TEXT NOT NULL DEFAULT 'exact',
    certainty    TEXT NOT NULL DEFAULT 'exact',
    node         TEXT,
    source_note  TEXT,
    error_cost   REAL,
    confirm_by   TEXT,
    note         TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_gfacts ON gfacts(ws, domain, key, valid_from);
CREATE TABLE IF NOT EXISTS gdocs (
    ws         TEXT NOT NULL,
    kind       TEXT NOT NULL,
    name       TEXT NOT NULL,
    body       TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (ws, kind, name)
);
CREATE TABLE IF NOT EXISTS ws_created (
    day TEXT NOT NULL, ip TEXT NOT NULL, n INTEGER NOT NULL,
    PRIMARY KEY (day, ip)
);
"""

FACT_COLS = ("domain", "key", "value", "value_text", "unit", "currency", "valid_from",
             "valid_to", "source_id", "artifact_sha", "extracted_by", "confidence",
             "certainty", "node", "source_note", "error_cost", "confirm_by", "note")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_key() -> str:
    return secrets.token_hex(KEY_BYTES)


def ws_id(key: str) -> str:
    """Хеш ключа — то, что лежит в базе. Сам ключ сервер не хранит."""
    return hashlib.sha256(key.strip().lower().encode()).hexdigest()


def valid_key(key: str | None) -> bool:
    k = (key or "").strip().lower()
    return len(k) == KEY_BYTES * 2 and all(c in "0123456789abcdef" for c in k)


def mask_ip(ip: str) -> str:
    """Адрес без хвоста — та же маска, что у журнала Caddy: IPv4 без
    последних 8 бит, IPv6 — первые 48. Не адрес — пустая строка."""
    try:
        a = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return ""
    bits = 24 if a.version == 4 else 48
    return str(ipaddress.ip_network(f"{a}/{bits}", strict=False).network_address)


class GuestDB:
    """Файл мест гостей. Один на сервер; замок свой, не справочника."""

    def __init__(self, path: str | Path = DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()
        self.lock = threading.Lock()

    # ── места ──────────────────────────────────────────────────────────
    def create(self, ip: str = "") -> str:
        """Новое место. Возвращает КЛЮЧ — единственный раз, когда он виден серверу."""
        day = date.today().isoformat()
        ip = mask_ip(ip)                      # полный адрес на диск не ложится
        with self.lock:
            row = self.db.execute("SELECT n FROM ws_created WHERE day=? AND ip=?",
                                  (day, ip)).fetchone()
            n = row["n"] if row else 0
            if n >= MAX_NEW_PER_DAY:
                raise PermissionError(f"из этой сети сегодня создано {n} мест — "
                                      f"предел {MAX_NEW_PER_DAY} в сутки")
            key = new_key()
            self.db.execute("INSERT INTO workspaces VALUES (?,?,?,?,NULL)",
                            (ws_id(key), _now(), _now(), ip))
            self.db.execute("INSERT INTO ws_created VALUES (?,?,?) "
                            "ON CONFLICT(day, ip) DO UPDATE SET n = n + 1", (day, ip, 1))
            self.db.commit()
        return key

    def touch(self, key: str) -> str | None:
        """Есть ли место с таким ключом; отмечает открытие. Возвращает ws."""
        if not valid_key(key):
            return None
        w = ws_id(key)
        with self.lock:
            row = self.db.execute("SELECT 1 FROM workspaces WHERE ws=?", (w,)).fetchone()
            if row is None:
                return None
            self.db.execute("UPDATE workspaces SET last_seen=? WHERE ws=?", (_now(), w))
            self.db.commit()
        return w

    def rotate(self, ws: str) -> str:
        """Новая ссылка к тому же месту: старая перестаёт открывать."""
        key = new_key()
        with self.lock:
            nw = ws_id(key)
            for t in ("gfacts", "gdocs"):
                self.db.execute(f"UPDATE {t} SET ws=? WHERE ws=?", (nw, ws))
            self.db.execute("UPDATE workspaces SET ws=?, last_seen=? WHERE ws=?",
                            (nw, _now(), ws))
            self.db.commit()
        return key

    def delete(self, ws: str) -> None:
        with self.lock:
            for t in ("gfacts", "gdocs", "workspaces"):
                self.db.execute(f"DELETE FROM {t} WHERE ws=?", (ws,))
            self.db.commit()

    def prune(self, idle_days: int = IDLE_DAYS, today: date | None = None) -> int:
        """Удаляет места, которые не открывали `idle_days`, и суточные
        счётчики старше `COUNTER_DAYS`. Возвращает число мест."""
        today = today or date.today()
        cutoff = (today - timedelta(days=idle_days)).isoformat()
        counters = (today - timedelta(days=COUNTER_DAYS - 1)).isoformat()
        with self.lock:
            old = [r["ws"] for r in self.db.execute(
                "SELECT ws FROM workspaces WHERE last_seen < ?", (cutoff,))]
            for w in old:
                for t in ("gfacts", "gdocs", "workspaces"):
                    self.db.execute(f"DELETE FROM {t} WHERE ws=?", (w,))
            self.db.execute("DELETE FROM ws_created WHERE day < ?", (counters,))
            self.db.commit()
        return len(old)

    def info(self, ws: str) -> dict:
        with self.lock:
            row = self.db.execute("SELECT created_at, last_seen FROM workspaces WHERE ws=?",
                                  (ws,)).fetchone()
            if row is None:
                return {"exists": False}
            docs = {k: n for k, n in self.db.execute(
                "SELECT kind, COUNT(*) FROM gdocs WHERE ws=? GROUP BY kind", (ws,))}
            types = [r[0] for r in self.db.execute(
                "SELECT DISTINCT substr(key, 1, instr(key, '/') - 1) FROM gfacts "
                "WHERE ws=? AND domain='aircraft' AND valid_to IS NULL", (ws,))]
            size = self._bytes(ws)
        return {"exists": True, "created_at": row["created_at"], "last_seen": row["last_seen"],
                "docs": docs, "aircraft": sorted(types), "bytes": size,
                "limits": {"bytes": MAX_BYTES, "docs": MAX_DOCS, "idle_days": IDLE_DAYS}}

    def _bytes(self, ws: str) -> int:
        a = self.db.execute("SELECT COALESCE(SUM(LENGTH(body)), 0) FROM gdocs WHERE ws=?",
                            (ws,)).fetchone()[0]
        b = self.db.execute("SELECT COALESCE(SUM(LENGTH(key) + LENGTH(COALESCE(value_text, ''))"
                            " + LENGTH(COALESCE(note, '')) + 64), 0) FROM gfacts WHERE ws=?",
                            (ws,)).fetchone()[0]
        return int(a + b)

    def _check_room(self, ws: str, adding: int) -> None:
        if self._bytes(ws) + adding > MAX_BYTES:
            raise ValueError(f"место заполнено: предел {MAX_BYTES // 1024} КБ — удалите "
                             f"лишние сети и сценарии или сделайте экспорт")

    # ── документы ──────────────────────────────────────────────────────
    def put_doc(self, ws: str, kind: str, name: str, body: Any) -> None:
        if kind not in DOC_KINDS:
            raise ValueError(f"неизвестный вид документа {kind!r}")
        name = (name or "").strip()[:80]
        if not name:
            raise ValueError("у документа нет имени")
        text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        with self.lock:
            n = self.db.execute("SELECT COUNT(*) FROM gdocs WHERE ws=?", (ws,)).fetchone()[0]
            exists = self.db.execute("SELECT 1 FROM gdocs WHERE ws=? AND kind=? AND name=?",
                                     (ws, kind, name)).fetchone()
            if not exists and n >= MAX_DOCS:
                raise ValueError(f"в месте уже {n} документов — предел {MAX_DOCS}")
            self._check_room(ws, len(text))
            self.db.execute("INSERT INTO gdocs VALUES (?,?,?,?,?) ON CONFLICT(ws, kind, name) "
                            "DO UPDATE SET body=excluded.body, updated_at=excluded.updated_at",
                            (ws, kind, name, text, _now()))
            self.db.commit()

    def get_doc(self, ws: str, kind: str, name: str) -> Any:
        with self.lock:
            row = self.db.execute("SELECT body FROM gdocs WHERE ws=? AND kind=? AND name=?",
                                  (ws, kind, name)).fetchone()
        return json.loads(row["body"]) if row else None

    def list_docs(self, ws: str, kind: str | None = None) -> list[dict]:
        q = "SELECT kind, name, updated_at, LENGTH(body) AS bytes FROM gdocs WHERE ws=?"
        args: list = [ws]
        if kind:
            q += " AND kind=?"; args.append(kind)
        with self.lock:
            rows = self.db.execute(q + " ORDER BY kind, updated_at DESC", args).fetchall()
        return [dict(r) for r in rows]

    def delete_doc(self, ws: str, kind: str, name: str) -> bool:
        with self.lock:
            cur = self.db.execute("DELETE FROM gdocs WHERE ws=? AND kind=? AND name=?",
                                  (ws, kind, name))
            self.db.commit()
        return cur.rowcount > 0

    # ── факты ──────────────────────────────────────────────────────────
    def replace_facts(self, ws: str, domain: str, prefix: str, facts: Iterable,
                      as_of: str | None = None) -> dict:
        """Свои факты под префиксом ключа: прежние закрываются сегодняшним
        днём (append-only, как в справочнике), новые ложатся."""
        if domain not in FACT_DOMAINS:
            raise ValueError(f"домен {domain} гостю не пишется")
        today = as_of or date.today().isoformat()
        rows = []
        for f in facts:
            d = {c: getattr(f, c, None) for c in FACT_COLS}
            if d["domain"] != domain or not str(d["key"]).startswith(prefix):
                raise ValueError(f"факт {d['domain']}/{d['key']} вне {domain}/{prefix}")
            d.setdefault("valid_from", today)
            d["valid_from"] = d["valid_from"] or today
            rows.append(d)
        with self.lock:
            self._check_room(ws, sum(len(str(r["key"])) + len(str(r.get("value_text") or ""))
                                     + 64 for r in rows))
            closed = self.db.execute(
                "UPDATE gfacts SET valid_to=? WHERE ws=? AND domain=? AND key LIKE ? "
                "AND valid_to IS NULL", (today, ws, domain, prefix + "%")).rowcount
            for r in rows:
                self.db.execute(
                    f"INSERT INTO gfacts (ws, {', '.join(FACT_COLS)}, created_at) "
                    f"VALUES (?, {', '.join('?' * len(FACT_COLS))}, ?)",
                    (ws, *[r[c] for c in FACT_COLS], _now()))
            self.db.commit()
        return {"added": len(rows), "closed": closed}

    def retire_facts(self, ws: str, domain: str, prefix: str, as_of: str | None = None) -> int:
        today = as_of or date.today().isoformat()
        with self.lock:
            n = self.db.execute(
                "UPDATE gfacts SET valid_to=? WHERE ws=? AND domain=? AND key LIKE ? "
                "AND valid_to IS NULL", (today, ws, domain, prefix + "%")).rowcount
            self.db.commit()
        return n

    def facts(self, ws: str, domain: str | None = None, current_only: bool = True) -> list:
        q = "SELECT * FROM gfacts WHERE ws=?"
        args: list = [ws]
        if domain:
            q += " AND domain=?"; args.append(domain)
        if current_only:
            q += " AND valid_to IS NULL"
        with self.lock:
            return self.db.execute(q + " ORDER BY domain, key", args).fetchall()

    # ── экспорт и импорт ───────────────────────────────────────────────
    def export(self, ws: str) -> dict:
        with self.lock:
            docs = self.db.execute("SELECT kind, name, body, updated_at FROM gdocs WHERE ws=?",
                                   (ws,)).fetchall()
            facts = self.db.execute("SELECT * FROM gfacts WHERE ws=? AND valid_to IS NULL",
                                    (ws,)).fetchall()
        return {"schema": "fca.workspace/1", "exported_at": _now(),
                "docs": [{"kind": r["kind"], "name": r["name"],
                          "body": json.loads(r["body"]), "updated_at": r["updated_at"]}
                         for r in docs],
                "facts": [{c: r[c] for c in FACT_COLS} for r in facts]}

    def import_(self, ws: str, data: dict, *, merge: bool = True) -> dict:
        if not isinstance(data, dict) or data.get("schema") != "fca.workspace/1":
            raise ValueError("это не файл рабочего места fca (schema fca.workspace/1)")
        docs = data.get("docs") or []
        facts = data.get("facts") or []
        if len(docs) > MAX_DOCS:
            raise ValueError(f"в файле {len(docs)} документов — предел {MAX_DOCS}")
        n_docs = n_facts = 0
        with self.lock:
            if not merge:
                self.db.execute("DELETE FROM gdocs WHERE ws=?", (ws,))
                self.db.execute("DELETE FROM gfacts WHERE ws=?", (ws,))
            for d in docs:
                if d.get("kind") not in DOC_KINDS or not d.get("name"):
                    continue
                text = json.dumps(d.get("body"), ensure_ascii=False, separators=(",", ":"))
                self.db.execute(
                    "INSERT INTO gdocs VALUES (?,?,?,?,?) ON CONFLICT(ws, kind, name) "
                    "DO UPDATE SET body=excluded.body, updated_at=excluded.updated_at",
                    (ws, d["kind"], str(d["name"])[:80], text, d.get("updated_at") or _now()))
                n_docs += 1
            prefixes = {(f.get("domain"), str(f.get("key", "")).split("/")[0]) for f in facts}
            for dom, pref in prefixes:
                if dom in FACT_DOMAINS:
                    self.db.execute("UPDATE gfacts SET valid_to=? WHERE ws=? AND domain=? "
                                    "AND key LIKE ? AND valid_to IS NULL",
                                    (date.today().isoformat(), ws, dom, pref + "/%"))
            for f in facts:
                if f.get("domain") not in FACT_DOMAINS or not f.get("key"):
                    continue
                r = {c: f.get(c) for c in FACT_COLS}
                r["valid_from"] = r["valid_from"] or date.today().isoformat()
                r["source_id"] = r["source_id"] or "aircraft_user"
                r["extracted_by"] = r["extracted_by"] or "import:workspace@1"
                r["confidence"] = r["confidence"] or "exact"
                r["certainty"] = r["certainty"] or "exact"
                self.db.execute(
                    f"INSERT INTO gfacts (ws, {', '.join(FACT_COLS)}, created_at) "
                    f"VALUES (?, {', '.join('?' * len(FACT_COLS))}, ?)",
                    (ws, *[r[c] for c in FACT_COLS], _now()))
                n_facts += 1
            if self._bytes(ws) > MAX_BYTES:
                self.db.rollback()
                raise ValueError(f"после импорта место превысило бы {MAX_BYTES // 1024} КБ")
            self.db.commit()
        return {"docs": n_docs, "facts": n_facts}


class GuestStore:
    """Справочник с наложенным слоем гостя. Читается как `Store`.

    Своё значение главнее общего по тому же ключу; ключи, которых в слое
    нет, читаются из справочника. Запись — только через `GuestDB`: методы
    записи справочника здесь намеренно не прокинуты, чтобы гость не мог
    попасть в общее хранилище ни по какому пути.
    """

    def __init__(self, base, gdb: GuestDB, ws: str):
        self.base, self.gdb, self.ws = base, gdb, ws
        self.db = base.db                      # прямые SELECT — по справочнику
        self.path = base.path

    def __getattr__(self, name):
        if name in ("commit_facts", "retire_missing", "mark_source", "add_proposal",
                    "resolve_proposal", "put_artifact", "add_observations",
                    "mark_fetched", "ack_review"):
            raise AttributeError(f"{name}: запись в справочник из слоя гостя закрыта")
        return getattr(self.base, name)

    # ── чтение с наложением ────────────────────────────────────────────
    def _own(self, domain: str, key: str, as_of: str):
        with self.gdb.lock:
            return self.gdb.db.execute(
                """SELECT * FROM gfacts WHERE ws=? AND domain=? AND key=?
                   AND valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)
                   ORDER BY valid_from DESC, created_at DESC LIMIT 1""",
                (self.ws, domain, key, as_of, as_of)).fetchone()

    def get(self, domain, key, as_of=None):
        d = str(as_of or date.today())[:10]
        return self._own(domain, key, d) or self.base.get(domain, key, as_of)

    def latest_before(self, domain, key, before):
        with self.gdb.lock:
            row = self.gdb.db.execute(
                """SELECT * FROM gfacts WHERE ws=? AND domain=? AND key=? AND valid_from < ?
                   ORDER BY valid_from DESC, created_at DESC LIMIT 1""",
                (self.ws, domain, key, str(before))).fetchone()
        return row or self.base.latest_before(domain, key, before)

    def value_with_age(self, domain, key, as_of=None):
        d = str(as_of or date.today())[:10]
        row = self._own(domain, key, d)
        if row is not None:
            return row["value"], 0
        return self.base.value_with_age(domain, key, as_of)

    def value(self, domain, key, as_of=None, default=None):
        row = self.get(domain, key, as_of)
        return row["value"] if row else default

    def current(self, domain, as_of=None):
        out = self.base.current(domain, as_of)
        d = str(as_of or date.today())[:10]
        with self.gdb.lock:
            keys = [r[0] for r in self.gdb.db.execute(
                "SELECT DISTINCT key FROM gfacts WHERE ws=? AND domain=?", (self.ws, domain))]
        for k in keys:
            row = self._own(domain, k, d)
            if row is not None:
                out[k] = row
        return out

    def own_types(self) -> list[str]:
        return self.gdb.info(self.ws).get("aircraft", [])
