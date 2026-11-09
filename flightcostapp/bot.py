"""Телеграм-бот FlightCost: приём данных от людей и пульт владельца.

Две стороны одного бота (чекап, раздел 4):

* **Для людей с данными.** Тариф аэропорта, данные по типу, ошибка в
  расчёте, ставки лизинга и ТОиР. Документ или ссылка, три вопроса
  (что это, откуда, на какую дату), как можно использовать, подпись по
  желанию. Ответ — когда данные приняты или отклонены, с причиной.
* **Для владельца.** Карточка каждого присланного с кнопками, очередь
  приёмки справочника (`fca review`) кнопками, сообщения таймеров и
  агентов из общего ящика (notify.py).

Что бот обещает (и что держит tests/test_bot.py):

* модели здесь нет — бот ничего не «понимает» в присланном, а значит, его
  нельзя уговорить текстом в документе;
* имя и ник не сохраняются; идентификатор чата хранится, только пока на
  присланное не ответили (и не дольше REPLY_KEEP_DAYS), потом стирается;
* предел отправок в сутки считается по хешу с суточной солью, которая
  живёт только в памяти, — между сутками человека не связать;
* файлы — только PDF, XLSX, CSV и картинки, до 20 МБ; присланное не
  исполняется и не открывается ничем, кроме разбора текста;
* ставки лизинга и ТОиР хранятся «только для проверки» всегда.

Запуск: `python -m flightcostapp.bot` (служба fca-bot.service).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from queue import Empty, Queue
from dataclasses import dataclass, field
from pathlib import Path

from .tg import Bot, TgError, load_token

HOME = Path(os.environ.get("FCA_BOT_DIR", "/srv/fca/bot"))
SPOOL = Path(os.environ.get("FCA_SPOOL", "/srv/fca/spool"))
AGENT_QUEUE = Path(os.environ.get("FCA_AGENT_QUEUE", "/srv/fca/agent/queue"))
AGENT_OUT = Path(os.environ.get("FCA_AGENT_OUT", "/srv/fca/agent/out"))
# Откуда бот вправе прикладывать файлы к сообщениям из ящика. Иначе
# строка «attach» в чужом JSON превратилась бы в чтение любого файла,
# доступного пользователю бота.
ATTACH_ROOTS = (AGENT_OUT, HOME / "files")

ALLOWED_EXT = {".pdf", ".xlsx", ".csv", ".png", ".jpg", ".jpeg"}
MAX_FILE = 20 * 1024 * 1024
MAX_FILES = 5
PER_DAY = 5                 # отправок в сутки от одного чата
# Общие пределы на всех: предел на чат обходится новыми аккаунтами, а сервер
# общий (рядом игра). Счёт общий, не по людям — его можно хранить на диске.
DAY_SUBMISSIONS = 40
DAY_BYTES = 300 * 1024 * 1024
MIN_FREE_BYTES = 3 * 1024 ** 3
REPLY_KEEP_DAYS = 90        # дольше без ответа чат не держим
DRAFT_TTL = 3600            # незаконченная анкета живёт час, в памяти
SNAPSHOT_QUIET = 90         # снимок витрине — через столько секунд после последней приёмки
TEXT_MAX = 1000

# idea — предложение в план работ: только текст, без вопросов про источник и
# дату, агенту не уходит; подпись автора — для вкладки «План работ» на сайте.
KINDS = ("tariff", "aircraft", "error", "rates", "idea")
TEXT_ONLY = ("error", "idea")
USAGE = ("publish", "check")


# ── тексты ───────────────────────────────────────────────────────────────
T = {
    "ru": {
        "hello": ("Здравствуйте! Это бот проекта FlightCost (flightcost.app) — открытой модели "
                  "экономики авиамаршрутов.\n\nСюда можно прислать данные, которых нам не хватает, "
                  "сообщить об ошибке или предложить работу в план. Что у вас?"),
        "k_tariff": "Тариф аэропорта", "k_aircraft": "Данные по типу ВС",
        "k_error": "Ошибка в расчёте", "k_rates": "Ставки: лизинг, ТОиР",
        "k_idea": "Предложение в план работ",
        "ask_doc": ("Пришлите документ (PDF, XLSX, CSV, картинка, до 20 МБ) или ссылку на него. "
                    "Можно несколько файлов. Когда закончите — нажмите «Дальше»."),
        "ask_doc_error": "Опишите ошибку: маршрут, тип, что не так. Можно приложить снимок экрана или ссылку на расчёт.",
        "ask_doc_idea": ("Опишите предложение: что посчитать, исследовать или исправить и зачем. "
                         "Можно приложить файл или ссылку. Когда закончите — нажмите «Дальше»."),
        "idea_note": ("Принятые предложения попадают в план работ на сайте. Подпись автора — "
                      "как укажете на следующем шаге, или без подписи."),
        "next": "Дальше", "skip": "Пропустить", "cancel": "Отменить", "send": "Отправить",
        "got_file": "Файл получен ({n}). Ещё один или «Дальше».",
        "bad_file": "Этот формат не принимаю: только PDF, XLSX, CSV, PNG, JPG.",
        "big_file": "Файл больше 20 МБ — пришлите, пожалуйста, ссылку.",
        "too_many": "Больше пяти файлов в одной отправке не принимаю.",
        "need_doc": "Нужен хотя бы один файл, ссылка или описание.",
        "q_what": "1/3. Что это? (например: «тариф аэропорта Пулково на 2026 год»)",
        "q_origin": "2/3. Откуда? (издатель документа, ссылка или «мой собственный расчёт»)",
        "q_date": "3/3. На какую дату действует? (например: 2026-01-01 или «с 1 апреля 2026»)",
        "q_usage": ("Как можно использовать?\n\n• «Публиковать» — с указанием источника; данные сайта "
                    "идут под лицензией CC BY 4.0.\n• «Только для проверки» — сверяем расчёт, нигде не "
                    "показываем и в открытый репозиторий не кладём."),
        "u_publish": "Публиковать с источником", "u_check": "Только для проверки",
        "rates_check": "Ставки лизинга и ТОиР храним только для проверки — они нигде не публикуются.",
        "q_author": "Подписать? Напишите, как указать автора, или «Пропустить» — тогда анонимно.",
        "confirm": ("Проверьте и отправьте:\n\n{card}\n\nОтправляя, вы соглашаетесь: файлы и ответы хранятся "
                    "на нашем сервере; документы может прочитать модель Claude (Anthropic, США), чтобы "
                    "подготовить черновик разбора, — решение принимает человек. /privacy — подробнее."),
        "thanks": ("Спасибо! Принято под номером #{id}. Мы проверим и ответим здесь. "
                   "Чат храним только до ответа."),
        "limit": "На сегодня отправок достаточно — пожалуйста, продолжите завтра.",
        "busy": "Сегодня бот принял слишком много — пожалуйста, пришлите завтра или напишите на почту из Impressum.",
        "cancelled": "Отменено. /start — начать заново.",
        "expired": "Анкета устарела. /start — начать заново.",
        "accepted": "Ваша отправка #{id} принята: {what}. Спасибо! Данные появятся в расчёте после проверки.",
        "rejected": "Ваша отправка #{id} ({what}) не принята. Причина: {why}",
        "privacy": ("Что бот хранит: присланные файлы и ответы на вопросы; номер чата — только до "
                    "нашего ответа (не дольше 90 дней). Имя и ник не сохраняем. Документы может прочитать "
                    "модель Claude (Anthropic) для черновика разбора; Anthropic не обучает на них модели. "
                    "Отозвать согласие и удалить присланное — письмом по адресу из Impressum. Подробнее: "
                    "https://flightcost.app/datenschutz"),
    },
    "en": {
        "hello": ("Hello! This is the FlightCost bot (flightcost.app) — an open model of airline "
                  "route economics.\n\nYou can send us data we are missing or report an error or suggest work for the plan. What do you have?"),
        "k_tariff": "Airport charges", "k_aircraft": "Aircraft type data",
        "k_error": "Error in a calculation", "k_rates": "Rates: lease, MRO",
        "k_idea": "Suggestion for the work plan",
        "ask_doc": ("Send a document (PDF, XLSX, CSV, image, up to 20 MB) or a link to it. Several files "
                    "are fine. Press “Next” when done."),
        "ask_doc_error": "Describe the error: route, type, what is wrong. A screenshot or link to the calculation helps.",
        "ask_doc_idea": ("Describe your suggestion: what to calculate, research or fix, and why. "
                         "A file or link is welcome. Press “Next” when done."),
        "idea_note": ("Accepted suggestions go into the work plan on the site, credited as you choose "
                      "in the next step, or without credit."),
        "next": "Next", "skip": "Skip", "cancel": "Cancel", "send": "Send",
        "got_file": "File received ({n}). Another one or “Next”.",
        "bad_file": "I can't take this format: PDF, XLSX, CSV, PNG, JPG only.",
        "big_file": "The file is over 20 MB — please send a link instead.",
        "too_many": "Up to five files per submission.",
        "need_doc": "Please add at least one file, link or description.",
        "q_what": "1/3. What is it? (e.g. “Pulkovo airport charges 2026”)",
        "q_origin": "2/3. Where is it from? (publisher, link, or “my own calculation”)",
        "q_date": "3/3. Valid as of which date? (e.g. 2026-01-01 or “from 1 April 2026”)",
        "q_usage": ("How may we use it?\n\n• “Publish” — with attribution; site data is licensed CC BY 4.0.\n"
                    "• “Check only” — used to verify calculations, never shown and never put in the public repository."),
        "u_publish": "Publish with source", "u_check": "Check only",
        "rates_check": "Lease and MRO rates are always kept check-only — they are never published.",
        "q_author": "Credit you? Type how to name the author, or “Skip” to stay anonymous.",
        "confirm": ("Please check and send:\n\n{card}\n\nBy sending you agree: files and answers are stored on "
                    "our server; documents may be read by the Claude model (Anthropic, USA) to draft an "
                    "extraction — a human decides. /privacy for details."),
        "thanks": ("Thank you! Received as #{id}. We will check it and reply here. "
                   "We keep this chat only until we reply."),
        "limit": "That's enough submissions for today — please continue tomorrow.",
        "busy": "The bot has received too much today — please send it tomorrow or email the address in our Impressum.",
        "cancelled": "Cancelled. /start to begin again.",
        "expired": "This form has expired. /start to begin again.",
        "accepted": "Your submission #{id} was accepted: {what}. Thank you! It will be used after review.",
        "rejected": "Your submission #{id} ({what}) was not accepted. Reason: {why}",
        "privacy": ("What the bot stores: your files and answers; the chat id only until we reply "
                    "(at most 90 days). We don't store your name or username. Documents may be read by the "
                    "Claude model (Anthropic) to draft an extraction; Anthropic does not train on them. To "
                    "withdraw consent and delete your submission, email the address in our Impressum. Details: "
                    "https://flightcost.app/datenschutz"),
    },
}
REJECT_REASONS = {
    "nosrc": ("нет источника", "no source given"),
    "dup": ("эти данные уже есть", "we already have this data"),
    "old": ("документ устарел", "the document is outdated"),
    "scope": ("вне задач проекта", "outside the project's scope"),
}


def lang_of(user: dict | None) -> str:
    code = ((user or {}).get("language_code") or "").lower()
    return "ru" if code[:2] in ("ru", "uk", "be", "kk") else "en"


# ── хранилище ────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    lang TEXT NOT NULL,
    kind TEXT NOT NULL,
    what TEXT, origin TEXT, as_of TEXT,
    usage TEXT NOT NULL,
    author TEXT,
    note TEXT,
    files TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'new',
    verdict TEXT,
    answered_at TEXT,
    reply_chat INTEGER
);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""


class Db:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    def get(self, k, default=None):
        r = self.db.execute("SELECT v FROM kv WHERE k = ?", (k,)).fetchone()
        return r[0] if r else default

    def put(self, k, v):
        self.db.execute("INSERT INTO kv VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v", (k, str(v)))
        self.db.commit()

    def add(self, d: "Draft", chat_id: int) -> int:
        cur = self.db.execute(
            "INSERT INTO submissions (created_at, lang, kind, what, origin, as_of, usage, author, "
            "note, files, reply_chat) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), d.lang, d.kind, d.what, d.origin,
             d.as_of, d.usage, d.author, "\n".join(d.notes)[:4000], "[]", chat_id))
        self.db.commit()
        return cur.lastrowid

    def sub(self, sid: int):
        return self.db.execute("SELECT * FROM submissions WHERE id = ?", (sid,)).fetchone()

    def resolve(self, sid: int, status: str, verdict: str):
        """Решение по отправке; номер чата стирается в той же транзакции."""
        self.db.execute("UPDATE submissions SET status = ?, verdict = ?, answered_at = ?, "
                        "reply_chat = NULL WHERE id = ?",
                        (status, verdict, time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), sid))
        self.db.commit()

    def forget_old_chats(self, days: int = REPLY_KEEP_DAYS) -> int:
        n = self.db.execute("UPDATE submissions SET reply_chat = NULL WHERE reply_chat IS NOT NULL "
                            "AND created_at < datetime('now', ?)", (f"-{days} days",)).rowcount
        self.db.commit()
        return n


# ── анкета ───────────────────────────────────────────────────────────────
@dataclass
class Draft:
    lang: str
    step: str = "kind"
    kind: str = ""
    files: list = field(default_factory=list)       # (file_id, ext, size, name)
    notes: list = field(default_factory=list)       # ссылки и текст
    what: str = ""
    origin: str = ""
    as_of: str = ""
    usage: str = ""
    author: str = ""
    touched: float = field(default_factory=time.time)


def _clean(s: str | None) -> str:
    s = (s or "").replace("\x00", "").strip()
    return re.sub(r"[‪-‮⁦-⁩]", "", s)[:TEXT_MAX]


def card(d, lang="ru", sid: int | None = None) -> str:
    """Карточка отправки — одна и та же для автора и для владельца."""
    kind = T[lang][f"k_{d['kind'] if isinstance(d, sqlite3.Row) else d.kind}"]
    g = (lambda k: d[k]) if isinstance(d, sqlite3.Row) else (lambda k: getattr(d, k))
    files = json.loads(d["files"]) if isinstance(d, sqlite3.Row) else d.files
    usage = T[lang]["u_publish" if g("usage") == "publish" else "u_check"] if g("usage") else "—"
    notes = g("note") if isinstance(d, sqlite3.Row) else "\n".join(d.notes)
    lines = [(f"#{sid} " if sid else "") + kind,
             f"• {'что' if lang == 'ru' else 'what'}: {g('what') or '—'}",
             f"• {'откуда' if lang == 'ru' else 'from'}: {g('origin') or '—'}",
             f"• {'дата' if lang == 'ru' else 'as of'}: {g('as_of') or '—'}",
             f"• {'использование' if lang == 'ru' else 'use'}: {usage}",
             f"• {'автор' if lang == 'ru' else 'author'}: {g('author') or ('анонимно' if lang == 'ru' else 'anonymous')}",
             f"• {'файлов' if lang == 'ru' else 'files'}: {len(files)}"]
    if notes:
        lines.append(("ссылки и текст:\n" if lang == "ru" else "links and text:\n") + notes[:1500])
    return "\n".join(lines)


def plan_entry(row) -> str:
    """Готовая запись для data/plan.yaml по принятому предложению. Владелец
    правит формулировку и область и вставляет её коммитом: бот в репозиторий
    не пишет (у него нет и не должно быть доступа к коду сайта)."""
    text = " ".join((row["note"] or row["what"] or "").split())[:300]
    author = row["author"] or ""
    q = lambda s: json.dumps(s, ensure_ascii=False)                  # noqa: E731 — строка YAML в кавычках
    return ("📝 Запись для data/plan.yaml (проверьте area и формулировку):\n\n"
            f"  - id: bot-{row['id']}\n"
            "    status: next\n"
            "    area: calc\n"
            "    title:\n"
            f"      ru: {q(text)}\n"
            f"    by: {q(author) if author else 'owner'}\n"
            f"    via: \"bot #{row['id']}\"\n"
            f"    added: {time.strftime('%Y-%m-%d', time.gmtime())}\n"
            + ("" if author else "\n(автор не подписался — в плане будет «автор проекта»; при желании "
               "впишите «участник сообщества»)"))


# ── бот ──────────────────────────────────────────────────────────────────
class FcaBot:
    def __init__(self, bot: Bot, owner: int, *, home: Path = HOME, review_db: str | None = None,
                 after_accept: str | None = None):
        self.bot, self.owner, self.home = bot, int(owner), home
        self.db = Db(home / "bot.db")
        self.review_db = review_db
        self.after_accept = after_accept
        self.drafts: dict[int, Draft] = {}
        self.owner_wait: dict | None = None        # ждём текст причины отказа
        self._salt_day, self._salt, self._count = "", b"", {}
        self._busy_told = False
        # Медленное (fca review по базе в сотни МБ, снимок витрине) — в
        # отдельном потоке: иначе бот минутами не отвечает никому. Снимок
        # после приёмки один на серию: собирается через SNAPSHOT_QUIET с
        # последнего «принять», а не после каждого.
        self.jobs: Queue = Queue()
        self.snapshot_due = 0.0
        self._lock = threading.Lock()

    # ── предел отправок: суточная соль только в памяти ──────────────────
    def _rate_key(self, chat_id: int) -> str:
        day = time.strftime("%Y-%m-%d", time.gmtime())
        if day != self._salt_day:
            self._salt_day, self._salt, self._count = day, os.urandom(16), {}
        return hashlib.sha256(self._salt + str(chat_id).encode()).hexdigest()[:16]

    def _over_limit(self, chat_id: int) -> bool:
        return self._count.get(self._rate_key(chat_id), 0) >= PER_DAY

    def _counted(self, chat_id: int):
        k = self._rate_key(chat_id)
        self._count[k] = self._count.get(k, 0) + 1

    # ── цикл ─────────────────────────────────────────────────────────────
    def _worker(self):
        while True:
            try:
                job = self.jobs.get(timeout=5)
            except Empty:
                job = None
            if job is not None:
                try:
                    job()
                except Exception as e:                               # noqa: BLE001
                    try:
                        self.bot.send(self.owner, f"⚠️ служебная операция не удалась: {type(e).__name__}: {e}"[:3000])
                    except TgError:
                        pass
                continue
            with self._lock:
                due = self.snapshot_due and time.time() - self.snapshot_due > SNAPSHOT_QUIET
                if due:
                    self.snapshot_due = 0.0
            if due and self.after_accept:
                self.bot.send(self.owner, "⏳ собираю снимок витрине с принятым…")
                r = subprocess.run(self.after_accept, shell=True, capture_output=True, text=True, timeout=3600)
                self.bot.send(self.owner, ("✅ витрина обновится через минуту" if r.returncode == 0
                                           else "публикация не прошла") + f"\n{(r.stdout + r.stderr)[-1500:]}")

    def run_forever(self):
        threading.Thread(target=self._worker, daemon=True).start()
        offset = int(self.db.get("offset", 0)) or None
        last_spool = last_clean = 0.0
        while True:
            try:
                ups = self.bot.updates(offset, wait=25)
            except TgError as e:
                print(f"getUpdates: {e}", file=sys.stderr)
                time.sleep(10)
                ups = []
            for u in ups:
                offset = u["update_id"] + 1
                try:
                    self.handle(u)
                except Exception as e:                           # noqa: BLE001
                    print(f"обработка {u.get('update_id')}: {type(e).__name__}: {e}", file=sys.stderr)
                self.db.put("offset", offset)
            now = time.time()
            if now - last_spool > 20:
                self.drain_spool()
                last_spool = now
            if now - last_clean > 6 * 3600:
                self.db.forget_old_chats()
                self.drafts = {k: v for k, v in self.drafts.items() if now - v.touched < DRAFT_TTL}
                last_clean = now

    def handle(self, u: dict):
        if "callback_query" in u:
            return self.on_button(u["callback_query"])
        m = u.get("message")
        if not m or m.get("chat", {}).get("type") != "private":
            return                                  # группы и каналы не обслуживаем
        chat = m["chat"]["id"]
        if chat == self.owner and self.on_owner_message(m):
            return
        self.on_user_message(chat, m)

    # ── сторона человека ─────────────────────────────────────────────────
    def _start(self, chat: int, lang: str):
        self.drafts[chat] = Draft(lang=lang)
        t = T[lang]
        self.bot.send(chat, t["hello"], [[{"text": t["k_tariff"], "callback_data": "k:tariff"}],
                                         [{"text": t["k_aircraft"], "callback_data": "k:aircraft"}],
                                         [{"text": t["k_error"], "callback_data": "k:error"}],
                                         [{"text": t["k_rates"], "callback_data": "k:rates"}],
                                         [{"text": t["k_idea"], "callback_data": "k:idea"}]])

    def on_user_message(self, chat: int, m: dict):
        lang = lang_of(m.get("from"))
        text = _clean(m.get("text") or m.get("caption"))
        if text in ("/start", "/new"):
            return self._start(chat, lang)
        if text in ("/privacy", "/datenschutz"):
            return self.bot.send(chat, T[lang]["privacy"])
        d = self.drafts.get(chat)
        if d is None:
            return self._start(chat, lang)
        t = T[d.lang]
        if time.time() - d.touched > DRAFT_TTL:
            self.drafts.pop(chat, None)
            return self.bot.send(chat, t["expired"])
        d.touched = time.time()
        if d.step == "doc":
            doc = m.get("document")
            photo = (m.get("photo") or [None])[-1]
            if doc or photo:
                if len(d.files) >= MAX_FILES:
                    return self.bot.send(chat, t["too_many"])
                if doc:
                    name = _clean(doc.get("file_name")) or "file"
                    ext = Path(name).suffix.lower()
                    fid, size = doc["file_id"], doc.get("file_size") or 0
                else:
                    name, ext, fid, size = "photo.jpg", ".jpg", photo["file_id"], photo.get("file_size") or 0
                if ext not in ALLOWED_EXT:
                    return self.bot.send(chat, t["bad_file"])
                if size > MAX_FILE:
                    return self.bot.send(chat, t["big_file"])
                d.files.append((fid, ext, size, name))
                if text:
                    d.notes.append(text)
                return self.bot.send(chat, t["got_file"].format(n=len(d.files)), self._kb_next(d))
            if text:
                d.notes.append(text)
                return self.bot.send(chat, t["got_file"].format(n=len(d.files)) if d.files else "✓",
                                     self._kb_next(d))
            return
        if d.step in ("what", "origin", "as_of") and text:
            setattr(d, d.step, text)
            d.step = {"what": "origin", "origin": "as_of", "as_of": "usage"}[d.step]
            return self._ask(chat, d)
        if d.step == "author" and text:
            d.author = text[:120]
            d.step = "confirm"
            return self._ask(chat, d)

    def _kb_next(self, d: Draft):
        t = T[d.lang]
        return [[{"text": t["next"], "callback_data": "n:next"}, {"text": t["cancel"], "callback_data": "n:cancel"}]]

    def _ask(self, chat: int, d: Draft):
        t = T[d.lang]
        cancel = {"text": t["cancel"], "callback_data": "n:cancel"}
        if d.step == "doc":
            key = f"ask_doc_{d.kind}" if d.kind in TEXT_ONLY else "ask_doc"
            return self.bot.send(chat, t[key], [[cancel]])
        if d.step in ("what", "origin", "as_of"):
            return self.bot.send(chat, t[f"q_{'date' if d.step == 'as_of' else d.step}"], [[cancel]])
        if d.step == "usage":
            if d.kind == "rates":
                d.usage, d.step = "check", "author"
                self.bot.send(chat, t["rates_check"])
                return self._ask(chat, d)
            return self.bot.send(chat, t["q_usage"], [[{"text": t["u_publish"], "callback_data": "u:publish"}],
                                                       [{"text": t["u_check"], "callback_data": "u:check"}],
                                                       [cancel]])
        if d.step == "author":
            return self.bot.send(chat, t["q_author"], [[{"text": t["skip"], "callback_data": "a:skip"}, cancel]])
        if d.step == "confirm":
            return self.bot.send(chat, t["confirm"].format(card=card(d, d.lang)),
                                 [[{"text": t["send"], "callback_data": "n:send"}, cancel]])

    def _global_ok(self, want_bytes: int) -> bool:
        day = time.strftime("%Y-%m-%d", time.gmtime())
        if self.db.get("busy_told") != day:
            self._busy_told = False
        n = int(self.db.get(f"day:{day}:n", 0))
        b = int(self.db.get(f"day:{day}:bytes", 0))
        try:
            free = shutil.disk_usage(self.home).free
        except OSError:
            free = 0
        return n < DAY_SUBMISSIONS and b + want_bytes <= DAY_BYTES and free - want_bytes > MIN_FREE_BYTES

    def _global_count(self, nbytes: int):
        day = time.strftime("%Y-%m-%d", time.gmtime())
        self.db.put(f"day:{day}:n", int(self.db.get(f"day:{day}:n", 0)) + 1)
        self.db.put(f"day:{day}:bytes", int(self.db.get(f"day:{day}:bytes", 0)) + nbytes)

    def _submit(self, chat: int, d: Draft):
        t = T[d.lang]
        if self._over_limit(chat):
            self.drafts.pop(chat, None)
            return self.bot.send(chat, t["limit"])
        want = sum(f[2] or MAX_FILE for f in d.files)
        if not self._global_ok(want):
            self.drafts.pop(chat, None)
            if not self._busy_told:
                self._busy_told = True
                self.db.put("busy_told", time.strftime("%Y-%m-%d", time.gmtime()))
                self.bot.send(self.owner, "⚠️ Бот упёрся в общий суточный предел отправок или место на диске — "
                                          "новые отправки сегодня не принимаются.")
            return self.bot.send(chat, t["busy"])
        sid = self.db.add(d, chat)
        stored, bad = [], 0
        for i, (fid, ext, _size, name) in enumerate(d.files, 1):
            dest = self.home / "files" / str(sid) / f"{i}{ext}"
            try:
                self.bot.download(fid, dest, MAX_FILE)
                os.chmod(dest, 0o640)
                stored.append({"path": f"{sid}/{i}{ext}", "name": name})
            except TgError:
                bad += 1
        self.db.db.execute("UPDATE submissions SET files = ? WHERE id = ?",
                           (json.dumps(stored, ensure_ascii=False), sid))
        self.db.db.commit()
        self._counted(chat)
        self._global_count(sum((self.home / "files" / f["path"]).stat().st_size for f in stored))
        self.drafts.pop(chat, None)
        self.bot.send(chat, t["thanks"].format(id=sid))
        self._to_owner_new(sid, bad)
        self._queue_for_agent(sid)

    def _queue_for_agent(self, sid: int):
        """Черновик разбора — агенту (только если присланы файлы и очередь есть)."""
        row = self.db.sub(sid)
        files = json.loads(row["files"])
        if not files or not AGENT_QUEUE.is_dir() or row["kind"] in TEXT_ONLY:
            return
        d = AGENT_QUEUE / f".sub-{sid}"
        try:
            d.mkdir()                 # не exist_ok: заранее подложенное имя — отказ, а не переход
        except FileExistsError:
            print(f"очередь агента: {d.name} уже существует — пропуск", file=sys.stderr)
            return
        for f in files:
            shutil.copyfile(self.home / "files" / f["path"], d / Path(f["path"]).name, follow_symlinks=False)
        meta = {k: row[k] for k in ("id", "kind", "what", "origin", "as_of", "usage", "note")}
        meta["names"] = [f["name"] for f in files]
        (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
        d.rename(AGENT_QUEUE / f"sub-{sid}")

    # ── кнопки ───────────────────────────────────────────────────────────
    def on_button(self, q: dict):
        chat = q.get("message", {}).get("chat", {}).get("id")
        data = q.get("data") or ""
        self.bot.answer(q["id"])
        if chat == self.owner and data[:2] in ("s:", "p:", "r:"):
            return self.on_owner_button(q, data)
        d = self.drafts.get(chat)
        if d is None:
            return self.bot.send(chat, T[lang_of(q.get("from"))]["expired"])
        d.touched = time.time()
        t = T[d.lang]
        if data == "n:cancel":
            self.drafts.pop(chat, None)
            return self.bot.send(chat, t["cancelled"])
        if data.startswith("k:") and d.step == "kind" and data[2:] in KINDS:
            d.kind, d.step = data[2:], "doc"
            return self._ask(chat, d)
        if data == "n:next" and d.step == "doc":
            if not d.files and not d.notes:
                return self.bot.send(chat, t["need_doc"])
            if d.kind == "idea":
                d.what = (d.notes[0] if d.notes else "")[:120]
                d.usage, d.step = "publish", "author"
                self.bot.send(chat, t["idea_note"])
                return self._ask(chat, d)
            d.step = "what"
            return self._ask(chat, d)
        if data.startswith("u:") and d.step == "usage" and data[2:] in USAGE:
            d.usage, d.step = data[2:], "author"
            return self._ask(chat, d)
        if data == "a:skip" and d.step == "author":
            d.step = "confirm"
            return self._ask(chat, d)
        if data == "n:send" and d.step == "confirm":
            return self._submit(chat, d)

    # ── сторона владельца ────────────────────────────────────────────────
    def _to_owner_new(self, sid: int, bad_files: int = 0):
        row = self.db.sub(sid)
        txt = "📥 Новая отправка\n\n" + card(row, "ru", sid)
        if bad_files:
            txt += f"\n⚠️ не скачалось файлов: {bad_files}"
        self.bot.send(self.owner, txt, self._kb_sub(sid))

    def _kb_sub(self, sid: int):
        return [[{"text": "✅ Принять", "callback_data": f"s:acc:{sid}"},
                 {"text": "❌ Отклонить", "callback_data": f"s:rej:{sid}"}],
                [{"text": "📎 Файлы и разбор", "callback_data": f"s:det:{sid}"}]]

    def on_owner_message(self, m: dict) -> bool:
        text = _clean(m.get("text"))
        if self.owner_wait and text and not text.startswith("/"):
            w, self.owner_wait = self.owner_wait, None
            self._reject(w["sid"], text)
            return True
        if text in ("/help", "/start"):
            self.bot.send(self.owner, "Служебная сторона:\n/subs — отправки без ответа\n"
                                      "/queue — очередь приёмки справочника\n/new — анкета, как у всех\n"
                                      "/ping — бот жив?")
            return True
        if text == "/ping":
            self.bot.send(self.owner, "на месте")
            return True
        if text == "/subs":
            rows = self.db.db.execute("SELECT * FROM submissions WHERE status = 'new' ORDER BY id").fetchall()
            if not rows:
                self.bot.send(self.owner, "отправок без ответа нет")
            for r in rows[:10]:
                self.bot.send(self.owner, card(r, "ru", r["id"]), self._kb_sub(r["id"]))
            return True
        if text == "/queue":
            self._queue()
            return True
        if text == "/new":
            self._start(self.owner, "ru")
            return True
        return False

    def on_owner_button(self, q: dict, data: str):
        kind, act, num = (data.split(":") + ["", ""])[:3]
        msg = q["message"]
        if kind == "s":
            sid = int(num)
            row = self.db.sub(sid)
            if row is None:
                return self.bot.send(self.owner, f"#{sid} нет")
            if act == "det":
                return self._details(row)
            if row["status"] != "new":
                return self.bot.send(self.owner, f"#{sid} уже решена: {row['status']}")
            if act == "acc":
                self._answer_user(row, "accepted", "")
                self.db.resolve(sid, "accepted", "")
                if row["kind"] == "idea":
                    self.bot.send(self.owner, plan_entry(row))
                return self.bot.edit(self.owner, msg["message_id"], msg.get("text", "") + "\n\n✅ принято")
            if act == "rej":
                kb = [[{"text": v[0], "callback_data": f"r:{k}:{sid}"}] for k, v in REJECT_REASONS.items()]
                kb.append([{"text": "✍️ написать свою", "callback_data": f"r:own:{sid}"}])
                return self.bot.send(self.owner, f"Причина отказа для #{sid}:", kb)
        if kind == "r":
            sid = int(num)
            if act == "own":
                self.owner_wait = {"sid": sid}
                return self.bot.send(self.owner, f"Напишите причину для #{sid} одним сообщением.")
            if act in REJECT_REASONS:
                return self._reject(sid, act)
        if kind == "p":
            return self._proposal(act, int(num), msg)

    def _reject(self, sid: int, why_key: str):
        row = self.db.sub(sid)
        if row is None or row["status"] != "new":
            return self.bot.send(self.owner, f"#{sid} уже решена")
        why = REJECT_REASONS.get(why_key)
        text = why[0 if row["lang"] == "ru" else 1] if why else why_key
        self._answer_user(row, "rejected", text)
        self.db.resolve(sid, "rejected", text)
        self.bot.send(self.owner, f"#{sid} отклонена: {text}")

    def _answer_user(self, row, status: str, why: str):
        if not row["reply_chat"]:
            return
        t = T[row["lang"]]
        what = row["what"] or t[f"k_{row['kind']}"]
        try:
            self.bot.send(row["reply_chat"], t["accepted" if status == "accepted" else "rejected"]
                          .format(id=row["id"], what=what, why=why))
        except TgError as e:            # человек остановил бота — ответить нечем
            self.bot.send(self.owner, f"автору #{row['id']} не доставлено: {e}")

    def _details(self, row):
        for f in json.loads(row["files"]):
            p = self.home / "files" / f["path"]
            if p.exists():
                self.bot.send_file(self.owner, p, f"#{row['id']}: {f['name']}")
        draft = AGENT_OUT / f"sub-{row['id']}.json"
        if draft.exists():
            self.bot.send_file(self.owner, draft, f"#{row['id']}: черновик разбора агента — проверьте цитаты")
        elif json.loads(row["files"]):
            self.bot.send(self.owner, f"#{row['id']}: черновика агента пока нет")

    # ── очередь приёмки справочника (`fca review`) ──────────────────────
    def _fca(self, *args) -> tuple[int, str]:
        # Через точку входа `fca`, а не `-m flightcostapp.cli`: в cli.py
        # блок `if __name__ == "__main__"` стоит раньше констант публикации.
        fca = Path(sys.executable).with_name("fca")
        cmd = [str(fca), "--db", self.review_db, *args]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        return r.returncode, (r.stdout + r.stderr).strip()

    def _queue(self):
        if not self.review_db:
            return self.bot.send(self.owner, "Приёмка справочника на сервере не включена "
                                             "(FCA_REVIEW_DB не задан): принимайте дома, fca review.")
        # Быстрый список прямо из очереди, без `fca review`: тот сравнивает
        # каждое предложение со всей базой и идёт минуты. Сравнение — по
        # кнопке «Подробнее», в фоне.
        db = sqlite3.connect(f"file:{Path(self.review_db).resolve()}?mode=ro", uri=True, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            rows = db.execute("SELECT id, source_id, created_at, payload FROM proposals "
                              "WHERE status = 'pending' ORDER BY id").fetchall()
        finally:
            db.close()
        if not rows:
            return self.bot.send(self.owner, "предложений на приёмке нет")
        seen: dict[str, int] = {}
        for r in rows[:15]:
            p = json.loads(r["payload"])
            n, fl = len(p.get("facts", [])), len(p.get("findings", []))
            h = hashlib.sha256(json.dumps(p.get("facts", []), sort_keys=True, default=str).encode()).hexdigest()
            dup = f"\n⚠️ то же содержимое, что #{seen[h]} — принять один" if h in seen else ""
            seen.setdefault(h, r["id"])
            origin = " · с компьютера" if p.get("origin") == "computer" else ""
            self.bot.send(self.owner, f"#{r['id']} {r['source_id']} · {r['created_at'][:16]}{origin}\n"
                                      f"фактов {n}" + (f", выделено проверкой {fl}" if fl else "") + dup,
                          [[{"text": "✅ Принять", "callback_data": f"p:acc:{r['id']}"},
                            {"text": "❌ Отклонить", "callback_data": f"p:rej:{r['id']}"},
                            {"text": "🔎 Подробнее", "callback_data": f"p:det:{r['id']}"}]])

    def _proposal(self, act: str, pid: int, msg: dict):
        if not self.review_db:
            return self._queue()
        head = msg.get("text", "")
        if act == "det":
            self.bot.send(self.owner, f"⏳ #{pid}: сравниваю с базой…")

            def job():
                _, text = self._fca("review", str(pid))
                self.bot.send(self.owner, text[:3900])
            return self.jobs.put(job)
        self.bot.edit(self.owner, msg["message_id"], f"{head}\n\n⏳ {'принимаю' if act == 'acc' else 'отклоняю'}…")

        def job():
            code, text = self._fca("review", "--accept" if act == "acc" else "--reject", str(pid))
            self.bot.edit(self.owner, msg["message_id"], f"{head}\n\n{text[:500]}")
            if code == 0 and act == "acc":
                with self._lock:
                    self.snapshot_due = time.time()
        self.jobs.put(job)

    # ── ящик сообщений от таймеров и агента ─────────────────────────────
    def drain_spool(self, spool: Path = SPOOL):
        if not spool.is_dir():
            return
        for p in sorted(spool.glob("*.json"))[:20]:
            try:
                msg = json.loads(p.read_text("utf-8"))
                icon = {"warn": "🟡 ", "alert": "🔴 "}.get(msg.get("level"), "")
                # Кнопок в ящике нет: кнопку приёмки, присланную в ящик
                # процессом из группы fcaspool, одно нажатие превратило бы
                # в приёмку. Ящик — только текст и вложение.
                self.bot.send(self.owner, icon + str(msg.get("text", ""))[:3900])
                att = msg.get("attach")
                if att:
                    data = read_attachment(Path(att))
                    if data is not None:
                        self.bot.send_file(self.owner, Path(att), data=data)
                        stash_draft(Path(att).name, data)
                    else:
                        self.bot.send(self.owner, f"вложение не отправлено: вне разрешённых каталогов "
                                                  f"или ссылка ({Path(att).name})")
            except TgError as e:
                print(f"ящик {p.name}: {e}", file=sys.stderr)
                return                       # сеть: попробуем в следующий раз, файл оставляем
            except Exception as e:                                   # noqa: BLE001
                print(f"ящик {p.name}: битое сообщение: {e}", file=sys.stderr)
            p.unlink(missing_ok=True)


DRAFTS = Path(os.environ.get("FCA_DRAFTS_DIR", "/srv/fca/master/export/drafts"))


def stash_draft(name: str, data: bytes, drafts: Path | None = None) -> bool:
    """Черновик агента (тариф, ряд топлива, ночные ограничения) — ещё и туда, откуда его заберёт домой
    `fca master drafts` (решение владельца 09.11.2026). Каталог принадлежит
    боту и читается группой fcaxfer — той же, через которую дом забирает
    главную базу; агенту туда писать нельзя, поэтому копирует бот."""
    drafts = DRAFTS if drafts is None else drafts
    if not (name.startswith(("charges-", "fuel-", "night-")) and name.endswith(".json")) or "/" in name:
        return False
    try:
        drafts.mkdir(parents=True, exist_ok=True)
        tmp = drafts / f".{name}.tmp"
        tmp.write_bytes(data)
        os.chmod(tmp, 0o640)
        tmp.replace(drafts / name)
        return True
    except OSError as e:
        print(f"черновик {name} не сохранён для дома: {e}", file=sys.stderr)
        return False


def read_attachment(p: Path, roots=None, limit: int = MAX_FILE) -> bytes | None:
    """Прочитать вложение, только если это обычный файл прямо в разрешённом
    каталоге. Открывается с O_NOFOLLOW, а каталог сверяется по открытому
    файлу: подменить путь ссылкой между проверкой и чтением нельзя."""
    roots = ATTACH_ROOTS if roots is None else roots
    try:
        parent = p.parent.resolve(strict=True)
    except OSError:
        return None
    if not any(parent == r.resolve() or parent.is_relative_to(r.resolve()) for r in roots):
        return None
    try:
        # O_NONBLOCK: подложенный канал (FIFO) не повесит бота на чтении.
        fd = os.open(parent / p.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        import stat as _stat
        if not _stat.S_ISREG(st.st_mode) or st.st_size > limit:
            return None
        with os.fdopen(fd, "rb") as f:
            fd = -1
            return f.read(limit + 1)[:limit]
    finally:
        if fd >= 0:
            os.close(fd)


def main() -> int:
    owner = os.environ.get("FCA_BOT_OWNER", "").strip()
    if not owner.lstrip("-").isdigit():
        print("FCA_BOT_OWNER не задан: номер вашего чата (узнать — @userinfobot) в /etc/fca/bot.env",
              file=sys.stderr)
        return 2
    bot = Bot(load_token())
    me = bot.call("getMe")
    print(f"бот @{me.get('username')} на связи; владелец — чат {owner}", flush=True)
    # Приёмка кнопками — только когда главная база на сервере уже есть.
    review = os.environ.get("FCA_REVIEW_DB") or None
    if review and not Path(review).exists():
        review = None
    FcaBot(bot, int(owner), review_db=review,
           after_accept=os.environ.get("FCA_AFTER_ACCEPT") or None).run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
