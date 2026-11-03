"""Агент: деньги, проверка результата и клетка OpenClaw.

Без сети и без ключа. Настоящий OpenClaw проверяется, только если задан
FCA_TEST_OPENCLAW (путь к бинарнику; на сервере —
/srv/fca/openclaw/node_modules/.bin/openclaw): тест поднимает макет
API Anthropic, запускает `agent exec` с закреплённым конфигом и смотрит,
какие инструменты получила модель. Командной строки среди них быть не должно.
"""

from __future__ import annotations

import http.server
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from flightcostapp import agent_run as A

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "deploy" / "agent" / "openclaw.json5"
ALLOWED_TOOLS = {"read", "write", "web_fetch", "pdf", "skills_read"}


class Checks(unittest.TestCase):

    def test_quote_must_be_in_document(self):
        doc = "Landing charge  8,58 EUR per tonne MTOW\n=== стр. 2 ==="
        p = {"items": [{"field": "a", "value": 8.58, "quote": "Landing charge 8,58 EUR", "confidence": "exact"},
                       {"field": "b", "value": 99, "quote": "Parking 99 EUR", "confidence": "exact"},
                       {"field": "c", "value": None, "quote": "", "confidence": "missing"}]}
        self.assertEqual(A.check_quotes(p, doc), ["b"])

    def test_value_without_quote_is_an_error(self):
        errs = A.validate_submission({"items": [{"field": "x", "value": 1, "confidence": "exact"}]})
        self.assertTrue(errs)
        self.assertEqual(A.validate_submission({"items": [
            {"field": "x", "value": 1, "quote": "q", "where": "1.pdf, стр. 1", "confidence": "exact"}]}), [])

    def test_rules_never_name_the_community_source(self):
        text = A.RULES + A.SUBMISSION_TASK + A.CHARGES_TASK
        self.assertNotRegex(text, re.compile(r"ТКП|клиринг", re.I))


def fake_openclaw(tmp: Path, cost: float, write_out: dict | None) -> Path:
    """Подменный openclaw: пишет out/proposal.json и печатает конверт."""
    p = tmp / "openclaw"
    out = json.dumps(write_out) if write_out is not None else ""
    p.write_text(f"""#!{sys.executable}
import json, sys, pathlib
cwd = pathlib.Path(sys.argv[sys.argv.index('--cwd') + 1])
assert 'exec' in sys.argv and '--config' in sys.argv
out = {out!r}
if out:
    (cwd / 'out' / 'proposal.json').write_text(out)
print(json.dumps({{"ok": True, "status": "ok", "final": "готово", "costUsd": {cost},
                  "model": "claude-haiku-5-5", "provider": "anthropic"}}))
""")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


class Runner(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "agent"
        self.queue = self.home / "queue" / "sub-7"
        self.queue.mkdir(parents=True)
        (self.queue / "meta.json").write_text(json.dumps({"id": 7, "kind": "tariff"}))
        (self.queue / "1.csv").write_text("charge;rate\nlanding;8,58 EUR/t\n")
        self.spool = self.tmp / "spool"
        key = self.tmp / "key"
        key.write_text("sk-test")
        self.env = mock.patch.dict(os.environ, {"FCA_ANTHROPIC_KEY_FILE": str(key)})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def run_one(self, cost=0.03, out=None, month=20.0):
        oc = fake_openclaw(self.tmp, cost, out)
        r = A.Runner(self.home, openclaw=str(oc), config=str(CONFIG), month_usd=month, spool=self.spool)
        return r, r.submissions(self.home / "queue")

    def spool_texts(self):
        return [json.loads(p.read_text())["text"] for p in sorted(self.spool.glob("*.json"))]

    def test_draft_checked_and_cost_recorded(self):
        prop = {"summary": "s", "items": [
            {"field": "landing", "value": 8.58, "quote": "landing;8,58 EUR/t", "where": "1.csv", "confidence": "exact"},
            {"field": "parking", "value": 3, "quote": "parking 3 EUR", "where": "1.csv", "confidence": "exact"}]}
        r, n = self.run_one(out=prop)
        self.assertEqual(n, 1)
        draft = json.loads((self.home / "out" / "sub-7.json").read_text())
        self.assertEqual(draft["_check"]["quotes_not_found"], ["parking"])
        self.assertAlmostEqual(A.month_spent(r.ledger), 0.03)
        self.assertFalse(self.queue.exists(), "разобранное должно уйти из очереди")
        self.assertTrue(any("цитат не найдено" in t for t in self.spool_texts()))

    def test_budget_stops_runs(self):
        self.home.mkdir(exist_ok=True)
        (self.home / "ledger.jsonl").write_text(json.dumps(
            {"ts": A._now().isoformat(), "cost_usd": 25.0}) + "\n")
        r, n = self.run_one(month=20.0)
        self.assertEqual(n, 0)
        self.assertTrue(self.queue.exists(), "при исчерпанном бюджете очередь не трогаем")
        self.assertTrue(any("потрачено" in t for t in self.spool_texts()))


class RunnerFailures(Runner):

    def test_failed_item_moves_aside_and_queue_continues(self):
        (self.home / "queue" / "sub-8").mkdir()
        (self.home / "queue" / "sub-8" / "meta.json").write_text("{}")
        with mock.patch.dict(os.environ, {"FCA_ANTHROPIC_KEY_FILE": "/nonexistent"}):
            r, n = self.run_one()
        failed = list((self.home / "queue" / "failed").iterdir())
        self.assertEqual(len(failed), 2, "обе отправки отложены, ни одна не держит очередь")
        self.assertFalse(self.queue.exists())

    def test_unknown_cost_is_charged_as_estimate_and_stops(self):
        oc = self.tmp / "openclaw"
        oc.write_text(f"#!{sys.executable}\nprint('{{\"ok\": false, \"status\": \"timeout\"}}')\n")
        oc.chmod(0o755)
        (self.home / "queue" / "sub-9").mkdir()
        (self.home / "queue" / "sub-9" / "meta.json").write_text("{}")
        r = A.Runner(self.home, openclaw=str(oc), config=str(CONFIG), run_usd=1.5, spool=self.spool)
        n = r.submissions(self.home / "queue")
        self.assertEqual(n, 1, "после неизвестной стоимости прогоны останавливаются")
        self.assertAlmostEqual(A.month_spent(r.ledger), 1.5)


@unittest.skipUnless(os.environ.get("FCA_TEST_OPENCLAW"), "FCA_TEST_OPENCLAW не задан")
class Cage(unittest.TestCase):
    """Какие инструменты закреплённый конфиг на самом деле отдаёт модели."""

    def test_model_gets_no_shell(self):
        seen = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
                seen.append([t.get("name") or t.get("function", {}).get("name") for t in body.get("tools", [])])
                self.send_response(401)   # отказ ключа — без повторов
                self.end_headers()

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        tmp = Path(tempfile.mkdtemp())
        cfg = CONFIG.read_text("utf-8").replace(
            "  tools: {", f'  models: {{ providers: {{ anthropic: {{ baseUrl: '
                         f'"http://127.0.0.1:{srv.server_port}", models: [] }} }} }},\n  tools: {{', 1)
        (tmp / "cfg.json5").write_text(cfg, "utf-8")
        (tmp / "ws").mkdir()
        env = {**os.environ, "ANTHROPIC_API_KEY": "sk-test", "HOME": str(tmp), "NO_PROXY": "127.0.0.1",
               "no_proxy": "127.0.0.1"}
        subprocess.run([os.environ["FCA_TEST_OPENCLAW"], "agent", "exec", "--config", str(tmp / "cfg.json5"),
                        "--cwd", str(tmp / "ws"), "--model", "anthropic/claude-haiku-5-5", "--json",
                        "--timeout", "15", "привет"], env=env, capture_output=True, timeout=120)
        srv.shutdown()
        self.assertTrue(seen, "OpenClaw не обратился к макету API")
        tools = set(seen[0])
        self.assertTrue(tools, "модель не получила инструментов — проверить, не сломан ли конфиг")
        self.assertLessEqual(tools, ALLOWED_TOOLS, f"лишние инструменты: {tools - ALLOWED_TOOLS}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
