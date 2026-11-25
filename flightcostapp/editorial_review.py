"""Private, version-bound editorial review. The Telegram bot is the only updates consumer."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import sqlite3
import stat
import tempfile
import time
from pathlib import Path

from . import editorial_article as article
from . import editorial_queue as queue
from .tg import Bot, TgError, load_token


def json_bytes(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2).encode()


def write_atomic(path, data, mode):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        name = tmp.name
        try:
            os.fchmod(tmp.fileno(), mode)
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)


class Review:
    def __init__(self, root, private):
        self.root, self.private = Path(root), Path(private)
        self.private.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.inbox = self.root/"work/inbox"
        self.outbox = self.root/"work/outbox"
        self.publication_queue = self.root/"publication_queue"
        self.db = sqlite3.connect(self.private/"review.sqlite", timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS reviews (
                article INTEGER, revision INTEGER, token TEXT UNIQUE, payload BLOB NOT NULL,
                document BLOB NOT NULL, sha TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                delivered INTEGER, last_try REAL DEFAULT 0, PRIMARY KEY(article,revision)
            );
            CREATE TABLE IF NOT EXISTS comments (
                article INTEGER, revision INTEGER, message_id INTEGER PRIMARY KEY, body TEXT NOT NULL
            );
        """)

    def latest(self, n):
        return self.db.execute("SELECT article,revision,token,state,delivered FROM reviews WHERE article=? "
                               "ORDER BY revision DESC LIMIT 1", (n,)).fetchone()

    def job(self, n):
        row = self.latest(n)
        if not row:
            return dict(article=n, revision=1, comments=[])
        if row["state"] != "changes_requested":
            return None
        comments = [x[0] for x in self.db.execute(
            "SELECT body FROM comments WHERE article=? AND revision=? ORDER BY message_id", (n,row["revision"]))]
        previous = self.db.execute("SELECT payload FROM reviews WHERE token=?", (row["token"],)).fetchone()
        return dict(article=n, revision=row["revision"]+1, comments=comments,
                    feedback_token=hashlib.sha256(json_bytes([row["token"],comments])).hexdigest(),
                    previous=json.loads(previous[0]))

    def sync_job(self, n):
        # Serialize bot replies and the hourly process while publishing a job snapshot.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            job = self.job(n)
            if job:
                target = self.inbox/f"{n:02d}-r{job['revision']:03d}.json"
                data = json_bytes(job)
                if not target.is_file() or target.read_bytes() != data:
                    write_atomic(target,data,0o640)
        finally:
            self.db.rollback()

    def ingest(self, path, n, rev):
        job = self.job(n)
        if not job or job["revision"] != rev:
            return
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd,"rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                raise ValueError("Expected regular outbox file")
            raw = f.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("Draft exceeds size limit")
        payload = json.loads(raw)
        if (type(payload.get("article")) is not int or type(payload.get("revision")) is not int or
                (payload["article"],payload["revision"]) != (n,rev)):
            raise ValueError("Draft ID mismatch")
        if (payload.get("feedback_token") or "") != (job.get("feedback_token") or ""):
            return  # the writer is preparing the latest owner's comments
        document = article.render(payload, self.root)
        digest = hashlib.sha256(document).hexdigest()
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if self.job(n) != job:
                return
            self.db.execute("INSERT INTO reviews(article,revision,token,payload,document,sha) VALUES (?,?,?,?,?,?)",
                            (n,rev,secrets.token_hex(10),raw,document,digest))

    @staticmethod
    def filename(row):
        return f"FlightCost-{row['article']:02d}-r{row['revision']:03d}-{row['token']}.html"

    @staticmethod
    def keys(row, phase):
        action,title = ("queue","В очередь подготовки") if phase == "approved" else ("approve","Согласовать")
        return {"inline_keyboard":[[{"text":title,"callback_data":f"art:{action}:{row['token']}"}]]}

    def deliver(self, bot, owner):
        for row in self.db.execute("SELECT * FROM reviews WHERE state='pending' AND delivered IS NULL "
                                   "AND last_try<? ORDER BY article", (time.time()-300,)).fetchall():
            with self.db:
                self.db.execute("UPDATE reviews SET last_try=? WHERE token=?", (time.time(),row["token"]))
            payload = json.loads(row["payload"])
            caption = (f"Статья №{row['article']}, версия {row['revision']} · {payload['title']}\n\n"
                       f"{payload['lede'][:470]}\n\n"
                       "Откройте HTML. Для правок ответьте текстом на этот документ. "
                       "После согласования оригинал можно поставить в очередь подготовки. Сайт не изменится.")
            response = bot.upload("sendDocument","document",Path(self.filename(row)),row["document"],
                                  chat_id=owner,caption=caption[:1024],reply_markup=self.keys(row,"pending"))
            with self.db:
                self.db.execute("UPDATE reviews SET delivered=? WHERE token=?", (response["message_id"],row["token"]))

    def poll(self, bot, owner):
        # systemd and a manual replay must never deliver the queue concurrently.
        with (self.private/"review.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for n in range(2,19):
                self.sync_job(n)
            errors = []
            for p in sorted(self.outbox.glob("*-r*.json")):
                m = re.fullmatch(r"(\d{2})-r(\d{3})\.json", p.name)
                if not m or not 2 <= int(m[1]) <= 18:
                    continue
                try:
                    self.ingest(p,int(m[1]),int(m[2]))
                except (ValueError, KeyError, TypeError, OSError) as exc:
                    errors.append(f"{p.name}: {type(exc).__name__}: {exc}")
            self.deliver(bot,owner)
            if errors:
                raise ValueError("; ".join(errors))

    def enqueue(self, row):
        """Only a bound, approved snapshot can enter the private queue."""
        if row["state"] != "approved":
            raise ValueError("Сначала согласуйте оригинал.")
        payload = json.loads(row["payload"])
        document = row["document"]
        if hashlib.sha256(document).hexdigest() != row["sha"]:
            raise ValueError("Контрольная сумма согласованной версии не совпадает.")
        meta = queue.make_manifest(row["article"], row["revision"], payload["title"], payload["lede"], document)
        queue.store_bundle(self.publication_queue, meta["id"], queue.encode_manifest(meta), document, server=True)

    def event(self, bot, owner, update):
        cb = update.get("callback_query",{})
        m = cb.get("message",{}) if cb else update.get("message",{})
        key = re.fullmatch(r"art:(approve|publish|queue):([0-9a-f]{20})",str(cb.get("data",""))) if cb else None
        reference = m if cb else m.get("reply_to_message") or {}
        docname = str((reference.get("document") or {}).get("file_name",""))
        reply_tag = re.fullmatch(r"FlightCost-(\d\d)-r(\d{3})-([0-9a-f]{20})\.html",docname)
        if not key and (cb or not reply_tag):
            return False
        sender = (cb if cb else m).get("from") or {}
        if m.get("chat",{}).get("type") != "private" or m["chat"].get("id") != owner or sender.get("id") != owner:
            if cb:
                bot.answer(cb["id"], "Доступно владельцу.")
            return True
        token = key[2] if cb else reply_tag[3]
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT * FROM reviews WHERE token=?",(token,)).fetchone()
            # A matching document identity also recovers a sent message after a
            # lost sendDocument response or process restart before the receipt.
            known_doc = (reply_tag and row and self.filename(row) == docname and
                         reference.get("from",{}).get("is_bot") and not reference.get("forward_origin"))
            bound = (row and type(reference.get("message_id")) is int and
                     (row["delivered"] == reference["message_id"] or known_doc))
            active = bound and self.latest(row["article"])["token"] == token
            updated = None
            refresh_legacy = False
            if not active:
                result = "Эта версия устарела. Откройте последний документ."
            elif cb and key[1] == "publish":
                # Old Telegram messages cannot publish or enqueue anything.
                result = "Прямая публикация отключена. Используйте очередь подготовки."
                refresh_legacy = row["state"] == "approved"
            elif row["state"] == "approved" and (
                    self.publication_queue / queue.bundle_id(row["article"], row["revision"])).exists():
                # Recover a successful atomic queue write before the DB commit.
                try:
                    self.enqueue(row)
                    updated,result = "queued","Оригинал уже в очереди. Требуются EN и DE."
                except (ValueError, OSError) as exc:
                    result = f"Проверьте комплект очереди: {exc}"
            elif cb and key[1] == "approve" and row["state"] in ("pending","approved"):
                updated,result = "approved","Оригинал согласован. Можно поставить в очередь подготовки."
            elif cb and key[1] == "queue" and row["state"] == "approved":
                try:
                    self.enqueue(row)
                    updated,result = "queued","Оригинал в очереди. Требуются EN и DE; на сайте изменений нет."
                except (ValueError, OSError) as exc:
                    result = f"Не удалось добавить в очередь: {exc}"
            elif not cb and row["state"] in ("pending","approved","changes_requested"):
                body = (m.get("text") or m.get("caption") or "").strip()
                if not body:
                    result = "Пришлите правки текстом в ответ на документ."
                else:
                    self.db.execute("INSERT OR IGNORE INTO comments VALUES (?,?,?,?)",
                                    (row["article"],row["revision"],m["message_id"],body[:10000]))
                    updated,result = "changes_requested","Комментарий сохранён для следующей версии."
            elif row["state"] == "queued":
                result = "Оригинал уже в очереди подготовки; выпуск только с компьютера."
            elif row["state"] == "published":
                result = "Эта версия уже опубликована."
            elif row["state"] == "changes_requested":
                result = "К этой версии есть правки. Дождитесь следующей."
            else:
                result = "Сначала согласуйте просмотренную версию."
            if updated:
                self.db.execute("UPDATE reviews SET state=?,delivered=COALESCE(delivered,?) WHERE token=?",
                                (updated,reference["message_id"],token))
        if updated == "changes_requested":
            self.sync_job(row["article"])
        if cb:
            bot.answer(cb["id"],result)
            if active and (updated == "approved" or refresh_legacy or (updated or row["state"]) in ("queued", "published")):
                markup = self.keys(row,"approved") if updated == "approved" or refresh_legacy else {"inline_keyboard":[]}
                try:
                    bot.call("editMessageReplyMarkup",chat_id=owner,message_id=reference["message_id"],reply_markup=markup)
                except TgError as exc:
                    if "not modified" not in str(exc):
                        raise
            if updated == "queued":
                identifier = queue.bundle_id(row["article"], row["revision"])
                bot.send(owner, f"{result} ID: {identifier}")
        else:
            bot.send(owner,result)
        return True


def configured():
    root = os.environ.get("FCA_EDITORIAL_ROOT")
    if not root:
        raise ValueError("FCA_EDITORIAL_ROOT is required")
    private = Path(os.environ.get("FCA_BOT_DIR","/srv/fca/bot"))/"editorial"
    return Review(root,private)


def handle_update(bot, owner, update):
    if not os.environ.get("FCA_EDITORIAL_ROOT"):
        return False
    cb = update.get("callback_query",{})
    reply = (update.get("message",{}).get("reply_to_message") or {}).get("document") or {}
    if not str(cb.get("data","")).startswith("art:") and not str(reply.get("file_name","")).startswith("FlightCost-"):
        return False
    review = configured()
    try:
        return review.event(bot,owner,update)
    finally:
        review.db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=["poll"])
    parser.parse_args()
    review = configured()
    try:
        review.poll(Bot(load_token()),int(os.environ["FCA_BOT_OWNER"]))
    finally:
        review.db.close()


if __name__ == "__main__":
    main()
