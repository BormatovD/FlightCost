#!/usr/bin/env python3
"""Independent final multilingual audit of the new supply/birthplace section."""
from collections import Counter
import copy
import gzip
import hashlib
import json
from pathlib import Path

from lxml import html

HERE=Path(__file__).resolve().parent
OUT=HERE.parent/"out"


def read(path):
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix==".gz" else path.read_bytes())


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def plain(node):
    node=copy.deepcopy(node)
    for sup in node.xpath('.//sup'):sup.getparent().remove(sup)
    return " ".join(node.text_content().split())


def fmt(value,lang,digits=0):
    result=f"{value:,.{digits}f}"
    if lang=="ru":result=result.replace(","," ").replace(".",",")
    elif lang=="de":result=result.replace(",","\x01").replace(".",",").replace("\x01",".")
    return result


def main():
    supply=read(OUT/"supply_summary.json")
    migrant=read(OUT/"migrant_stock_summary.json")
    migrant_panel=read(OUT/"migrant_stock.json.gz")
    failures=[]; checks=[]
    expected_pairs={"EDDF-LEBL","EDDL-LEPA","EDDF-LIMC","EDDF-VIDP","EHAM-LFRN"}
    prior=read(HERE/"demand_collection_0056.json")
    retained={"collection_summary":sha(OUT/"collection_summary.json")==prior["summary_sha256"],
              "data_inventory":sha(OUT/"data_inventory.json")==prior["inventory_sha256"]}
    if not all(retained.values()):failures.append({"problem":"prior collected-data digest changed","retained":retained})
    for filename,data in (("supply_0056_v2.json",supply),("migrant_stock_0056_v2.json",migrant)):
        audit=read(HERE/filename)
        expected_sha=sha(OUT/("supply_summary.json" if filename.startswith("supply") else "migrant_stock_summary.json"))
        if audit.get("summary_sha256")!=expected_sha or audit.get("failures"):
            failures.append({"problem":"new source-data audit stale or failed","file":filename})
    for lang,name in (("ru","report.html"),("en","report.en.html"),("de","report.de.html")):
        path=HERE.parent/name;doc=html.fromstring(path.read_text())
        ids=doc.xpath('//*[@id]/@id')
        duplicates=[k for k,v in Counter(ids).items() if v>1]
        broken=[h for h in doc.xpath('//a[starts-with(@href,"#")]/@href') if h[1:] not in ids]
        if duplicates or broken:failures.append({"lang":lang,"problem":"internal anchors","duplicate_ids":duplicates,"broken":broken})
        nodes=doc.xpath('//*[@id="supply-collected"]')
        if len(nodes)!=1:
            failures.append({"lang":lang,"problem":"new collection section absent"});continue
        section=[]
        for item in nodes[0].itersiblings():
            if item.tag=='h2':break
            section.append(plain(item))
        text=" ".join(section)
        for value in (sum(supply['series'].values()),supply['pairs'],supply['pair_months_any_measure'],
                      supply['pair_months_matched_triplet'],supply['overlap_with_pas_crd_panel']['pairs_with_both_datasets'],
                      supply['quality']['no_complete_common_reporter'],supply['quality']['reporter_disagreement_above_10pct'],
                      supply['quality']['passengers_exceed_available_seats'],sum(r.get('checked_values',0) for r in supply['primary_comparisons'])):
            if fmt(value,lang) not in text:failures.append({"lang":lang,"problem":"new coverage number missing or incorrect","expected":value})
        for code in ('PAS_BRD','PAS_CRD','ST_PAS','CAF_PAS'):
            if code not in text:failures.append({"lang":lang,"problem":"measure distinction absent","code":code})
        def cited_urls(row):
            links=[]
            for href in row.xpath('.//sup//a/@href'):
                if href.startswith('#'):
                    sources=doc.xpath('//*[@id="'+href[1:]+'"]')
                    if sources:links.extend(sources[0].xpath('.//a/@href'))
            return set(links)
        supply_rows=doc.xpath('//table[@id="supply-diagnostics"]//tr[@data-pair]')
        if {r.get('data-pair') for r in supply_rows}!=expected_pairs or len(supply_rows)!=5:failures.append({"lang":lang,"problem":"five diagnostic pairs absent or duplicated"})
        route_values={}
        for row in supply_rows:
            pair=row.get('data-pair'); annual=supply['diagnostic_annual'][pair]['2024']
            actual=[plain(cell) for cell in row.findall('td')]
            if len(actual)!=5:
                failures.append({"lang":lang,"problem":"supply table columns","pair":pair});continue
            expected=[fmt(annual['seats'],lang,0 if float(annual['seats']).is_integer() else 1),
                      fmt(annual['flights'],lang,0 if float(annual['flights']).is_integer() else 1),
                      fmt(100*annual['seat_load_factor'],lang,1)+'%',fmt(annual['seats_per_flight'],lang,1)]
            if actual[1:]!=expected:failures.append({"lang":lang,"problem":"supply example numeric result","pair":pair,"actual":actual[1:],"expected":expected})
            required_urls={s['url'] for s in supply['primary_comparisons'] if s.get('pair')==pair and s.get('status')=='matched_primary'}
            if not required_urls.issubset(cited_urls(row)):failures.append({"lang":lang,"problem":"pair primary references missing","pair":pair})
            route_values[pair]=expected
        migrant_rows=doc.xpath('//table[@id="migrant-coverage"]//tr[@data-residence]')
        if {r.get('data-residence') for r in migrant_rows}!=set(migrant['reporters']) or len(migrant_rows)!=5:failures.append({"lang":lang,"problem":"five residence countries absent or duplicated"})
        migrant_values={}
        for row in migrant_rows:
            cc=row.get('data-residence');stats=migrant['reporters'][cc]
            actual=[plain(cell) for cell in row.findall('td')]
            if stats['bilateral_country_input_available']:
                expected=[fmt(stats['annual_coverage'][-1]['cross_border_origins_numeric'],lang),fmt(stats['cross_border_country_pairs']['series_with_all_21_numeric_values'],lang)]
            else:expected=[{'ru':'Нет детализации','en':'No country detail','de':'Keine Länderdetails'}[lang],'—']
            if actual[1:]!=expected:failures.append({"lang":lang,"problem":"migrant foreign-origin coverage","residence":cc,"actual":actual[1:],"expected":expected})
            required=migrant_panel['meta']['sources']['eurostat-migr-pop3ctb-'+cc.lower()]['url']
            if required not in cited_urls(row):failures.append({"lang":lang,"problem":"residence primary source absent","residence":cc})
            migrant_values[cc]=expected
        checks.append({'language':lang,'file':name,'sha256':sha(path),'diagnostic_pair_values':route_values,'foreign_birth_origin_coverage':migrant_values,'broken_internal_links':broken,'new_section_present':True})
    result={'stage':'0056-v2','status':'pass' if not failures else 'fail','independent':True,
            'scope':'Final RU/EN/DE supply and birthplace tables, coverage counts and citations; static content verification, not a browser layout claim.',
            'source_summary_digests':{'supply':sha(OUT/'supply_summary.json'),'migrant':sha(OUT/'migrant_stock_summary.json')},
            'retained_prior_data_audit':retained,'checks':checks,'failures':failures,
            'manual_semantic_review':['Supply examples use both directions and all airlines; averaged reporter totals can be fractional, as stated.','Every 2024 example requires twelve matched months; ratios use sums, and no PAS_CRD/seat ratio is called occupancy.','Market growth, changed capacity, aircraft gauge and causal demand remain distinct. Average seats per flight does not identify an aircraft type.','The migrant table counts foreign birth-country/territory categories with data, not persons; own-country births are excluded.','DE lack of individual-origin coverage is labelled missing detail, not zero migrants. FR/ES changing detail remains explicit.','Neither the country stock nor high realized occupancy is represented as a fitted diaspora effect, hidden demand or airline market share.','The next comparison uses the same time splits and past-only baselines. Future observed capacity is not permitted as information available at the forecast origin.','Future Aena/CAA/BTS source work is a collection queue, not a claim of downloaded or validated new data.'],
            'limitations':['The five-country archive ends in 2024; an observed 2026 route anchor remains unresolved.','The added section does not deliver fitted 3/5/10-year forecasts or aircraft recommendations.','Historical publication vintages, fares, competitors, complete connecting journeys and city allocation remain separate work.']}
    (HERE/'review_0056_v2.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(result['status'],json.dumps(failures,ensure_ascii=False))


if __name__=='__main__':main()
