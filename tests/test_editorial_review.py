"""Owner-bound publication and per-version mailboxes."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flightcostapp import editorial_article as article
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
        for folder in ("work/inbox","work/outbox","published"):
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

    def test_owner_and_version_binding_and_immutable_publication(self):
        self.r.poll(self.b,21)
        self.r.poll(self.b,21)
        self.assertEqual(len(self.b.sent),1)
        self.assertIn(b"&lt;script&gt;",self.b.sent[0][1])
        self.assertEqual(len(list(self.r.inbox.glob("*-r001.json"))),17)
        self.click("publish")
        self.click("approve",123)
        self.assertEqual(self.r.latest(5)["state"],"pending")
        self.click("approve")
        self.assertEqual(self.r.latest(5)["state"],"approved")
        self.click("publish")
        path = self.r.published/"05/report.html"
        self.assertEqual(path.read_bytes(),self.b.sent[0][1])
        item = article.public_items([dict(slug=article.article_slug(5),planned_release=True)])[0]
        self.assertFalse(item["planned_release"])
        self.assertEqual(item["path"],path)
        self.click("publish")
        self.comment()
        self.assertEqual(self.r.latest(5)["state"],"published")
        existing_article = dict(slug=article.article_slug(5),title="Редакция сайта")
        self.assertEqual(article.public_items([existing_article]),[existing_article])

    def test_feedback_replies_and_concurrent_revisions(self):
        self.r.poll(self.b,21)
        self.click("approve")
        self.comment()
        self.comment()  # same Telegram message replayed after a restart
        job_path = self.r.inbox/"05-r002.json"
        first = json.loads(job_path.read_bytes())
        self.assertEqual(first["comments"],["перепроверить"])
        self.click("publish")
        self.assertFalse((self.r.published/"05").exists())
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
        self.assertEqual(self.r.latest(5)["state"],"pending")
        self.click("approve")
        self.click("publish")
        self.assertEqual((self.r.published/"05/report.html").read_bytes(),self.b.sent[1][1])

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
