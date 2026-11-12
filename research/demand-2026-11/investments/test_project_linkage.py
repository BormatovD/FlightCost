"""0064-F offline source-linkage regression tests, no API calls or credentials."""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

try:
    from .project_linkage import (country_set, emit, group_explicit_relations,
                                  id_index, identity_rows, normalize, point_claims,
                                  title_suggestions, tokens)
except ImportError:
    from project_linkage import (country_set, emit, group_explicit_relations,
                                 id_index, identity_rows, normalize, point_claims,
                                 title_suggestions, tokens)


def activity(ident, title, *, origin='bulk', dataset='a', publisher='org-a',
             country='MA', sector='21040', status='2', planned='2030-12-31',
             rel=None, locations=None):
    return {
        'iati_identifier':ident, 'title':title, '_origin':origin,
        'dataset_name':dataset, 'reporting_org':publisher,
        'recipient_countries':[{'iso2':country}] if country else [],
        'sectors':[{'vocabulary':'1','code':sector}] if sector else [],
        'status_code':status,
        'activity_dates':[{'type_code':'3','date':planned}] if planned else [],
        'related_activities':rel or [], 'locations': locations or [],
        'transactions':[{'kind':'commitment','amount':'100000000','currency':'EUR'}],
        'budgets':[{'amount':'250000000','currency':'EUR'}],
    }


class LinkageTest(unittest.TestCase):
    def test_same_iati_id_across_two_inputs_is_not_two_ids(self):
        a=activity('P1','Nador port infrastructure',origin='bulk')
        b=activity('P1','Nador port infrastructure',origin='datastore',status='3')
        records=identity_rows(id_index([a,b]))
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['source_records'],2)
        self.assertEqual(records[0]['seen_in_bulk'],1)
        self.assertEqual(records[0]['seen_in_datastore'],1)
        self.assertEqual(records[0]['needs_source_reconciliation'],1)
        self.assertEqual(records[0]['independent_investment_project_proven'],0)

    def test_both_directions_of_parent_child_make_one_evidence_family(self):
        a=activity('P','Shinyanga solar power plant',rel=[{'ref':'C','type':'2'}])
        b=activity('C','Shinyanga solar power plant',rel=[{'ref':'P','type':'1'}])
        idx,fam,links,edges=group_explicit_relations([a,b],[])
        self.assertEqual(len(fam),1)
        self.assertEqual(idx['P'],idx['C'])
        self.assertEqual(edges,{('P','C')})
        self.assertTrue(all(x['same_physical_asset_proven']==0 for x in links))

    def test_cofunding_thirdparty_and_sibling_do_not_merge(self):
        a=activity('P','New city railway',rel=[{'ref':'Q','type':'4'},
                                                 {'ref':'R','type':'5'},
                                                 {'ref':'S','type':'3'}])
        rows=[a, activity('Q','New city railway'),activity('R','New city railway'),
              activity('S','New city railway')]
        _,families,rels,edges=group_explicit_relations(rows,[])
        self.assertEqual(len(families),4)
        self.assertEqual(len(edges),0)
        self.assertEqual({r['meaning'] for r in rels},{'co_funded','third_party_report_of_activity','sibling'})

    def test_external_parent_preserved_not_inferred_as_new_asset(self):
        r=activity('C','Port access road',rel=[{'ref':'not-downloaded','type':'1'}])
        _,fam,rels,edges=group_explicit_relations([r],[])
        self.assertEqual(len(fam),1)
        self.assertEqual(len(edges),0)
        self.assertEqual(rels[0]['both_ids_in_inputs'],0)

    def test_cross_publisher_title_match_requires_review(self):
        a=activity('A','Nador West Med Port Complex Construction Project',publisher='AfDB',dataset='afdb')
        b=activity('B','Nador West Med Port',publisher='EBRD',dataset='ebrd')
        suggestions=title_suggestions(id_index([a,b]), {'A':'A','B':'B'})
        self.assertEqual(len(suggestions),1)
        self.assertEqual(suggestions[0]['link_type'],'cross_publisher_shared_scope')
        self.assertEqual(suggestions[0]['same_physical_asset_proven'],0)
        self.assertEqual(suggestions[0]['review_decision'],'')

    def test_similar_title_in_different_countries_not_suggested(self):
        a=activity('A','Nador West Med Port',country='MA')
        b=activity('B','Nador West Med Port',country='KE',dataset='b',publisher='org-b')
        self.assertFalse(title_suggestions(id_index([a,b]), {'A':'A','B':'B'}))

    def test_unrelated_sector_not_merged_from_identical_title(self):
        a=activity('A','New regional logistics park',sector='21061')
        b=activity('B','New regional logistics park',sector='33220',dataset='b',publisher='org-b')
        self.assertFalse(title_suggestions(id_index([a,b]), {'A':'A','B':'B'}))

    def test_same_dataset_title_repetition_not_match(self):
        a=activity('A','Annual Industrial Development Programme')
        b=activity('B','Annual Industrial Development Programme')
        self.assertFalse(title_suggestions(id_index([a,b]), {'A':'A','B':'B'}))

    def test_generic_title_does_not_create_cross_publisher_link(self):
        a=activity('A','Financing Programme')
        b=activity('B','Financing Programme',dataset='b',publisher='org-b')
        self.assertFalse(title_suggestions(id_index([a,b]), {'A':'A','B':'B'}))

    def test_same_issuer_different_datasets_not_proven(self):
        a=activity('A','Nador West Med Port Complex',dataset='a',publisher='AfDB')
        b=activity('B','Nador West Med Port Complex',dataset='b',publisher='AfDB')
        p=title_suggestions(id_index([a,b]), {'A':'A','B':'B'})
        self.assertEqual(p[0]['link_type'],'same_publisher_repeat_or_component')
        self.assertEqual(p[0]['suggestion_only'],1)

    def test_approximate_city_is_not_verified_site(self):
        r=activity('A','Shinyanga solar plant',locations=[{
            'coordinates':{'lat':-6.8,'lon':39.2},'location_class_code':'2',
            'exactness_code':'2','reach_code':'1'}])
        self.assertEqual(point_claims([r]),[('2','1','2')])
        with tempfile.TemporaryDirectory() as tmp:
            m=emit(Path(tmp)/'out',[r],[],as_of='2026-11-12',max_pairs=100)
            self.assertEqual(m['physical_assets_verified'],0)
            with (Path(tmp)/'out'/'evidence_families.csv').open(encoding='utf-8-sig') as f:
                row=next(csv.DictReader(f))
            self.assertEqual(row['structure_site_claims_unverified'],'0')
            self.assertEqual(row['verified_site'],'0')

    def test_structure_claim_without_independent_source_is_still_unverified(self):
        r=activity('A','Shinyanga solar plant',locations=[{
            'coordinates':{'lat':-6.8,'lon':39.2},'location_class_code':'3',
            'exactness_code':'1','reach_code':'1'}])
        with tempfile.TemporaryDirectory() as tmp:
            emit(Path(tmp)/'out',[r],[],as_of='2026-11-12',max_pairs=100)
            with (Path(tmp)/'out'/'evidence_families.csv').open(encoding='utf-8-sig') as f:
                row=next(csv.DictReader(f))
            self.assertEqual(row['structure_site_claims_unverified'],'1')
            self.assertEqual(row['verified_site'],'0')

    def test_outputs_do_not_contain_aggregated_amount_or_verified_site(self):
        a=activity('A','Morocco airport terminal')
        b=activity('B','Morocco airport terminal',dataset='b',publisher='org-b')
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out'
            m=emit(out,[a,b],[],as_of='2026-11-12',max_pairs=100)
            self.assertEqual(m['distinct_iati_ids'],2)
            self.assertEqual(m['review_link_suggestions'],1)
            self.assertFalse(m['finance_aggregation_performed'])
            self.assertFalse(m['airport_assignment_performed'])
            for f in out.iterdir():
                self.assertEqual(stat.S_IMODE(f.stat().st_mode),0o600)
                self.assertNotIn('100000000',f.read_text())
            self.assertEqual(stat.S_IMODE(out.stat().st_mode),0o700)

    def test_reproducible_manifest_bytes(self):
        a=activity('A','Airport expansion project')
        with tempfile.TemporaryDirectory() as d:
            o=Path(d)/'out';emit(o,[a],[],as_of='2026-11-12',max_pairs=100)
            first=(o/'manifest.json').read_bytes()
            emit(o,[a],[],as_of='2026-11-12',max_pairs=100)
            self.assertEqual(first,(o/'manifest.json').read_bytes())

    def test_country_code_requires_iso_two_characters(self):
        a=activity('A','Port extension',country='ZZZ')
        self.assertEqual(country_set(a),set())

    def test_no_false_title_reconciliation_on_parent_child(self):
        a=activity('A','Mombasa special economic zone')
        b=activity('B','Mombasa special economic zone',publisher='org-b',dataset='b')
        idx,fams,_,_=group_explicit_relations([a,b],[{'source_id':'A','target_id':'B','type_code':'2'}])
        self.assertEqual(len(fams),1)
        self.assertEqual(title_suggestions(id_index([a,b]),idx),[])


if __name__ == '__main__': unittest.main()
