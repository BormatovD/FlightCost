#!/usr/bin/env python3
"""Independently check collected history, using pandas/lxml and pdfplumber.

Run with --html-cache and --pdf-cache pointing outside the repository to
independently retrieved primary-source files. No producer module is imported.
The source chart axes and legend-to-curve assignments were inspected visually.
"""
import argparse
from collections import Counter, defaultdict
from decimal import Decimal
import hashlib
import io
import json
import math
from pathlib import Path
import re

import pandas as pd
import pdfplumber

HERE=Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def curve_y(path, x):
    """PDF commands from pdfminer; exact cubic solution instead of a sampled curve."""
    current=None
    for cmd in path:
        op=cmd[0]
        if op=='m':
            current=cmd[1]
            continue
        end=cmd[-1]
        if op=='l':
            points=[current,end]
        elif op=='c':
            points=[current,*cmd[1:]]
        elif op=='v':
            points=[current,current,*cmd[1:]]
        elif op=='y':
            points=[current,*cmd[1:],end]
        else:
            raise ValueError('Unexpected PDF curve command '+op)
        if min(current[0],end[0])-1e-7<=x<=max(current[0],end[0])+1e-7:
            if op=='l':
                return current[1]+(end[1]-current[1])*(x-current[0])/(end[0]-current[0])
            def bez(t,k):
                return (1-t)**3*points[0][k]+3*(1-t)**2*t*points[1][k]+3*(1-t)*t*t*points[2][k]+t**3*points[3][k]
            lo,hi=0.,1.
            for _ in range(60):
                m=(lo+hi)/2
                if (bez(m,0)<x)==(end[0]>current[0]):lo=m
                else:hi=m
            return bez((lo+hi)/2,1)
        current=end
    raise ValueError('Requested coordinate outside source curve')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--html-cache',type=Path,required=True)
    parser.add_argument('--pdf-cache',type=Path,required=True)
    a=parser.parse_args()
    data_path=HERE.parent/'out/segments_history.json'
    d=json.loads(data_path.read_text())
    rows=d['observations']
    failures=[]
    results=[]
    tables={}
    for year in range(2016,2021):
        tables[year]=pd.read_html(io.StringIO((a.html_cache/f'avac-{year}.html').read_text()),flavor='lxml',keep_default_na=False)
    for o in rows:
        if o['quality']!='published_table':continue
        year=int(o['period'][:4]);df=tables[year][0 if o['kind']=='value' else 1]
        found=[]
        for _,r in df.iterrows():
            for c in (1,7):
                if str(r.iloc[c]).strip()==o['source_label']:
                    age=o['age']['years'];position={0:2,5:3,10:4,20:5}[age]
                    cell=str(r.iloc[c+position]).strip()
                    match=re.fullmatch(r'([\d,.]+)([^\d]*)',cell)
                    if match:
                        value=int(Decimal(match[1].replace(',',''))*(1000000 if o['kind']=='value' else 1000))
                        flags=' '.join(re.findall(r'\(([^)]*)\)',str(r.iloc[c]))+[str(r.iloc[c+1]),match[2]])
                        legend=({'†':'HGW','‡':'LGW','§':'IGW','♠':'Winglets','♣':'Sharklets','♥':'Enhanced'}
                            if year==2017 else {'†':'Enhanced','‡':'IGW','♯':'LGW','§':'HGW','∞':'conversion'})
                        specs={v for k,v in legend.items() if k in flags}
                        specs|={w for w in ('Enhanced','HGW','LGW','IGW','Winglets','Sharklets') if w.lower() in flags.lower()}
                        found.append((value,sorted(specs),cell))
        ok=len(found)==1 and found[0][0]==o['amount_low_usd']==o['amount_high_usd'] and found[0][1]==o['technical_specification']
        if not ok:failures.append({'id':o['id'],'problem':'AVAC cell or specification mismatch','independent':found})
        results.append({'id':o['id'],'status':'pass' if ok else 'fail','method':'independent pandas/lxml HTML cell and year-specific footnote legend'})

    # Independent pdfplumber curve indices; distinct parser from producer PyMuPDF.
    # Axis values are those printed on the source figures, not market estimates.
    configs=[
      ('truenoord-turboprop-2023','truenoord-2023.pdf',51,'6.1(i)','AT46','value',{0:33,3:34,5:35,10:36},(2011,67.5692,2023,521.8102),(2,236.599,18,141.684)),
      ('truenoord-turboprop-2023','truenoord-2023.pdf',51,'6.1(ii)','AT76','value',{0:29,3:30,5:31,10:32},(2011,65.9644,2023,523.1944),(4,386.406,22,279.626)),
      ('truenoord-turboprop-2023','truenoord-2023.pdf',51,'6.1(iii)','DH8D','value',{0:37,3:38,5:39,10:40},(1998,70.1339,2022,522.552),(4,546.647,24,428.003)),
      ('truenoord-turboprop-2023','truenoord-2023.pdf',53,'6.3(i)','AT46','lease',{0:29,3:30,5:31,10:32},(2011,75.5441,2023,524.9791),(40,460.895,180,367.930)),
      ('truenoord-turboprop-2023','truenoord-2023.pdf',53,'6.3(ii)','AT76','lease',{0:33,3:34,5:35,10:36},(2011,75.4834,2023,524.7594),(50,606.239,200,501.653)),
      ('truenoord-turboprop-2023','truenoord-2023.pdf',53,'6.3(iii)','DH8D','lease',{0:37,3:38,5:39,10:40},(2011,75.54,2023,524.76),(50,762.866,230,646.66)),
      ('truenoord-regional-2025','truenoord-regional-2025.pdf',42,'6.3','E75L','lease',{0:35},(2005,95.8671,2024,529.2801),(160,753.254,240,618.357)),
      ('truenoord-regional-2025','truenoord-regional-2025.pdf',43,'6.5','CRJ9','value',{5:33,10:31,15:32},(2006,149.6588,2024,500.4548),(5,760.7213,21,639.0268)),
      ('truenoord-regional-2025','truenoord-regional-2025.pdf',44,'6.6','CRJ9','lease',{5:34,10:35,15:36},(2009,102.6564,2024,526.5354),(50,291.2831,210,177.1771)),
      ('truenoord-regional-2022','truenoord-regional-2022.pdf',34,'32','E195','value',{3:33,5:34,10:35},(2009,111.5341,2022,498.8361),(5,723.4477,35,638.7521)),
    ]
    docs={name:pdfplumber.open(a.pdf_cache/name) for name in {r[1] for r in configs}}
    chart_checks=[]
    verified_chart_ids=set()
    for source,filename,pi,figure,code,kind,curves,xcal,ycal in configs:
        page=docs[filename].pages[pi]
        y0,yp0,y1,yp1=ycal
        # Independently read horizontal grid coordinates in the raw PDF.
        grid=[l['top'] for l in page.lines if l['width']>250]
        grid.extend(c['top'] for c in page.curves if c['width']>250 and c['height']<.02)
        grid_ok=all(min(abs(g-y) for g in grid)<.03 for y in (yp0,yp1))
        if not grid_ok:failures.append({'figure':source+' '+figure,'problem':'printed grid calibration mismatch'})
        checked=0;max_difference=0
        for o in rows:
            if o['quality']!='chart_digitized' or o['source_id']!=source or o['icao']!=code or o['kind']!=kind:continue
            if not o['curve_id'].startswith(source+'-fig'+figure+'-'):continue
            age=o['age']['years'];year=int(o['period'])
            x=xcal[1]+(year-xcal[0])*(xcal[3]-xcal[1])/(xcal[2]-xcal[0])
            curve=page.curves[curves[age]]
            # The source drawings contain sub-point alignment differences.
            # A <=0.75 PDF-point edge clamp is a drawing tolerance, not a new year.
            rawx=x
            if x<curve['x0']-.75 or x>curve['x1']+.75:
                failures.append({'id':o['id'],'problem':'observation outside the drawn curve'})
                continue
            x=min(max(x,curve['x0']),curve['x1'])
            try:
                y=curve_y(curve['path'],x)
            except ValueError as exc:
                raise ValueError(f"{o['id']}: x={x}; path={curve['path']}") from exc
            amount=(y0+(yp0-y)*(y1-y0)/(yp0-yp1))*(1e6 if kind=='value' else 1000)
            difference=abs(amount-o['amount_low_usd'])
            max_difference=max(max_difference,difference)
            ok=(difference<=o['extraction_rounding_usd']/2+5 and o['amount_low_usd']==o['amount_high_usd']
                and o['period_precision']=='year' and o['source_sha256']==sha(a.pdf_cache/filename))
            if code=='DH8D' and age==0:ok=ok and year<=2021
            if not ok:failures.append({'id':o['id'],'problem':'digitized point mismatch','independent_unrounded_usd':amount,'stored':o['amount_low_usd']})
            checked+=1;verified_chart_ids.add(o['id'])
        chart_checks.append({'source_id':source,'figure':figure,'pdf_page':pi+1,'icao':code,'kind':kind,'checked_points':checked,'maximum_rounding_distance_usd':max_difference,'printed_grid_checked':grid_ok,'curve_age_legend_visually_checked':True,'status':'pass' if grid_ok else 'fail'})
    all_chart_ids={o['id'] for o in rows if o['quality']=='chart_digitized'}
    if all_chart_ids!=verified_chart_ids:failures.append({'problem':'unchecked chart observations','ids':sorted(all_chart_ids-verified_chart_ids)})
    for doc in docs.values():doc.close()

    expected_text={
      ('oriel-istat-e2-2026','E295','value',0): (45000000,45000000),
      ('oriel-istat-e2-2026','E295','lease',0): (285000,285000),
      ('truenoord-crossover-2021','E295','value',0):(33900000,33900000),
      ('truenoord-crossover-2021','E295','lease',0):(242000,242000),
      ('truenoord-regional-2022','E195','lease',10):(100000,100000),
      ('iba-iclg-2026','A332','value',12):(30000000,30000000),
      ('iba-iclg-2026','B77W','value',12):(57000000,57000000),
      ('iba-iclg-2026','A332','lease',12):(324000,345000),
      ('iba-iclg-2026','B77W','lease',12):(450000,587000),
      ('iba-iclg-2026','A359','lease',0):(1190000,1250000),
      ('iba-iclg-2026','B789','lease',0):(1070000,1150000),
    }
    new_text=[]
    for key,bounds in expected_text.items():
        matches=[o for o in rows if (o['source_id'],o['icao'],o['kind'],o['age'].get('years'))==key]
        ok=len(matches)==1 and (matches[0]['amount_low_usd'],matches[0]['amount_high_usd'])==bounds
        if not ok:failures.append({'problem':'new source printed number mismatch','key':key})
        new_text.append({'source_id':key[0],'icao':key[1],'kind':key[2],'age':key[3],'status':'pass' if ok else 'fail'})
    series_rows=defaultdict(list)
    for o in rows:series_rows[o['series_key']].append(o)
    invariant_keys=('icao','kind','age','variant','valuation_basis','source_family','extraction_basis','technical_specification')
    for key,ss in series_rows.items():
        for k in invariant_keys:
            values={json.dumps(o.get(k),sort_keys=True) for o in ss}
            if len(values)!=1:failures.append({'problem':'mixed series semantics','series':key,'field':k})
    coverage_checks=[]
    for aircraft in d['aircraft']:
        code=aircraft['icao'];n=0
        for age_group,kinds in aircraft['coverage'].items():
            for kind,cov in kinds.items():
                ss=[o for o in rows if o['icao']==code and o['age']['category']==age_group and o['kind']==kind]
                years=sorted({int(o['period'][:4]) for o in ss})
                expected={'count':len(ss),'years':years,'periods':sorted({o['period'] for o in ss}),'missing_years_2016_2026':[y for y in range(2016,2027) if y not in years],'source_ids':sorted({o['source_id'] for o in ss})}
                if cov!=expected:failures.append({'problem':'coverage mismatch','icao':code,'age_group':age_group,'kind':kind})
                n+=len(ss)
        coverage_checks.append({'icao':code,'observations':n})
    result={'stage':'0056','status':'pass_with_limitations' if not failures else 'fail','independent':True,
        'data_sha256':sha(data_path),'rows':len(rows),'quality_counts':dict(Counter(o['quality'] for o in rows)),
        'segments':len(d['segments']),'types':len(d['aircraft']),
        'segment_sizes':{s['id']:len(s['types']) for s in d['segments']},
        'avac_cell_checks':results,'chart_checks':chart_checks,'new_printed_number_checks':new_text,
        'inherited_printed_number_scope':'Previously verified 0055 IBA rows retain their source/age/variant checks; new rows above were independently reopened.',
        'coverage_checks':coverage_checks,'series_semantics_checked':len(series_rows),'failed_checks':failures,
        'limitations':['Digitized points reproduce drawn appraiser-average curves, not precise transaction data. The independently checked PDF geometry does not establish market accuracy.',
          'Year-axis line alignment is approximate artwork. Rounding and digitization tolerance must remain visible and are not confidence bounds or observed market ranges.',
          'The 2023 turboprop narrative and plotted averages differ; source locators and bases remain separate.',
          'New DH8D source curves end in 2021; no new 2023 point is inferred from old-vintage values.',
          'AVAC age labels are nominal; e.g. five can mean four to six years. Different technical specifications stay in different series.',
          'Oriel text 45m is rounded; the January 2026 value table has 45.31m. Its date is not assigned to the separate rent statement.',
          'CMV historical charts exclude future base-value curves. Current 2026 source points are not joined across incompatible appraiser/age/technical bases.',
          'History is research-only and does not alter accepted production prices or calculator coefficients.']}
    (HERE/'history_0056.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(result['status'],len(rows),'rows;',len(results),'AVAC;',len(verified_chart_ids),'chart;',len(new_text),'new printed anchors')
    print(json.dumps(failures,ensure_ascii=False))


if __name__=='__main__':main()
