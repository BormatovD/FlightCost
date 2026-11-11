"""Агент: деньги, проверка результата и клетка OpenClaw.

Без сети и без ключа. Настоящий OpenClaw проверяется, только если задан
FCA_TEST_OPENCLAW (путь к бинарнику; на сервере —
/srv/fca/openclaw/node_modules/.bin/openclaw): тест поднимает макет
API OpenAI Responses, запускает `agent exec` с закреплённым конфигом и смотрит,
какие инструменты получила модель. Командной строки среди них быть не должно.
"""

from __future__ import annotations

import http.server
import io
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
from flightcostapp import prices as PR

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
import json, sys, pathlib, os
cwd = pathlib.Path(sys.argv[sys.argv.index('--cwd') + 1])
assert 'exec' in sys.argv and '--config' in sys.argv
model = sys.argv[sys.argv.index('--model') + 1]
assert model.startswith('openai/')
assert os.environ.get('OPENAI_API_KEY') == 'sk-test'
assert 'ANTHROPIC_API_KEY' not in os.environ
out = {out!r}
if out:
    (cwd / 'out' / 'proposal.json').write_text(out)
print(json.dumps({{"ok": True, "status": "ok", "final": "готово", "costUsd": {cost},
                  "model": model, "provider": "openai"}}))
""")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


class Runner(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "agent"
        self.queue = self.home / "queue" / "sub-7"
        self.queue.mkdir(parents=True)
        (self.queue / "meta.json").write_text(json.dumps({"id": 7, "kind": "tariff", "ai_provider": "openai"}))
        (self.queue / "1.csv").write_text("charge;rate\nlanding;8,58 EUR/t\n")
        self.spool = self.tmp / "spool"
        key = self.tmp / "key"
        key.write_text("sk-test")
        self.env = mock.patch.dict(os.environ, {"FCA_OPENAI_KEY_FILE": str(key),
                                               "CREDENTIALS_DIRECTORY": "", "OPENAI_API_KEY": ""})
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
        (self.home / "queue" / "sub-8" / "meta.json").write_text('{"ai_provider":"openai"}')
        with mock.patch.dict(os.environ, {"FCA_OPENAI_KEY_FILE": "/nonexistent"}):
            r, n = self.run_one()
        failed = list((self.home / "queue" / "failed").iterdir())
        self.assertEqual(len(failed), 2, "обе отправки отложены, ни одна не держит очередь")
        self.assertFalse(self.queue.exists())

    def test_unknown_cost_is_charged_as_estimate_and_stops(self):
        oc = self.tmp / "openclaw"
        oc.write_text(f"#!{sys.executable}\nprint('{{\"ok\": false, \"status\": \"timeout\"}}')\n")
        oc.chmod(0o755)
        (self.home / "queue" / "sub-9").mkdir()
        (self.home / "queue" / "sub-9" / "meta.json").write_text('{"ai_provider":"openai"}')
        r = A.Runner(self.home, openclaw=str(oc), config=str(CONFIG), run_usd=1.5, spool=self.spool)
        n = r.submissions(self.home / "queue")
        self.assertEqual(n, 1, "после неизвестной стоимости прогоны останавливаются")
        self.assertAlmostEqual(A.month_spent(r.ledger), 1.5)

    def test_expired_key_is_named_and_costs_nothing(self):
        oc = self.tmp / "openclaw"
        oc.write_text(f"#!{sys.executable}\nimport json\nprint(json.dumps({{'ok': False, 'status': 'error', "
                      f"'costUsd': 0, 'error': {{'message': 'invalid_api_key: Incorrect API key'}}}}))\n")
        oc.chmod(0o755)
        r = A.Runner(self.home, openclaw=str(oc), config=str(CONFIG), run_usd=1.5, spool=self.spool)
        r.submissions(self.home / "queue")
        self.assertEqual(A.month_spent(r.ledger), 0.0)
        self.assertTrue(any("ключ OpenAI не принят" in t for t in self.spool_texts()))

    def test_auth_error_does_not_erase_already_billed_steps(self):
        oc = self.tmp / "openclaw"
        oc.write_text(f"#!{sys.executable}\nimport json\nprint(json.dumps({{'ok': False, 'status': 'error', "
                      f"'costUsd': 0.07, 'error': {{'message': 'invalid_api_key'}}}}))\n")
        oc.chmod(0o755)
        r = A.Runner(self.home, openclaw=str(oc), config=str(CONFIG), spool=self.spool)
        r.submissions(self.home / "queue")
        self.assertAlmostEqual(A.month_spent(r.ledger), 0.07)
        self.assertTrue(r.stop)

    def test_pdf_auxiliary_usage_is_not_silently_free(self):
        oc = self.tmp / "openclaw"
        oc.write_text(f"#!{sys.executable}\nimport json\nprint(json.dumps({{'ok': True, 'status': 'ok', "
                      f"'costUsd': 0.07, 'toolSummary': {{'calls': 2, 'tools': ['pdf','write']}}}}))\n")
        oc.chmod(0o755)
        r = A.Runner(self.home, openclaw=str(oc), config=str(CONFIG), run_usd=1.5, spool=self.spool)
        r.submissions(self.home / "queue")
        row = json.loads(r.ledger.read_text())
        self.assertAlmostEqual(row["cost_usd"], 1.57)
        self.assertAlmostEqual(row["reported_cost_usd"], 0.07)
        self.assertTrue(row["estimated"])
        self.assertTrue(r.stop)
        result = json.loads(next((self.home / "runs").glob("*/result.json")).read_text())
        self.assertIsNone(result["costUsd"])
        self.assertEqual(result["reportedCostUsd"], 0.07)

    def test_legacy_submission_is_held_without_api_call(self):
        (self.queue / "meta.json").write_text('{"id":7,"kind":"tariff"}')
        r, n = self.run_one()
        self.assertEqual(n, 0)
        self.assertFalse(r.ledger.exists(), "старую отправку нельзя передать новому провайдеру")
        held = list((self.home / "queue" / "held-provider").iterdir())
        self.assertEqual(len(held), 1)
        self.assertTrue((held[0] / "1.csv").is_file())
        self.assertTrue(any("в API документы не переданы" in t for t in self.spool_texts()))

    def test_other_provider_cannot_be_selected(self):
        r = A.Runner(self.home, spool=self.spool)
        ws = r.workspace("sub", "test")
        with mock.patch.object(A.subprocess, "run") as launch:
            with self.assertRaisesRegex(ValueError, "модель не настроена"):
                r.exec("submissions", ws, "test", "anthropic/claude-haiku-5-5")
        launch.assert_not_called()
        self.assertFalse(r.ledger.exists())


class OpenAIKeys(unittest.TestCase):
    def test_environment_key_wins_over_optional_credentials_and_files(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {
                "CREDENTIALS_DIRECTORY": tmp, "OPENAI_API_KEY": " env-key\n",
                "FCA_OPENAI_KEY_FILE": "/nonexistent", "ANTHROPIC_API_KEY": "old-key"}):
            self.assertEqual(A._api_key(), "env-key")
            (Path(tmp) / "openai").write_text("credential-key\n")
            self.assertEqual(A._api_key(), "env-key")

    def test_optional_systemd_credential_never_reads_anthropic_key(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {
                "CREDENTIALS_DIRECTORY": tmp, "OPENAI_API_KEY": "", "FCA_OPENAI_KEY_FILE": "",
                "ANTHROPIC_API_KEY": "old-key"}):
            self.assertIsNone(A._api_key())
            (Path(tmp) / "anthropic").write_text("old-key")
            self.assertIsNone(A._api_key())
            (Path(tmp) / "openai").write_text("credential-key\n")
            self.assertEqual(A._api_key(), "credential-key")

    def test_optional_file_without_environment_key(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {
                "CREDENTIALS_DIRECTORY": "", "FCA_OPENAI_KEY_FILE": "", "OPENAI_API_KEY": "  "}):
            self.assertIsNone(A._api_key())
            with mock.patch.dict(os.environ, {"FCA_OPENAI_KEY_FILE": "/nonexistent"}):
                self.assertIsNone(A._api_key())
            key = Path(tmp) / "openai.key"
            key.write_text("file-key\n")
            with mock.patch.dict(os.environ, {"FCA_OPENAI_KEY_FILE": str(key)}):
                self.assertEqual(A._api_key(), "file-key")

    def test_environment_key_reaches_openclaw_without_key_file(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {
                "OPENAI_API_KEY": "sk-test", "FCA_OPENAI_KEY_FILE": "/nonexistent",
                "CREDENTIALS_DIRECTORY": "/nonexistent", "ANTHROPIC_API_KEY": "old-key"}):
            home = Path(tmp)
            oc = fake_openclaw(home, 0.03, None)
            runner = A.Runner(home, openclaw=str(oc), config=str(CONFIG), spool=home / "spool")
            workspace = home / "run"
            workspace.mkdir()
            result = runner.exec("submissions", workspace, "test")
            self.assertEqual(result["status"], "ok")
            self.assertAlmostEqual(A.month_spent(runner.ledger), 0.03)

    def test_document_extractor_does_not_inherit_api_credentials(self):
        with mock.patch.dict(os.environ, {
                "OPENAI_API_KEY": "env-key", "ANTHROPIC_API_KEY": "old-key",
                "FCA_OPENAI_KEY_FILE": "/secret", "CREDENTIALS_DIRECTORY": "/credentials"}), \
                mock.patch.object(A.subprocess, "run", return_value=subprocess.CompletedProcess(
                    [], 0, b"extracted text")) as extract:
            self.assertEqual(A.extract_text_safe(Path("document.pdf")), "extracted text")
            env = extract.call_args.kwargs["env"]
            for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "FCA_OPENAI_KEY_FILE", "CREDENTIALS_DIRECTORY"):
                self.assertNotIn(name, env)

    def test_invalid_cost_never_passes_as_zero(self):
        for cost in (None, "0", True, -1, float("nan"), float("inf")):
            with self.subTest(cost=cost):
                self.assertIsNone(A._reported_cost({"costUsd": cost}))
        self.assertEqual(A._reported_cost({"costUsd": 0}), 0.0)
        self.assertEqual(A._reported_cost({"costUsd": 0.03}), 0.03)


class Smoke(unittest.TestCase):
    def test_both_models_must_write_probe_without_publishing_a_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = A.Runner(Path(tmp), spool=Path(tmp) / "spool")
            called = []

            def execute(job, ws, task, model):
                called.append(model)
                self.assertEqual(job, "smoke")
                self.assertIn("Не обращайся в интернет", task)
                self.assertEqual(list((ws / "in").iterdir()), [])
                (ws / "out" / "probe.json").write_text('{"provider":"openai","ok":true}')
                return {"status": "ok", "costUsd": 0.001}

            with mock.patch.object(r, "exec", side_effect=execute):
                self.assertTrue(r.smoke())
            self.assertEqual(called, ["openai/gpt-6-luna", "openai/gpt-6.1-sol"])
            self.assertFalse(r.out.exists())

    def test_missing_probe_is_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = A.Runner(Path(tmp), spool=Path(tmp) / "spool")
            with mock.patch.object(r, "exec", return_value={"status": "ok", "costUsd": 0.001}):
                self.assertFalse(r.smoke("gpt-6-luna"))

    def test_busy_lock_is_not_a_successful_smoke(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(A, "HOME", Path(tmp)), \
                mock.patch.object(A.fcntl, "flock", side_effect=BlockingIOError):
            self.assertEqual(A.main(["smoke"]), 2)


class PricesRunner(unittest.TestCase):
    """Успешный поиск продвигает очередь отдельно от приёмки цен; сбой — нет."""

    WANTED = ["AT76", "B772", "CRJ9", "DH8D"]

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="fca-price-runner-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.home = self.tmp / "agent"
        self.doc = {"observations": [], "searched": {
            code: "2026-11-01" for code in A.PRICE_TYPES if code not in self.WANTED}}
        self.original_doc = json.loads(json.dumps(self.doc))
        self.load = self.enterContext(mock.patch.object(PR, "load", return_value=self.doc))
        self.merge = self.enterContext(mock.patch.object(PR, "merge"))
        self.prepare = self.enterContext(mock.patch.object(A.Runner, "prepare_price_sources"))
        self.now = self.enterContext(mock.patch.object(A, "_now", return_value=
            A.datetime(2026, 11, 10, 21, 3, 2, tzinfo=A.timezone.utc)))
        self.enterContext(mock.patch.object(A, "_api_key", side_effect=AssertionError("API не нужен")))
        self.runner = A.Runner(self.home, spool=self.tmp / "spool")

    def run_prices(self, draft, *, status="ok", runner=None, cost=0.006035):
        runner = runner or self.runner

        def execute(job, ws, task, model):
            self.assertEqual(job, "prices")
            self.assertIn("in/price_sources.json", task)
            self.assertIn("https://www.bing.com/news/search?", task)
            self.assertNotIn("https://news.google.com/rss/", task)
            if draft is not None:
                (ws / "out" / "prices.json").write_text(
                    draft if isinstance(draft, str) else json.dumps(draft, ensure_ascii=False), "utf-8")
            return {"status": status, "costUsd": cost}

        with mock.patch.object(runner, "exec", side_effect=execute) as execute_mock:
            result = runner.prices()
        execute_mock.assert_called_once()
        return result

    def test_empty_draft_is_exported_and_next_runner_moves_on_without_acceptance(self):
        # Формат searched из реального пустого production-черновика.
        draft = {"observations": [], "searched": [
            "AT76 (ATR 72-600)", "B772 (777-200ER)", "CRJ9 (CRJ900)", "DH8D (Dash 8-400)"],
            "doubts": ["ATR: первичная статья вернула 403.", "WLFC: цена за борт не указана."]}
        self.assertEqual(self.run_prices(draft), 0)
        self.assertEqual(self.prepare.call_args.args[1], self.WANTED)
        first_path = next(self.runner.out.glob("prices-*.json"))
        first_bytes = first_path.read_bytes()
        exported = json.loads(first_bytes)
        self.assertEqual(exported["searched"], self.WANTED)
        self.assertEqual(exported["observations"], [])
        self.assertEqual(exported["doubts"], draft["doubts"])
        self.assertEqual(exported["searched_at"], "2026-11-10T21:03:02+00:00")
        state = json.loads((self.home / "prices_state.json").read_text())
        self.assertEqual(set(state), set(self.WANTED))
        for code in self.WANTED:
            self.assertEqual(state[code], {"at": exported["searched_at"],
                                         "run": exported["run"], "observations": 0})
        message = json.loads(next((self.tmp / "spool").glob("*.json")).read_text())
        self.assertEqual(message["attach"], str(first_path))
        self.assertEqual(message["level"], "warn")
        self.assertIn("очередь типов продвинута", message["text"])
        self.assertIn("стоимость 0.0060 USD", message["text"])
        self.assertIn("принимать цены нечего", message["text"])
        for doubt in draft["doubts"]:
            self.assertIn(doubt, message["text"])

        # Второй процесс в тот же день получает прежний принятый справочник,
        # но читает сохранённые попытки. Первый черновик должен сохраниться.
        self.now.return_value = A.datetime(2026, 11, 10, 21, 5, 30, tzinfo=A.timezone.utc)
        second = A.Runner(self.home, spool=self.tmp / "spool")
        self.assertEqual(self.run_prices({"observations": [], "doubts": ["Второй поиск пуст."]},
                                         runner=second), 0)
        self.assertEqual(self.prepare.call_args.args[1], ["A20N", "A21N", "B38M", "B39M"])
        outputs = list(second.out.glob("prices-*.json"))
        self.assertEqual(len(outputs), 2)
        self.assertEqual(first_path.read_bytes(), first_bytes)
        second_path = next(p for p in outputs if p != first_path)
        self.assertEqual(json.loads(second_path.read_text())["searched"], ["A20N", "A21N", "B38M", "B39M"])
        self.assertEqual({json.loads(p.read_text())["attach"] for p in (self.tmp / "spool").glob("*.json")},
                         {str(first_path), str(second_path)})
        self.assertEqual(self.doc, self.original_doc, "поиск не должен менять принятые данные")
        self.merge.assert_not_called()

    def test_api_error_or_timeout_never_exports_even_when_model_wrote_json(self):
        for status in ("error", "timeout"):
            with self.subTest(status=status):
                runner = A.Runner(self.tmp / status, spool=self.tmp / "spool")
                self.assertEqual(self.run_prices({"observations": [], "searched": self.WANTED,
                                                  "doubts": ["Неполная попытка."]},
                                                 status=status, runner=runner), 0)
                self.assertTrue(list((runner.home / "runs").glob("*/out/prices.json")),
                                "для регрессии нужен файл, созданный до ошибки API")
                self.assertFalse((runner.home / "prices_state.json").exists())
                self.assertEqual(list(runner.out.glob("*.json")), [])

        self.assertTrue(all("attach" not in json.loads(p.read_text())
                            for p in (self.tmp / "spool").glob("*.json")))
        self.assertEqual(self.doc, self.original_doc)
        self.merge.assert_not_called()

    def test_successful_scalar_draft_remains_for_manual_acceptance(self):
        observation = {"icao": "at76", "kind": "lease", "value": 180000,
                       "currency": "USD", "month": "2019-12", "age": "new",
                       "source": "https://example.org/report.pdf",
                       "quote": "Lease rate US$180,000 per month."}
        self.assertEqual(self.run_prices({"observations": [observation], "searched": 42}), 1)
        exported = json.loads(next(self.runner.out.glob("*.json")).read_text())
        self.assertEqual(exported["observations"][0]["icao"], "AT76")
        self.assertEqual(exported["observations"][0]["value"], 180000)
        self.assertEqual(exported["searched"], self.WANTED)
        self.assertEqual(self.runner.prices_state()["AT76"]["observations"], 1)
        self.merge.assert_not_called()

    def test_invalid_observation_does_not_export_or_advance_queue(self):
        valid = {"icao": "AT76", "kind": "lease", "value": 180000,
                 "currency": "USD", "month": "2019-12",
                 "source": "https://example.org/report.pdf", "quote": "US$180,000 per month"}
        invalid = [{}, {**valid, "source": [valid["source"]]},
                   {**valid, "value": float("nan")}, {**valid, "value": True},
                   {**valid, "icao": "A21N"}, {**valid, "kind": "unknown"}]
        for i, observation in enumerate(invalid):
            with self.subTest(i=i):
                runner = A.Runner(self.tmp / f"bad-row-{i}", spool=self.tmp / "spool")
                self.assertEqual(self.run_prices({"observations": [observation]}, runner=runner), 0)
                self.assertFalse((runner.home / "prices_state.json").exists())
                self.assertEqual(list(runner.out.glob("*.json")), [])

    def test_same_second_runs_keep_both_drafts(self):
        # Часы намеренно заморожены: одной секундной метки для имени мало.
        self.run_prices({"observations": [], "doubts": ["Первый поиск."]})
        first = next(self.runner.out.glob("*.json"))
        original = first.read_bytes()
        self.run_prices({"observations": [], "doubts": ["Второй поиск."]})
        self.assertEqual(len(list(self.runner.out.glob("*.json"))), 2)
        self.assertEqual(len(list((self.home / "runs").iterdir())), 2)
        self.assertEqual(first.read_bytes(), original)

    def test_missing_invalid_or_wrong_shape_json_never_advances_or_exports(self):
        for i, draft in enumerate((None, "not JSON", "[]", "null", "{}",
                                   '{"observations":{}}', '{"observations":[1]}',
                                   '{"observations":[],"doubts":"not a list"}')):
            with self.subTest(draft=draft):
                runner = A.Runner(self.tmp / f"invalid-{i}", spool=self.tmp / "spool")
                self.assertEqual(self.run_prices(draft, runner=runner), 0)
                self.assertEqual(self.prepare.call_args.args[1], self.WANTED)
                self.assertFalse((runner.home / "prices_state.json").exists())
                self.assertEqual(list(runner.out.glob("*.json")), [])
        self.assertEqual(self.doc, self.original_doc)
        self.merge.assert_not_called()


class PriceSourcePreparation(unittest.TestCase):
    """Загрузка опорных документов — локальный текст, отказ одного не отменяет остальные."""

    def test_unavailable_report_does_not_discard_other_text_or_known_publications(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = A.Runner(Path(tmp), spool=Path(tmp) / "spool")
            ws = runner.workspace("prices", "sources")
            reports = A.PRICE_REPORTS
            text = "=== стр. 33 ===\nLease rates are stated in USD per month."
            doc = {"observations": [
                {"icao": "AT76", "month": "2025-01", "source": "https://example.org/a"},
                {"icao": "AT76", "month": "2026-01", "source": "https://example.org/a"},
                {"icao": "CRJ9", "month": "2026-02", "source": "https://example.org/b"},
                {"icao": "B772", "month": "2026-03", "source": "https://example.org/unrelated"},
                {"icao": "AT76", "month": "2026-03", "source": "file:///private/document"}]}
            with mock.patch.object(A.urllib.request, "urlopen", side_effect=[
                    io.BytesIO(b"<html>Access denied</html>"), io.BytesIO(b"%PDF-1.4 fixture")]) as fetch, \
                    mock.patch.object(A, "extract_text_safe", return_value=text) as extract:
                runner.prepare_price_sources(ws, ["AT76", "CRJ9"], doc)
            self.assertEqual([c.args[0].full_url for c in fetch.call_args_list],
                             [report["url"] for report in reports])
            sources = json.loads((ws / "in" / "price_sources.json").read_text())
            self.assertIn("не PDF", sources["reports"][0]["error"])
            self.assertNotIn("text", sources["reports"][0])
            ready = sources["reports"][1]
            self.assertEqual((ws / ready["text"]).read_text(), text)
            self.assertEqual(ready["url"], reports[1]["url"])
            extract.assert_called_once_with(ws / ready["pdf"])
            self.assertEqual(sources["known_publications"], ["https://example.org/b", "https://example.org/a"])

    def test_oversized_report_is_bounded_and_not_sent_to_extractor(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = A.Runner(Path(tmp), spool=Path(tmp) / "spool")
            ws = runner.workspace("prices", "sources")
            response = mock.MagicMock()
            response.__enter__.return_value = response
            response.read.return_value = b"%PDF-1.4X"
            with mock.patch.object(A, "MAX_DOC", 8), \
                    mock.patch.object(A.urllib.request, "urlopen", return_value=response) as fetch, \
                    mock.patch.object(A, "extract_text_safe") as extract:
                runner.prepare_price_sources(ws, ["AT76"], {})
            fetch.assert_called_once()
            response.read.assert_called_once_with(9)
            extract.assert_not_called()
            sources = json.loads((ws / "in" / "price_sources.json").read_text())
            self.assertEqual(len(sources["reports"]), 1)
            self.assertIn("error", sources["reports"][0])
            self.assertNotIn("text", sources["reports"][0])
            self.assertEqual(list((ws / "in").glob("*.pdf")), [])


@unittest.skipUnless(os.environ.get("FCA_TEST_OPENCLAW"), "FCA_TEST_OPENCLAW не задан")
class Cage(unittest.TestCase):
    """Настоящий закреплённый OpenClaw, локальный Responses API, без платных вызовов."""

    @staticmethod
    def _pdf(path):
        # Небольшой настоящий PDF с текстовым слоем, без внешних программ/шрифтов.
        objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
                   b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                   b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                   b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
                   b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
        content = b"BT /F1 12 Tf 72 720 Td (Number 42. " + b"Test document. " * 30 + b") Tj ET"
        objects.append(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" +
                       content + b"\nendstream")
        blob, offsets = b"%PDF-1.4\n", [0]
        for i, obj in enumerate(objects, 1):
            offsets.append(len(blob))
            blob += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
        xref = len(blob)
        blob += f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode()
        blob += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
        blob += (f"trailer << /Size {len(offsets)} /Root 1 0 R >>\n"
                 f"startxref\n{xref}\n%%EOF").encode()
        path.write_bytes(blob)

    @staticmethod
    def _events(body, item, number):
        response = {"id": f"resp_{number}", "object": "response", "created_at": 1,
                    "status": "completed", "model": body["model"], "output": [item],
                    "service_tier": "default", "usage": {
                        "input_tokens": 1000, "output_tokens": 100, "total_tokens": 1100,
                        "input_tokens_details": {"cached_tokens": 200, "cache_write_tokens": 100},
                        "output_tokens_details": {"reasoning_tokens": 20}}}
        events = [{"type": "response.created", "response": {
                      **response, "status": "in_progress", "output": [], "usage": None}},
                  {"type": "response.output_item.added", "output_index": 0,
                   "item": {**item, "status": "in_progress"}}]
        if item["type"] == "message":
            common = {"item_id": item["id"], "output_index": 0, "content_index": 0}
            value = item["content"][0]["text"]
            events.extend([
                {**common, "type": "response.content_part.added", "part": {
                    "type": "output_text", "text": "", "annotations": []}},
                {**common, "type": "response.output_text.delta", "delta": value},
                {**common, "type": "response.output_text.done", "text": value}])
        else:
            events.append({"type": "response.function_call_arguments.done", "item_id": item["id"],
                           "output_index": 0, "arguments": item["arguments"]})
        events.extend([{"type": "response.output_item.done", "output_index": 0, "item": item},
                       {"type": "response.completed", "response": response}])
        return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()

    def _run(self, model, scenario="write"):
        seen, main_calls = [], 0
        with tempfile.TemporaryDirectory(prefix="fca-openai-cage-") as directory:
            tmp = Path(directory)
            ws = tmp / "ws"
            (ws / "in").mkdir(parents=True)
            (ws / "out").mkdir()
            self._pdf(ws / "in" / "check.pdf")
            self._pdf(tmp / "protected.pdf")
            (tmp / "protected.txt").write_text("WORKSPACE_GUARD_SENTINEL")
            outer = self

            class H(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"object": "list", "data": [
                        {"id": name, "object": "model", "owned_by": "openai"}
                        for name in ("gpt-6-luna", "gpt-6.1-sol", "gpt-6-astra")]}).encode())

                def do_POST(self):
                    nonlocal main_calls
                    body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                    seen.append({"path": self.path, "body": body,
                                 "auth": self.headers.get("Authorization")})
                    is_main = bool(body.get("tools"))
                    if is_main:
                        main_calls += 1
                    tool, args = None, None
                    if is_main and scenario == "escape" and main_calls == 2:
                        tool, args = "read", {"path": "../protected.txt"}
                    elif is_main and scenario == "escape" and main_calls == 3:
                        tool, args = "pdf", {"pdf": str(tmp / "protected.pdf"),
                                             "prompt": "Report the number in the document."}
                    elif is_main and scenario == "pdf" and main_calls == 1:
                        tool, args = "pdf", {"pdf": str(ws / "in" / "check.pdf"), "pages": "1",
                                             "prompt": "Report the number in the document."}
                    elif is_main and main_calls == (2 if scenario == "pdf" else 1):
                        tool, args = "write", {
                            "path": "../escaped.json" if scenario == "escape" else "out/proposal.json",
                            "content": '{"summary":"OpenAI smoke","items":[]}'}
                    if tool:
                        item = {"type": "function_call", "id": f"fc_{tool}", "call_id": f"call_{tool}",
                                "name": tool, "arguments": json.dumps(args), "status": "completed"}
                    else:
                        item = {"type": "message", "id": f"msg_{len(seen)}", "role": "assistant",
                                "status": "completed", "content": [{"type": "output_text",
                                "text": "Готово." if is_main else "Document says 42.", "annotations": []}]}
                    payload = outer._events(body, item, len(seen))
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)

                def log_message(self, *args):
                    pass

            srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            try:
                config = CONFIG.read_text("utf-8")
                self.assertEqual(config.count('"https://api.openai.com/v1"'), 1)
                config = config.replace('"https://api.openai.com/v1"',
                                        f'"http://127.0.0.1:{srv.server_port}/v1"')
                (tmp / "cfg.json5").write_text(config, "utf-8")
                # Не наследуем ключи, прокси и профиль оператора. Единственный ключ — макет.
                env = {"PATH": os.environ["PATH"], "HOME": str(tmp), "OPENAI_API_KEY": "sk-test",
                       "NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1", "NO_COLOR": "1"}
                proc = subprocess.run([
                    os.environ["FCA_TEST_OPENCLAW"], "agent", "exec", "--config", str(tmp / "cfg.json5"),
                    "--cwd", str(ws), "--model", "openai/" + model, "--json", "--timeout", "60",
                    "Проверь документ in/check.pdf и запиши out/proposal.json."],
                    env=env, capture_output=True, text=True, timeout=150)
                self.assertEqual(proc.returncode, 0, (proc.stdout + proc.stderr)[-6000:])
                result = json.loads(proc.stdout)
                output = ws / "out" / "proposal.json"
                return result, seen, output.read_text() if output.exists() else None, (tmp / "escaped.json").exists()
            finally:
                srv.shutdown()
                srv.server_close()

    def _assert_requests(self, seen, model, thinking):
        self.assertTrue(seen, "OpenClaw не обратился к макету API")
        main = []
        for request in seen:
            self.assertEqual(request["path"], "/v1/responses")
            self.assertEqual(request["auth"], "Bearer sk-test")
            body = request["body"]
            self.assertTrue(body.get("stream"))
            if body.get("tools"):
                main.append(body)
                tools = {t.get("name") for t in body["tools"]}
                self.assertEqual(tools, {"read", "write", "web_fetch", "pdf"})
                self.assertLessEqual(tools, ALLOWED_TOOLS)
                self.assertEqual(body["model"], model)
                self.assertEqual(body["service_tier"], "default")
                self.assertEqual(body["reasoning"]["effort"], thinking)
        self.assertTrue(main)
        return main

    def test_models_write_and_account_without_shell(self):
        # Раздельные тарифы input, cache-read, cache-write, output; reasoning уже входит в output.
        for model, thinking, per_call in (("gpt-6-luna", "low", 0.0001345),
                                          ("gpt-6.1-sol", "medium", 0.00267)):
            with self.subTest(model=model):
                result, seen, output, escaped = self._run(model)
                main = self._assert_requests(seen, model, thinking)
                self.assertEqual(len(main), 2)
                self.assertEqual(result["provider"], "openai")
                self.assertEqual(json.loads(output)["summary"], "OpenAI smoke")
                self.assertFalse(escaped)
                replay = [x for x in main[1]["input"] if x["type"] == "function_call_output"]
                self.assertEqual(replay[0]["call_id"], "call_write")
                self.assertEqual(result["toolSummary"], {"calls": 1, "tools": ["write"], "failures": 0})
                self.assertAlmostEqual(result["costUsd"], 2 * per_call)
                self.assertEqual(result["usage"]["input"], 1400)
                self.assertEqual(result["usage"]["cacheRead"], 400)
                self.assertEqual(result["usage"]["cacheWrite"], 200)

    def test_file_tools_cannot_escape_workspace(self):
        result, seen, output, escaped = self._run("gpt-6-luna", "escape")
        main = self._assert_requests(seen, "gpt-6-luna", "low")
        self.assertFalse(escaped, "write вышел за пределы задания")
        self.assertIsNone(output)
        self.assertEqual(result["toolSummary"]["failures"], 3)
        self.assertEqual(set(result["toolSummary"]["tools"]), {"write", "read", "pdf"})
        self.assertEqual(len(main), 4)
        self.assertEqual(len(seen), len(main), "PDF вне задания передан вспомогательной модели")
        self.assertNotIn("WORKSPACE_GUARD_SENTINEL", json.dumps(seen))

    def test_pdf_uses_openai_but_raw_envelope_omits_auxiliary_cost(self):
        result, seen, output, escaped = self._run("gpt-6.1-sol", "pdf")
        main = self._assert_requests(seen, "gpt-6.1-sol", "medium")
        auxiliary = [r["body"] for r in seen if not r["body"].get("tools")]
        self.assertEqual(len(main), 3)
        self.assertEqual(len(auxiliary), 1)
        self.assertEqual(auxiliary[0]["model"], "gpt-6-luna")
        self.assertIn("42", json.dumps(auxiliary[0]["input"]))
        self.assertEqual(result["toolSummary"], {"calls": 2, "tools": ["pdf", "write"], "failures": 0})
        self.assertIsNotNone(output)
        self.assertFalse(escaped)
        # Ограничение именно 2026.10.5: PDF usage теряется внутри инструмента.
        # Runner обязан резервировать бюджет и останавливать пачку; эту сумму нельзя
        # выдавать за полный счёт. При исправлении upstream нужен пересмотр Runner.
        self.assertAlmostEqual(result["costUsd"], 3 * 0.00267)
        self.assertLess(result["costUsd"], 3 * 0.00267 + 0.0001345)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class SourceUrl(unittest.TestCase):
    """09.11.2026, KATL: агент нашёл документ, но не записал source_url."""

    def setUp(self):
        self.ws = Path(tempfile.mkdtemp())
        self.f = self.ws / "KATL-2026.json"

    def put(self, d):
        self.f.write_text(json.dumps(d))

    def got(self):
        return json.loads(self.f.read_text()).get("source_url")

    def test_known_url_filled_silently(self):
        self.put({"icao": "KATL"})
        self.assertEqual(A.fill_source_url(self.f, "https://x.org/t.pdf", {}, self.ws), "")
        self.assertEqual(self.got(), "https://x.org/t.pdf")

    def test_single_url_from_answer(self):
        self.put({"icao": "KATL", "doubts": ["взят https://www.atl.com/rates-and-charges.pdf."]})
        note = A.fill_source_url(self.f, None, {"final": "готово"}, self.ws)
        self.assertEqual(self.got(), "https://www.atl.com/rates-and-charges.pdf")
        self.assertIn("проверь", note)

    def test_several_urls_listed_not_guessed(self):
        self.put({"icao": "KATL"})
        note = A.fill_source_url(self.f, None, {"final": "https://a.com/fees.pdf и https://b.com/tariff.pdf"}, self.ws)
        self.assertIsNone(self.got())
        self.assertIn("https://b.com/tariff.pdf", note)

    def test_present_url_untouched(self):
        self.put({"icao": "KATL", "source_url": "https://keep.me"})
        self.assertEqual(A.fill_source_url(self.f, "https://other", {}, self.ws), "")
        self.assertEqual(self.got(), "https://keep.me")


class Watch(unittest.TestCase):
    """Новая редакция заведённого тарифа встаёт первой в очередь агента «тарифы»."""

    def test_refresh_goes_first(self):
        doc = {"regions": {"europe": {"prefixes": ["E"], "min": 2,
                                      "candidates": [{"icao": "EDDM", "city": "Мюнхен"}]}}}
        st = {"EDDF": {"status": "refresh", "url": "https://fraport/2027.pdf"}}
        icao, a, _ = A.pick_charges(doc, {"EDDF"}, st)
        self.assertEqual((icao, a["url"]), ("EDDF", "https://fraport/2027.pdf"))
        st["EDDF"]["status"] = "draft"
        self.assertEqual(A.pick_charges(doc, {"EDDF"}, st)[0], "EDDM")


class Drafts(unittest.TestCase):
    """Бот кладёт черновик тарифа туда, откуда его заберёт дом, — и только его."""

    def test_only_charges_json_is_stashed(self):
        from flightcostapp import bot as B
        d = Path(tempfile.mkdtemp())
        self.assertTrue(B.stash_draft("charges-KATL-2026.json", b"{}", d))
        self.assertEqual(oct((d / "charges-KATL-2026.json").stat().st_mode & 0o777), "0o640")
        self.assertFalse(B.stash_draft("report.pdf", b"x", d))
        self.assertFalse(B.stash_draft("charges-../../x.json", b"x", d))


class DraftCheck(unittest.TestCase):
    def test_band_for_region_without_tariff_set(self):
        from flightcostapp import drafts as D
        code, _, lo, hi = D.band_of("KDEN")
        self.assertEqual(code, "north_america")
        self.assertAlmostEqual(hi / lo, 4.0)

    def test_draft_replaces_only_its_airport(self):
        from flightcostapp import drafts as D

        class Inner:
            def current(self, domain, as_of=None, prefixes=None):
                return {"KATL/old": "старое", "KDEN/x": "чужое"}
        f = {"domain": "airport_charge", "key": "KATL/new", "value_text": "{}"}
        rows = D.DraftStore(Inner(), "KATL", [f]).current("airport_charge")
        self.assertEqual(set(rows), {"KATL/new", "KDEN/x"})
