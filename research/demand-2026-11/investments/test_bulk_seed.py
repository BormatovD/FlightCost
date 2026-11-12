"""Offline 0064-C tests: no Datastore API or real publisher downloads."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('bulk_seed', HERE / 'bulk_seed.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

DATASETS = {'datasets': [{
    'id': 'dataset-1', 'short_name': 'afdb-kenya', 'reporting_org_short_name': 'afdb',
    'last_known_good_dataset': {
        'hash_excluding_generated_timestamp': 'e'*32,
        'cached_dataset_url_xml': 'https://bulk-data.iatistandard.org/afdb/afdb-kenya.xml',
    },
}, {
    'id': 'dataset-2', 'short_name': 'afdb-tanzania', 'reporting_org_short_name': 'afdb',
    'last_known_good_dataset': {
        'hash_excluding_generated_timestamp': 'f'*32,
        'cached_dataset_url_xml': 'https://bulk-data.iatistandard.org/afdb/afdb-tanzania.xml',
    },
}]}

XML = b'''<?xml version="1.0" encoding="UTF-8"?>
<iati-activities version="2.03">
  <iati-activity>
    <iati-identifier>ABC-1</iati-identifier><reporting-org ref="46002"/>
    <title><narrative>Airport Upgrade</narrative></title>
    <activity-status code="2"/><recipient-country code="KE" percentage="100"/>
    <sector vocabulary="1" code="21050" percentage="100"/>
    <activity-date type="3" iso-date="2028-12-31"/>
    <location><name><narrative>Nairobi</narrative></name><location-class code="2"/>
        <location-reach code="1"/></location>
  </iati-activity>
  <iati-activity>
    <iati-identifier>DEF-2</iati-identifier><title><narrative>Other</narrative></title>
    <recipient-country code="TZ"/><sector vocabulary="2" code="21050"/>
  </iati-activity>
  <iati-activity><iati-identifier>GHI-3</iati-identifier><title><narrative>Unknown country</narrative></title></iati-activity>
</iati-activities>'''


class FakeResponse(io.BytesIO):
    def __init__(self, data, url):
        super().__init__(data)
        self.url = url
        self.headers = {'Content-Length': str(len(data))}
    def geturl(self):
        return self.url


class BulkSeedTests(unittest.TestCase):
    def test_exact_selection_keeps_source_url_and_hash(self):
        d = mod.select(DATASETS, ['afdb-kenya'])
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]['name'], 'afdb-kenya')
        self.assertEqual(d[0]['upstream_content_hash'], 'e'*32)
        self.assertIn('/afdb/afdb-kenya.xml', d[0]['url'])

    def test_missing_or_duplicate_name_is_error(self):
        with self.assertRaisesRegex(ValueError, 'Unknown exact'):
            mod.select(DATASETS, ['afdb-cv'])
        with self.assertRaises(ValueError):
            mod.name_list('afdb-kenya,afdb-kenya')
        with self.assertRaises(ValueError):
            mod.name_list('../private')

    def test_prevent_ssrf_and_unbounded_bulk_crawl(self):
        for u in ('http://bulk-data.iatistandard.org/a.xml',
                  'https://localhost/private.xml',
                  'https://bulk-data.iatistandard.org.evil.net/a.xml',
                  'https://bulk-data.iatistandard.org/../other.xml',
                  'https://bulk-data.iatistandard.org/a.zip'):
            with self.assertRaises(ValueError):
                mod.canonical_url(u)

    def test_extract_country_sector_stage_and_location(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t)/'source.xml';p.write_bytes(XML)
            got = mod.scan_file(p, mod.select(DATASETS,['afdb-kenya'])[0], countries={'KE'})
            self.assertEqual(got['counts']['activities'],3)
            self.assertEqual(got['counts']['matching_country'],1)
            self.assertEqual(got['counts']['matching_watch_sector'],1)
            self.assertEqual(got['counts']['missing_recipient_country'],1)
            row = got['rows'][0]
            self.assertEqual(row['iati_identifier'],'ABC-1')
            self.assertEqual(row['status'],'2')
            self.assertEqual(row['recipient_countries'][0]['code'],'KE')
            self.assertEqual(row['activity_dates'][0]['iso_date'],'2028-12-31')
            self.assertEqual(row['locations'][0]['class'],'2')

    def test_second_vocabulary_is_not_dac5(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'source.xml';p.write_bytes(XML)
            got=mod.scan_file(p, mod.select(DATASETS,['afdb-kenya'])[0],countries={'TZ'})
            self.assertEqual(got['counts']['matching_country'],1)
            self.assertEqual(got['counts'].get('matching_watch_sector',0),0)

    def test_namespaced_xml_and_related_activities(self):
        xml=b'''<iati-activities xmlns="http://example.org/iati"><iati-activity>
            <iati-identifier>A</iati-identifier><title><narrative>Nador</narrative></title>
            <recipient-country code="MA"/><related-activity ref="PARENT" type="1"/>
            </iati-activity></iati-activities>'''
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'source.xml';p.write_bytes(xml)
            got=mod.scan_file(p,mod.select(DATASETS,['afdb-kenya'])[0],countries={'MA'})
            self.assertEqual(got['rows'][0]['related_activities'][0]['ref'],'PARENT')

    def test_no_network_until_explicit_download(self):
        with tempfile.TemporaryDirectory() as t:
            idx=Path(t)/'idx.json';idx.write_text(json.dumps(DATASETS))
            r=mod.run(idx, Path(t)/'out',['afdb-kenya'],download=False)
            self.assertFalse(r['network_requested'])
            self.assertFalse((Path(t)/'out').exists())
            self.assertEqual(r['datastore_calls'],0)

    def test_bounded_download_then_content_hash_cache(self):
        with tempfile.TemporaryDirectory() as t:
            idx=Path(t)/'idx.json';idx.write_text(json.dumps(DATASETS))
            url=mod.select(DATASETS,['afdb-kenya'])[0]['url']
            requests=[]
            def opener(req,timeout):
                requests.append(req.full_url)
                return FakeResponse(XML,url)
            out=Path(t)/'out'
            first=mod.run(idx,out,['afdb-kenya'],download=True,countries={'KE'},opener=opener)
            second=mod.run(idx,out,['afdb-kenya'],download=True,countries={'KE'},opener=opener)
            self.assertEqual(len(requests),1)
            self.assertEqual(first['downloads_this_run'],1)
            self.assertEqual(second['downloads_this_run'],0)
            self.assertEqual(second['results'][0]['status'],'unchanged_cache')
            self.assertEqual(first['results'][0]['activities'],3)
            self.assertEqual(first['results'][0]['matching_country'],1)
            self.assertEqual((out/'raw/afdb-kenya.xml').stat().st_mode & 0o777,0o600)
            self.assertEqual(out.stat().st_mode & 0o777,0o700)

    def test_reject_unsafe_existing_cache_dir(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'shared';path.mkdir(mode=0o755)
            with self.assertRaises(PermissionError):
                mod._private_dir(path)

    def test_http_response_larger_than_cap_not_saved(self):
        with tempfile.TemporaryDirectory() as t:
            url=mod.select(DATASETS,['afdb-kenya'])[0]['url']
            dst=Path(t)/'private'/'one.xml'
            def opener(req,timeout):return FakeResponse(b'x'*105000,url)
            with self.assertRaisesRegex(ValueError,'exceeds per-file cap'):
                mod.stream_download(url,dst,max_bytes=100000,opener=opener)
            self.assertFalse(dst.exists())

    def test_bad_xml_cannot_complete_scan(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'bad.xml';p.write_bytes(b'<iati-activities><iati-activity>')
            with self.assertRaisesRegex(ValueError,'Malformed IATI'):
                mod.scan_file(p,mod.select(DATASETS,['afdb-kenya'])[0],countries={'KE'})

    def test_multidataset_selection_requires_limit(self):
        with tempfile.TemporaryDirectory() as t:
            idx=Path(t)/'idx.json';idx.write_text(json.dumps(DATASETS))
            with self.assertRaisesRegex(ValueError,'Choose 1'):
                mod.run(idx,Path(t)/'out',['afdb-kenya','afdb-tanzania'],max_files=1)

if __name__=='__main__':
    unittest.main()
