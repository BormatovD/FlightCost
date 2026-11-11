#!/usr/bin/env python3
"""Independent reconstruction; does not import benchmark.py or its functions."""
from pathlib import Path
from collections import Counter, defaultdict
import hashlib, json, math, statistics
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
FILES = {
    'pairs': ROOT/'research/routes-2026-11/out/pairs_eu.json',
    'airports': ROOT/'research/routes-2026-11/out/airports.json',
    'income': HERE.parent/'out/income_covariates.json',
    'summary': HERE.parent/'out/summary.json',
    'predictions': HERE.parent/'out/predictions.jsonl',
    'benchmark_code': HERE.parent/'benchmark.py',
    'tourism': HERE.parent/'out/tourism_covariates.json',
}
raw = json.loads(FILES['pairs'].read_text())
aps = json.loads(FILES['airports'].read_text())
inc = json.loads(FILES['income'].read_text())['values']
tourism = json.loads(FILES['tourism'].read_text())['values']
summary = json.loads(FILES['summary'].read_text())
published = [json.loads(s) for s in FILES['predictions'].read_text().splitlines() if s]
published = [r for r in published if r['experiment'] in ('forecast','heldout','income_forecast','income_heldout','tourism_forecast','tourism_heldout')]
independent_smearing = {}
idx = {a:i for i,a in enumerate(sorted(aps))}
airport_codes = sorted(aps)
rows = {}
excluded = {}
for year in [2023,2024]:
    res=[]; skipped=Counter()
    for pair, hist in sorted(raw['pairs'].items()):
        p=(hist.get(str(year)) or {}).get('pax')
        if not isinstance(p,(float,int)) or p<=0:
            skipped['no_positive_annual_observation']+=1;continue
        a,b=pair.split('-')
        if a not in aps or b not in aps:
            skipped['missing_coordinates']+=1;continue
        la,lo,lb,ob = [math.radians(float(q)) for q in [aps[a][0],aps[a][1],aps[b][0],aps[b][1]]]
        z=math.sin((la-lb)/2)**2+math.cos(la)*math.cos(lb)*math.sin((lo-ob)/2)**2
        km=2*6371.0088*math.atan2(math.sqrt(z),math.sqrt(max(0,1-z)))
        if km<100:
            skipped['distance_under_100_km']+=1;continue
        fold=int(hashlib.sha256(('flightcost-demand-pairs-v1/'+pair).encode()).hexdigest()[:16],16)%5
        res.append(dict(pair=pair,a=idx[a],b=idx[b],ca=aps[a][2],cb=aps[b][2],p=float(p),km=km,fold=fold))
    rows[year]=res;excluded[year]=dict(skipped)

def masses(train):
    ends=[r[k] for r in train for k in ['a','b']]
    w=[r['p'] for r in train for _ in range(2)]
    return np.bincount(ends,weights=w,minlength=len(aps))

def design(items,m,own,income,covariate_scope='country'):
    xs=[];keep=[]
    for r,s in zip(items,own):
        ma,mb=m[r['a']]-s,m[r['b']]-s
        if ma<=0 or mb<=0:continue
        d=math.log(r['km']/1000)
        x=[1.0,math.log(ma*mb),d,d*d,float(r['ca']==r['cb'])]
        if income is not None:
            ca,cb=(r['ca'],r['cb']) if covariate_scope=='country' else (airport_codes[r['a']],airport_codes[r['b']])
            va,vb=income.get(ca),income.get(cb)
            if va is None or vb is None or va<=0 or vb<=0:continue
            x.append(math.log(va*vb))
        keep.append(r);xs.append(x)
    return keep,np.asarray(xs,dtype=float)

def fit_and_score(train,test,m,own_test,inc_train,inc_test,experiment,prior=None,covariate_scope='country'):
    tr,x=design(train,m,[r['p'] for r in train],inc_train,covariate_scope)
    te,t=design(test,m,own_test,inc_test,covariate_scope)
    y=np.log([r['p'] for r in tr]); preds={}
    models={'distance':[0,2,3,4],'gravity':[0,1,2,3,4]}
    if inc_train is not None:models['gravity_tourism' if experiment.startswith('tourism_') else 'gravity_income']=[0,1,2,3,4,5]
    for model,cols in models.items():
        coef=np.linalg.lstsq(x[:,cols],y,rcond=None)[0]
        preds[model]=np.exp(t[:,cols]@coef)
    if experiment in ('forecast','heldout'):
        cols=models['gravity']
        coef=np.linalg.lstsq(x[:,cols],y,rcond=None)[0]
        smear=float(np.mean(np.exp(y-x[:,cols]@coef)))
        label=experiment if experiment=='forecast' else f'heldout_fold_{test[0]["fold"]}'
        independent_smearing[label]=smear
        preds['gravity_smearing']=preds['gravity']*smear
    out=[]
    for i,r in enumerate(te):
        p={m:float(v[i]) for m,v in preds.items()}
        if prior is not None:p['last_year']=prior[r['pair']]['p']
        out.append(dict(experiment=experiment,pair=r['pair'],actual=r['p'],year=2024,predictions=p))
    return out,len(tr)

rebuilt=[];train_sizes={}
for with_inc in [False,True]:
    train=rows[2023];hist={r['pair']:r for r in train}
    test=[r for r in rows[2024] if r['pair'] in hist]
    ex='income_forecast' if with_inc else 'forecast'
    scored,n=fit_and_score(train,test,masses(train),[hist[r['pair']]['p'] for r in test],inc['2022'] if with_inc else None,inc['2023'] if with_inc else None,ex,hist)
    rebuilt+=scored;train_sizes[ex]=n
    ex='income_heldout' if with_inc else 'heldout';train_sizes[ex]=[]
    for f in range(5):
        train=[r for r in rows[2024] if r['fold']!=f]
        test=[r for r in rows[2024] if r['fold']==f]
        scored,n=fit_and_score(train,test,masses(train),[0]*len(test),inc['2023'] if with_inc else None,inc['2023'] if with_inc else None,ex)
        for r in scored:r['fold']=f
        rebuilt+=scored;train_sizes[ex].append(n)

train=rows[2023];hist={r['pair']:r for r in train}
test=[r for r in rows[2024] if r['pair'] in hist]
scored,n=fit_and_score(train,test,masses(train),[hist[r['pair']]['p'] for r in test],tourism['2022'],tourism['2023'],'tourism_forecast',hist,'airport')
rebuilt+=scored;train_sizes['tourism_forecast']=n;train_sizes['tourism_heldout']=[]
for f in range(5):
    train=[r for r in rows[2024] if r['fold']!=f]
    test=[r for r in rows[2024] if r['fold']==f]
    scored,n=fit_and_score(train,test,masses(train),[0]*len(test),tourism['2023'],tourism['2023'],'tourism_heldout',None,'airport')
    for r in scored:r['fold']=f
    rebuilt+=scored;train_sizes['tourism_heldout'].append(n)

key=lambda r:(r['experiment'],r['pair'])
re={key(r):r for r in rebuilt};pub={key(r):r for r in published}
assert len(pub)==len(published),'duplicate published target pair within experiment'
assert set(re)==set(pub),'reconstructed scoring sample differs'
max_abs=max_rel=0
for k,r in re.items():
    v=pub[k]
    assert r['actual']==v['actual'] and v['year']==2024
    assert r.get('fold')==v.get('fold')
    assert set(r['predictions'])==set(v['predictions'])
    for model,p in r['predictions'].items():
        q=v['predictions'][model];max_abs=max(max_abs,abs(p-q));max_rel=max(max_rel,abs(p-q)/max(1,abs(q)))
        assert math.isclose(p,q,rel_tol=1e-9,abs_tol=1e-6),(k,model,p,q)

def metric(rs,m):
    a=[r['actual'] for r in rs];p=[r['predictions'][m] for r in rs]
    err=[abs(x-y) for x,y in zip(a,p)]
    logs=[abs(math.log(y/x)) for x,y in zip(a,p)]
    return dict(n=len(a),median_factor=math.exp(statistics.median(logs)),wape_pct=math.fsum(err)/math.fsum(a)*100,mae_pax_year=math.fsum(err)/len(a),bias_pct=math.fsum(y-x for x,y in zip(a,p))/math.fsum(a)*100,within_factor_2_pct=sum(max(x/y,y/x)<=2 for x,y in zip(a,p))/len(a)*100)

lookup={
 'forecast':summary['experiments']['forecast_2023_2024'],
 'heldout':summary['experiments']['heldout_pairs_2024'],
 'income_forecast':summary['macro']['income']['forecast_2023_2024'],
 'income_heldout':summary['macro']['income']['heldout_pairs_2024'],
 'tourism_forecast':summary['macro']['tourism']['forecast_2023_2024'],
 'tourism_heldout':summary['macro']['tourism']['heldout_pairs_2024'],
}
metrics={}
for ex in lookup:
    rr=[r for r in rebuilt if r['experiment']==ex]
    metrics[ex]={m:metric(rr,m) for m in rr[0]['predictions']}
    for m,vals in metrics[ex].items():
        for k,v in vals.items():assert math.isclose(v,lookup[ex]['models'][m][k],rel_tol=1e-9,abs_tol=1e-6),(ex,m,k)
for year in [2023,2024]:
    assert len(rows[year])==summary['coverage'][f'eligible_{year}']
    assert excluded[year]==summary['coverage'][f'excluded_{year}']
result={
 'as_of':'2026-11-11','status':'pass_with_scope_limits',
 'method':'Independent reconstruction from raw repository annual aggregates, own great-circle calculation, vectorized endpoint aggregation and OLS; no import of benchmark.py or its functions. All per-pair predictions and all summary metrics compared.',
 'input_sha256':{k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in FILES.items()},
 'checks':{'eligible_2023':len(rows[2023]),'eligible_2024':len(rows[2024]),'all_prediction_records_matched':len(rebuilt),'scope_experiments':['forecast','heldout','income_forecast','income_heldout','tourism_forecast','tourism_heldout'],'smearing_uses_training_residuals_only':True,'max_absolute_prediction_difference_pax':max_abs,'max_relative_prediction_difference':max_rel,'all_summary_metrics_match':True,'no_duplicate_pair_within_experiment':True,'test_target_year_is_2024':True,'forecast_train_and_traffic_features_from_2023_only':True,'whole_pair_fold_assignment_verified':True,'heldout_masses_use_training_folds_only':True,'own_training_flow_subtracted':True,'income_baselines_use_identical_rows':True,'income_forecast_lags_2022_train_2023_score':True,'income_heldout_uses_2023':True,'tourism_same_sample_baselines_verified':True,'tourism_forecast_uses_2022_train_2023_score':True,'tourism_heldout_uses_2023':True},
 'training_rows':train_sizes,'metrics':metrics,'independent_train_only_smearing_multipliers':independent_smearing,
 'conclusions':[
  'For already observed pairs the previous annual flow is substantially more accurate than these simplified cross-sectional regressions.',
  'Training airport-pair masses improve the distance-only comparison for held-out observed pairs.',
  'National GDP per capita PPP does not improve median multiplicative error in these matched-sample comparisons; its near-zero WAPE change does not establish a useful effect.',
  'A log-OLS central estimate without smearing materially underpredicts aggregate passenger totals; signed bias must remain visible.',
  'Annual regional accommodation nights give very small metric changes; this specification does not establish a material predictive improvement.',
  'Train-only smearing reduces aggregate signed bias in both base experiments, but worsens median multiplicative error; this is a diagnostic trade-off, not uniform accuracy improvement.',
 ],
 'limits':[
  'No zero-flow or absent-pair population is tested. Results do not validate opening a genuinely unserved route.',
  'The held-out experiment presumes both airports have other observed training routes; unknown endpoints are excluded.',
  'Endpoint masses are partial traffic sums for this published route sample, not verified whole-airport totals or resident populations.',
  'PAS_CRD is on-flight origin/destination airport-pair flow, not true journey origin/destination and not the PAS_BRD flight-stage measure.',
  'Annual aggregates with twelve positive months exclude seasonal and incomplete-year services; no monthly seasonality result is justified.',
  'Current-vintage historical data are a retrospective check; actual historical availability/revision vintages are not reconstructed.',
  'Only one fixed five-fold split and two adjacent calendar years; no uncertainty intervals or causal claim.',
  'This simplified research benchmark is not validation of the production P/T/F calculator.',
 ]}
HERE.mkdir(exist_ok=True)
(HERE/'benchmark.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
print(json.dumps({'status':result['status'],'records':len(rebuilt),'max_relative_difference':max_rel,'n':{x:next(iter(v.values()))['n'] for x,v in metrics.items()}}))
