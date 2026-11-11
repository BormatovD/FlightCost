#!/usr/bin/env python3
"""Scoped HTML audit of the 0057 demand-results presentation.

Checks source-data bindings, scenarios, cohorts, SVG bars and local references.
No builder imports, live-network verification or browser-rendering claims.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re

from lxml import html

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
OUT = HERE / "out"
CHECKS = Counter()
FAILURES = []


def read(name):
    return json.loads((OUT / name).read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(label, actual, expected, tolerance=None):
    CHECKS[label.split('/')[0]] += 1
    if tolerance is None:
        ok = actual == expected
    else:
        ok = math.isclose(float(actual),float(expected),abs_tol=tolerance,rel_tol=2e-10)
    if not ok:
        FAILURES.append({"check":label,"actual":actual,"expected":expected})


def cls(name):
    return f'contains(concat(" ",normalize-space(@class)," ")," {name} ")'


def text(node):
    return ''.join(node.itertext())


def plain(node):
    copied=deepcopy(node)
    for child in copied.xpath('.//sup['+cls('cite')+']'):
        child.drop_tree()
    return text(copied)


def number(value,lang):
    value=value.replace('\u00a0','').replace('\u202f','').replace(' ','').replace('−','-')
    value=value.replace('%','').replace('×','')
    if value=='—':
        return None
    if lang=='en':
        return float(value.replace(',',''))
    if lang=='de':
        value=value.replace('.','')
    return float(value.replace(',','.'))


def numbers(value,lang):
    return [number(x,lang) for x in re.findall(r'[+−-]?\d+(?:[.,\u00a0\u202f]\d+)*',value)]


def table_rows(doc,ident):
    return doc.get_element_by_id(ident).xpath('./tbody/tr')


def source_urls(node,doc):
    result=[]
    for a in node.xpath('.//sup['+cls('cite')+']//a'):
        target=doc.get_element_by_id(a.get('href')[1:])
        result.extend(target.xpath('./a/@href'))
    return result


def audit(path,lang,benchmark,evolution,evidence,copy):
    doc=html.fromstring(path.read_bytes());tag='html_'+lang
    check(tag+'/language',doc.get('lang'),lang)
    ids=doc.xpath('//*[@id]/@id')
    check(tag+'/ids_unique',len(ids),len(set(ids)))
    unresolved=[a.get('href') for a in doc.xpath('//a[starts-with(@href,"#")]') if a.get('href')[1:] not in set(ids)]
    check(tag+'/local_links_resolved',unresolved,[])
    for node in doc.xpath('//*[@aria-labelledby]'):
        for ident in node.get('aria-labelledby').split():
            check(tag+'/aria_target',ident in ids,True)
    source_nodes=doc.xpath('//ol['+cls('src')+']/li')
    for node in source_nodes:
        targets=node.xpath('./a/@href')
        check(tag+'/source_has_url',len(targets),1)
        check(tag+'/source_url_scheme',targets[0].startswith(('https://','http://')),True)

    section=doc.get_element_by_id('demand-model-results')
    check(tag+'/new_results_visible',len(section.xpath('ancestor::details')),0)
    tested={r['horizon_years_from_decision']:r for r in benchmark['experiments'] if r['availability_lag_years']==1}
    rows=table_rows(doc,'demand-temporal-benchmark')
    check(tag+'/benchmark_rows',len(rows),3)
    check(tag+'/benchmark_horizons',{int(r.get('data-horizon')) for r in rows},{3,5,10})
    for row in rows:
        h=int(row.get('data-horizon'));reference=tested[h]
        cells=[text(c) for c in row.xpath('./td')]
        check(tag+'/benchmark_lag',row.get('data-availability-lag'),'1')
        check(tag+'/horizon_cell',number(cells[0],lang),h)
        check(tag+'/scored_eligible',[number(x,lang) for x in cells[1].split('/')],
              [reference['scored_cases'],reference['eligible_origin_pair_cases']])
        for cell,model in zip(cells[2:],('last_year','damped_log_trend','log_trend')):
            check(tag+'/wape/'+str(h)+'/'+model,number(cell,lang),reference['metrics']['all'][model]['wape']*100,.050001)
    uncertainty=table_rows(doc,'demand-benchmark-uncertainty')
    for row in uncertainty:
        cells=[text(c) for c in row.xpath('./td')]
        h=int(number(cells[0],lang));m=tested[h]['metrics']['all']['last_year']
        expected=[m['mae_passengers'],m['signed_bias']*100,m['median_error_factor_positive'],
                  m['empirical_80pct_interval']['coverage'],m['empirical_80pct_interval']['n']]
        expected[3]=expected[3]*100 if expected[3] is not None else None
        for cell,value,tol in zip(cells[1:],expected,[.50001,.050001,.005001,.050001,0]):
            actual=number(cell,lang)
            check(tag+'/uncertainty_cell',actual,value,None if value is None else tol)

    aggregates={}
    for period in evolution['periods']:
        aggregates.update(period['aggregates'])
    years_table=doc.get_element_by_id('demand-same-cohort-years')
    check(tag+'/annual_year_headers',years_table.xpath('./thead/tr/th/text()')[1:],['2015','2019','2024'])
    annual_rows=table_rows(doc,'demand-same-cohort-years')
    check(tag+'/annual_rows',len(annual_rows),4)
    for row,(key,divisor,tolerance) in zip(annual_rows,[('passengers',1e6,.050001),('flights',1e6,.0005001),
                                                   ('seats_per_flight',1,.050001),('load_factor',.01,.050001)]):
        cells=row.xpath('./td')[1:]
        for cell,year in zip(cells,('2015','2019','2024')):
            check(tag+'/annual/'+year+'/'+key,number(text(cell),lang),aggregates[year][key]/divisor,tolerance)

    svg=doc.get_element_by_id('route-capacity-change-0057')
    bars=svg.xpath('.//rect[@data-metric]')
    check(tag+'/bar_count',len(bars),8)
    bins=svg.xpath('./g[@data-distance-group]')
    group_data={g['group']:next(p for p in g['periods'] if p['start']==2019 and p['end']==2024)
                for g in evolution['by_distance']}
    check(tag+'/distance_groups',{g.get('data-distance-group') for g in bins},set(group_data))
    check(tag+'/distance_cohort_count',sum(int(g.get('data-pairs')) for g in bins),evolution['main_pairs_with_coordinates'])
    ticks=sorted((number(text(t),lang),float(t.get('x'))) for t in svg.xpath('./text[@text-anchor="middle"]'))
    (v0,x0),(v1,x1)=ticks[0],ticks[-1]
    X=lambda value:x0+(value-v0)*(x1-x0)/(v1-v0)
    for group in bins:
        ref=group_data[group.get('data-distance-group')]
        check(tag+'/group_size',int(group.get('data-pairs')),ref['pairs'])
        local=group.xpath('./rect[@data-metric]')
        check(tag+'/two_bars_per_group',{bar.get('data-metric') for bar in local},{'flights','seats_per_flight'})
        shown=group.xpath('./text['+cls('evolution-value')+']')
        for bar,label in zip(local,shown):
            metric=bar.get('data-metric');value=ref['aggregate_decomposition']['factor_change_fraction'][metric]
            check(tag+'/bar_data',bar.get('data-change-fraction'),value,1e-11)
            check(tag+'/bar_label',number(text(label),lang),value*100,.050001)
            check(tag+'/bar_origin',bar.get('x'),min(X(0),X(value*100)),.012)
            check(tag+'/bar_width',bar.get('width'),abs(X(value*100)-X(0)),.012)
            check(tag+'/bar_side_label',label.get('text-anchor'),'end' if value<0 else 'start')
            check(tag+'/bar_and_label_colour',bar.get('fill'),label.get('fill'))
    caption=svg.xpath('ancestor::figure/figcaption')[0]
    caption_numbers=numbers(plain(caption),lang)
    check(tag+'/chart_caption_years',caption_numbers[:2],[2019,2024])
    check(tag+'/chart_caption_cohort',caption_numbers[2:4],[evolution['main_pairs_with_coordinates'],evolution['main_pairs']])

    example_lookup={r['pair']:r for r in evolution['examples'] if '2019' in r.get('years',{}) and '2024' in r.get('years',{})}
    examples=table_rows(doc,'demand-evolution-examples')
    check(tag+'/example_count',len(examples),len(example_lookup))
    for row in examples:
        ref=example_lookup[row.get('data-pair')];cells=row.xpath('./td')
        main=ref['in_main_balanced_cohort']
        check(tag+'/example_cohort_attribute',row.get('data-main-cohort'),str(main).lower())
        label={'ru':('Основная когорта','Отдельно: 2019/2024'),
               'en':('Main cohort','Separate: 2019/2024'),
               'de':('Hauptkohorte','Separat: 2019/2024')}[lang][0 if main else 1]
        check(tag+'/example_cohort_label',text(cells[4]),label)
        capacities=numbers(text(cells[1]),lang)
        for value,year in zip(capacities,('2019','2024')):
            check(tag+'/example_capacity',value,ref['years'][year]['seats_per_flight'],.050001)
        decomposition=ref['decomposition']['2019_2024']
        check(tag+'/example_flights',number(text(cells[2]),lang),decomposition['factor_change_fraction']['flights']*100,.050001)
        check(tag+'/example_passengers',number(text(cells[3]),lang),decomposition['passenger_change_fraction']*100,.050001)
        check(tag+'/example_cited',len(source_urls(cells[0],doc))>0,True)

    source_map={s['id']:s['url'] for s in evidence['sources']}
    archetypes=table_rows(doc,'route-archetypes')
    check(tag+'/archetype_count',len(archetypes),4)
    check(tag+'/archetype_headers',doc.get_element_by_id('route-archetypes').xpath('./thead/tr/th/text()'),copy['archetype_columns'][lang])
    for row,ref in zip(archetypes,copy['archetypes']):
        cells=row.xpath('./td')
        check(tag+'/archetype_text',[plain(cell) for cell in cells],ref[lang])
        check(tag+'/archetype_citations',set(source_urls(cells[2],doc)),{source_map[s] for s in ref['sources']})
    paragraphs=doc.xpath('//p')
    for expected in copy['paragraphs']:
        matching=[p for p in paragraphs if plain(p)==expected[lang]]
        check(tag+'/aircraft_evidence_paragraph_present',len(matching),1)
        if matching:
            check(tag+'/aircraft_evidence_citations',set(source_urls(matching[0],doc)),{source_map[s] for s in expected['sources']})

    frequency=table_rows(doc,'frequency-scenarios')
    check(tag+'/frequency_row_count',len(frequency),3)
    for row,seats in zip(frequency,(145,182,220)):
        cells=[text(c) for c in row.xpath('./td')]
        check(tag+'/frequency_seats',number(cells[0],lang),seats)
        check(tag+'/frequency_arithmetic',number(cells[1],lang),100000/(2*52*seats*.82),.050001)
    scenario=doc.get_element_by_id('frequency-scenarios').xpath('ancestor::div['+cls('aircraft-scenario')+']')[0]
    scenario_intro=plain(scenario.xpath('./p')[0])
    check(tag+'/scenario_inputs',numbers(scenario_intro,lang)[:2],[100000,82])
    check(tag+'/scenario_assumption_label',scenario_intro.startswith({'ru':'Условный пример:','en':'Illustration:','de':'Rechenbeispiel:'}[lang]),True)
    check(tag+'/scenario_assumption_colour','var(--guess)' in scenario.get('style',''),True)
    formula=[p for p in doc.xpath('//p['+cls('formula')+']') if 'P' in text(p) and '104 × S × LF' in text(p)]
    check(tag+'/frequency_formula_present',len(formula),1)
    check(tag+'/frequency_both_directions','2 × 52' in text(formula[0]),True)

    archive=[d for d in doc.xpath('//details') if d.xpath('./summary') and '0056-v2' in text(d.xpath('./summary')[0])]
    check(tag+'/one_old_collection_archive',len(archive),1)
    check(tag+'/old_archive_closed',archive[0].get('open'),None)
    for ident in ('supply-diagnostics','migrant-coverage'):
        check(tag+'/archived_'+ident,doc.get_element_by_id(ident) in archive[0].iterdescendants(),True)
    check(tag+'/new_benchmark_not_archived',doc.get_element_by_id('demand-temporal-benchmark') in archive[0].iterdescendants(),False)
    return {'language':lang,'benchmark_rows':3,'supply_years':[2015,2019,2024],'chart_bars':8,
            'main_supply_cohort':evolution['main_pairs'],'geocoded_chart_cohort':evolution['main_pairs_with_coordinates'],
            'examples':len(examples),'archetypes':4,'frequency_scenarios':3,
            'source_entries':len(source_nodes),'unresolved_internal_links':len(unresolved)}


def main():
    benchmark=read('forecast_benchmark.json');evolution=read('route_evolution.json')
    evidence=read('route_aircraft_evidence.json');copy=read('route_aircraft_copy.json')
    model_audit=json.loads((HERE/'verify/modelling_0057.json').read_text())
    check('upstream/model_audit_status',model_audit['status'],'pass_with_limitations')
    for relative,expected in model_audit['inputs_sha256'].items():
        check('upstream/reviewed_artifact_unchanged/'+relative,sha(HERE/relative),expected)
    files=[];reports=[]
    for lang in ('ru','en','de'):
        path=HERE/('report.html' if lang=='ru' else f'report.{lang}.html')
        files.append(path);reports.append(audit(path,lang,benchmark,evolution,evidence,copy))
    inputs=files+[HERE/'modelling_update.py',HERE/'aircraft_demand_section.py',HERE/'build_report.py',
                 OUT/'forecast_benchmark.json',OUT/'route_evolution.json',OUT/'route_aircraft_evidence.json',OUT/'route_aircraft_copy.json']
    result={'checked_on':'2026-11-11','status':'fail' if FAILURES else 'pass_with_limitations',
            'scope':'Independent scoped HTML/data-binding audit, using already independently audited numerical outputs.',
            'checks':dict(CHECKS),'checks_total':sum(CHECKS.values()),'failure_count':len(FAILURES),'failures':FAILURES[:80],
            'reports':reports,'inputs_sha256':{str(p.relative_to(ROOT)):sha(p) for p in inputs},
            'limitations':['No browser interaction or pixel/font-layout validation is claimed.',
                           'Source checks resolve citations to the intended bibliography URLs; they do not refetch external pages.',
                           'The flight-frequency example is explicitly assumed arithmetic, not a fitted forecast or type recommendation.',
                           'Forecast and supply limitations remain those of modelling_0057.json: latest-vintage history, observable-target selection and a retrospective balanced supply cohort.']}
    (Path(__file__).parent/'report_0057.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=lambda x:sorted(x))+'\n')
    print(result['status'],result['checks_total'],'checks;',len(FAILURES),'failures')
    if FAILURES:
        print(json.dumps(FAILURES[:12],ensure_ascii=False,default=lambda x:sorted(x),indent=2))
        raise SystemExit(1)


if __name__=='__main__':
    main()
