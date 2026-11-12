"""Offline regression tests for IATI 0064-D source-preserving XML enrichment."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

import bulk_seed
import bulk_detail


PREFIX = '<iati-activities version="2.03">'
SUFFIX = '</iati-activities>'


def activity(identifier='FR-3-CTZ1075', *, end='2028-02-11', amount='1250000.00',
             title='Public transport BRT', parent_ref=None):
    relation = (f'<related-activity ref="{parent_ref}" type="1"/>' if parent_ref else '')
    return f'''<iati-activity default-currency="EUR" last-updated-datetime="2026-11-12T09:00:00Z">
    <iati-identifier>{identifier}</iati-identifier>
    <reporting-org ref="FR-3"/><title><narrative>{title}</narrative></title>
    <description type="1"><narrative>Public transport investment</narrative></description>
    <activity-status code="2"/>
    <recipient-country code="TZ" percentage="100"/><sector vocabulary="1" code="21012" percentage="100"/>
    <activity-date type="2" iso-date="2022-08-17"/><activity-date type="3" iso-date="{end}"/>
    <location><name><narrative>Dar es Salaam</narrative></name><location-class code="2"/>
      <location-reach code="1"/><exactness code="2"/>
      <location-id vocabulary="G1" code="160263"/>
      <point srsName="http://www.opengis.net/def/crs/EPSG/0/4326"><pos>-6.81 39.28</pos></point></location>
    <transaction><transaction-type code="2"/><transaction-date iso-date="2026-09-01"/>
      <value currency="EUR" value-date="2026-09-01">{amount}</value></transaction>
    <transaction><transaction-type code="3"/><transaction-date iso-date="2026-10-01"/>
      <value currency="EUR">150000</value></transaction>
    <budget type="1"><period-start iso-date="2026-01-01"/><period-end iso-date="2026-12-31"/>
      <value currency="EUR">100000</value></budget>
    {relation}
    </iati-activity>'''


def fixture(root: Path, name='afd-tz', xml=None):
    rawdir = root / 'raw'
    rawdir.mkdir(mode=0o700)
    os.chmod(rawdir, 0o700)
    xml = xml if xml is not None else (PREFIX+activity()+SUFFIX).encode()
    p=rawdir/(name+'.xml')
    p.write_bytes(xml)
    dataset={'name':name,'dataset_id':'c275292e-be89-47af-a39d-b61142438d7c',
             'publisher':'afd','url':f'https://bulk-data.iatistandard.org/afd/{name}.xml',
             'upstream_content_hash':'a'*40,'verified_on_server':'2026-11-12T17:00:25+00:00'}
    cache={**dataset,'sha256':hashlib.sha256(xml).hexdigest(),'bytes':len(xml)}
    (rawdir/(name+'.cache.json')).write_text(json.dumps(cache))
    scan=bulk_seed.scan_file(p,dataset,countries={'TZ','MA','CV','KE'})
    scanpath=root/(name+'.scan.json')
    scanpath.write_text(json.dumps(scan))
    return scanpath,rawdir


class BulkDetailTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def test_read_finances_locations_and_relations_without_aggregation(self):
        scan,rawdir=fixture(self.root,xml=(PREFIX+activity()+activity('FR-3-CTZ107501', parent_ref='FR-3-CTZ1075')+SUFFIX).encode())
        rows,summary=bulk_detail.read_dataset(scan,rawdir,now='2026-11-13T00:00:00+00:00')
        self.assertEqual(len(rows),2)
        r=rows[0]
        self.assertEqual(r['source_id'],'iati_bulk:afd-tz')
        self.assertEqual(len(r['transactions']),2)
        self.assertEqual(r['transactions'][0]['amount'],'1250000.00')
        self.assertEqual(r['transactions'][0]['kind'],'commitment')
        self.assertEqual(r['transactions'][1]['kind'],'disbursement')
        self.assertEqual(r['budgets'][0]['amount'],'100000')
        self.assertEqual(r['locations'][0]['coordinates'],{'lat':-6.81,'lon':39.28})
        self.assertEqual(r['locations'][0]['reach_code'],'1')
        self.assertEqual(r['related_activities'],[])
        self.assertEqual(rows[1]['related_activities'],[{'ref':'FR-3-CTZ1075','type':'1'}])
        self.assertEqual(summary['transactions'],4)
        self.assertEqual(summary['locations_with_points'],2)

    def test_end_to_end_creates_private_files(self):
        scan,rawdir=fixture(self.root)
        out=self.root/'report'
        result=bulk_detail.run([scan],rawdir,out)
        self.assertEqual(result['unique_identifiers'],1)
        self.assertEqual(result['datastore_api_calls'],0)
        self.assertEqual(result['financial_aggregation_performed'],False)
        self.assertEqual(len((out/'candidates.jsonl').read_text().splitlines()),1)
        self.assertEqual((out/'manifest.json').stat().st_mode & 0o077,0)
        self.assertEqual((out/'candidates.jsonl').stat().st_mode & 0o077,0)
        self.assertEqual(out.stat().st_mode & 0o077,0)
        with self.assertRaisesRegex(ValueError,'already contains'):
            bulk_detail.run([scan],rawdir,out)

    def test_source_cache_mismatch_blocks(self):
        scan,rawdir=fixture(self.root)
        (rawdir/'afd-tz.xml').write_bytes(PREFIX.encode()+activity(title='Changed') .encode()+SUFFIX.encode())
        with self.assertRaisesRegex(ValueError,'hash differs'):
            bulk_detail.read_dataset(scan,rawdir,now='2026-11-13T00:00:00+00:00')

    def test_scan_metadata_disagreement_blocks(self):
        scan,rawdir=fixture(self.root)
        data=json.loads(scan.read_text())
        data['rows'][0]['status']='5'
        scan.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'metadata disagrees'):
            bulk_detail.read_dataset(scan,rawdir,now='2026-11-13T00:00:00+00:00')

    def test_refuses_dtd_and_missing_data(self):
        scan,rawdir=fixture(self.root)
        raw=rawdir/'afd-tz.xml'
        p=raw.read_bytes().replace(b'<iati-activities',b'<!DOCTYPE data [<!ENTITY hack "xx">]><iati-activities')
        raw.write_bytes(p)
        marker=rawdir/'afd-tz.cache.json'
        m=json.loads(marker.read_text());m['sha256']=hashlib.sha256(p).hexdigest();marker.write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError,'DTD/entities'):
            bulk_detail.read_dataset(scan,rawdir,now='2026-11-13T00:00:00+00:00')

    def test_not_convert_ml_or_money_by_assumption(self):
        scan,rawdir=fixture(self.root)
        rows,_=bulk_detail.read_dataset(scan,rawdir,now='2026-11-13T00:00:00+00:00')
        self.assertNotIn('sum',rows[0])
        self.assertIsNone(rows[0]['locations'][0].get('airport_icao'))
        self.assertEqual(rows[0]['historically_available_before_snapshot'],'unverified')
        self.assertEqual(rows[0]['sectors'][0]['category'],None)

    def test_watch_list_includes_real_world_indirect_projects(self):
        for code in ('21012', '21023', '23220', '23230', '23231'):
            self.assertIn(code,bulk_seed.WATCH_SECTORS)
        self.assertNotIn('15110',bulk_seed.WATCH_SECTORS)

    def test_invalid_numeric_aborts(self):
        scan,rawdir=fixture(self.root,xml=(PREFIX+activity(amount='not-a-number')+SUFFIX).encode())
        with self.assertRaisesRegex(ValueError,'Invalid amount'):
            bulk_detail.read_dataset(scan,rawdir,now='2026-11-13T00:00:00+00:00')

    def test_conflicting_same_identifier_versions_preserved(self):
        scan,rawdir=fixture(self.root, xml=(PREFIX+activity(title='One')+activity(title='Two')+SUFFIX).encode())
        out=self.root/'out'
        result=bulk_detail.run([scan],rawdir,out)
        self.assertEqual(result['unique_identifiers'],1)
        self.assertEqual(result['distinct_variants'],2)
        self.assertEqual(result['conflict_identifiers'],['FR-3-CTZ1075'])
        lines=[json.loads(x) for x in (out/'candidates.jsonl').read_text().splitlines()]
        self.assertTrue(all(x['identifier_conflict'] for x in lines))
        self.assertTrue(all(x['financial_aggregation_blocked_reason'] for x in lines))

    def test_invalid_location_coordinates_left_unknown(self):
        scan,rawdir=fixture(self.root,xml=(PREFIX+activity().replace('-6.81 39.28','-300 600')+SUFFIX).encode())
        rows,_=bulk_detail.read_dataset(scan,rawdir,now='2026-11-13T00:00:00+00:00')
        self.assertIsNone(rows[0]['locations'][0]['coordinates'])


if __name__=='__main__':
    unittest.main()

class RegistryIntegrationTests(unittest.TestCase):
    def test_offline_bulk_records_go_to_separate_namespace_with_all_finance_stages(self):
        import registry
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            scan,rawdir=fixture(root)
            out=root/'enriched'
            bulk_detail.run([scan],rawdir,out)
            rows=[json.loads(s) for s in (out/'candidates.jsonl').read_text().splitlines()]
            db=sqlite3.connect(':memory:')
            registry.init(db)
            result=registry.ingest(db,rows)
            self.assertEqual(result['unique_projects'],1)
            self.assertEqual(result['site_assignments'],0)
            fees=db.execute('SELECT finance_stage, amount_decimal FROM project_finance ORDER BY kind,ordinal').fetchall()
            self.assertEqual(len(fees),3)
            self.assertEqual({k for k,v in fees},{'budget','commitment','disbursement'})
            pr=db.execute('SELECT source_id,iati_identifier FROM project').fetchone()
            self.assertEqual(pr,('iati_bulk:afd-tz','FR-3-CTZ1075'))
            loc=db.execute('SELECT geometry_type,geo_quality,airport_assignment_allowed FROM project_location').fetchone()
            self.assertEqual(loc,('settlement_reference','settlement_resolved',0))
            db.close()
