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
    extension_checks, extension_failures = audit_new_features(history, econ)
    failures.extend(extension_failures)
    result={'extensions':extension_checks,'stage':'0056-v2','status':'pass' if not failures else 'fail','scope':'Content, numerical and SVG data verification; no screenshot-based layout claim.',
        'checks':checks,'failures':failures,
        'manual_semantic_review':['All three languages distinguish required model rent from negotiated market rent.','Nominal historical periods, coarse dates, new versus aged aircraft, appraiser bases, chart digitization and published ranges remain explicit.','Range midpoint is a scenario convention, not a published transaction mean.','Debt cash flows are separate from the unlevered asset valuation; residual debt is repaid at sale.','Accounting residual and depreciation differ from ten-year resale; initial costs are capitalized.','Gross rent/price, asset IRR, equity IRR, accounting profit and equity cash flow are correctly distinguished.','IFRS 16 recognition is described with exceptions; deposits and maintenance reserves are not automatically profit, and reimbursed maintenance is not double counted.','Lufthansa transaction counts and tenors agree with its primary report; no per-aircraft transaction price is inferred.']}
    (HERE/'review_0056_v2.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(result['status'],json.dumps(failures,ensure_ascii=False))


def audit_new_features(history, econ):
    """Model geometry, directed money flows and exact source-stage separation."""
    model = json.loads((HERE.parent/'out/model_reference.json').read_text())
    references = {a['icao']:a for a in model['aircraft']}
    p,b,f = econ['inputs'],econ['base'],econ['financing']
    failures=[]; reports=[]
    prior=json.loads((HERE/'lease_economics_0056.json').read_text())
    same_cash_input=hashlib.sha256((HERE.parent/'out/lease_economics.json').read_bytes()).hexdigest()==prior['input_sha256']
    if not same_cash_input:
        failures.append({'problem':'accepted illustrative cash-flow inputs changed; prior full audit invalid'})
    # Independently discount each payment; do not reuse producer annuity helpers.
    asset_npv=-(p['purchase_usd']+p['upfront_cost_usd'])
    for t in range(1,p['lease_months']+1):
        asset_npv+=(b['rent_usd_month_end']-p['owner_cost_usd_month'])/(1+p['asset_return_annual_effective'])**(t/12)
    asset_npv+=(p['resale_usd']-p['sale_cost_usd'])/(1+p['asset_return_annual_effective'])**(p['lease_months']/12)
    if abs(asset_npv)>1e-5:failures.append({'problem':'asset NPV imbalance','usd':asset_npv})
    loan_npv=-f['opening_debt_usd']
    for t in range(1,p['debt_maturity_months']+1):
        loan_npv+=f['scheduled_debt_payment_usd_month']/(1+p['debt_interest_annual_effective'])**(t/12)
    loan_npv+=f['remaining_debt_at_sale_usd']/(1+p['debt_interest_annual_effective'])**(p['debt_maturity_months']/12)
    if abs(loan_npv)>1e-5:failures.append({'problem':'lender NPV imbalance','usd':loan_npv})
    equity_npv=-f['initial_equity_usd']
    for t in range(1,p['lease_months']+1):
        equity_npv+=f['regular_equity_cash_usd_month']/(1+f['equity_irr_annual_effective_pre_tax'])**(t/12)
    equity_npv+=f['net_sale_cash_to_equity_usd']/(1+f['equity_irr_annual_effective_pre_tax'])**(p['lease_months']/12)
    if abs(equity_npv)>1e-5:failures.append({'problem':'equity NPV imbalance','usd':equity_npv})
    expected_flows={
        'debt-advance':('purchase','bank','lessor',f['opening_debt_usd']),
        'equity-injection':('purchase','investor','lessor',f['initial_equity_usd']),
        'aircraft-purchase':('purchase','lessor','seller',p['purchase_usd']),
        'purchase-cost':('purchase','lessor','services',p['upfront_cost_usd']),
        'monthly-rent':('monthly','airline','lessor',b['rent_usd_month_end']),
        'monthly-debt':('monthly','lessor','bank',f['scheduled_debt_payment_usd_month']),
        'monthly-cost':('monthly','lessor','services',p['owner_cost_usd_month']),
        'monthly-equity':('monthly','lessor','investor',f['regular_equity_cash_usd_month']),
        'resale-proceeds':('sale','buyer','lessor',p['resale_usd']),
        'balloon':('sale','lessor','bank',f['remaining_debt_at_sale_usd']),
        'sale-cost':('sale','lessor','services',p['sale_cost_usd']),
        'sale-equity':('sale','lessor','investor',f['net_sale_cash_to_equity_usd']),
    }
    for lang,filename in [('ru','report.html'),('en','report.en.html'),('de','report.de.html')]:
        doc=html.fromstring((HERE.parent/filename).read_text())
        model_paths=doc.xpath('//svg[contains(@class,"segment-history")]//polyline[contains(@class,"model-reference")]')
        if Counter(x.get('data-icao') for x in model_paths)!=Counter(references.keys()):
            failures.append({'lang':lang,'problem':'missing or duplicate model reference curves'})
        max_error=0
        for path in model_paths:
            code=path.get('data-icao'); row=references[code]
            svg=path.getparent()
            if svg.get('data-kind')!='lease':failures.append({'lang':lang,'problem':'invented purchase-price model','icao':code})
            if path.get('data-reference-role')!='raw_parametric':failures.append({'lang':lang,'problem':'model baseline role','icao':code})
            if int(path.get('data-model-age-years'))!=row['model_age_years']:failures.append({'lang':lang,'problem':'model age mismatch','icao':code})
            if not math.isclose(float(path.get('data-model-lease-eur-month')),row['raw_parametric_lease_eur_month'],rel_tol=1e-11):failures.append({'lang':lang,'problem':'wrong plotted EUR model baseline','icao':code})
            axis=svg.xpath('.//text[@text-anchor="end"]')
            def numeric(s):
                s=s.replace(' ','').replace('\xa0','')
                if lang=='ru':s=s.replace(',','.')
                elif lang=='de':s=s.replace('.','').replace(',','.')
                else:s=s.replace(',','')
                return float(s)
            ymax=max(numeric(x.text_content()) for x in axis)
            actual=[tuple(map(float,point.split(','))) for point in path.get('points').split()]
            expected=[(64+(point['x']-2016)/11*672,232-point['lease_thousand_usd_month']/ymax*206) for point in row['nominal_usd_points']]
            if len(actual)!=11:failures.append({'lang':lang,'problem':'model annual point count','icao':code})
            error=max(abs(a-b) for A,B in zip(actual,expected) for a,b in zip(A,B))
            max_error=max(max_error,error)
            if error>.015:failures.append({'lang':lang,'problem':'model SVG geometry','icao':code,'max_px':error})
            if path.get('stroke-dasharray')!='10 4 2 4':failures.append({'lang':lang,'problem':'model line not distinguished','icao':code})
            observations=svg.xpath('.//g[@data-icao="'+code+'"]//circle')
            if observations and any(c.get('stroke')!=path.get('stroke') for c in observations):failures.append({'lang':lang,'problem':'model and data type colours differ','icao':code})
        for seg in model['segments']:
            nodes=doc.xpath('//div[@data-model-segment="'+seg['id']+'"]')
            if len(nodes)!=1:
                failures.append({'lang':lang,'problem':'age cohort label missing','segment':seg['id']});continue
            text=nodes[0].text_content()
            for code in seg['types']:
                if references[code]['label'] not in text:failures.append({'lang':lang,'problem':'type missing visible model-age note','icao':code})
            if any(references[c]['model_age_years']>0 for c in seg['types']) and not nodes[0].xpath('.//*[contains(@class,"model-age-mismatch")]'):
                failures.append({'lang':lang,'problem':'age mismatch warning absent','segment':seg['id']})
        maps=doc.xpath('//svg[contains(@class,"deal-cashflow")]')
        if {s.get('data-stage') for s in maps}!={'purchase','monthly','sale'} or len(maps)!=3:
            failures.append({'lang':lang,'problem':'cash-flow stages missing'})
        nodes=doc.xpath('//*[@data-flow]')
        if Counter(n.get('data-flow') for n in nodes)!=Counter(expected_flows.keys()):failures.append({'lang':lang,'problem':'cash-flow edge set'})
        balance=defaultdict(float)
        for node in nodes:
            ident=node.get('data-flow')
            if ident not in expected_flows:continue
            stage,source,target,amount=expected_flows[ident]
            if (node.get('data-period'),node.get('data-from'),node.get('data-to'))!=(stage,source,target):failures.append({'lang':lang,'problem':'cash-flow direction or period','flow':ident})
            actual=float(node.get('data-amount-usd'))
            if not math.isclose(actual,amount,rel_tol=1e-11,abs_tol=1e-5):failures.append({'lang':lang,'problem':'cash-flow amount','flow':ident})
            money_nodes=node.xpath('.//*[@data-c="USD"]')
            if not money_nodes:failures.append({'lang':lang,'problem':'cash amount lacks currency wrapper','flow':ident})
            balance[stage]+=actual if target=='lessor' else -actual
            paths=node.findall('path')
            if not paths or paths[0].get('marker-end')!='url(#arrow-'+stage+')':failures.append({'lang':lang,'problem':'cash-flow arrow marker','flow':ident})
            actors={a.get('data-actor') for a in node.getparent().xpath('.//*[@data-actor]')}
            if source not in actors or target not in actors:failures.append({'lang':lang,'problem':'flow actor absent','flow':ident})
        if any(abs(v)>1e-4 for v in balance.values()):failures.append({'lang':lang,'problem':'lessor cash balance','usd':dict(balance)})
        terms=doc.xpath('//div[contains(concat(" ",normalize-space(@class)," ")," contract-flow ")]')
        if len(terms)!=6:failures.append({'lang':lang,'problem':'qualitative contract flow coverage'})
        if any(t.xpath('.//*[@data-v]') for t in terms):failures.append({'lang':lang,'problem':'invented amount for qualitative deposit/reserve flow'})
        reports.append({'language':lang,'model_curves':len(model_paths),'model_annual_points':len(model_paths)*11,'max_model_svg_coordinate_error_px':max_error,'cash_flow_diagrams':len(maps),'cash_flow_edges':len(nodes),'lessor_balance_usd':dict(balance),'qualitative_contract_flows':len(terms)})
    return {'reports':reports,'asset_npv_usd':asset_npv,'lender_npv_usd':loan_npv,'equity_npv_usd':equity_npv,
            'unchanged_53_check_cash_input':same_cash_input,'prior_financial_audit':'lease_economics_0056.json',
            'manual_semantics':['Ten-year loan maturity and fifteen-year scheduled amortization are explicitly distinguished.','Resale amounts come after the ordinary payment in month 120, so principal is not deducted twice.','Debt repayment and equity cash are not labelled net accounting profit.','Deposits, maintenance reserve payments, reimbursements and return-condition compensation are qualitative and contract-dependent.','All displayed lease-model ages match the actual production classification.','Model purchase price is absent; CPI-adjusted rent is not a historical prediction.']},failures


if __name__=='__main__':main()
