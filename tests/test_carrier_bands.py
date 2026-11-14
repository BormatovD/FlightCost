"""Regression checks for accepted reports, period boundaries and entity weights."""
import json
import sqlite3
import unittest
from datetime import date
from types import SimpleNamespace

from flightcostapp.carrier_bands import comparison


class CarrierBands(unittest.TestCase):
    def setUp(self):
        db = sqlite3.connect(':memory:')
        db.row_factory = sqlite3.Row
        db.execute('CREATE TABLE facts (key TEXT,value REAL,value_text TEXT,currency TEXT,note TEXT,domain TEXT,valid_to TEXT)')
        self.store = SimpleNamespace(db=db)

    def report(self, code, end='2025-12-31', entity=None, currency='EUR', rate=None):
        meta = json.dumps(dict(name=code, entity_id=entity or code, segment='lowcost',
                               period_start=end[:4]+'-01-01', period_end=end))
        values = dict(ask_km=1e8, rpk_km=8e7, pax=80000,
                      opex_eur=1e7, fuel_cost_eur=4e6)
        if rate:
            values['fx_per_eur'] = rate
        for key, value in values.items():
            self.store.db.execute('INSERT INTO facts VALUES (?,?,?,?,?,?,NULL)',
                                  (f'{code}/{end[:4]}/{key}',value,meta,currency,'https://example.com/report','carrier_benchmark'))

    def test_exfuel_adjustment_and_independent_entity_quantiles(self):
        for i in range(5):
            self.report(str(i))
        self.report('GROUP', entity='0')
        result = comparison(self.store, 250, date(2026,11,14))
        self.assertEqual(len(result['carriers']),5)
        self.assertAlmostEqual(result['segments'][0]['p50'],12)
        small = comparison(self.store, 1000, date(2026,11,14))
        self.assertAlmostEqual(small['segments'][0]['p50'],6)

    def test_freshness_exact_boundaries_and_opt_in(self):
        self.report('FR')
        self.assertEqual(len(comparison(self.store,1000,date(2027,6,30))['carriers']),1)
        self.assertEqual(len(comparison(self.store,1000,date(2027,7,1))['carriers']),0)
        self.assertTrue(comparison(self.store,1000,date(2027,7,1),True)['carriers'][0]['stale'])
        self.assertEqual(len(comparison(self.store,1000,date(2028,1,1),True)['carriers']),0)

    def test_no_current_fx_fallback_and_small_sample_has_no_band(self):
        self.report('USD',currency='USD')
        self.report('EUR')
        result=comparison(self.store,1000,date(2026,11,14))
        self.assertEqual(len(result['carriers']),1)
        self.assertIsNone(result['segments'][0]['p50'])

    def test_latest_eligible_period_only(self):
        self.report('A',end='2024-12-31')
        self.report('A',end='2025-12-31')
        rows=comparison(self.store,1000,date(2026,11,14),True)['carriers']
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['period_end'],'2025-12-31')


class AcceptedReportPipeline(unittest.TestCase):
    def test_review_then_reload_revision_retires_removed_values(self):
        import tempfile
        from pathlib import Path
        from flightcostapp import carrier_reports
        from flightcostapp.refresh import refresh_source
        from flightcostapp.store import Store
        from tests.test_carrier_reports import report

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / 'reports'
            store = Store(Path(directory) / 'facts.db')
            registry = {'sources': {'carrier_benchmark': {
                'kind': 'directory', 'path': str(folder), 'glob': '*.yaml',
                'domain': 'carrier_benchmark', 'parser': 'carrier_benchmark',
                'gate': 'review', 'tier': 1, 'validators': {}}}}
            for i in range(5):
                doc = report()
                doc.update(carrier=f'X{i}',entity_id=f'X{i}',name=f'Airline {i}')
                carrier_reports.accept(doc, folder)
            result = refresh_source('carrier_benchmark',registry,store)
            self.assertEqual(result['outcome'],'proposal')
            self.assertEqual(comparison(store,800,date(2026,11,14))['carriers'],[])
            store.resolve_proposal(result['proposal_id'],True)
            band = comparison(store,800,date(2026,11,14))['segments'][0]
            self.assertEqual(band['n'],5)
            self.assertAlmostEqual(band['p50'],8)
            # A corrected accepted report removes fuel. It must not inherit old fuel.
            doc = report()
            doc.update(carrier='X0',entity_id='X0',name='Airline 0',report_id='revision2')
            del doc['values']['fuel_cost_eur']
            carrier_reports.accept(doc,folder)
            result = refresh_source('carrier_benchmark',registry,store)
            store.resolve_proposal(result['proposal_id'],True)
            self.assertEqual(comparison(store,800,date(2026,11,14))['segments'][0]['n'],4)


if __name__ == '__main__':
    unittest.main()
