"""Offline tests of the 0064 research registry; no IATI keys or network."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import importlib.util
import json
import sqlite3
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


def mod(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f'{name}.py')
    instance = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(instance)
    return instance


geo, reg, budget, cat = (mod(x) for x in ('georesolve', 'registry', 'usage_budget', 'catalogue'))


def sample(identifier='IATI-X', digest='1'*64, snapshot='2026-11-12T06:51:43+00:00'):
    return {'source_id': 'iati_datastore_v3', 'iati_identifier': identifier,
            'source_variant_sha256': digest, 'snapshot_at': snapshot,
            'title': 'Pilot infrastructure', 'reporting_org': 'X',
            'recipient_countries': [{'iso2':'KE','share_pct':'100'}],
            'sectors': [{'code':'21050', 'vocabulary':'1','share_pct':'100','category':'air_transport'}],
            'status_code':'2',
            'activity_dates': [{'type_code':'1','date':'2028-12-01'},
                               {'type_code':'2','date':'2025-04-12'}],
            'transactions': [{'kind':'outgoing_commitment','kind_code':'2',
                              'amount':'30000000.00','currency':'USD','date':'2024-01-01'},
                             {'kind':'disbursement','kind_code':'3',
                              'amount':'5000000.00','currency':'USD','date':'2025-06-01'}],
            'budgets': [{'amount':'2500000','currency':'EUR','start':'2026-01-01',
                         'end':'2026-12-31','type_code':'1'}],
            'locations': [{'name':'Kenya','coordinates':{'lat':1.0,'lon':38.0},
                           'location_class_code':'1','reach_code':'1','exactness_code':'1'},
                          {'name':'Project workers','coordinates':{'lat':-1.3,'lon':36.8},
                           'location_class_code':'3','reach_code':'2','exactness_code':'1'}]}


class GeoTests(unittest.TestCase):
    def test_country_centroid_is_not_a_site(self):
        x=geo.resolve(sample()['locations'][0],[{'iso2':'KE'}])
        self.assertEqual(x['geo_quality'],'admin_region_unresolved')
        self.assertEqual((x['latitude_reported_or_gazetteer'],x['longitude_reported_or_gazetteer']), (1.0,38.0))
        self.assertFalse(x['airport_assignment_allowed'])

    def test_beneficiaries_are_not_sites_even_if_structure(self):
        x=geo.resolve(sample()['locations'][1],[{'iso2':'KE'}])
        self.assertEqual(x['role'],'beneficiaries')
        self.assertFalse(x['airport_assignment_allowed'])

    def test_single_country_no_coordinates_remains_country_only(self):
        x=geo.country_fallback([{'iso2':'KE'}])
        self.assertEqual(x['geo_quality'],'country_only')
        self.assertIsNone(x['latitude_reported_or_gazetteer'])

    def test_multiple_countries_unknown(self):
        self.assertEqual(geo.country_fallback([{'iso2':'KE'},{'iso2':'TZ'}])['geo_quality'],'unknown')

    def test_offline_ambiguous_city_remains_unresolved(self):
        gaz={('KE','nakuru'):[{'lat':1.,'lon':2.},{'lat':3.,'lon':4.}]}
        x=geo.resolve({'name':'Nakuru','location_class_code':'2'},[{'iso2':'KE'}],gaz)
        self.assertIsNone(x['latitude_reported_or_gazetteer'])
        self.assertEqual(x['candidate_count'],2)

    def test_offline_unique_city(self):
        gaz={('KE','nakuru'):[{'lat':-0.3,'lon':36.1}]}
        x=geo.resolve({'name':'Nakuru','location_class_code':'2'},[{'iso2':'KE'}],gaz)
        self.assertEqual(x['geo_quality'],'settlement_resolved')
        self.assertFalse(x['airport_assignment_allowed'])

    def test_invalid_point_and_beneficiary(self):
        x=geo.resolve({'coordinates':{'lat':float('nan'),'lon':1000}, 'reach_code':'2'}, [])
        self.assertEqual(x['role'],'beneficiaries')
        self.assertIsNone(x['latitude_reported_or_gazetteer'])


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        reg.init(self.db)

    def tearDown(self):
        self.db.close()

    def test_idempotence(self):
        self.assertEqual(reg.ingest(self.db,[sample()])['new_variants'],1)
        self.assertEqual(reg.ingest(self.db,[sample()])['new_variants'],0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM project_finance').fetchone()[0],3)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM source_sighting').fetchone()[0],1)

    def test_conflicting_versions_preserve_original_amounts(self):
        one=sample();two=sample(digest='2'*64);two['transactions'][0]['amount']='90000000'
        x=reg.ingest(self.db,[one,two])
        self.assertEqual(x['unique_projects'],1)
        self.assertEqual(x['conflicted_identifiers'],1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM project_source').fetchone()[0],2)
        rows=self.db.execute('SELECT DISTINCT amount_decimal FROM project_finance WHERE finance_stage="outgoing_commitment"').fetchall()
        self.assertEqual({r[0] for r in rows},{'30000000.00','90000000'})
        self.assertEqual(self.db.execute('SELECT review_state FROM project').fetchone()[0],'review')

    def test_known_as_of_snapshot_not_event(self):
        x=sample();reg.ingest(self.db,[x])
        known=self.db.execute('SELECT DISTINCT known_as_of FROM project_event').fetchall()
        self.assertEqual(known,[(x['snapshot_at'],)])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM project_airport_exposure').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM forecast_feature').fetchone()[0],0)

    def test_sightings_preserve_versions_over_time(self):
        a=sample();b=sample(snapshot='2026-12-01T00:00:00+00:00'); reg.ingest(self.db,[a,b])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM source_sighting').fetchone()[0],2)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM project_source').fetchone()[0],1)

    def test_finance_types_separated(self):
        reg.ingest(self.db,[sample()]);self.assertEqual(
            self.db.execute('SELECT kind,finance_stage,currency FROM project_finance ORDER BY kind,ordinal').fetchall(),
            [('budget','budget','EUR'),('transaction','outgoing_commitment','USD'),('transaction','disbursement','USD')])

    def test_invalid_amount_rolls_back(self):
        a=sample();a['transactions'][0]['amount']='NaN'
        with self.assertRaises(ValueError):reg.ingest(self.db,[a])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM project').fetchone()[0],0)

    def test_invalid_hash_rejected(self):
        a=sample();a['source_variant_sha256']='bad'
        with self.assertRaises(ValueError):reg.ingest(self.db,[a])


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:',isolation_level=None)
        budget.init(self.db)
        self.now=datetime(2026,11,12,tzinfo=timezone.utc)

    def tearDown(self):self.db.close()

    def test_minute_limit_and_weekly_limit(self):
        for i in range(5):budget.reserve(self.db,now=self.now)
        self.assertFalse(budget.snapshot(self.db,now=self.now)['allowed'])
        with self.assertRaises(RuntimeError):budget.reserve(self.db,now=self.now)
        self.assertTrue(budget.snapshot(self.db,now=self.now+timedelta(seconds=61))['allowed'])

    def test_week_limit_blocks_across_minutes(self):
        for i in range(2):budget.reserve(self.db,now=self.now+timedelta(minutes=i*2),week_limit=2)
        with self.assertRaises(RuntimeError):budget.reserve(self.db,now=self.now+timedelta(minutes=4),week_limit=2)

    def test_failed_attempt_still_counts_and_finishes_once(self):
        x=budget.reserve(self.db,now=self.now)
        budget.finish(self.db,x,http_status=403,now=self.now)
        self.assertEqual(budget.snapshot(self.db,now=self.now)['minute_used'],1)
        with self.assertRaises(ValueError):budget.finish(self.db,x,http_status=200,now=self.now)

    def test_retry_after(self):
        x=budget.reserve(self.db,now=self.now)
        budget.finish(self.db,x,http_status=429,retry_after_seconds=150,now=self.now)
        self.assertFalse(budget.snapshot(self.db,now=self.now+timedelta(seconds=61))['allowed'])
        self.assertTrue(budget.snapshot(self.db,now=self.now+timedelta(seconds=151))['allowed'])


class CatalogueTests(unittest.TestCase):
    def test_synthetic_index_list(self):
        b=json.dumps([{'id':'a'},{'id':'b','countries':['KE']}]).encode()
        s=cat.inspect_index(b)
        self.assertEqual(s['datasets'],2)
        self.assertTrue(s['cannot_filter_projects_from_index_alone'])

    def test_index_mapping(self):
        self.assertEqual(len(cat.entries({'datasets':{'a':{'name':'a'},'b':{'name':'b'}}})),2)

    def test_unknown_index_rejected(self):
        with self.assertRaises(ValueError):cat.inspect_index(b'{"strange":123}')

    def test_unapproved_url_rejected_without_network(self):
        with self.assertRaises(ValueError):cat.download_index(url='https://untrusted.example/index')


if __name__=='__main__':unittest.main()

class GazetteerExportTests(unittest.TestCase):
    def test_converts_only_city_facts_without_traffic_or_secrets(self):
        from io import StringIO
        import csv
        converter=mod('gazetteer_from_tail')
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'sample.jsonl'; dst=Path(d)/'cities.csv'
            rows=[{'record':'fact','domain':'city','source_id':'geonames_cities',
                   'key':'123','value_text':'-1.2,36.8|KE|Nairobi','valid_to':None},
                  {'record':'fact','domain':'traffic','source_id':'eurostat_par',
                   'key':'SENSITIVE','value_text':'not a city'}]
            src.write_text('\n'.join(json.dumps(x) for x in rows)+'\n',encoding='utf-8')
            result=converter.export_cities(src,dst)
            self.assertEqual(result['unique_current_cities'],1)
            lines=dst.read_text(encoding='utf-8')
            self.assertIn('Nairobi',lines)
            self.assertNotIn('SENSITIVE',lines)
