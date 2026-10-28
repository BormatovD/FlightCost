"""Статистика посещений витрины без cookie и без хранения адресов.

Что считается. Просмотры и уникальные посетители страниц (не запросов к
API) — по суткам UTC. «Уникальный посетитель» — это хеш от суточной соли,
полного адреса и строки браузера: в одни сутки один и тот же человек даёт
один и тот же хеш, а на следующие сутки соль новая, и связать два дня
нельзя. Так считают Plausible и подобные сервисы.

Что хранится. Навсегда — только счётчики: день, страница, просмотры,
уникальные. Соль и хеши текущих суток лежат в той же базе (иначе
перезапуск витрины при выкладке посреди дня удваивал бы уникальных) и
стираются при первом обращении в новые сутки. Адрес и строка браузера на
диск не пишутся никогда. Политика конфиденциальности (раздел 4) описывает
ровно это — меняете здесь, меняйте там.

Роботы (поисковики, мониторинг, curl) не считаются — по строке браузера.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

BOT = re.compile(r"bot|crawl|spider|slurp|curl|wget|python|httpx|go-http|java/|monitor|uptime|"
                 r"headless|lighthouse|preview|facebookexternalhit|embedly|scan", re.I)
ALL = "*"           # «все страницы»: уникальные за сутки по сайту целиком

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily (day TEXT, page TEXT, views INTEGER, uniques INTEGER,
                                  PRIMARY KEY (day, page));
CREATE TABLE IF NOT EXISTS salt (day TEXT PRIMARY KEY, value BLOB);
CREATE TABLE IF NOT EXISTS seen (day TEXT, page TEXT, h TEXT, PRIMARY KEY (day, page, h));
"""


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class Visits:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._lock = threading.Lock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.db.commit()

    def _salt(self, day: str) -> bytes:
        row = self.db.execute("SELECT value FROM salt WHERE day = ?", (day,)).fetchone()
        if row:
            return row[0]
        # Новые сутки: соль и хеши прошлых суток стираются — после этого
        # вчерашних посетителей уже ни с кем не сопоставить.
        self.db.execute("DELETE FROM salt")
        self.db.execute("DELETE FROM seen")
        s = os.urandom(16)
        self.db.execute("INSERT INTO salt VALUES (?, ?)", (day, s))
        return s

    def hit(self, page: str, ip: str, ua: str, day: str | None = None) -> bool:
        """Учесть просмотр страницы. False — не учтён (робот)."""
        if not ua or BOT.search(ua):
            return False
        day = day or _today()
        with self._lock:
            s = self._salt(day)
            h = hashlib.sha256(s + ip.encode() + b"\0" + ua.encode()).hexdigest()[:16]
            for p in (page, ALL):
                new = self.db.execute("INSERT OR IGNORE INTO seen VALUES (?, ?, ?)", (day, p, h)).rowcount
                self.db.execute(
                    "INSERT INTO daily VALUES (?, ?, 1, ?) ON CONFLICT(day, page) DO UPDATE SET "
                    "views = views + 1, uniques = uniques + excluded.uniques", (day, p, new))
            self.db.commit()
        return True

    def report(self, days: int = 30) -> list[tuple]:
        """(день, страница, просмотры, уникальные) за последние `days` суток, новые сверху."""
        return self.db.execute(
            "SELECT day, page, views, uniques FROM daily WHERE day >= date('now', ?) "
            "ORDER BY day DESC, page = '*' DESC, views DESC", (f"-{days} days",)).fetchall()


def stats_path(store_path: Path | str) -> Path:
    """Рядом со справочником, как user.db: в снимок `fca publish` не входит."""
    return Path(store_path).parent / "stats.db"
