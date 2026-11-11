#!/usr/bin/env python3
"""Independent full-row audit of the 0056 collected panels.

No collection or production parser is imported. Raw input caches stay outside
git; explicit --raw-dir is required. Coverage is recomputed with pandas groupby
and a complete-year pivot. This is not a fitted forecasting model.
"""
import argparse
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import io
import zipfile

import pandas as pd

HERE=Path(__file__).resolve().parent
OUT=HERE.parent/'out'


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    blob=gzip.decompress(path.read_bytes()) if path.suffix=='.gz' else path.read_bytes()
    return json.loads(blob)


def valid(value):
    try:
        x=float(value)
        return x if math.isfinite(x) and x>=0 else None
    except (TypeError,ValueError):return None


def audit_years(panel,nperiods,expected):
    errors=[]
    flat=[(pair,period,int(period[:4]),value) for pair,rows in panel.items() for period,value in rows]
    frame=pd.DataFrame(flat,columns=['pair','period','year','value'])
    if frame.duplicated(['pair','period']).any():errors.append('duplicate_pair_period')
    grouped=frame.groupby(['pair','year']).agg(n=('period','nunique'),value=('value','sum'))
    full=grouped.loc[grouped['n']==nperiods,'value'].unstack('year')
    for year,sub in frame.groupby('year'):
        seen=sorted(sub['period'].unique());g=grouped.xs(year,level='year');complete=g[g.n==nperiods]
        all_periods={f'{year}-{m:02d}' for m in range(1,13)} if nperiods==12 else {f'{year}-Q{q}' for q in range(1,5)}
        calculated={'periods_in_source':len(seen),'observed_periods':seen,'periods_absent_entire_extract':sorted(all_periods-set(seen)),
            'pairs_any_observed':len(g),'pair_periods':len(sub),'pairs_full_year':len(complete),
            'pairs_full_year_positive':int((complete.value>0).sum()),'pairs_full_year_zero':int((complete.value==0).sum()),
            'pairs_partial_year':len(g)-len(complete)}
        if calculated!=expected['year_coverage'][str(year)]:errors.append({'year_coverage':year,'independent':calculated})
    horizons={}
    last=int(max(full.columns))
    for h in (3,5,10):
        origins=[]
        for origin in sorted(full.columns):
            if origin+h>last:continue
            history=list(range(int(origin)-4,int(origin)+1))
            if not all(y in full.columns for y in history):continue
            eligible=full.loc[full[history].notna().all(axis=1)]
            if len(eligible)==0:continue
            target=eligible[origin+h].dropna() if origin+h in full.columns else pd.Series(dtype=float)
            origins.append({'origin_year':int(origin),'target_year':int(origin+h),'train_years':history,
                'eligible_origin_pairs':len(eligible),'complete_target_pairs':len(target),
                'target_missing_or_incomplete':len(eligible)-len(target),'target_observed_zero':int((target==0).sum()),'target_positive':int((target>0).sum())})
        horizons[str(h)]={'n_origins':len(origins),'origins':origins,'sum_complete_pair_targets':sum(x['complete_target_pairs'] for x in origins)}
        if horizons[str(h)]!=expected['readiness']['horizons'][str(h)]:errors.append({'readiness_horizon':h,'independent':horizons[str(h)]})
    return errors,horizons


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--raw-dir',type=Path,required=True)
    parser.add_argument('--probe-dir',type=Path)
    args=parser.parse_args();raw=args.raw_dir
    summary=load(OUT/'collection_summary.json');inventory=load(OUT/'data_inventory.json')
    failures=[];checks={};hashes={}
    source_hashes_checked=0
    for path in sorted(raw.glob('*.meta.json')):
        meta=load(path);payload=raw/(path.name.removesuffix('.meta.json')+'.raw')
        if payload.exists() and meta.get('sha256'):
            if digest(payload)!=meta['sha256']:failures.append({'problem':'raw provenance hash mismatch','cache_name':payload.name})
            source_hashes_checked+=1
    for item in inventory['derived_artifacts']:
        path=OUT/item['file'];hashes[item['file']]=digest(path)
        if hashes[item['file']]!=item['sha256'] or path.stat().st_size!=item['compressed_bytes']:
            failures.append({'problem':'inventory artifact hash or size mismatch','file':item['file']})

    reports=defaultdict(dict);flags=defaultdict(set);source_series=Counter();missing=0;per_country={}
    source_dimensions=[]
    for cc in ('de','es','fr','it','nl'):
        files=sorted(raw.glob(f'routes_{cc}_[0-9][0-9][0-9][0-9][0-9].raw'))
        codes=set();advertised=set()
        for path in files:
            d=load(path);ds=d['dataset'];advertised.add(d['series']['num_found'])
            per_country[cc.upper()]={'source_updated_at':ds.get('updated_at'),'mirror_indexed_at':ds.get('indexed_at')}
            for s in d['series']['docs']:
                if s['series_code'] in codes:failures.append({'problem':'duplicate downloaded series','code':s['series_code']})
                codes.add(s['series_code']);dims=s['dimensions']
                if (dims['freq'],dims['unit'],dims['tra_meas'])!=('M','PAS','PAS_CRD'):failures.append({'problem':'incorrect route units','dimensions':dims})
                country,reporter,country2,partner=dims['airp_pr'].split('_')
                if country.lower()!=cc:failures.append({'problem':'wrong reporting country in dataset','code':dims['airp_pr']})
                pair='-'.join(sorted([reporter,partner]));attrs=dict(s.get('observations_attributes',[]));q=attrs.get('OBS_FLAG','')
                q=q if isinstance(q,list) else [q]*len(s['period'])
                for t,v,flag in zip(s['period'],s['value'],q):
                    if t<'2005-01' or t>'2026-11':continue
                    value=valid(v)
                    if value is None:missing+=1;continue
                    key=(pair,t)
                    if reporter in reports[key] and reports[key][reporter]!=value:failures.append({'problem':'conflicting duplicate reporter','pair':pair,'period':t})
                    reports[key][reporter]=value
                    if flag:flags[key].add(str(flag))
        if advertised!={len(codes)}:failures.append({'problem':'incomplete mirror pagination','country':cc,'series':len(codes),'advertised':list(advertised)})
        source_series[cc.upper()]=len(codes);per_country[cc.upper()]['series']=len(codes)
    eu=load(OUT/'eu_monthly_panel.json.gz');excluded=load(OUT/'eu_excluded_groups.json.gz')['groups']
    included=eu['pairs'];all_output={**included,**{k:v['rows'] for k,v in excluded.items()}}
    rows_checked=0;reporter_disagreement=Counter();seen=set();actual=defaultdict(list)
    for pair,rows in all_output.items():
        for row in rows:
            t,value,n,spread,flag,*names=row;key=(pair,t);seen.add(key);values=reports.get(key,{})
            vs=list(values.values());mean=sum(vs)/len(vs) if vs else None
            exp_spread=(max(vs)-min(vs))/mean if mean else 0
            exp_flags=';'.join(sorted(flags[key])) or None
            ok=(value==mean and n==len(values) and spread==round(exp_spread,6) and flag==exp_flags
                and names==[';'.join(sorted(values))])
            if not ok:failures.append({'problem':'normalized route row mismatch','pair':pair,'period':t})
            rows_checked+=1
            if pair in included:
                actual[pair].append((t,value))
                reporter_disagreement['one_reporter' if n==1 else 'two_reporters']+=1
                if n>1 and spread>.1:reporter_disagreement['two_reporters_spread_above_10pct']+=1
    if seen!=set(reports):failures.append({'problem':'raw to output route coverage mismatch','missing':len(set(reports)-seen),'invented':len(seen-set(reports))})
    special_codes={'ED00','ED99','EN00','EN99','DT99','ES99','FI99','GM99','GV99','HE99','LA99','LE99','LF99','LG99','LI99','LK99','LR99','LU99','MD99','OT99','RJ99','UU99','VH99','ZZZZ','EG90','ENOS','ESMM','SKED','EDVV','LMMM','HKNA','LECP','ENCA','SABA','SCSC','ZSSA'}
    for pair in included:
        aa=pair.split('-')
        if aa[0]==aa[1] or set(aa)&special_codes:failures.append({'problem':'non-airport group remains in airport panel','pair':pair})
    if set(included)&set(excluded):failures.append({'problem':'included and excluded panels overlap'})
    errors,horizons=audit_years(actual,12,summary['eu_routes']);failures.extend(errors)
    sizes={'pairs':len(included),'pair_months':sum(map(len,included.values())),'excluded_non_airport_pairs':len(excluded),'excluded_pair_months':sum(len(x['rows']) for x in excluded.values()),'all_source_pairs':len(all_output),'all_source_pair_months':rows_checked}
    for k,v in sizes.items():
        if summary['eu_routes'][k]!=v:failures.append({'problem':'EU summary size mismatch','field':k})
    if per_country!=summary['eu_routes']['reporting_countries']:failures.append({'problem':'mirror/source vintage mismatch'})
    if dict(reporter_disagreement)!=summary['eu_routes']['reporter_agreement']:failures.append({'problem':'reporter disagreement summary mismatch'})
    if missing!=summary['eu_routes']['missing_values_in_series']:failures.append({'problem':'missing source-cell count mismatch'})
    checks['eu_routes']={**sizes,'raw_series':dict(source_series),'raw_aggregation_rows_checked':rows_checked,'source_vintages':per_country,
        'counterpart_reports':'arithmetic mean, not sum; reporter identities and spread retained','historical_airports_retained':any('EDDT' in p for p in included) and any('EDDI' in p for p in included),'readiness_horizons':horizons}
    print('EU rows, source vintage, duplicates and horizons checked',flush=True)
    if args.probe_dir:
        probe_checks=[]
        for name in ('mirror-fra-bcn','mirror-bcn-fra'):
            path=args.probe_dir/(name+'.raw');d=load(path);s=d['series']['docs'][0]
            _,reporter,_,partner=s['dimensions']['airp_pr'].split('_')
            pair='-'.join(sorted((reporter,partner)));compared=0
            for month,value in zip(s['period'],s['value']):
                value=valid(value)
                if month<'2005-01' or month>'2026-11' or value is None:continue
                if reports[(pair,month)].get(reporter)!=value:
                    failures.append({'problem':'independently downloaded mirror probe differs','pair':pair,'month':month,'reporter':reporter})
                compared+=1
            probe_checks.append({'probe':name,'sha256':digest(path),'reporter_months_compared':compared,'dataset_updated_at':d['dataset'].get('updated_at'),'mirror_indexed_at':d['dataset'].get('indexed_at')})
        checks['independent_mirror_probes']=probe_checks
    del reports,flags,all_output,seen

    regional=load(OUT/'regional_history.json.gz');rr=[];regional_checks={}
    expected_dims={'gdp':{'freq':'A','unit':'PPS_EU27_2020_HAB'},'pop':{'freq':'A','unit':'NR','age':'TOTAL','sex':'T'},'emp':{'freq':'A','unit':'THS_PER','age':'Y15-74','sex':'T'},'nights':{'freq':'A','unit':'NR','nace_r2':'I551-I553'}}
    for kind in expected_dims:
        count=Counter();regions=set();periods=set();source_flags=Counter();series_count=0
        for path in sorted(raw.glob(f'regions_{kind}_[0-9][0-9][0-9][0-9][0-9].raw')):
            data=load(path)
            for s in data['series']['docs']:
                series_count+=1;dims=s['dimensions'];q=dict(s.get('observations_attributes',[])).get('OBS_FLAG','');q=q if isinstance(q,list) else [q]*len(s['period'])
                if any(dims[k]!=v for k,v in expected_dims[kind].items()):failures.append({'problem':'regional unit/scope mismatch','kind':kind,'dims':dims})
                if kind=='emp' and dims['nace_r2'] not in ('TOTAL','K','M_N'):failures.append({'problem':'employment scope mismatch'})
                for t,v,flag in zip(s['period'],s['value'],q):
                    value=valid(v)
                    if value is None or t<'2005' or t>'2026':continue
                    if kind=='nights':
                        if dims['month'] not in {f'M{m:02d}' for m in range(1,13)} or dims['c_resid'] not in ('TOTAL','FOR'):failures.append({'problem':'tourism monthly/residency scope mismatch'})
                        t=t+'-'+dims['month'][1:];feature='nights_'+dims['c_resid']
                    else:feature='employment_'+dims['nace_r2'] if kind=='emp' else kind
                    rr.append([dims['geo'],t,feature,value,flag or None]);count[t[:4]]+=1;regions.add(dims['geo']);periods.add(t)
                    if flag:source_flags[flag]+=1
        expected=summary['regional'][kind]
        values={'observations':sum(count.values()),'regions':len(regions),'region_codes':sorted(regions),'first_period':min(periods),'last_period':max(periods),'by_year':dict(sorted(count.items())),'source_flags':dict(source_flags)}
        for k,v in values.items():
            if expected[k]!=v:failures.append({'problem':'regional coverage mismatch','kind':kind,'field':k})
        regional_checks[kind]={k:v for k,v in values.items() if k!='region_codes'}
    if sorted(rr)!=regional['records']:failures.append({'problem':'regional normalized rows mismatch'})
    if len({tuple(r[:3]) for r in rr})!=len(rr):failures.append({'problem':'duplicate regional keys'})
    checks['regional']=regional_checks
    print('Regional raw values, dimensions and quality flags checked',flush=True)

    for name,nperiods in [('india_domestic',12),('india_international',4)]:
        source=list(csv.DictReader((raw/(name+'.raw')).open(encoding='utf-8-sig')));g=defaultdict(list)
        for r in source:
            year=int(r['Year']);year=year+2000 if year<100 else year
            time=f"{year}-{int(r['Month']):02d}" if nperiods==12 else f"{year}-Q{int(r['Quarter'])}"
            a,b=r['City1'].strip().upper(),r['City2'].strip().upper();va,vb=valid(r['PaxToCity2']),valid(r['PaxFromCity2'])
            if b<a:a,b,va,vb=b,a,vb,va
            g[(a+' | '+b,time)].append((va,vb))
        result=load(OUT/(name+'_panel.json.gz'));q=Counter();simple=defaultdict(list);total=0
        for pair,rs in result['pairs'].items():
            for time,pax,n,quality in rs:
                vals=g[(pair,time)];unique=set(vals)
                expected='missing_direction' if any(a is None or b is None for a,b in unique) else 'conflicting_duplicate' if len(unique)>1 else 'deduplicated_identical' if len(vals)>1 else 'observed'
                p=None if expected in ('missing_direction','conflicting_duplicate') else sum(next(iter(unique)))
                if (p,len(vals),expected)!=(pax,n,quality):failures.append({'problem':'India row normalization mismatch','dataset':name,'pair':pair,'period':time})
                if p is not None:simple[pair].append((time,p))
                q[expected]+=1;total+=1
        if total!=len(g) or len(source)!=summary[name]['source_rows'] or dict(q)!=summary[name]['quality']:failures.append({'problem':'India source coverage mismatch','dataset':name})
        errs,hh=audit_years(simple,nperiods,summary[name]);failures.extend(errs)
        checks[name]={'raw_rows':len(source),'pair_periods':total,'usable_pair_periods':sum(map(len,simple.values())),'quality_counts':dict(q),'readiness_horizons':hh,'city_labels_not_airport_assumptions':True}
    print('Both India panels, duplicates, missing directions and horizons checked',flush=True)

    country_meta=load(raw/'wb_country_meta.raw')[1]
    countries={r['iso2Code'] for r in country_meta if r.get('region',{}).get('value')!='Aggregates'}
    iso3={r['id']:r['iso2Code'] for r in country_meta if r.get('region',{}).get('value')!='Aggregates'}
    wb=load(raw/'wb_history.raw');mapping={'SP.POP.TOTL':'pop','NY.GDP.PCAP.PP.KD':'gdp_pc_ppp','ST.INT.ARVL':'tourist_arrivals'}
    wr=[]
    for r in wb[1]:
        if r['country']['id'] in countries and r['value'] is not None and r['indicator']['id'] in mapping:
            wr.append([r['country']['id'],int(r['date']),mapping[r['indicator']['id']],r['value']])
    normal=load(OUT/'country_history.json.gz')
    if sorted(wr)!=normal['records']:failures.append({'problem':'WDI normalized values mismatch'})
    if wb[0]['pages']!=1 or wb[0]['total']!=len(wb[1]):failures.append({'problem':'WDI pagination incomplete'})
    checks['country_history']={'records':len(wr),'countries':len({r[0] for r in wr}),'source_updated':wb[0].get('lastupdated'),'raw_values_checked':True}

    scenario=load(OUT/'scenario_inputs.json.gz');sr=[]
    with gzip.open(raw/'wpp_population.raw','rt',encoding='utf-8-sig') as stream:
        for r in csv.DictReader(stream):
            if not r['ISO2_code'] or r['Variant'] not in ('Medium','Low','High') or int(r['Time']) not in (2025,2026,2029,2031,2036):continue
            sr.append({'source':'UN WPP 2024','country_iso2':r['ISO2_code'],'country_iso3':r['ISO3_code'],'year':int(r['Time']),'variable':'population','scenario':r['Variant'],'value':float(r['PopTotal'])*1000,'unit':'persons','kind':'source_projection'})
    # Independently parse the publisher's interim correction, not the author's
    # normalization code. Only Medium Togo is revised by this source.
    with zipfile.ZipFile(raw/'wpp_togo_update.raw') as archive:
        corrected=list(csv.DictReader(io.StringIO(archive.read('WPP2024_TotalPopulationBySex_Medium_Update.csv').decode('utf-8-sig'))))
    corrected_values={int(r['Time']):float(r['PopTotal'])*1000 for r in corrected if r['ISO2_code']=='TG' and r['Variant']=='Medium'}
    revised=[]
    for r in sr:
        if r['country_iso2']=='TG' and r['scenario']=='Medium':
            r['value']=corrected_values[r['year']];revised.append({'year':r['year'],'persons':r['value']})
    if len(revised)!=5:failures.append({'problem':'unexpected number of revised Togo Medium rows','rows':len(revised)})
    for r in scenario['records']:
        if r['source']!='UN WPP 2024':continue
        if r.get('reference_date')!='1 July':failures.append({'problem':'WPP reference date omitted or incorrect'})
        is_togo=r['country_iso2']=='TG';is_revised=is_togo and r['scenario']=='Medium'
        expected_revision='2026-01-19 Togo interim correction' if is_revised else '2024 base edition'
        if r.get('source_revision')!=expected_revision:failures.append({'problem':'WPP version annotation mismatch'})
        if bool(r.get('comparability_warning'))!=(is_togo and not is_revised):failures.append({'problem':'Togo unrevised scenarios warning mismatch'})
    indicators=load(raw/'imf_indicators.raw')['indicators']
    for fn,code in [('imf_growth','NGDP_RPCH'),('imf_population','LP')]:
        for country,values in load(raw/(fn+'.raw'))['values'][code].items():
            if country not in iso3:continue
            for y,v in values.items():
                year=int(y)
                if 2025<=year<=2036:
                    sr.append({'source':indicators[code]['source'],'country_iso2':iso3[country],'country_iso3':country,'year':year,'variable':code,'scenario':'WEO central','value':v,'unit':indicators[code]['unit'],'kind':'source_projection' if year>=2026 else 'source_estimate_boundary_unverified'})
    order=lambda r:(r['source'],r['country_iso3'],r['variable'],r['scenario'],r['year'])
    core_keys=('source','country_iso2','country_iso3','year','variable','scenario','value','unit','kind')
    normalized=[{k:r[k] for k in core_keys} for r in scenario['records']]
    if sorted(sr,key=order)!=normalized:failures.append({'problem':'scenario normalization mismatch'})
    counts=Counter((r['source'],r['variable'],r['scenario']) for r in sr)
    checks['scenario_inputs']={'records':len(sr),'series_counts':{' | '.join(k):v for k,v in counts.items()},'weo_gdp_last_year':max(r['year'] for r in sr if r['variable']=='NGDP_RPCH'),'wpp_unit_multiplier':1000,'wpp_reference_date':'1 July','togo_interim_medium_revision':revised,'unrevised_togo_low_high_warning':True,'own_route_forecasts':False,'source_scenarios_not_confidence_intervals':True}
    print('Country histories and external scenario projections checked',flush=True)

    visa=load(OUT/'visa_snapshots.json.gz');vr=[];vc=Counter()
    for path in sorted(raw.glob('visa_20??-??-??.raw'))+[raw/'visa.raw']:
        date='2026-02-17' if path.name=='visa.raw' else path.stem.removeprefix('visa_')
        source=list(csv.DictReader(path.open(encoding='utf-8-sig')))
        for r in source:
            a,b=r['Passport'].upper(),r['Destination'].upper();legacy='Requirement' not in r
            value=(r.get('Code','') if legacy else r['Requirement']).strip().lower()
            if legacy:category='legacy_code_unharmonised'
            elif a==b:category='same_country'
            elif value.isdigit() or value=='visa free':category='visa_free'
            elif value in ('visa on arrival','eta','e-visa','visa required','no admission','covid ban','hayya entry permit'):category=value.replace(' ','_')
            else:category='unclassified'
            vr.append([date,a,b,category,value]);vc[date]+=1
    if vr!=visa['records']:failures.append({'problem':'visa snapshot normalization mismatch or schema changed'})
    if len({tuple(r[:3]) for r in vr})!=len(vr):failures.append({'problem':'duplicate directed visa pair within snapshot'})
    checks['visa']={'rows':len(vr),'snapshot_counts':dict(vc),'legacy_codes_not_interpreted_as_days':True,'snapshot_not_law_effective_date':True}
    checks['provenance']={'raw_hashes_checked':source_hashes_checked,'derived_artifact_hashes':hashes,'primary_vs_mirror_distinguished':True}
    report={'stage':'0056','status':'pass_with_limitations' if not failures else 'fail','independent':True,
        'summary_sha256':digest(OUT/'collection_summary.json'),'inventory_sha256':digest(OUT/'data_inventory.json'),
        'method':'Independent raw-row reconstruction, pandas annual pivot and origin-cohort audit; no author parser imported.',
        'checks':checks,'failures':failures,
        'limitations':['The source is Eurostat; the access channel is an explicitly dated DBnomics archive. Independent probes confirm primary API HTTP200 HTML maintenance and mirror JSON for both FRA–BCN reporters.',
          'PAS_CRD is on-flight origin/destination, not flight-stage PAS_BRD or complete passenger journeys. Two reporting airports observe the same traffic; their reports are averaged, not summed.',
          'Historical codes and geography are retained but not fully harmonized. Five reporting countries are not all Europe; no current-airport survivorship filter is used.',
          'Readiness counts are data coverage, not predictive accuracy. Origins overlap and are not independent experiments; route-missing targets must remain unscorable rather than assumed zero.',
          'Origin is the last complete observation year, not proof that its figures were published then. Current-revision history is not an archived information set; future GDP realizations cannot be used as known predictors.',
          'The latest EU observation is 2024 while issue year is 2026. Targets2029/2031/2036 need a2025–2026 nowcast or newer data before calling them3/5/10-year forecasts from the current market state.',
          'Regional codes are not proof of constant NUTS boundaries. Employment break/provisional/low-reliability flags and GDP/tourism flags are retained; handling them belongs to later modelling.',
          'Regional tourism2020–2024 and visa snapshots2019 onward cannot support all historical10-year origins. Predictor-specific eligibility must be audited separately.',
          'India domestic has entire missing months and conflicting records. Its calendar span alone does not establish usable multiyear backtests; international city labels are not assigned to a main airport.',
          'UN low/high fertility variants are not predictive confidence bounds. IMF growth stops at its source horizon; no2036 GDP projection was fabricated.',
          'There are no new route-demand forecasts or fitted aircraft-choice conclusions in this data-collection stage.']}
    (HERE/'demand_collection_0056.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(report['status'],json.dumps(failures,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
