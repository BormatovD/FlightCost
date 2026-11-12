"""0066: generic mass billing. Synthetic fees, not LAWA/DEN source data."""
import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from flightcostapp import charges, drafts
from flightcostapp.parsers import airport_charges


class MassChargeTests(unittest.TestCase):
    def context(self, mlw=68.5, mtow=78.0):
        return {**{k: None for k in charges.CONDITION_KEYS},
                **charges.EVENT_COUNTS, "mtow_t": mtow, "mlw_t": mlw,
                "pax": 148, "cargo_kg": 0}

    def rule(self, **changes):
        args = dict(code="landing", base="per_mass", rate=8.65, currency="USD",
                    events="landing", mass_basis="mlw", rate_unit="1000lb")
        args.update(changes)
        return charges.Rule(**args)

    def test_mlw_1000lb_fractional(self):
        report = {}
        out = charges.evaluate([self.rule()], self.context(),
                               fx=lambda _: 1.0, report=report)
        self.assertAlmostEqual(out['landing'], 68.5 / .45359237 * 8.65)
        self.assertFalse(report['lost_codes'])

    def test_ceil_mass_units_not_result_and_movement_twice(self):
        out = charges.evaluate([self.rule(round_mass='ceil_unit')], self.context(),
                               fx=lambda _: 1.)
        self.assertAlmostEqual(out['landing'], 152 * 8.65)
        another = self.rule(rate=10, events='movement', round_mass='ceil_unit')
        c = self.context(mlw=.45359237 * 1.5)
        self.assertEqual(charges.evaluate([another], c, fx=lambda _: 1)['landing'], 40)
        nearest = self.rule(rate=10, round_mass='nearest_unit')
        self.assertEqual(charges.evaluate([nearest], c, fx=lambda _: 1)['landing'], 20)

    def test_universal_types_and_units(self):
        for unit, units in (('tonne', 78), ('100kg', 780),
                            ('1000lb', 78 / .45359237)):
            with self.subTest(unit=unit):
                r = self.rule(mass_basis='mtow', rate_unit=unit)
                result = charges.evaluate([r], self.context(mlw=None),
                                          fx=lambda _: 1)['landing']
                self.assertAlmostEqual(result, units * 8.65)

    def test_mlw_missing_not_zero_or_mtow(self):
        report = {}
        result = charges.evaluate([self.rule()], self.context(mlw=None),
                                  fx=lambda _: 1, report=report)
        self.assertNotIn('landing', result)
        self.assertEqual(report['lost_codes'], ['landing'])
        self.assertEqual(report['missing_data'], ['mlw_t'])
        self.assertTrue(any('mlw_t' in k for k in result if k.startswith('_')))
        legacy = charges.Rule(code='landing', base='per_tonne_mtow', rate=8.65,
                              events='landing', currency='USD')
        self.assertAlmostEqual(charges.evaluate([legacy], self.context(mlw=None),
                                                fx=lambda _: 1)['landing'], 78 * 8.65)

    def test_mixed_rule_partial_loss(self):
        report = {}
        legacy = charges.Rule(code='landing', base='per_tonne_mtow', rate=2.,
                              events='landing')
        out = charges.evaluate([self.rule(), legacy], self.context(mlw=None),
                               fx=lambda _: 1, report=report)
        self.assertEqual(out['landing'], 156)
        self.assertEqual(report['partial_codes'], ['landing'])
        self.assertEqual(report['missing_data'], ['mlw_t'])

    def test_invalid_parameters_cannot_silently_pass(self):
        for kw in ({'mass_basis': None}, {'mass_basis': 'actual_landing'},
                   {'rate_unit': None}, {'rate_unit': 'pounds'},
                   {'round_mass': 'ceil_1000lb'}, {'round_mtow': 'ceil_tonne'},
                   {'pct_of': 'landing'}):
            with self.subTest(kw=kw):
                self.assertTrue(charges.self_check([self.rule(**kw)]))
        old = charges.Rule(code='landing', base='per_tonne_mtow', rate=1,
                           mass_basis='mtow')
        self.assertTrue(charges.self_check([old]))

    def test_legacy_keys_and_value_text_stable(self):
        r = charges.Rule(code='landing', base='per_tonne_mtow', rate=6.)
        original = {'base':r.base, 'events':r.events, 'when':r.when,
                    'currency':r.currency, 'threshold':r.threshold,
                    'exponent':r.exponent, 'pct_of':r.pct_of,
                    'round_mtow':r.round_mtow, 'variant':''}
        h = hashlib.sha256(json.dumps(original, sort_keys=True,
                                      ensure_ascii=False).encode()).hexdigest()[:8]
        self.assertEqual(airport_charges._rule_key('KLAX',r), f'KLAX/landing/{h}')
        self.assertTrue({'mass_basis','rate_unit','round_mass'}.isdisjoint(
                        json.loads(r.to_json())))
        new = self.rule()
        self.assertEqual(json.loads(new.to_json())['mass_basis'], 'mlw')
        self.assertNotEqual(airport_charges._rule_key('KLAX',r),
                            airport_charges._rule_key('KLAX',new))

    def test_parser_round_trip(self):
        doc = {'icao':'KLAX', 'valid_from':'2026-07-01',
               'source':'synthetic', 'source_url':'https://example.com/tariff.pdf',
               'map_node':'src_airport_tariff', 'rules':[
                   {'code':'landing', 'base':'per_mass','rate':8.65,'currency':'USD',
                    'events':'landing', 'mass_basis':'mlw','rate_unit':'1000lb',
                    'round_mass':'ceil_unit'}]}
        rows = airport_charges.parse(json.dumps(doc).encode(),
                                     {'source_id':'airport_charges_tier1',
                                      'node':'src_airport_tariff'})
        self.assertEqual(len(rows), 1)
        r = charges.Rule(**{**json.loads(rows[0].value_text),'rate':rows[0].value})
        self.assertEqual((r.base,r.mass_basis,r.rate_unit,r.round_mass),
                         ('per_mass','mlw','1000lb','ceil_unit'))

    def test_empty_and_meta_only_draft_rejected(self):
        data = json.dumps({'icao':'KLAX','rules':[]}).encode()
        with patch('flightcostapp.parsers.airport_charges.parse', return_value=[]):
            result = drafts.check(data, object())
        self.assertEqual(result['verdict'], 'reject')
        self.assertEqual(result['priced_rules'], 0)
        meta = SimpleNamespace(domain='airport_charge',key='KLAX/_cat/ac_class',
                               value_text='{"named":{}}')
        with patch('flightcostapp.parsers.airport_charges.parse', return_value=[meta]):
            self.assertEqual(drafts.check(data, object())['verdict'],'reject')

    def test_parser_rejects_empty_official_document(self):
        doc = {'icao':'KLAX', 'valid_from':'2026-07-01', 'rules':[],
               'source':'synthetic', 'source_url':'https://example.com/tariff.pdf',
               'map_node':'src_airport_tariff'}
        with self.assertRaisesRegex(ValueError, 'правил 0'):
            airport_charges.parse(json.dumps(doc).encode(),
                                  {'source_id':'airport_charges_tier1','node':'src_airport_tariff'})

    def test_parser_rejects_missing_source_url(self):
        with self.assertRaisesRegex(ValueError, 'source_url'):
            airport_charges.parse(json.dumps({'icao':'KDEN','rules':[]}).encode(),
                                  {'source_id':'airport_charges_tier1','node':'src_airport_tariff'})


if __name__ == '__main__': unittest.main()
