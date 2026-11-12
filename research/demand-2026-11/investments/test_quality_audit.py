"""0064-E quality audit: deterministic and strictly evidence-only."""
import unittest

try:
    from .quality_audit import audit, groups_from_relations
except ImportError:
    from quality_audit import audit, groups_from_relations


def case(identifier, *, status='2', planned='2030-01-01', actual=None, loc=None, sector='21050', ds='afd-tz'):
    dates=[{'type_code':'3','date':planned}]
    if actual:dates.append({'type_code':'4','date':actual})
    return {'iati_identifier':identifier,'dataset_name':ds,'status_code':status,
            'activity_dates':dates,'locations':[loc] if loc else [],
            'title':identifier,'sectors':[{'vocabulary':'1','code':sector}],
            'transactions':[],'budgets':[], 'historically_available_before_snapshot':'unverified'}


class TestQualityAudit(unittest.TestCase):
    def test_explicit_parent_child_group_not_extra_investments(self):
        x=[case('parent'),case('child')]
        links=[{'source_id':'parent','target_id':'child','type_code':'2'},
               {'source_id':'child','target_id':'parent','type_code':'1'}]
        summary,_,_,future=audit(x,links,as_of='2026-11-12')
        self.assertEqual((summary['future_active_activities'],summary['future_related_groups']), (2,1))
        self.assertEqual(summary['non_singleton_related_groups'],1)
        self.assertEqual(len(future),1)
        self.assertEqual(future[0]['has_verified_site'],0)
    def test_other_relations_do_not_group(self):
        ids,fam,used,other=groups_from_relations([case('A'),case('B')],
                            [{'source_id':'A','target_id':'B','type_code':'3'}])
        self.assertEqual(len(fam),2)
    def test_approximate_city_point_is_not_a_facility(self):
        loc={'coordinates':{'lat':-6.79,'lon':39.28},'location_class_code':'2',
             'exactness_code':'2','reach_code':'1','name':'Dar es Salaam'}
        result,acts,locs,_=audit([case('A',loc=loc),case('B',loc=loc)],[],as_of='2026-11-12')
        self.assertEqual(result['site_verified_count'],0)
        self.assertEqual(result['locations_total'],2)
        self.assertEqual(locs[0]['shared_by_activities_in_dataset'],2)
        self.assertEqual(acts[0]['geo_quality'],'settlement_or_region')
    def test_future_actual_and_overdue_are_flags_not_completion(self):
        s,activities,_,_=audit([case('A',planned='2025-01-01'),
                                case('B',planned='2030-01-01',actual='2030-01-01')],[],as_of='2026-11-12')
        self.assertEqual(s['future_actual_end_count'],1)
        self.assertEqual(s['active_after_planned_end_count'],1)
        self.assertEqual(s['future_active_activities'],1)
    def test_finance_is_counted_not_added(self):
        r=case('A');r['transactions']=[{'kind':'commitment','amount':'5','currency':'EUR'},
                                      {'kind':'disbursement','amount':'3','currency':'EUR'},
                                      {'kind':'interest_payment','amount':'2','currency':'EUR'}]
        s,acts,_,_=audit([r],[],as_of='2026-11-12')
        self.assertEqual(s['transactions_by_kind']['interest_payment'],1)
        self.assertEqual(acts[0]['financial_aggregation_allowed'],0)
        self.assertNotIn('total_finance', s)
    def test_no_false_geometry_on_missing_coordinates(self):
        loc={'coordinates':None, 'location_class_code':'3','reach_code':'1','exactness_code':'1'}
        s,acts,ls,_=audit([case('A',loc=loc)],[],as_of='2026-11-12')
        self.assertEqual(acts[0]['site_claims_unverified'],0)
        self.assertEqual(s['site_verified_count'],0)
    def test_nonempty_site_claim_still_unverified(self):
        loc={'coordinates':{'lat':1.0,'lon':2.0}, 'location_class_code':'3','reach_code':'1','exactness_code':'1'}
        s,acts,ls,_=audit([case('A',loc=loc)],[],as_of='2026-11-12')
        self.assertEqual(ls[0]['possible_site'],1)
        self.assertEqual(ls[0]['site_verified'],0)
        self.assertEqual(s['site_verified_count'],0)

if __name__=='__main__':unittest.main()
