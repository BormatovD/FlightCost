#!/usr/bin/env python3
"""0064-E: offline quality audit of normalized IATI evidence.

No HTTP, model, API key or production DB. Produces review *candidates*;
never infers physical facilities, adds financial types/currencies, or assigns airports.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
import os
import tempfile
import io
import csv
import json
from pathlib import Path

# Watchlists are for review ranking only; absence never discards source evidence.
AIR_TOURISM = frozenset({'21050', '33210', '33220'})  # airport; tourism-related sectors (leads only)
NETWORK = frozenset({'21011', '21012', '21020', '21023', '21030', '21040', '21061'})
INDUSTRY = frozenset({'23220', '23230', '23231', '23630', '32110', '32120'})


def load_candidates(path: Path) -> list[dict]:
    out=[]
    with path.open('rt', encoding='utf-8') as fh:
        for line_number,line in enumerate(fh, 1):
            if not line.strip():
                continue
            item=json.loads(line)
            if not isinstance(item,dict) or not item.get('iati_identifier'):
                raise ValueError(f'{path}:{line_number}: no IATI identifier')
            out.append(item)
    return out


def dates_of(row: dict) -> dict[str, str]:
    return {str(d['type_code']): str(d['date']) for d in row.get('activity_dates') or []
            if d.get('type_code') and d.get('date')}


def point_of(loc: dict):
    p=loc.get('coordinates') or {}
    if not isinstance(p,dict) or p.get('lat') is None or p.get('lon') is None:
        return None
    return (float(p['lat']),float(p['lon']))


def available_sectors(row):
    return sorted({str(s.get('code')) for s in row.get('sectors') or []
                   if str(s.get('vocabulary')) == '1' and s.get('code')})


def groups_from_relations(rows: list[dict], rels: list[dict]):
    ids={r['iati_identifier'] for r in rows}
    par={i:i for i in ids}
    def find(i):
        while par[i]!=i:
            par[i]=par[par[i]]
            i=par[i]
        return i
    def union(a,b):
        a,b=find(a),find(b)
        if a!=b:
            par[max(a,b)] = min(a,b)
    recognized=[]
    external=[]
    for rel in rels:
        a,b=str(rel.get('source_id') or ''),str(rel.get('target_id') or '')
        if not a or not b:continue
        if str(rel.get('type_code')) not in {'1','2'}:
            continue # other relationships are NOT evidence of project identity
        if a not in ids or b not in ids:
            external.append((a,b))
            continue
        union(a,b)
        recognized.append((a,b))
    by=defaultdict(set)
    for i in ids:
        by[find(i)].add(i)
    id_to_group={i: min(group) for group in by.values() for i in group}
    group_to_ids={min(group): sorted(group) for group in by.values()}
    return id_to_group,group_to_ids,recognized,external


def audit(rows: list[dict], rels: list[dict], *, as_of: str):
    date.fromisoformat(as_of)
    dups=Counter(r['iati_identifier'] for r in rows)
    ids_to_family,families,used_rel,ext_rel=groups_from_relations(rows,rels)
    per_ds=defaultdict(list)
    coord_activities=defaultdict(set)
    for row in rows:
        ds=row['dataset_name']
        per_ds[ds].append(row)
        for loc in row.get('locations') or []:
            p=point_of(loc)
            if p is not None:
                coord_activities[(ds,*p)].add(row['iati_identifier'])
    activity_rows=[]
    location_rows=[]
    all_loc=[]
    for r in rows:
        dates=dates_of(r)
        locs=r.get('locations') or []
        sector=available_sectors(r)
        status=str(r.get('status_code') or '')
        act_end=dates.get('4')
        planned_end=dates.get('3')
        future_actual=bool(act_end and act_end>as_of)
        overdue=bool(status=='2' and planned_end and planned_end<as_of)
        future_plan=bool(status in ('1','2') and planned_end and '2027' <= planned_end[:4] <= '2036')
        unique_coords=len({point_of(l) for l in locs if point_of(l) is not None})
        shared_coords=sum(bool(point_of(l) and len(coord_activities[(r['dataset_name'],*point_of(l))])>1) for l in locs)
        class_values={str(l.get('location_class_code')) for l in locs}
        site_claims=sum(l.get('location_class_code')=='3' and point_of(l) is not None for l in locs)
        # A claimed structure is not a VERIFIED site. Requires external inspection.
        if not locs: geo='unknown'
        elif '3' in class_values:geo='structure_claim_unverified'
        elif any(l.get('location_class_code') in ('1','2','4') for l in locs): geo='settlement_or_region'
        else:geo='unclassified_coordinates'
        if future_plan and AIR_TOURISM.intersection(sector):priority='P1_air_tourism'
        elif future_plan and NETWORK.intersection(sector):priority='P2_network'
        elif future_plan and INDUSTRY.intersection(sector):priority='P3_industry'
        elif future_plan:priority='P4_context'
        else:priority='historical_or_other'
        tx=Counter(str(t.get('kind') or 'unknown') for t in r.get('transactions') or [])
        flags=[]
        if future_actual:flags.append('future_actual_end')
        if overdue:flags.append('active_after_planned_end')
        if shared_coords:flags.append('coordinate_shared_between_activities')
        if not locs:flags.append('no_location')
        if site_claims==0:flags.append('no_structure_site_claim')
        if dups[r['iati_identifier']]>1 or r.get('identifier_conflict'):flags.append('duplicate_identifier_variants')
        if len(families[ids_to_family[r['iati_identifier']]])>1:flags.append('has_parent_child_links')
        if r.get('historically_available_before_snapshot') != 'verified':flags.append('historical_availability_unverified')
        activity_rows.append({
            'dataset':r['dataset_name'],'iati_identifier':r['iati_identifier'],
            'family_key':ids_to_family[r['iati_identifier']],
            'family_ids':len(families[ids_to_family[r['iati_identifier']]]),
            'title':r.get('title') or '', 'status_code':status,
            'planned_end':planned_end or '', 'actual_end':act_end or '',
            'future_plan_2027_2036':int(future_plan),'priority':priority,
            'sector_dac_codes':';'.join(sector),'locations':len(locs),
            'unique_coordinates_in_activity':unique_coords, 'coordinate_reuses':shared_coords,
            'site_claims_unverified':site_claims,'geo_quality':geo,
            'tx_commitments':tx['commitment'],'tx_disbursements':tx['disbursement'],
            'tx_expenditure':tx['expenditure'],
            'tx_interest_payments':tx['interest_payment'],
            'tx_loan_repayments':tx['loan_repayment'],
            'budgets':len(r.get('budgets') or []),
            'financial_aggregation_allowed':0,'airport_assignment_allowed':0,
            'source_url':r.get('source_url') or '', 'flags':';'.join(flags)
        })
        for idx,loc in enumerate(locs,1):
            p=point_of(loc)
            reach=loc.get('reach_code') or ''
            cl=loc.get('location_class_code') or ''
            exact=loc.get('exactness_code') or ''
            count=len(coord_activities[(r['dataset_name'],*p)]) if p else 0
            location_rows.append({
                'dataset':r['dataset_name'],'iati_identifier':r['iati_identifier'],
                'location_index':idx,'name':loc.get('name') or '',
                'latitude':p[0] if p else '', 'longitude':p[1] if p else '',
                'class_code':cl, 'reach_code':reach, 'exactness_code':exact,
                'shared_by_activities_in_dataset':count,
                'possible_site':int(cl=='3' and reach=='1' and exact=='1'),
                'site_verified':0,
                'location_ids':json.dumps(loc.get('location_ids') or [],ensure_ascii=False),
                'administrative_ids':json.dumps(loc.get('administrative_ids') or [],ensure_ascii=False),
                'review_note':'Location-class 3 + reach 1 + exactness 1 is only a claim, not verification' if cl=='3' else
                              'Coordinates are evidence of region/settlement, NOT a confirmed project site',
            })
            all_loc.append(loc)
    # Conservative family level: an explicit parent-child relationship makes
    # only a family GROUP, never an assertion of one physical investment.
    per_family=defaultdict(list)
    for row in activity_rows:per_family[row['family_key']].append(row)
    future_families=[]
    for fid,members in per_family.items():
        future=[r for r in members if r['future_plan_2027_2036']]
        if not future:continue
        representatives=sorted(future,key=lambda r:(r['iati_identifier']!=fid, r['iati_identifier']))
        r=representatives[0]
        priority=min((x['priority'] for x in future),key=lambda p:['P1_air_tourism','P2_network','P3_industry','P4_context'].index(p))
        future_families.append({
            'family_key':fid,'related_iati_ids':len(families[fid]),
            'related_ids':';'.join(families[fid]),'dataset':r['dataset'],
            'representative_title':r['title'],'planned_end':r['planned_end'],
            'priority':priority,'dac_codes':r['sector_dac_codes'],
            'geography':r['geo_quality'],'has_verified_site':0,
            'finances_aggregated':0,'review_action':
            'Identify actual facility or service-area, independent source for construction status, and project dates before airport exposure'
        })
    future_families.sort(key=lambda r:(r['priority'],r['planned_end'],r['dataset'],r['family_key']))
    total_by_ds=[]
    for ds,dd in sorted(per_ds.items()):
        locs=[l for r in dd for l in r.get('locations') or []]
        coords={(p[0],p[1]) for l in locs if (p:=point_of(l)) is not None}
        total_by_ds.append({
            'dataset':ds,'activities':len(dd),'with_location':sum(bool(r.get('locations')) for r in dd),
            'location_entries':len(locs),'distinct_coordinate_pairs':len(coords),
            'future_active_activities':sum(x['future_plan_2027_2036'] for x in activity_rows if x['dataset']==ds),
            'future_related_groups':sum(x['dataset']==ds for x in future_families)
        })
    summary={
        'observed_at':as_of,'note':'Records are IATI activities; related groups are NOT necessarily unique physical investment projects',
        'activities':len(rows),'unique_iati_ids':len(dups),'duplicate_id_variants':sum(v>1 for v in dups.values()),
        'related_links_input':len(rels),'used_parent_child_links':len(used_rel),'external_parent_child_links':len(ext_rel),
        'explicit_related_groups':len(families),'non_singleton_related_groups':sum(len(v)>1 for v in families.values()),
        'future_active_activities':sum(r['future_plan_2027_2036'] for r in activity_rows),
        'future_related_groups':len(future_families),
        'future_actual_end_count':sum('future_actual_end' in r['flags'].split(';') for r in activity_rows),
        'active_after_planned_end_count':sum('active_after_planned_end' in r['flags'].split(';') for r in activity_rows),
        'locations_total':len(location_rows),'activities_with_locations':sum(r['locations']>0 for r in activity_rows),
        'locations_by_class':dict(Counter(str(l.get('location_class_code') or 'missing') for l in all_loc)),
        'locations_by_exactness':dict(Counter(str(l.get('exactness_code') or 'missing') for l in all_loc)),
        'locations_by_reach':dict(Counter(str(l.get('reach_code') or 'missing') for l in all_loc)),
        'site_verified_count':0,
        'transactions_by_kind':dict(Counter(t.get('kind') or 'unknown' for r in rows for t in r.get('transactions') or [])),
        'transactions_by_currency':dict(Counter(t.get('currency') or 'unknown' for r in rows for t in r.get('transactions') or [])),
        'budgets_total':sum(len(r.get('budgets') or []) for r in rows),
        'budgets_by_currency':dict(Counter(b.get('currency') or 'unknown' for r in rows for b in r.get('budgets') or [])),
        'financial_aggregation_performed':False,'airport_assignment_performed':False,
        'historical_as_of_verified_count':sum(r.get('historically_available_before_snapshot') == 'verified' for r in rows),
        'by_dataset':total_by_ds
    }
    return summary,activity_rows,location_rows,future_families


def atomic_write(path: Path, data: bytes):
    if path.is_symlink():
        raise PermissionError(f'Unsafe output symlink: {path}')
    fd, name=tempfile.mkstemp(prefix='.'+path.name+'.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(name,path)
        path.chmod(0o600)
    finally:
        if os.path.exists(name):os.unlink(name)


def write_csv(path: Path, rows: list[dict]):
    if not rows:raise ValueError('empty report')
    contents=io.StringIO(newline='')
    writer=csv.DictWriter(contents, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    atomic_write(path, ('\ufeff'+contents.getvalue()).encode('utf-8'))


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidates',type=Path,required=True)
    p.add_argument('--relations',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--as-of',default='2026-11-12')
    args=p.parse_args(argv)
    if not args.candidates.is_file() or not args.relations.is_file():p.error('input files missing')
    if args.out.is_symlink():p.error('output directory symlink is forbidden')
    args.out.mkdir(parents=True,exist_ok=True,mode=0o700)
    args.out.chmod(0o700)
    rows=load_candidates(args.candidates)
    rels=json.loads(args.relations.read_text(encoding='utf-8'))
    summary,activities,locations,future=audit(rows,rels,as_of=args.as_of)
    for filename,data in [('activities_review.csv',activities),('locations_review.csv',locations),('future_related_groups.csv',future)]:
        write_csv(args.out/filename,data)
    atomic_write(args.out/'summary.json',(json.dumps(summary,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    print(json.dumps({k:summary[k] for k in ('activities','locations_total','explicit_related_groups','future_active_activities','future_related_groups','future_actual_end_count','site_verified_count')},ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
