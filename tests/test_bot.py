"""Бот держит обещания из своего описания и из /datenschutz — без сети.

Телеграм подменён записью вызовов. Проверяется путь человека от /start до
ответа и то, что после ответа номер чата стёрт; что имя и ник нигде не
лежат; что ставки всегда «только для проверки»; что чужой формат файла не
скачивается; что вложение из ящика не читает файлы вне разрешённых мест.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from flightcostapp import bot as B
from flightcostapp import notify

OWNER = 1000
USER = 2000
USER_FROM = {"id": USER, "first_name": "Ivan", "username": "ivan_secret_nick", "language_code": "ru"}


class FakeBot:
    def __init__(self):
        self.sent, self.files, self.edits = [], [], []

    def send(self, chat_id, text, buttons=None, **kw):
        self.sent.append((chat_id, text, buttons))
        return {"message_id": len(self.sent)}

    def edit(self, chat_id, mid, text, buttons=None):
        self.edits.append((chat_id, text))

    def answer(self, *_a, **_k):
        pass

    def send_file(self, chat_id, path, caption="", data=None):
        self.files.append((chat_id, Path(path)))

    def download(self, file_id, dest, limit):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"%PDF-1.4 test " + file_id.encode())
        return 10

    def to(self, chat):
        return [t for c, t, _ in self.sent if c == chat]


def msg(text=None, **extra):
    m = {"chat": {"id": USER, "type": "private"}, "from": USER_FROM}
    if text is not None:
        m["text"] = text
    m.update(extra)
    return {"update_id": 1, "message": m}


def btn(data, chat=USER):
    return {"update_id": 2, "callback_query": {"id": "q", "data": data, "from": USER_FROM,
                                                "message": {"chat": {"id": chat}, "message_id": 5, "text": "x"}}}


class BotFlow(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.queue = self.tmp / "queue"
        self.queue.mkdir()
        self.p = mock.patch.multiple(B, AGENT_QUEUE=self.queue, AGENT_OUT=self.tmp / "out",
                                     ATTACH_ROOTS=(self.tmp / "out", self.tmp / "bot" / "files"))
        self.p.start()
        self.tg = FakeBot()
        self.b = B.FcaBot(self.tg, OWNER, home=self.tmp / "bot")

    def tearDown(self):
        self.p.stop()

    def submit(self, kind="tariff", usage="publish"):
        h = self.b.handle
        h(msg("/start"))
        h(btn(f"k:{kind}"))
        h(msg(caption="вот тариф", document={"file_id": "F1", "file_name": "tariff.pdf", "file_size": 1000}))
        h(btn("n:next"))
        h(msg("Тариф Пулково 2026"))
        h(msg("pulkovoairport.ru"))
        h(msg("2026-01-01"))
        if kind != "rates":
            h(btn(f"u:{usage}"))
        h(btn("a:skip"))
        h(btn("n:send"))
        return self.b.db.db.execute("SELECT * FROM submissions ORDER BY id DESC").fetchone()

    def test_full_path_and_chat_forgotten_after_answer(self):
        row = self.submit()
        self.assertEqual((row["kind"], row["what"], row["usage"], row["reply_chat"]),
                         ("tariff", "Тариф Пулково 2026", "publish", USER))
        self.assertTrue((self.tmp / "bot" / "files" / str(row["id"]) / "1.pdf").exists())
        self.assertTrue(any("Новая отправка" in t for t in self.tg.to(OWNER)))
        self.assertTrue((self.queue / f"sub-{row['id']}" / "meta.json").exists(), "агенту не ушло")
        self.b.handle(btn(f"s:acc:{row['id']}", chat=OWNER))
        row = self.b.db.sub(row["id"])
        self.assertEqual(row["status"], "accepted")
        self.assertIsNone(row["reply_chat"], "номер чата должен стираться ответом")
        self.assertTrue(any("принята" in t for t in self.tg.to(USER)))

    def test_no_name_or_username_stored(self):
        self.submit()
        blob = b"".join(p.read_bytes() for p in (self.tmp / "bot").rglob("*.db"))
        for s in ("Ivan", "ivan_secret_nick"):
            self.assertNotIn(s.encode(), blob)

    def test_rates_are_always_check_only(self):
        row = self.submit(kind="rates")
        self.assertEqual(row["usage"], "check")

    def test_reject_with_reason_reaches_author(self):
        row = self.submit()
        self.b.handle(btn(f"s:rej:{row['id']}", chat=OWNER))
        self.b.handle(btn(f"r:dup:{row['id']}", chat=OWNER))
        self.assertTrue(any("уже есть" in t for t in self.tg.to(USER)))
        self.assertIsNone(self.b.db.sub(row["id"])["reply_chat"])

    def test_disallowed_format_is_not_downloaded(self):
        self.b.handle(msg("/start"))
        self.b.handle(btn("k:tariff"))
        self.b.handle(msg(document={"file_id": "X", "file_name": "run.exe", "file_size": 10}))
        self.assertIn("формат", self.tg.to(USER)[-1])
        self.assertEqual(self.b.drafts[USER].files, [])

    def test_daily_limit(self):
        for _ in range(B.PER_DAY):
            self.submit()
        before = self.b.db.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
        self.submit()
        after = self.b.db.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
        self.assertEqual(before, after)

    def test_old_unanswered_chat_is_forgotten(self):
        row = self.submit()
        self.b.db.db.execute("UPDATE submissions SET created_at = datetime('now', '-100 days')")
        self.b.db.forget_old_chats()
        self.assertIsNone(self.b.db.sub(row["id"])["reply_chat"])

    def test_groups_ignored(self):
        self.b.handle({"update_id": 3, "message": {"chat": {"id": -5, "type": "group"}, "text": "/start"}})
        self.assertEqual(self.tg.sent, [])


class Spool(unittest.TestCase):

    def test_spool_roundtrip_and_attach_guard(self):
        tmp = Path(tempfile.mkdtemp())
        out = tmp / "out"
        out.mkdir()
        ok = out / "draft.json"
        ok.write_text("{}")
        secret = tmp / "secret.txt"
        secret.write_text("token")
        notify.post("hello", spool=tmp / "spool", attach=str(ok))
        notify.post("evil", spool=tmp / "spool", attach=str(out / ".." / "secret.txt"))
        tg = FakeBot()
        with mock.patch.multiple(B, ATTACH_ROOTS=(out,)):
            b = B.FcaBot(tg, OWNER, home=tmp / "bot")
            b.drain_spool(tmp / "spool")
        self.assertEqual([p.name for _, p in tg.files], ["draft.json"])
        self.assertTrue(any("вне разрешённых" in t for t in tg.to(OWNER)))
        self.assertEqual(list((tmp / "spool").glob("*.json")), [])

    def test_symlink_attach_and_buttons_refused(self):
        tmp = Path(tempfile.mkdtemp())
        out = tmp / "out"
        out.mkdir()
        (tmp / "secret.txt").write_text("token")
        (out / "link.json").symlink_to(tmp / "secret.txt")
        self.assertIsNone(B.read_attachment(out / "link.json", roots=(out,)))
        sp = tmp / "spool"
        sp.mkdir()
        (sp / "1.json").write_text(json.dumps({"text": "нажми", "buttons": [[{"text": "ok",
                                                "callback_data": "p:acc:1"}]]}))
        tg = FakeBot()
        B.FcaBot(tg, OWNER, home=tmp / "bot").drain_spool(sp)
        self.assertIsNone(tg.sent[-1][2], "кнопки из ящика не должны доходить до владельца")


class Queue(unittest.TestCase):

    def test_queue_lists_fast_marks_duplicates_and_defers_accept(self):
        from flightcostapp.store import Store
        tmp = Path(tempfile.mkdtemp())
        st = Store(tmp / "m.db")
        payload = {"facts": [{"domain": "x", "key": "a", "valid_from": "2026-01-01", "value": 1}]}
        st.add_proposal("jet_fuel_price", payload)
        st.add_proposal("jet_fuel_price", payload)
        st.db.close()
        tg = FakeBot()
        b = B.FcaBot(tg, OWNER, home=tmp / "bot", review_db=str(tmp / "m.db"))
        b._queue()
        texts = tg.to(OWNER)
        self.assertEqual(len(texts), 2)
        self.assertIn("то же содержимое, что #1", texts[1])
        b.handle(btn("p:acc:1", chat=OWNER))
        self.assertEqual(b.jobs.qsize(), 1, "приёмка уходит в фон, бот не ждёт")
        self.assertTrue(any("принимаю" in t for _, t in tg.edits))


class GlobalCap(BotFlow):

    def test_global_daily_cap(self):
        with mock.patch.object(B, "DAY_SUBMISSIONS", 2):
            for _ in range(3):
                self.b._count = {}           # другой чат
                self.submit()
        n = self.b.db.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
        self.assertEqual(n, 2)
        self.assertTrue(any("общий суточный предел" in t for t in self.tg.to(OWNER)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
