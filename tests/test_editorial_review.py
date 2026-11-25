"""Owner-bound private queue and per-version mailboxes."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flightcostapp import editorial_article as article
from flightcostapp import editorial_queue as queue
from flightcostapp.editorial_review import Review, json_bytes
from flightcostapp.tg import TgDeliveryUnknown


class Telegram:
    def __init__(self):
        self.sent, self.answers, self.acks = [], [], []
        self.unknown = False

    def upload(self, method, field, path, data, **kw):
        self.sent.append((path.name,data,kw))
        if self.unknown:
            raise TgDeliveryUnknown("lost receipt")
        return {"message_id":len(self.sent)}

    def answer(self, cid, text):
        self.answers.append(text)

    def send(self, owner, text):
        self.acks.append(text)

    def call(self, kind, **kw):
        self.answers.append(kw)


class EditorialTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for folder in ("work/inbox","work/outbox","published","publication_queue"):
            (self.root/folder).mkdir(parents=True)
        env = patch.dict(os.environ, {"FCA_EDITORIAL_PUBLISHED":str(self.root/"published")})
        env.start()
        self.addCleanup(env.stop)
        self.r = Review(self.root,self.root/"private")
        self.addCleanup(self.r.db.close)
        self.b = Telegram()
        self.source = {"article":5,"revision":1,"title":"Исследование","lede":"Данные прогноза",
                       "sections":[{"heading":"Спрос","paragraphs":["<script>прогноз</script>"]}],
                       "sources":[{"label":"Источник","url":"https://flightcost.app/ru/research"}]}
        self.write(self.source)

    def write(self, payload):
        p = self.r.outbox/f"{payload['article']:02d}-r{payload['revision']:03d}.json"
        p.write_bytes(json_bytes(payload))
        return p

    def ref(self, i=-1):
        name = self.b.sent[i][0]
        return dict(chat={"id":21,"type":"private"},message_id=i+1 if i >= 0 else len(self.b.sent),
                    document={"file_name":name},**{"from":{"id":99,"is_bot":True}})

    def click(self, action, actor=21, i=-1):
        ref = self.ref(i)
        call = self.b.sent[i][2]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        tok = call.split(":")[2]
        return self.r.event(self.b,21,{"callback_query":dict(id="abc",data=f"art:{action}:{tok}",
                                                             message=ref,**{"from":{"id":actor}})})

    def comment(self, text="перепроверить", mid=119, i=-1):
        return self.r.event(self.b,21,{"message":dict(text=text,chat={"id":21,"type":"private"},
                                                      reply_to_message=self.ref(i), message_id=mid,**{"from":{"id":21}})})

    def test_owner_and_version_binding_and_immutable_queue(self):
        self.r.poll(self.b,21)
        self.r.poll(self.b,21)
        self.assertEqual(len(self.b.sent),1)
        self.assertIn(b"&lt;script&gt;",self.b.sent[0][1])
        self.assertEqual(len(list(self.r.inbox.glob("*-r001.json"))),17)
        self.click("queue")
        self.click("publish")
        self.click("approve",123)
        self.assertEqual(self.r.latest(5)["state"],"pending")
        self.assertFalse(list(self.r.publication_queue.iterdir()))
        self.click("approve")
        self.assertEqual(self.r.latest(5)["state"],"approved")
        self.click("publish")  # Legacy button must neither publish nor enqueue.
        self.assertEqual(self.r.latest(5)["state"],"approved")
        self.assertFalse(list(self.r.publication_queue.iterdir()))
        self.click("queue",123)
        self.assertFalse(list(self.r.publication_queue.iterdir()))
        self.click("queue")
        manifest, document = queue.read_bundle(self.r.publication_queue,"05-r001")
        self.assertEqual(document,self.b.sent[0][1])
        self.assertEqual(json.loads(manifest)["status"],"approved_original_needs_translation")
        self.assertEqual(json.loads(manifest)["available_languages"],["ru"])
        self.assertFalse(list((self.root/"published").iterdir()))
        placeholder = dict(slug=article.article_slug(5),planned_release=True)
        self.assertEqual(article.public_items([placeholder]),[placeholder])
        self.click("queue")
        self.click("publish")
        self.comment()
        self.assertEqual(self.r.latest(5)["state"],"queued")
        self.assertEqual(queue.read_bundle(self.r.publication_queue,"05-r001"),(manifest,document))

    def test_feedback_replies_and_concurrent_revisions(self):
        self.r.poll(self.b,21)
        self.click("approve")
        self.comment()
        self.comment()  # same Telegram message replayed after a restart
        job_path = self.r.inbox/"05-r002.json"
        first = json.loads(job_path.read_bytes())
        self.assertEqual(first["comments"],["перепроверить"])
        self.click("queue")
        self.assertFalse((self.r.publication_queue/"05-r001").exists())
        self.comment("добавить источники",120)
        second = json.loads(job_path.read_bytes())
        old = {**self.source,"revision":2,"feedback_token":first["feedback_token"]}
        self.write(old)
        self.r.poll(self.b,21)
        self.assertEqual(len(self.b.sent),1)
        self.write({**old,"feedback_token":second["feedback_token"],"title":"Исправленная версия"})
        self.r.poll(self.b,21)
        self.assertEqual(len(self.b.sent),2)
        self.click("approve",i=0)
        self.click("queue",i=0)
        self.assertEqual(self.r.latest(5)["state"],"pending")
        self.click("approve")
        self.click("queue")
        self.assertEqual((self.r.publication_queue/"05-r002/report.html").read_bytes(),self.b.sent[1][1])
        self.assertFalse(list((self.root/"published").iterdir()))

    def test_missing_queue_and_retry(self):
        self.r.poll(self.b,21)
        self.click("approve")
        self.r.publication_queue.rmdir()
        self.click("queue")
        self.assertEqual(self.r.latest(5)["state"],"approved")
        self.r.publication_queue.mkdir()
        self.click("queue")
        self.assertEqual(self.r.latest(5)["state"],"queued")

    def test_queue_recovers_after_atomic_write_before_db_commit(self):
        self.r.poll(self.b,21)
        self.click("approve")
        row = self.r.db.execute("SELECT * FROM reviews WHERE article=5").fetchone()
        self.r.enqueue(row)  # Simulate crash before updating SQLite state.
        self.assertEqual(self.r.latest(5)["state"],"approved")
        self.click("queue")
        self.assertEqual(self.r.latest(5)["state"],"queued")
        self.assertEqual(len(list(self.r.publication_queue.iterdir())),1)

    def test_existing_published_history_is_untouched(self):
        self.r.poll(self.b,21)
        old = self.root/"published"/"05"
        old.mkdir()
        (old/"report.html").write_bytes(b"old original")
        with self.r.db:
            self.r.db.execute("UPDATE reviews SET state='published' WHERE article=5")
        self.click("publish")
        self.click("queue")
        self.comment()
        self.assertEqual(self.r.latest(5)["state"],"published")
        self.assertEqual((old/"report.html").read_bytes(),b"old original")
        self.assertFalse(list(self.r.publication_queue.iterdir()))

    def test_local_bundle_integrity_and_no_overwrite(self):
        content = b"<html>approved original</html>"
        meta = queue.make_manifest(5,1,"Title","Description",content)
        manifest = queue.encode_manifest(meta)
        root = self.root/"local"
        root.mkdir()
        self.assertTrue(queue.store_bundle(root,"05-r001",manifest,content))
        self.assertFalse(queue.store_bundle(root,"05-r001",manifest,content))
        other = b"<html>different</html>"
        with self.assertRaises(ValueError):
            queue.store_bundle(root,"05-r001",queue.encode_manifest(queue.make_manifest(5,1,"Title","Description",other)),other)
        self.assertEqual(queue.read_bundle(root,"05-r001"),(manifest,content))
        (root/"05-r001/report.html").write_bytes(other)
        with self.assertRaises(ValueError):
            queue.read_bundle(root,"05-r001")
        with self.assertRaises(ValueError):
            queue.check_id("../../research")

    def test_local_bundle_rejects_extra_files_and_symlinks(self):
        root = self.root/"local"
        root.mkdir()
        content = b"<html>draft</html>"
        manifest = queue.encode_manifest(queue.make_manifest(5,1,"Title","Description",content))
        queue.store_bundle(root,"05-r001",manifest,content)
        folder = root/"05-r001"
        (folder/"extra.py").write_text("bad")
        with self.assertRaises(ValueError):
            queue.read_bundle(root,"05-r001")
        (folder/"extra.py").unlink()
        (folder/"report.html").unlink()
        (folder/"report.html").symlink_to(folder/"manifest.json")
        with self.assertRaises(ValueError):
            queue.read_bundle(root,"05-r001")

    def test_lost_telegram_receipt_recovers_from_original_document(self):
        self.b.unknown = True
        with self.assertRaises(TgDeliveryUnknown):
            self.r.poll(self.b,21)
        self.click("approve")
        self.assertEqual(self.r.latest(5)["state"],"approved")
        self.assertEqual(self.r.latest(5)["delivered"],1)

    def test_symlink_and_script_url_rejected_and_separate_good_article_delivered(self):
        self.write({**self.source,"article":6,"sources":[{"label":"x","url":"javascript:alert(1)"}]})
        (self.r.outbox/"07-r001.json").symlink_to(self.write(self.source))
        with self.assertRaises(ValueError):
            self.r.poll(self.b,21)
        self.assertIsNone(self.r.latest(6))
        self.assertIsNone(self.r.latest(7))
        self.assertEqual(len(self.b.sent),1)


if __name__ == "__main__":
    unittest.main()
