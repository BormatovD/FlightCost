"""Хранилище справочных значений.

Два принципа, из которых следует всё остальное:

1. APPEND-ONLY. Ни одно значение никогда не перезаписывается. Новая ставка
   не затирает старую, а закрывает её интервал действия. Расчёт, сделанный
   в марте, воспроизводится в декабре байт в байт — это то, чего нет ни в
   одном коммерческом аналоге и что критично, если модель когда-нибудь
   будет чем-то подкреплять решение.

2. PROVENANCE. У каждого числа есть sha исходного артефакта, дата загрузки,
   и метка того, кто его извлёк — детерминированный парсер или агент.
   Числа от агента всегда отличимы от чисел от парсера.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id           INTEGER PRIMARY KEY,
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
CREATE INDEX IF NOT EXISTS ix_facts_lookup ON facts(domain, key, valid_from);

CREATE TABLE IF NOT EXISTS artifacts (
    sha        TEXT PRIMARY KEY,
    source_id  TEXT NOT NULL,
    url        TEXT,
    fetched_at TEXT NOT NULL,
    n_bytes    INTEGER,
    media_type TEXT,
    path       TEXT
);

CREATE TABLE IF NOT EXISTS source_state (
    source_id    TEXT PRIMARY KEY,
    last_checked TEXT,
    last_changed TEXT,
    last_ok      TEXT,
    status       TEXT,
    message      TEXT
);

-- Наблюдения — временной ряд, а не медленный справочник. В `facts` им
-- нельзя (решение 9, тот же довод, что был с ценами билетов): поток
-- задавит историю шумом. Сюда пишется сырое, в `facts` уезжают агрегаты.
CREATE TABLE IF NOT EXISTS observations (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       REAL NOT NULL,
    unit        TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    ref         TEXT,
    note        TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_obs_dedup
    ON observations(kind, key, ref, observed_at);
CREATE INDEX IF NOT EXISTS ix_obs_lookup ON observations(kind, key, observed_at);

CREATE TABLE IF NOT EXISTS review_ack (
    value_sha  TEXT PRIMARY KEY,
    key        TEXT NOT NULL,
    trigger    TEXT,
    acked_at   TEXT NOT NULL,
    who        TEXT,
    note       TEXT
);

CREATE TABLE IF NOT EXISTS proposals (
    id         INTEGER PRIMARY KEY,
    source_id  TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending',
    payload    TEXT NOT NULL,
    verdict    TEXT
);
"""

# Качество происхождения: откуда взялось число.
CONFIDENCE = ("exact", "derived", "estimated")

# Достоверность прочтения: насколько мы уверены, что прочли документ верно.
# Ортогонально CONFIDENCE и путать нельзя. `estimated` говорит «мы это
# посчитали сами по параметрике», `stale_edition` — «мы это списали из
# документа, но документ негоден». Первое обещано в README как ярус 3,
# второе появилось из тарифа Дохи 2015 года.
CERTAINTY = ("exact", "reading_unconfirmed", "stale_edition", "disputed")


@dataclass
class Fact:
    """Одно справочное значение с интервалом действия."""

    domain: str
    key: str
    valid_from: str
    unit: str | None = None
    value: float | None = None
    value_text: str | None = None
    currency: str | None = None
    valid_to: str | None = None
    source_id: str = ""
    artifact_sha: str | None = None
    extracted_by: str = "unknown"
    confidence: str = "exact"
    certainty: str = "exact"
    node: str | None = None          # узел карты данных
    source_note: str | None = None   # оговорка о разрешении ключа
    # Цена ошибки — числом, а не прозой (решение 75): EUR за оборот
    # эталонного A320 78 т / 148 пасс. Без числа интерфейс скажет «тут не
    # всё точно», а это украшение, не предупреждение.
    error_cost: float | None = None
    # Адресат долга (решение 76): чьё подтверждение и какой документ
    # закроют вопрос. «Подтвердить при случае» не закрывается никогда.
    confirm_by: str | None = None
    note: str | None = None

    def natural_id(self) -> str:
        return f"{self.domain}::{self.key}"


class Store:
    def __init__(self, path: str | Path = "data/flightcost.db",
                 *, shared: bool = False):
        """`shared` — соединение переживает смену потока.

        SQLite привязывает соединение к породившему потоку, а сервер даёт
        поток на запрос. Снимать привязку МОЖНО ТОЛЬКО вместе с замком на
        стороне вызывающего: `check_same_thread` отключает проверку, а не
        обеспечивает безопасность. Замок держит `serve.Context`.

        По умолчанию False: у CLI поток один, и лишняя вольность там не
        нужна — проверка, которую отключили «на всякий случай», однажды
        промолчит там, где должна была сработать.
        """
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=not shared)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._migrate()
        self.db.commit()

    def _migrate(self) -> None:
        """Добавление колонок в уже существующую базу.

        Append-only относится к значениям, а не к схеме: старые строки
        получают значения по умолчанию и остаются читаемыми.
        """
        have = {r["name"] for r in self.db.execute("PRAGMA table_info(facts)")}
        for col, ddl in (("certainty", "TEXT NOT NULL DEFAULT 'exact'"),
                         ("node", "TEXT"), ("source_note", "TEXT"),
                         ("error_cost", "REAL"), ("confirm_by", "TEXT")):
            if col not in have:
                self.db.execute(f"ALTER TABLE facts ADD COLUMN {col} {ddl}")

    # ---------- чтение ----------

    def get(self, domain: str, key: str, as_of: str | date | None = None) -> sqlite3.Row | None:
        """Значение, действовавшее на указанную дату. Сердце воспроизводимости."""
        as_of = _as_str(as_of or date.today())
        cur = self.db.execute(
            """SELECT * FROM facts
               WHERE domain = ? AND key = ?
                 AND valid_from <= ?
                 AND (valid_to IS NULL OR valid_to > ?)
               ORDER BY valid_from DESC, created_at DESC LIMIT 1""",
            (domain, key, as_of, as_of),
        )
        return cur.fetchone()

    def latest_before(self, domain: str, key: str, before: str) -> sqlite3.Row | None:
        """Последнее известное значение до указанной даты — независимо от
        того, действует оно ещё или уже истекло.

        Нужно проверке дельты. `get()` для этого не годится: у источников
        с помесячной заменой интервал истекает ровно тогда, когда
        начинается новый, поэтому на дату нового значения действующего
        предыдущего нет, и сравнение молча не выполняется.
        """
        return self.db.execute(
            """SELECT * FROM facts
               WHERE domain = ? AND key = ? AND valid_from < ?
               ORDER BY valid_from DESC, created_at DESC LIMIT 1""",
            (domain, key, _as_str(before)),
        ).fetchone()

    def value_with_age(self, domain: str, key: str, as_of=None):
        """Значение и его возраст: (value, days_expired).

        days_expired = 0 — действует. Больше нуля — интервал истёк, но
        значение последнее известное. Возвращать None вместо истёкшего
        нельзя: месячные источники стыкуются встык, и в первые дни
        месяца, пока не вышел новый документ, действующего значения
        просто не существует. Опубликованная ставка прошлого месяца
        несравнимо лучше выдуманной константы.
        """
        as_of = _as_str(as_of or date.today())
        row = self.get(domain, key, as_of)
        if row is not None:
            return row["value"], 0
        row = self.latest_before(domain, key, as_of)
        if row is None:
            return None, None
        try:
            end = row["valid_to"] or row["valid_from"]
            age = (date.fromisoformat(as_of[:10])
                   - date.fromisoformat(end[:10])).days
        except Exception:                              # noqa: BLE001
            age = 0
        return row["value"], max(age, 1)

    def value(self, domain: str, key: str, as_of=None, default=None) -> Any:
        row = self.get(domain, key, as_of)
        return row["value"] if row else default

    def current(self, domain: str, as_of=None) -> dict[str, sqlite3.Row]:
        as_of = _as_str(as_of or date.today())
        cur = self.db.execute(
            "SELECT DISTINCT key FROM facts WHERE domain = ?", (domain,)
        )
        out = {}
        for (key,) in [(r["key"],) for r in cur.fetchall()]:
            row = self.get(domain, key, as_of)
            if row is not None:
                out[key] = row
        return out

    # ---------- запись ----------

    def icao_index(self, as_of=None) -> set[str]:
        """Коды ИКАО, встречающиеся в домене `airport`.

        Домен ключуется кодом ИАТА (для аэродромов без него — местным
        идентификатором), а ИКАО лежит вторым полем `value_text`:

            key='FRA'  value_text='50.026706,8.558350|EDDF|DE|Frankfurt Main'

        Ссылочная проверка искала `select("airport", prefix="EDDF/")` и не
        находила ничего ни при каком наполнении: слэша в ключах нет вовсе.
        Отвергались все пятнадцать аэропортов, а первый ложный срабатыв
        совпал с искомым случаем и был прочитан как подтверждение
        (решение 100).

        ВРЕМЕННО. Снять, когда появится домен-указатель `airport_code`
        (решения 103, 104): тогда ИКАО станет ключом, а прочие коды —
        отдельным доменом со своей историей действия.
        """
        as_of = _as_str(as_of or date.today())
        # Указатель, если он заведён: перебор `value_text` по сорока
        # восьми тысячам строк работал, но на каждый ключ — и это была
        # временная мера до появления домена `airport_code` (решение 104).
        #
        # ОБЪЕДИНЕНИЕ, а не «указатель, иначе справочник». Указатель собран
        # из снимка IP2Location и нового аэропорта не знает: Нави-Мумбаи
        # (VANM, открыт 25.12.2025) в нём нет, а в OurAirports есть. При
        # «иначе» справочник не читался вовсе, и ссылочная проверка
        # отвергала тариф настоящего аэропорта — а с ним весь источник.
        # Проверка отвечает на вопрос «существует ли такой аэродром», и
        # знание любого из двух источников — достаточный ответ.
        idx = {r[0] for r in self.db.execute(
            """SELECT value_text FROM facts WHERE domain = 'airport_code'
               AND valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)""",
            (as_of, as_of))}
        return idx | {icao for _k, icao in self._airport_icao_pairs(as_of)}

    def _airport_icao_pairs(self, as_of) -> list[tuple[str, str]]:
        """(ключ, ИКАО) из справочника аэропортов — только настоящие коды.

        Поле ИКАО записи OurAirports бывает собственным идентификатором
        (`IN-0277`), и в указатель такое не годится. Берутся четыре буквы.
        Ключ записи — ИАТА, если он есть; иначе идентификатор OurAirports.
        """
        out = []
        for key, txt in self.db.execute(
                """SELECT key, value_text FROM facts WHERE domain = 'airport'
                   AND valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)""",
                (as_of, as_of)):
            parts = (txt or "").split("|", 2)
            icao = parts[1].strip().upper() if len(parts) >= 2 else ""
            if len(icao) == 4 and icao.isalpha() and icao.isascii():
                out.append(((key or "").upper(), icao))
        return out

    def icao_of_iata(self, as_of=None) -> dict[str, str]:
        """ИАТА -> ИКАО. Прямая сторона указателя.

        Указатель главнее; справочник аэропортов дополняет его ТОЛЬКО теми
        кодами ИАТА, которых в указателе нет (новые аэропорты). Без этого
        цены по NMI не переводились бы в VANM и не стыковались ни с чем.
        Ключ справочника — ИАТА, если он у записи есть; трёхбуквенный
        идентификатор без ИАТА от него здесь не отличить, поэтому
        дополнение не перебивает указатель никогда.
        """
        as_of = _as_str(as_of or date.today())
        out = {(key or "").split("/")[-1]: icao for key, icao in self.db.execute(
            """SELECT key, value_text FROM facts WHERE domain = 'airport_code'
               AND valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)""",
            (as_of, as_of))}
        for key, icao in self._airport_icao_pairs(as_of):
            if len(key) == 3 and key.isalpha() and key not in out:
                out[key] = icao
        return out

    def iata_of(self, as_of=None) -> dict[str, str]:
        """ИКАО -> ИАТА. Обратная сторона указателя.

        Нужна там, где внешний интерфейс говорит на ИАТА, а мы на ИКАО:
        парсер билетов, часть статистики пассажиропотока. Перевод делается
        ОДИН раз и в одном месте — иначе он расползётся по вызывающим и
        разойдётся, как это случилось с отпечатком состава.

        Один ИКАО может иметь несколько кодов ИАТА (у Базель-Мюлуза их
        три). Возвращается первый по алфавиту и это ПРОИЗВОЛЬНЫЙ выбор:
        там, где он значим, спрашивать надо весь список.
        """
        as_of = _as_str(as_of or date.today())
        out: dict[str, str] = {}
        for key, icao in self.db.execute(
                """SELECT key, value_text FROM facts WHERE domain = 'airport_code'
                   AND valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)
                   ORDER BY key""", (as_of, as_of)):
            code = (key or "").split("/")[-1]
            out.setdefault(icao, code)
        # Дополнение справочником — только для ИКАО, которых указатель не
        # знает; тот же довод, что у прямой стороны.
        for key, icao in self._airport_icao_pairs(as_of):
            if icao not in out and len(key) == 3 and key.isalpha():
                out[icao] = key
        return out

    def count_keys(self, domain: str, as_of=None) -> int:
        """Сколько ключей действует в домене. Дешёвый COUNT вместо обхода
        всех ключей через get(): на 48 тыс. аэропортов разница между одним
        запросом и сорока восемью тысячами."""
        as_of = _as_str(as_of or date.today())
        return self.db.execute(
            """SELECT COUNT(DISTINCT key) c FROM facts
               WHERE domain = ? AND valid_from <= ?
                 AND (valid_to IS NULL OR valid_to > ?)""",
            (domain, as_of, as_of),
        ).fetchone()["c"]

    @staticmethod
    def _flat(value, field: str, key: str):
        """Текстовое поле факта обязано быть текстом.

        Парсер положил в `note` список адресов из реестра, и SQLite
        отказался привязывать параметр — сообщение назвало НОМЕР
        параметра, а не поле и не источник. Причина чинится в `refresh`,
        но проверка остаётся: единственная точка записи должна называть
        то, что не приняла.
        """
        if value is None or isinstance(value, str):
            return value
        if isinstance(value, (list, tuple, set, dict)):
            raise ValueError(
                f"{key}: поле {field!r} должно быть строкой, получено "
                f"{type(value).__name__} — вероятно, парсер положил туда "
                f"значение из реестра как есть")
        return str(value)

    def commit_facts(self, facts: Iterable[Fact]) -> dict[str, int]:
        """Вставка с закрытием интервала предыдущего значения.

        Возвращает счётчики: added / unchanged. Значение считается
        неизменившимся, если совпали value, unit и currency — тогда мы
        НИЧЕГО не пишем. Это важно: иначе ежемесячный прогон за год
        раздует базу 12 копиями одного и того же числа и убьёт
        читаемость истории.
        """
        stats = {"added": 0, "unchanged": 0, "superseded": 0}
        now = datetime.utcnow().isoformat(timespec="seconds")
        for f in facts:
            if f.confidence not in CONFIDENCE:
                raise ValueError(f"bad confidence: {f.confidence}")
            if f.certainty not in CERTAINTY:
                raise ValueError(f"bad certainty: {f.certainty}")
            # Неточность без цены и без адресата — украшение. Класс
            # неоднозначности отдельным полем не хранится (решение 74):
            # он и есть значение certainty.
            if f.certainty != "exact" and (f.error_cost is None or not f.confirm_by):
                raise ValueError(
                    f"{f.key}: certainty={f.certainty} без цены ошибки или "
                    f"адресата подтверждения (решения 75 и 76)")
            prev = self.get(f.domain, f.key, f.valid_from)
            if prev is not None and _same(prev, f):
                stats["unchanged"] += 1
                continue
            if prev is not None and (prev["valid_to"] is None or prev["valid_to"] > f.valid_from):
                self.db.execute(
                    "UPDATE facts SET valid_to = ? WHERE id = ?", (f.valid_from, prev["id"])
                )
                stats["superseded"] += 1
            self.db.execute(
                """INSERT INTO facts (domain, key, value, value_text, unit, currency,
                       valid_from, valid_to, source_id, artifact_sha, extracted_by,
                       confidence, certainty, node, source_note, error_cost,
                       confirm_by, note, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (f.domain, f.key, f.value,
                 self._flat(f.value_text, "value_text", f.key), f.unit,
                 f.currency, f.valid_from, f.valid_to, f.source_id,
                 f.artifact_sha, f.extracted_by, f.confidence, f.certainty,
                 self._flat(f.node, "node", f.key),
                 self._flat(f.source_note, "source_note", f.key),
                 f.error_cost,
                 self._flat(f.confirm_by, "confirm_by", f.key),
                 self._flat(f.note, "note", f.key), now),
            )
            stats["added"] += 1
        self.db.commit()
        return stats

    def select(self, domain: str, *, suffix: str | None = None,
               prefix: str | None = None, as_of=None) -> dict[str, sqlite3.Row]:
        """Значения домена одним запросом, с провенансом.

        Долг ветки C: `heatmap.py` ходил в `db.execute` напрямую, минуя
        единственную точку чтения. `econ.py` перестал так делать на M5.
        Вреда сегодня нет — карта провенанс не показывает; он появится при
        первой попытке показать на ней «ставка из истёкшего документа».

        `current()` для этого не годится по цене: она делает `get()` на
        каждый ключ, а на 48 тыс. аэропортов это 48 тыс. запросов.
        """
        as_of = _as_str(as_of or date.today())
        sql = ["""SELECT * FROM facts WHERE domain = ? AND valid_from <= ?
                  AND (valid_to IS NULL OR valid_to > ?)"""]
        args: list = [domain, as_of, as_of]
        if suffix:
            sql.append("AND key LIKE ?"); args.append(f"%{suffix}")
        if prefix:
            sql.append("AND key LIKE ?"); args.append(f"{prefix}%")
        sql.append("ORDER BY key, valid_from, created_at")
        out: dict[str, sqlite3.Row] = {}
        for row in self.db.execute(" ".join(sql), args):
            out[row["key"]] = row        # последняя запись интервала побеждает
        return out

    def inventory(self, domain: str, as_of=None) -> dict:
        """Что вообще есть в домене: ключей, валют, единиц, достоверности.

        Второе применение перечисления: назвать, какие валюты и какие
        единицы присутствуют в хранилище, чтобы эталонный набор мог
        сказать, каких он не задействует. Без этого набор сужается молча
        (решение 89).
        """
        as_of = _as_str(as_of or date.today())
        live = """FROM facts WHERE domain = ? AND valid_from <= ?
                  AND (valid_to IS NULL OR valid_to > ?)"""
        args = (domain, as_of, as_of)
        # Пустая строка — не значение. Валюта `""` у безразмерной величины
        # (плотность в кг/л) попадала в перечень как отдельная валюта, и
        # эталонный набор честно жаловался на «валюту без маршрута» с
        # пустым именем. Проверка, ругающаяся на пустоту, учит не читать
        # свои же жалобы.
        grab = lambda col: {r[0]: r[1] for r in self.db.execute(
            f"SELECT {col}, COUNT(DISTINCT key) {live} GROUP BY {col} ORDER BY {col}",
            args) if r[0]}
        return {"keys": self.count_keys(domain, as_of),
                "currencies": grab("currency"), "units": grab("unit"),
                "certainty": grab("certainty")}

    # ---------- наблюдения ----------

    # ── что уже забрано ──────────────────────────────────────────
    # Метка живёт в той же таблице наблюдений: своя таблица ради двух
    # колонок — лишняя схема, а дедупликация тут работает ровно так же.
    # Вид `_fetched`, ключ «аэропорт/вид», момент — сутки забора.
    FETCH_MARK = "_fetched"

    def mark_fetched(self, day: str, pairs, *, source_id: str) -> int:
        rows = [dict(kind=self.FETCH_MARK, key=f"{a}/{k}", value=1.0,
                     unit="забор", observed_at=str(day)[:10],
                     source_id=source_id, ref=None, note=None)
                for a, k in pairs]
        return self.add_observations(rows)["added"]

    def fetched_marks(self, day: str) -> set[tuple[str, str]]:
        """Пары «аэропорт, вид», уже забранные за эти сутки."""
        out = set()
        for (key,) in self.db.execute(
                "SELECT key FROM observations WHERE kind = ? AND observed_at = ?",
                (self.FETCH_MARK, str(day)[:10])):
            a, _, k = (key or "").partition("/")
            if a and k:
                out.add((a, k))
        return out

    def unfetched_days(self, airports, back: int = 7, today=None) -> list[str]:
        """Сутки за последние `back` дней, где забрано не всё.

        Вчерашние идут первыми: они полнее всего и дольше всех ждут.
        Сегодняшние не берём — сутки ещё не закончились.
        """
        today = date.fromisoformat(_as_str(today)) if today else date.today()
        want = {(a, k) for a in airports for k in ("departure", "arrival")}
        out = []
        for i in range(1, back + 1):
            d = (today - timedelta(days=i)).isoformat()
            if self.fetched_marks(d) < want:
                out.append(d)
        return out

    def add_observations(self, rows: Iterable[dict]) -> dict:
        """Сырые наблюдения. Повторный забор того же рейса не удваивает ряд.

        Дедупликация по (вид, ключ, борт, момент): поток забирается
        перекрывающимися окнами, иначе пропуск на границе, а с
        перекрытием — двойной счёт.
        """
        added = dup = 0
        for r in rows:
            try:
                self.db.execute(
                    """INSERT INTO observations
                       (kind, key, value, unit, observed_at, source_id, ref, note)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (r["kind"], r["key"], float(r["value"]), r["unit"],
                     r["observed_at"], r.get("source_id", ""), r.get("ref"),
                     r.get("note")))
                added += 1
            except sqlite3.IntegrityError:
                dup += 1
        self.db.commit()
        return {"added": added, "duplicate": dup}

    def observation_stats(self, kind: str, key: str, *, since: str | None = None):
        rows = self.db.execute(
            """SELECT value FROM observations
               WHERE kind = ? AND key = ? AND (? IS NULL OR observed_at >= ?)""",
            (kind, key, since, since)).fetchall()
        return [r["value"] for r in rows]

    def observation_keys(self, kind: str, *, since: str | None = None) -> dict[str, int]:
        return {r["key"]: r["n"] for r in self.db.execute(
            """SELECT key, COUNT(*) n FROM observations
               WHERE kind = ? AND (? IS NULL OR observed_at >= ?)
               GROUP BY key ORDER BY key""", (kind, since, since))}

    def prune_observations(self, before: str) -> int:
        """Свой срок хранения: сырое стареет, агрегаты остаются."""
        cur = self.db.execute("DELETE FROM observations WHERE observed_at < ?",
                              (_as_str(before),))
        self.db.commit()
        return cur.rowcount

    def ack_review(self, value_sha: str, key: str, trigger: str,
                   who: str, note: str = "") -> None:
        """Человек посмотрел эту строку и принял её.

        Разрешение привязано к ОТПЕЧАТКУ ЗНАЧЕНИЯ, а не к ключу: если
        ставка изменится, кандидат обязан всплыть заново. Иначе принятое
        однажды становится непроверяемым навсегда.
        """
        self.db.execute(
            """INSERT OR REPLACE INTO review_ack
               (value_sha, key, trigger, acked_at, who, note) VALUES (?,?,?,?,?,?)""",
            (value_sha, key, trigger,
             datetime.utcnow().isoformat(timespec="seconds"), who, note))
        self.db.commit()

    def acked(self) -> set:
        return {r["value_sha"] for r in
                self.db.execute("SELECT value_sha FROM review_ack")}

    def composition(self, extra: dict | None = None) -> dict:
        """Состав хранилища и его отпечаток (решение 81).

        Редакция называется продуктом, а не от руки в отчёте: договорённость
        «указывайте, на чём получены числа» не сработала дважды в тот же
        день, когда была принята. Отпечаток считается по тому, что реально
        стоит, а не по тому, что помнит автор отчёта.

        `extra` — счётчики соседних веток (шаги трассировки, узлы карты,
        поля отчёта). Свои они считают сами, отпечаток общий.
        """
        cols = [r["name"] for r in self.db.execute("PRAGMA table_info(facts)")]
        by_dom = {r["domain"]: r["c"] for r in self.db.execute(
            """SELECT domain, COUNT(DISTINCT key) c FROM facts
               WHERE valid_to IS NULL GROUP BY domain ORDER BY domain""")}
        cert = {r["certainty"]: r["c"] for r in self.db.execute(
            """SELECT certainty, COUNT(*) c FROM facts
               WHERE valid_to IS NULL GROUP BY certainty ORDER BY certainty""")}
        out = {
            "schema_facts": cols,
            "keys_by_domain": by_dom,
            "certainty": cert,
            "unpriced_caveats": self.db.execute(
                """SELECT COUNT(*) c FROM facts WHERE valid_to IS NULL
                   AND certainty != 'exact' AND error_cost IS NULL""").fetchone()["c"],
            **(extra or {}),
        }
        out["fingerprint"] = hashlib.sha256(
            json.dumps(out, sort_keys=True, ensure_ascii=False,
                       default=str).encode()).hexdigest()[:12]
        return out

    def retire_missing(self, domain: str, source_id: str, *,
                       prefixes: Iterable[str], keep: Iterable[str],
                       as_of: str | None) -> list[str]:
        """Третье состояние факта: ключ перестал существовать.

        Не редакция (значение не менялось) и не исправление (интервал не
        тот же): ключа больше нет в полном разборе того же источника.
        Без этого состояния переход на ключ по содержанию оставляет старые
        записи с valid_to = NULL навсегда, и `load_rules` читает обе
        поставки — сумма удваивается молча.

        `prefixes` — документы, разобранные ПОЛНОСТЬЮ (решение 63).
        Отвергнутый документ ничего не снимает: иначе одна опечатка в
        файле стёрла бы весь аэропорт.

        Дата закрытия берётся из ПРИЧИНЫ, а не из календаря (решение 62):

        * `as_of=None` — артефакт тот же, изменился наш разбор. Запись
          аннулируется на всём своём интервале: её не было в мире, она
          была у нас в голове. Иначе расчёт на прошлую дату продолжает
          читать обе поставки и удваивает сумму — проверено на Вене,
          12 438,66 против 6 256,83 на 1 февраля.
        * `as_of=дата` — артефакт другой, строка исчезла в новой редакции.
          Интервал закрывается датой этой редакции.
        """
        keep = set(keep)
        pref = tuple(f"{p}/" for p in prefixes)
        if not pref:
            return []
        rows = self.db.execute(
            """SELECT id, key, valid_from FROM facts
               WHERE domain = ? AND source_id = ? AND valid_to IS NULL""",
            (domain, source_id)).fetchall()
        gone = [r for r in rows
                if r["key"].startswith(pref) and r["key"] not in keep]
        for r in gone:
            self.db.execute(
                "UPDATE facts SET valid_to = ? WHERE id = ?",
                (_as_str(as_of) if as_of is not None else r["valid_from"], r["id"]))
        self.db.commit()
        return sorted({r["key"] for r in gone})

    def put_artifact(self, source_id: str, url: str | None, blob: bytes,
                     media_type: str | None = None, raw_dir="data/raw") -> str:
        """Сохраняет сырой файл под адресом его хэша. Позволяет перепарсить
        прошлогодний циркуляр, не выкачивая его заново, и доказать, откуда
        взялось число."""
        sha = hashlib.sha256(blob).hexdigest()
        d = Path(raw_dir) / source_id
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{sha[:16]}.bin"
        if not p.exists():
            p.write_bytes(blob)
        self.db.execute(
            """INSERT OR IGNORE INTO artifacts (sha, source_id, url, fetched_at,
                   n_bytes, media_type, path) VALUES (?,?,?,?,?,?,?)""",
            (sha, source_id, url, datetime.utcnow().isoformat(timespec="seconds"),
             len(blob), media_type, str(p)),
        )
        self.db.commit()
        return sha

    def artifact_seen(self, source_id: str, sha: str) -> bool:
        return self.db.execute(
            "SELECT 1 FROM artifacts WHERE source_id = ? AND sha = ?", (source_id, sha)
        ).fetchone() is not None

    # ---------- состояние источников ----------

    def mark_source(self, source_id: str, *, status: str, message: str = "",
                    changed: bool = False) -> None:
        now = datetime.utcnow().isoformat(timespec="seconds")
        row = self.db.execute(
            "SELECT * FROM source_state WHERE source_id = ?", (source_id,)
        ).fetchone()
        last_changed = now if changed else (row["last_changed"] if row else None)
        last_ok = now if status == "ok" else (row["last_ok"] if row else None)
        self.db.execute(
            """INSERT INTO source_state (source_id, last_checked, last_changed, last_ok, status, message)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(source_id) DO UPDATE SET
                 last_checked=excluded.last_checked, last_changed=excluded.last_changed,
                 last_ok=excluded.last_ok, status=excluded.status, message=excluded.message""",
            (source_id, now, last_changed, last_ok, status, message),
        )
        self.db.commit()

    def source_state(self, source_id: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM source_state WHERE source_id = ?", (source_id,)
        ).fetchone()

    # ---------- предложения на ревью ----------

    def add_proposal(self, source_id: str, payload: dict) -> int:
        cur = self.db.execute(
            "INSERT INTO proposals (source_id, created_at, payload) VALUES (?,?,?)",
            (source_id, datetime.utcnow().isoformat(timespec="seconds"),
             json.dumps(payload, ensure_ascii=False, default=str)),
        )
        self.db.commit()
        return cur.lastrowid

    def pending_proposals(self) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM proposals WHERE status = 'pending' ORDER BY created_at"
        ).fetchall()

    def resolve_proposal(self, pid: int, accept: bool, verdict: str = "") -> list[Fact]:
        row = self.db.execute("SELECT * FROM proposals WHERE id = ?", (pid,)).fetchone()
        if row is None:
            raise KeyError(pid)
        self.db.execute(
            "UPDATE proposals SET status = ?, verdict = ? WHERE id = ?",
            ("accepted" if accept else "rejected", verdict, pid),
        )
        self.db.commit()
        if not accept:
            # Отклонение — тоже событие, и оно не успех: данные источника
            # остались прежними, а `last_ok` двигать не за что.
            self.mark_source(row["source_id"], status="rejected",
                             message=f"отклонено #{pid}: {verdict}".strip(": "))
            return []
        payload = json.loads(row["payload"])
        facts = [Fact(**d) for d in payload["facts"]]
        self.commit_facts(facts)
        # Приёмка человеком — та же поставка, что автоматическая, и снятие
        # с учёта относится к ней так же (решение 61). Без этого старые
        # ключи оставались открытыми рядом с новыми, а сумма удваивалась.
        ret = payload.get("retire")
        if ret and ret.get("prefixes"):
            self.retire_missing(ret["domain"], row["source_id"],
                                prefixes=ret["prefixes"],
                                keep={f.key for f in facts}, as_of=None)
        # Отметить источник ОБЯЗАТЕЛЬНО. Прежде приёмка не трогала
        # состояние, и в `fca status` навсегда оставалось «proposal #9» —
        # сообщение о событии, которое давно закрыто. Столбец описывает
        # последнее событие, поэтому событие приёмки должно в нём быть.
        self.mark_source(row["source_id"], status="ok", changed=True,
                         message=f"принято #{pid}: фактов {len(facts)}")
        return facts


def _same(prev, f: Fact) -> bool:
    """Совпадает ли новая запись с действующей настолько, чтобы не писать.

    Сравнивалось только значение: число, единица, валюта, текст. Узел карты
    и достоверность в сравнение не входили, и исправление провенанса не
    доезжало до хранилища НИКОГДА: разбор с узлом давал «931 без
    изменений», приёмка пропускалась, и факты навсегда оставались без
    узла. Так же молча терялось бы подтверждение прочтения —
    `reading_unconfirmed → exact` при том же числе.

    Свободный текст (`note`, `source_note`) по-прежнему не сравнивается:
    переформулировка пояснения в парсере не должна переписывать историю.
    Сравниваются поля, которые ЧИТАЕТ механизм: узел — сверка карты,
    достоверность, цена ошибки и адресат — оговорки отчёта.
    Новая запись при этом ложится на тот же интервал и побеждает при
    чтении как более поздняя — исправление кодирования, а не событие в
    мире (решение 64).
    """
    return (
        _close(prev["value"], f.value)
        and (prev["unit"] or None) == (f.unit or None)
        and (prev["currency"] or None) == (f.currency or None)
        and (prev["value_text"] or None) == (f.value_text or None)
        and (prev["node"] or None) == (f.node or None)
        and (prev["certainty"] or "exact") == (f.certainty or "exact")
        and _close(prev["error_cost"], f.error_cost)
        and (prev["confirm_by"] or None) == (f.confirm_by or None)
    )


def _close(a, b, eps=1e-9) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= eps * max(1.0, abs(a), abs(b))


def _as_str(d) -> str:
    return d.isoformat() if isinstance(d, (date, datetime)) else str(d)
