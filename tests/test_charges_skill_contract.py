"""0066: инструктаж тарифного агента проверяется до API-вызова."""
import unittest
from flightcostapp import agent_run
from flightcostapp.charges import Rule, self_check


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
