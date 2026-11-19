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
from io import BytesIO
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs

from flightcostapp import bot as B
from flightcostapp import notify
from flightcostapp.tg import TgNotSent

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

    def test_idea_skips_source_questions_and_agent(self):
        """Предложение в план: текст → подпись → отправка; без вопросов про
        источник и дату, публикуемое, агенту не уходит."""
        h = self.b.handle
        h(msg("/start"))
        h(btn("k:idea"))
        h(msg("Посчитать сезонность потока на курортах"))
        h(btn("n:next"))
        h(msg("Иван П., авиакомпания N"))
        h(btn("n:send"))
        row = self.b.db.db.execute("SELECT * FROM submissions ORDER BY id DESC").fetchone()
        self.assertEqual((row["kind"], row["usage"], row["author"]),
                         ("idea", "publish", "Иван П., авиакомпания N"))
        self.assertTrue(row["what"].startswith("Посчитать сезонность"))
        self.assertFalse(any(self.queue.iterdir()), "предложение не должно уходить агенту")
        self.assertTrue(any("план работ" in x for x in self.tg.to(USER)))
        self.b.handle(btn(f"s:acc:{row['id']}", chat=OWNER))
        entry = next(x for x in self.tg.to(OWNER) if "data/plan.yaml" in x)
        import yaml
        doc = yaml.safe_load("items:\n" + entry.split("\n\n", 1)[1])
        it = doc["items"][0]
        self.assertEqual((it["id"], it["by"], it["via"]), (f"bot-{row['id']}", "Иван П., авиакомпания N",
                                                          f"bot #{row['id']}"))

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


class SpoolDelivery(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.spool = self.tmp / "spool"
        self.now = 1000
        self.enterContext(mock.patch.object(B.time, "time", side_effect=lambda: self.now))
        self.log = self.enterContext(mock.patch("sys.stderr"))

    def client(self, *replies):
        self.opener = mock.Mock(side_effect=replies)
        self.telegram = B.Bot("test-token", opener=self.opener)
        self.b = B.FcaBot(self.telegram, OWNER, home=self.tmp / "bot")
        self.addCleanup(self.b.db.db.close)

    def messages(self):
        return [parse_qs(req.args[0].data.decode())["text"][0] for req in self.opener.call_args_list]

    def drain(self):
        self.b.drain_spool(self.spool)

    @staticmethod
    def accepted():
        return BytesIO(b'{"ok":true,"result":{"message_id":1}}')

    def test_read_timeout_stops_original_and_waits_to_report(self):
        reply = mock.MagicMock()
        reply.__enter__.return_value.read.side_effect = TimeoutError("read timed out")
        self.client(reply, self.accepted())
        notification = notify.post("Обновлён справочник", spool=self.spool)
        self.drain()
        self.assertEqual(self.messages(), ["Обновлён справочник"])
        self.assertTrue(notification.exists())
        for _ in range(10):
            self.now += 25
            self.b.drain_spool(self.spool, allow_notices=False)
        self.assertEqual(self.messages(), ["Обновлён справочник"])
        self.b = B.FcaBot(self.telegram, OWNER, home=self.tmp / "bot")
        self.addCleanup(self.b.db.db.close)
        self.drain()
        self.drain()
        self.assertEqual(len(self.messages()), 2)
        self.assertIn("Сбой доставки уведомления", self.messages()[1])
        self.assertNotIn("Обновлён справочник", self.messages()[1])
        self.assertFalse(notification.exists())

    def test_confirmed_rate_limit_retries_original_after_retry_after(self):
        limit = HTTPError("test", 429, "Too Many Requests", {}, BytesIO(
            b'{"ok":false,"error_code":429,"parameters":{"retry_after":75}}'))
        self.client(limit, self.accepted())
        notification = notify.post("Курсы обновлены", spool=self.spool)
        self.drain()
        self.now += 74
        self.drain()
        self.assertEqual(self.messages(), ["Курсы обновлены"])
        self.now += 1
        self.drain()
        self.assertEqual(self.messages(), ["Курсы обновлены", "Курсы обновлены"])
        self.assertFalse(notification.exists())

    def test_connection_refusal_has_bounded_retries_and_notice(self):
        refusal = URLError(ConnectionRefusedError("connection refused"))
        self.client(*([refusal] * 4), self.accepted())
        notification = notify.post("Курсы обновлены", spool=self.spool)
        self.drain()
        for delay in (30, 60, 120):
            self.now += delay
            self.drain()
        self.assertEqual(self.messages(), ["Курсы обновлены"] * 4)
        self.now += 60
        self.drain()
        self.assertIn("Отправка текста в Telegram завершилась ошибкой", self.messages()[-1])
        self.assertEqual(len(self.messages()), 5)
        self.assertFalse(notification.exists())

    def test_timeout_reporting_a_failure_does_not_create_another_notice(self):
        self.client(TimeoutError("read timed out"), TimeoutError("read timed out"))
        notification = notify.post("Курсы обновлены", spool=self.spool)
        self.drain()
        self.now += 60
        self.drain()
        self.now += 600
        self.drain()
        self.assertEqual(len(self.messages()), 2)
        self.assertFalse(notification.exists())

    def test_restart_after_request_started_does_not_replay_original(self):
        self.client(KeyboardInterrupt, self.accepted())
        notification = notify.post("Курсы обновлены", spool=self.spool)
        with self.assertRaises(KeyboardInterrupt):
            self.drain()
        self.b = B.FcaBot(self.telegram, OWNER, home=self.tmp / "bot")
        self.addCleanup(self.b.db.db.close)
        self.drain()
        self.now += 60
        self.drain()
        self.assertEqual(len(self.messages()), 2)
        self.assertIn("Сбой доставки уведомления", self.messages()[1])
        self.assertFalse(notification.exists())

    def test_spool_keeps_draft_when_text_times_out(self):
        self.client(TimeoutError("read timed out"))
        draft = self.tmp / "prices-test.json"
        draft.write_text("{}")
        notify.post("Черновик", spool=self.spool, attach=str(draft))
        with mock.patch.multiple(B, ATTACH_ROOTS=(self.tmp,), DRAFTS=self.tmp / "drafts"):
            self.drain()
        self.assertEqual((self.tmp / "drafts" / draft.name).read_text(), "{}")
        self.assertEqual(self.messages(), ["Черновик"])

    def test_attachment_retry_only_retries_the_attachment(self):
        draft = self.tmp / "draft.json"
        draft.write_text("{}")
        notify.post("Сообщение с вложением", spool=self.spool, attach=str(draft))
        telegram = FakeBot()
        b = B.FcaBot(telegram, OWNER, home=self.tmp / "bot")
        self.addCleanup(b.db.db.close)
        with (mock.patch.object(B, "ATTACH_ROOTS", (self.tmp,)),
              mock.patch.object(telegram, "send_file", side_effect=[TgNotSent("connection refused"), None]) as send):
            b.drain_spool(self.spool)
            self.now += 30
            b.drain_spool(self.spool)
        self.assertEqual(send.call_count, 2)
        self.assertEqual(telegram.to(OWNER), ["Сообщение с вложением"])
        self.assertEqual(list(self.spool.glob("*.json")), [])


class Queue(unittest.TestCase):

    def test_queue_lists_fast_marks_duplicates_and_defers_accept(self):
        from flightcostapp.store import Store
        tmp = Path(tempfile.mkdtemp())
        st = Store(tmp / "m.db")
        payload = {"facts": [{"domain": "x", "key": "a", "valid_from": "2026-01-01", "value": 1}]}
        # Повторы, накопленные до дедупликации в add_proposal (как #7 и #8 на сервере).
        for _ in range(2):
            st.db.execute("INSERT INTO proposals (source_id, created_at, payload) VALUES (?,?,?)",
                          ("jet_fuel_price", "2026-11-03T19:42", json.dumps(payload)))
        st.db.commit()
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
