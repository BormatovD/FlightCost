#!/usr/bin/env python3
"""Independent source decoding and geographic check. Raw cache stays outside repo."""
import argparse,hashlib,json,math
from collections import defaultdict
from pathlib import Path
import numpy as np
from matplotlib.path import Path as PolygonPath

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
def main(cache):
    covpath=HERE.parent/'out/tourism_covariates.json'
    cov=json.loads(covpath.read_text());aps=json.loads((ROOT/'research/routes-2026-11/out/airports.json').read_text())
    geob=(cache/'gisco_regions.json').read_bytes();nb=(cache/'eurostat_nights.json').read_bytes()
    geo=json.loads(geob);data=json.loads(nb)
    # Independent C implementation of polygon inclusion, not the researcher's raycaster.
    keys=sorted(aps);points=np.array([[aps[k][1],aps[k][0]] for k in keys])
    hits=[set() for _ in keys]
    for f in geo['features']:
        g=f['geometry'];polys=[g['coordinates']] if g['type']=='Polygon' else g['coordinates']
        for rings in polys:
            inside=PolygonPath(np.array(rings[0])[:,:2]).contains_points(points)
            for ring in rings[1:]:inside &= ~PolygonPath(np.array(ring)[:,:2]).contains_points(points)
            for i in np.where(inside)[0]:hits[i].add(f['properties']['NUTS_ID'])
    assigned={k:next(iter(h)) for k,h in zip(keys,hits) if len(h)==1}
    ambiguous=sorted(k for k,h in zip(keys,hits) if len(h)>1)
    assert assigned==cov['airport_region'],'Independent geographic assignment differs'
    assert ambiguous==sorted(cov['ambiguous_airports_excluded'])
    # Decode JSON-stat flat indices using numpy, without flightcostapp.parsers.
    reverse={d:{n:k for k,n in data['dimension'][d]['category']['index'].items()} for d in data['id']}
    months=defaultdict(dict);flags=defaultdict(set)
    observations=data['value'].items() if isinstance(data['value'],dict) else enumerate(data['value'])
    for i,v in observations:
        if v is None:continue
        dims={d:reverse[d][int(n)] for d,n in zip(data['id'],np.unravel_index(int(i),data['size']))}
        assert dims['freq']=='A' and dims['unit']=='NR' and dims['nace_r2']=='I551-I553'
        if dims['c_resid']!='TOTAL' or dims['month']=='TOTAL':continue
        year=dims['time'];month=int(dims['month'][1:]);region=dims['geo']
        assert month not in months[(region,year)],'Duplicate region-month would be summed twice'
        months[(region,year)][month]=v
        status=(data.get('status') or {}).get(str(i))
        if status:flags[(region,year)].add(status)
    annual={k:math.fsum(v.values()) for k,v in months.items() if set(v)==set(range(1,13)) and min(v.values())>=0}
    values={y:{a:annual[(r,y)] for a,r in assigned.items() if (r,y) in annual and annual[(r,y)]>0} for y in ['2022','2023']}
    assert values==cov['values'],'Independent annual TOTAL monthly sum differs'
    used={assigned[a] for y,d in values.items() for a in d}
    used_flags={f'{r}/{y}':sorted(flags[r,y]) for r in used for y in ['2022','2023'] if flags[r,y]}
    source_hashes={'eurostat_nights':hashlib.sha256(nb).hexdigest(),'gisco_regions':hashlib.sha256(geob).hexdigest()}
    assert source_hashes==cov['raw_sha256']
    res={'as_of':'2026-11-11','status':'pass_with_scope_limits','method':'Fresh independent primary downloads. Geographic assignment checked using matplotlib C polygon inclusion including holes; annual totals independently decoded from JSON-stat indices without project parsers.','input_sha256':hashlib.sha256(covpath.read_bytes()).hexdigest(),'independent_raw_sha256':source_hashes,'checks':{'all_airport_region_matches':len(assigned),'ambiguous_excluded':ambiguous,'yearly_airport_coverage':{y:len(v) for y,v in values.items()},'all_retained_airport_year_values_match':sum(map(len,values.values())),'regions_used':len(used),'twelve_months_required':True,'annual_TOTAL_row_not_double_counted':True,'residency_TOTAL_only':True,'missing_airports_not_nearest_imputed':True,'sample_region_matches':{a:assigned.get(a) for a in ['EDDF','LEBL']}},'source_flags_on_used_region_years':used_flags,'sources':[cov['source'],cov['geography_source']],'source_refs':['turn88view0','turn88view1'],'limits':['The underlying series uses annual reference years with a separate month dimension; all twelve months are summed exactly once.','NUTS2024 simplified boundaries and a2026 data vintage are retrospective; historical boundary/vintage consistency is not independently reconstructed.','Region of airport coordinates is not measured airport catchment; regional accommodation nights include residents and arrivals by all transport modes.','Accommodation nights are not passengers or visits. This annual proxy cannot validate passenger seasonality.','Point-on-boundary behaviour is implementation dependent; no observed assignment mismatch occurred in this sample.']}
    (HERE/'tourism_source.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n');print(json.dumps(res['checks']))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cache-dir',type=Path,required=True);main(p.parse_args().cache_dir)
