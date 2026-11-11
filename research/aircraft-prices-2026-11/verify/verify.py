#!/usr/bin/env python3
"""Independent arithmetic checks; no import of analyze.py."""
from pathlib import Path
import yaml,json,math,statistics,hashlib
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
base=ROOT/'data/prices/_observations.yaml';sp=HERE.parent/'out/summary.json';ep=HERE.parent/'out/additional_observations.json'
accepted=yaml.safe_load(base.read_text())['observations'];s=json.loads(sp.read_text());extra=json.loads(ep.read_text())['observations']
scale={'m':1e6,'k':1e3,'unit':1,'':1}
def amt(r):return (r.get('value') if r.get('value') is not None else (r['value_low']+r['value_high'])/2)*scale[r.get('scale','')]
ix={(r['icao'],r['kind'],r['month'],r.get('age'),r['source']):amt(r) for r in accepted}
pairs={}
for (icao,kind,period,age,source),v in ix.items():
 if kind=='value' and (icao,'lease',period,age,source) in ix:
  pairs[(icao,age,period[:4])]=ix[(icao,'lease',period,age,source)]/v
members=set.intersection(*[{(icao,age) for icao,age,y in pairs if y==str(year)} for year in range(2016,2021)])
fixed=[{'year':year,'n':len(members),'median_fraction':statistics.median(pairs[(icao,age,str(year))] for icao,age in members)} for year in range(2016,2021)]
assert {(r['icao'],r['age']) for r in s['lease_value_fixed_cohort']['members']}==members
for a,b in zip(fixed,s['lease_value_fixed_cohort']['years']):
 assert a['year']==b['year'] and a['n']==b['n'] and math.isclose(a['median_fraction'],b['median_fraction'])
for r in extra:
 if r['source_id'].startswith('avac-'):
  key=(r['icao'],r['kind'],r['period'],r['age'],r['source'])
  assert key not in ix
  assert r['amount_low_usd']==r['amount_high_usd']
  ix[key]=r['amount_low_usd']
age=[]
for (icao,kind,period,old,source),v in ix.items():
 if old in (5,10,20) and (icao,kind,period,'new',source) in ix:
  new=ix[(icao,kind,period,'new',source)]
  age.append((icao,kind,period,old,source,new,v,v/new))
pub={(r['icao'],r['kind'],r['period'],r['age'],r['source']):r for r in s['expanded_age_comparisons']}
assert len(age)==len(pub)
for icao,kind,period,old,source,new,v,frac in age:
 r=pub[icao,kind,period,old,source]
 assert math.isclose(r['new_usd'],new) and math.isclose(r['aged_usd'],v) and math.isclose(r['fraction_of_new'],frac)
# Hand-entered numerical source cells personally checked in the IBA-authored original.
expected={('A320-200N','lease','new'):(395000,424000),('A321-200NX','lease','new'):(456000,488000),('A320-200','lease',12):(215000,240000),('737-800','lease',12):(218000,249000),('A320-200N','value','new'):(56300000,56300000),('737 MAX 8','value','new'):(56300000,56300000),('A321-200NX','value','new'):(65000000,65000000),('A321-200NY','value','new'):(72500000,72500000),('A320-200','value',12):(22000000,22000000),('737-800','value',12):(23000000,23000000),('A330-900','value','new'):(118500000,118500000),('787-9','value','new'):(160000000,160000000),('787-10','value','new'):(168000000,168000000),('A350-900','value','new'):(168000000,168000000),('A350-1000','value','new'):(181000000,181000000)}
recent=[]
for r in extra:
 if r['source_id']!='iba-iclg-2026':continue
 k=(r['variant'],r['kind'],r['age']);assert (r['amount_low_usd'],r['amount_high_usd'])==expected[k]
 assert r['period']=='2026-Q1';recent.append(r['id'])
assert len(recent)==15
for r in s['recent_lease_value_pairs']:
 v=expected[(r['variant'],'value',r['age'])][0];lo,hi=expected[(r['variant'],'lease',r['age'])]
 assert r['value_usd']==v
 assert math.isclose(r['monthly_fraction_low'],lo/v) and math.isclose(r['monthly_fraction_high'],hi/v) and math.isclose(r['monthly_fraction_midpoint'],(lo+hi)/2/v)
assert len(s['recent_lease_value_pairs'])==4
podcast_expected={'value':56000000,'lease':400000};podcast=[]
for r in extra:
 if r['source_id']=='iba-podcast-2026-05':
  assert r['icao']=='A20N' and r['age']=='new' and r['period']=='2026-05' and r['estimate_type']=='approximate_point'
  assert r['amount_low_usd']==r['amount_high_usd']==podcast_expected[r['kind']]
  podcast.append(r['id'])
assert len(podcast)==2
res={'as_of':'2026-11-11','status':'pass_with_scope_limits','method':'Independent joins and arithmetic from accepted YAML and independently checked source cells, without importing analyze.py. ICLG and podcast expected numeric values transcribed separately from primary publisher texts.','input_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [base,sp,ep]},'checks':{'fixed_cohort_members':len(members),'fixed_cohort_years':fixed,'expanded_age_comparisons':len(age),'expanded_age_types':len({r[0] for r in age}),'additional_avac_rows_do_not_duplicate_accepted_keys':True,'fresh_iclg_observations_checked':len(recent),'fresh_podcast_observations_checked':len(podcast),'recent_exact_variant_age_period_rent_value_pairs':4,'quarter_preserved':True,'a321_nx_and_ny_not_pooled':True,'max8_numeric_lease_interval_not_invented':True,'podcast_future_390k_not_treated_as_current':True},'source_refs':['turn84view1','turn85view0'],'limitations':['A fixed type/age panel reduces composition changes but does not measure net lessor profitability or guarantee constant technical specifications.','AVAC age ratios compare cross-sectional appraisal categories; not observed physical depreciation trajectories.','The 2026 rent/value ranges are descriptive gross monthly fractions, not financing yields. Midpoints are scenario choices, not sample averages.','HLMV valuation condition is not aircraft age.','Appraiser and publication methods differ; no CPI conversion is used in these nominal joins.','Podcast numerical evidence is a publisher-supplied transcript, not an independent audio transcription.']}
(HERE/'summary.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n');print(json.dumps(res['checks'],ensure_ascii=False))
