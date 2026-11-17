"""0066: инструктаж тарифного агента проверяется до API-вызова."""
import json
import tempfile
import unittest
from dataclasses import fields
from pathlib import Path
from unittest import mock
from flightcostapp import agent_run
from flightcostapp.charges import Rule, self_check, CONDITION_KEYS, DOMAINS
from flightcostapp.parsers.airport_charges import RECORD_FIELDS


class ChargesSkillContract(unittest.TestCase):
    def test_charges_includes_new_contract(self):
        task = agent_run._task_text('charges', 'TEST TASK')
        for phrase in ('TEST TASK', '"base": "per_mass"', '"mass_basis": "mlw"',
                       '"rate_unit": "1000lb"', 'round_mass',
                       'permitted/non-permitted', 'rules: []'):
            self.assertIn(phrase, task)

    def test_unrelated_jobs_unchanged(self):
        text = agent_run._task_text('prices', 'TEST PRICES')
        self.assertIn('TEST PRICES', text)
        self.assertNotIn('permitted/non-permitted', text)

    def test_mass_rule_is_valid(self):
        r = Rule(code='landing', base='per_mass', mass_basis='mlw',
                 rate_unit='1000lb', rate=8.65, events='landing', currency='USD')
        self.assertEqual(self_check([r]), [])

    def test_legacy_rule_is_valid(self):
        r = Rule(code='landing', base='per_tonne_mtow', rate=8.65, events='landing')
        self.assertEqual(self_check([r]), [])

    def test_generated_schema_describes_owning_definitions(self):
        schema = agent_run.charges_schema()
        for field in fields(Rule):
            if field.init:
                self.assertIn(f'- {field.name}:', schema)
        for field in RECORD_FIELDS:
            self.assertIn(field, schema)
        for key in CONDITION_KEYS:
            self.assertIn(f'- {key}:', schema)
            domain = DOMAINS[key]
            if isinstance(domain, set):
                for value in domain:
                    self.assertIn(json.dumps(value, ensure_ascii=False), schema)
        self.assertIn('evidence', schema)
        self.assertIn('"code": "landing", "when": {}', schema)
        self.assertNotIn('rule_index', schema)
        self.assertIn('quote, where, confidence не входят в Rule', schema)


class ChargesPreflight(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.runner = agent_run.Runner(self.home)
        self.say = mock.patch.object(self.runner, 'say').start()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(agent_run, 'pick_charges', return_value=(
            'TEST', {'city': 'Test', 'url': 'https://example.test/tariff.pdf'}, 'test')).start()
        mock.patch.object(agent_run.urllib.request, 'urlopen', side_effect=OSError('offline test')).start()
        self.budget = mock.patch.object(self.runner, 'budget_ok', return_value=True).start()
        self.valid = {'icao': 'TEST', 'valid_from': '2026-01-01', 'source': 'Test tariff',
                      'source_url': 'https://example.test/tariff.pdf', 'map_node': 'charges.TEST',
                      'rules': [{'code': 'landing', 'base': 'per_mass', 'mass_basis': 'mlw',
                                 'rate_unit': '1000lb', 'rate': 8.65, 'events': 'landing',
                                 'source_note': 'section 1'}]}

    def execute_drafts(self, drafts):
        calls = []

        def execute(job, ws, task, model, **kwargs):
            calls.append((ws, task, kwargs))
            value = drafts[min(len(calls) - 1, len(drafts) - 1)]
            if isinstance(value, Exception):
                raise value
            if value is None:
                (ws / 'out' / 'TEST-2026.json').unlink()
                return {'status': 'error', 'costUsd': 0.05}
            (ws / 'out' / 'TEST-2026.json').write_text(
                json.dumps(value) if isinstance(value, dict) else value, 'utf-8')
            return {'status': 'ok', 'costUsd': 0.05}

        with mock.patch.object(self.runner, 'exec', side_effect=execute) as run:
            result = self.runner.charges_one(only='TEST')
        return result, calls, run

    def invalid(self):
        doc = json.loads(json.dumps(self.valid))
        doc['rules'][0]['quote'] = 'landing fee'
        return doc

    def test_invalid_rule_gets_one_same_workspace_repair_with_exact_error(self):
        result, calls, run = self.execute_drafts([self.invalid(), self.valid])
        self.assertEqual(result, 1)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(calls[0][0], calls[1][0])
        self.assertEqual(calls[1][2], {'attempt': 'correction'})
        checks = json.loads((calls[0][0] / 'validation.json').read_text())
        self.assertIn(checks[0]['error'], calls[1][1])
        self.assertIn("unexpected keyword argument 'quote'", checks[0]['error'])
        self.assertTrue(checks[1]['accepted'])
        self.assertEqual(self.runner.charges_state()['TEST']['status'], 'draft')
        exported = json.loads((self.runner.out / 'charges-TEST-2026.json').read_text())
        self.assertEqual(exported, self.valid)
        self.assertTrue((calls[0][0] / 'rejected-original.json').exists())
        self.assertIn('стоимость 0.10 USD', self.say.call_args.args[0])

    def test_persistent_failure_remains_rejected_and_retry_is_bounded(self):
        result, calls, run = self.execute_drafts([self.invalid()])
        self.assertEqual(result, 0)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(self.runner.charges_state()['TEST']['status'], 'rejected')
        self.assertTrue((self.runner.out / 'charges-TEST-2026.json').exists())
        self.assertIn('ОТКЛОНЁННЫЙ', self.say.call_args.args[0])
        self.assertEqual(self.say.call_args.args[1], 'warn')
        result, _, run = self.execute_drafts([self.invalid()])
        self.assertEqual(run.call_count, 2)
        self.assertEqual(self.runner.charges_state()['TEST']['status'], 'not_found')

    def test_valid_draft_needs_no_correction(self):
        result, _, run = self.execute_drafts([self.valid])
        self.assertEqual(result, 1)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(self.budget.call_count, 1)

    def test_exhausted_budget_exports_rejection_without_second_call(self):
        self.budget.side_effect = [True, False]
        result, _, run = self.execute_drafts([self.invalid()])
        self.assertEqual(result, 0)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(self.runner.charges_state()['TEST']['status'], 'rejected')
        self.assertIn('исчерпан бюджет', self.say.call_args.args[0])

    def test_empty_rules_is_not_a_successful_draft(self):
        self.valid['rules'] = []
        result, _, run = self.execute_drafts([self.valid])
        self.assertEqual(result, 0)
        self.assertEqual(run.call_count, 2)
        self.assertNotEqual(self.runner.charges_state()['TEST']['status'], 'draft')
        self.assertIn('тарифных правил 0', self.say.call_args.args[0])

    def test_malformed_json_gets_a_correction(self):
        result, _, run = self.execute_drafts(['{broken', self.valid])
        self.assertEqual(result, 1)
        self.assertEqual(run.call_count, 2)

    def test_failed_correction_keeps_rejected_draft_visible(self):
        result, _, run = self.execute_drafts([self.invalid(), RuntimeError('correction failed')])
        self.assertEqual(result, 0)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(self.runner.charges_state()['TEST']['status'], 'rejected')
        self.assertIn('correction failed', self.say.call_args.args[0])
        self.assertTrue((self.runner.out / 'charges-TEST-2026.json').exists())

    def test_deleted_correction_exports_original_as_rejected(self):
        result, _, run = self.execute_drafts([self.invalid(), None])
        self.assertEqual(result, 0)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(self.runner.charges_state()['TEST']['status'], 'rejected')
        exported = json.loads((self.runner.out / 'charges-TEST-2026.json').read_text())
        self.assertEqual(exported, self.invalid())

    def test_stopped_agent_does_not_attempt_a_correction(self):
        def execute(job, ws, task, model):
            (ws / 'out' / 'TEST-2026.json').write_text(json.dumps(self.invalid()))
            self.runner.stop = True
            return {'status': 'ok', 'costUsd': None}

        with mock.patch.object(self.runner, 'exec', side_effect=execute) as run:
            self.assertEqual(self.runner.charges_one(only='TEST'), 0)
        self.assertEqual(run.call_count, 1)
        self.assertIn('полная стоимость неизвестна', self.say.call_args.args[0])

    def test_same_workspace_attempts_preserve_both_costs(self):
        ws = self.runner.workspace('charges', 'TEST')
        responses = [mock.Mock(stdout=json.dumps({'status': 'ok', 'costUsd': cost}), stderr='')
                     for cost in (0.03, 0.04)]
        with mock.patch.object(agent_run, '_api_key', return_value='sk-test'), \
                mock.patch.object(agent_run.subprocess, 'run', side_effect=responses):
            self.runner.exec('charges', ws, 'first')
            self.runner.exec('charges', ws, 'repair', attempt='correction')
        ledger = [json.loads(line) for line in self.runner.ledger.read_text().splitlines()]
        self.assertEqual(len(ledger), 2)
        self.assertNotEqual(ledger[0]['run'], ledger[1]['run'])
        self.assertAlmostEqual(agent_run.month_spent(self.runner.ledger), 0.07)
        self.assertTrue((ws / 'result.json').exists())
        self.assertTrue((ws / 'result-correction.json').exists())
