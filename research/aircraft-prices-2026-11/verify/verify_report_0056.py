#!/usr/bin/env python3
"""Verify final multilingual historical SVG data and illustrative finance output."""
from pathlib import Path
from collections import Counter, defaultdict
import hashlib
import json
import math
import re
from lxml import html

HERE=Path(__file__).resolve().parent


def period(p):
    year=int(p[:4])
    if len(p)==4:return year+.5
    if 'Q' in p:return year+(int(p[-1])-.5)/4
    return year+(int(p[5:7])-.5)/12


def main():
    history=json.loads((HERE.parent/'out/segments_history.json').read_text())
    econ=json.loads((HERE.parent/'out/lease_economics.json').read_text())
    observations={o['id']:o for o in history['observations'] if o['age']['category']=='new'}
    failures=[];checks=[]
    for lang,filename in [('ru','report.html'),('en','report.en.html'),('de','report.de.html')]:
        path=HERE.parent/filename;doc=html.fromstring(path.read_text())
        graphs=doc.xpath('//svg[contains(@class,"segment-history")]')
        ids=doc.xpath('//*[@id]/@id')
        duplicate_ids=[k for k,v in Counter(ids).items() if v>1]
        broken=[a for a in doc.xpath('//a[starts-with(@href,"#")]/@href') if a[1:] not in ids]
        all_seen=[];line_count=range_count=0;max_error=0
        for svg in graphs:
            groups=svg.xpath('.//*[@data-observation-id]');segment=svg.get('data-segment');kind=svg.get('data-kind')
            divisor=1e6 if kind=='value' else 1000
            axis=svg.xpath('.//text[@text-anchor="end"]')
            def numeric(s):
                s=s.replace(' ','').replace('\xa0','')
                if lang=='ru':s=s.replace(',','.')
                elif lang=='de':s=s.replace('.','').replace(',','.')
                else:s=s.replace(',','')
                return float(s)
            ymax=max(numeric(x.text_content()) for x in axis)
            xof=lambda x:64+(x-2016)/11*672
            yof=lambda y:232-y/ymax*206
            lookup={}
            for group in groups:
                ident=group.get('data-observation-id');all_seen.append(ident);o=observations.get(ident)
                if o is None:
                    failures.append({'lang':lang,'problem':'non-new or unknown point','id':ident});continue
                circle=group.find('circle')
                expected_x=xof(period(o['period']));expected_y=yof((o['amount_low_usd']+o['amount_high_usd'])/2/divisor)
                error=max(abs(float(circle.get('cx'))-expected_x),abs(float(circle.get('cy'))-expected_y))
                max_error=max(max_error,error)
                if error>.015:failures.append({'lang':lang,'problem':'SVG geometry differs from data','id':ident,'px_error':error})
                if group.get('data-period')!=o['period'] or group.get('data-age-category')!='new':failures.append({'lang':lang,'problem':'date/age label mismatch','id':ident})
                if group.getparent().get('href')!=o['source_url']:failures.append({'lang':lang,'problem':'point source link mismatch','id':ident})
                if o['quality']=='chart_digitized' and circle.get('fill')!='var(--bg)':failures.append({'lang':lang,'problem':'digitized point not visually distinct','id':ident})
                paths=group.findall('path')
                if bool(paths)!=(o['amount_low_usd']!=o['amount_high_usd']):failures.append({'lang':lang,'problem':'published range omitted/invented','id':ident})
                if paths:
                    values=[float(v) for v in re.findall(r'-?\d+(?:\.\d+)?',paths[0].get('d'))]
                    if max(abs(values[0]-expected_x),abs(values[1]-yof(o['amount_high_usd']/divisor)),abs(values[2]-yof(o['amount_low_usd']/divisor)))>.015:failures.append({'lang':lang,'problem':'range endpoints wrong','id':ident})
                    range_count+=1
                lookup[ident]=(expected_x,expected_y)
            expected_edges=[]
            grouped=defaultdict(list)
            for ident in lookup:grouped[observations[ident]['series_key']].append(observations[ident])
            for key,os in grouped.items():
                os.sort(key=lambda o:(period(o['period']),o['id']))
                for a,b in zip(os,os[1:]):
                    if 0<period(b['period'])-period(a['period'])<=1.5:expected_edges.append((key,*lookup[a['id']],*lookup[b['id']]))
            actual_edges=svg.xpath('.//line[@data-series]');line_count+=len(actual_edges)
            if len(actual_edges)!=len(expected_edges):failures.append({'lang':lang,'segment':segment,'kind':kind,'problem':'series/gap edge count mismatch'})
            for edge in actual_edges:
                es=(edge.get('data-series'),float(edge.get('x1')),float(edge.get('y1')),float(edge.get('x2')),float(edge.get('y2')))
                if not any(es[0]==v[0] and max(abs(x-y) for x,y in zip(es[1:],v[1:]))<.015 for v in expected_edges):failures.append({'lang':lang,'problem':'edge joins incompatible series or long gap'})
        if len(graphs)!=8 or Counter(all_seen)!=Counter(observations.keys()):failures.append({'lang':lang,'problem':'historical chart coverage mismatch'})
        if broken or duplicate_ids:failures.append({'lang':lang,'problem':'internal citation/navigation IDs','broken':broken,'duplicates':duplicate_ids})
        economics_node=doc.xpath('//*[@id="lease-economics"]')[0]
        paragraphs=[]
        for sibling in economics_node.itersiblings():
            if sibling.tag=='h2':break
            paragraphs.append(' '.join(sibling.text_content().split()))
        economic_text=' '.join(paragraphs)
        monetary_values=[econ['base'][k] for k in ['rent_usd_month_end','rent_usd_month_advance']]
        monetary_values += [econ['financing'][k] for k in ['opening_debt_usd','initial_equity_usd','scheduled_debt_payment_usd_month','regular_equity_cash_usd_month','remaining_debt_at_sale_usd','net_sale_cash_to_equity_usd']]
        monetary_values += [econ['financing']['first_year'][k] for k in ['depreciation_usd','interest_usd','accounting_profit_usd_before_tax_and_other_items','equity_cash_usd_before_tax_and_terminal_sale']]
        for val in monetary_values:
            formatted=f'{val:,.0f}'.replace(',', ' ' if lang=='ru' else '.' if lang=='de' else ',')+' USD'
            if formatted not in economic_text:failures.append({'lang':lang,'problem':'finance result absent or incorrect','expected':formatted})
        required_links=['iata.org','aercap.com','sec.gov/Archives/edgar/data/1487712','report.lufthansagroup.com','ifrs.org','awg.aero']
        linked=doc.xpath('//li[starts-with(@id,"src")]//a/@href')
        for host in required_links:
            if not any(host in u for u in linked):failures.append({'lang':lang,'problem':'required finance source not linked','host':host})
        checks.append({'language':lang,'file':filename,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'main_history_graphs':len(graphs),'new_aircraft_points':len(all_seen),'comparable_series_edges':line_count,'published_range_bars':range_count,'maximum_svg_coordinate_error_px':max_error,'finance_amounts_checked':len(monetary_values),'broken_internal_links':broken})
    result={'stage':'0056','status':'pass' if not failures else 'fail','scope':'Content, numerical and SVG data verification; no screenshot-based layout claim.',
        'checks':checks,'failures':failures,
        'manual_semantic_review':['All three languages distinguish required model rent from negotiated market rent.','Nominal historical periods, coarse dates, new versus aged aircraft, appraiser bases, chart digitization and published ranges remain explicit.','Range midpoint is a scenario convention, not a published transaction mean.','Debt cash flows are separate from the unlevered asset valuation; residual debt is repaid at sale.','Accounting residual and depreciation differ from ten-year resale; initial costs are capitalized.','Gross rent/price, asset IRR, equity IRR, accounting profit and equity cash flow are correctly distinguished.','IFRS 16 recognition is described with exceptions; deposits and maintenance reserves are not automatically profit, and reimbursed maintenance is not double counted.','Lufthansa transaction counts and tenors agree with its primary report; no per-aircraft transaction price is inferred.']}
    (HERE/'review_0056.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(result['status'],json.dumps(failures,ensure_ascii=False))


if __name__=='__main__':main()
