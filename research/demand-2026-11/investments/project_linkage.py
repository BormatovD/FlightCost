#!/usr/bin/env python3
"""0064-F: offline IATI source reconciliation and *review* queue.

Evidence IDs, parent/child families and real-world investment facilities are NOT
interchangeable. No automatic physical-asset merge, financial aggregation,
location verification, airport assignment or change to production storage.

Input: normalized candidates.jsonl from 0063/0064-D and optional relations.json.
Output: immutable-looking CSV/JSON review artifacts (0600) in a private directory.
No HTTP, API key, models, external packages or timestamp-based guesses.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import date
from difflib import SequenceMatcher
import hashlib
import io
import itertools
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata

from quality_audit import AIR_TOURISM, NETWORK, INDUSTRY, available_sectors, dates_of

RELATION_KIND = {
    '1': 'parent_of_this_activity',
    '2': 'child_of_this_activity',
    '3': 'sibling',
    '4': 'co_funded',
    '5': 'third_party_report_of_activity',
}
# Stop words are only a blocking aid. They are NOT evidence of sameness.
STOP = frozenset('''the and of for to in on at with by from a an de des du la le les l d et
    un une pour projet programme program project development développement developpement
    investment investissement investments financement finance financing funding
    support soutien assistance appui phase phases component composants composante
    sector secteurs sectoriel sectorielle national nationale country etat
    infras infrastructure infrastructures republic republique morocco maroc
    tanzania tanzanie cabo verde cape verdes kenya kenyan afrique africa'''.split())


def normalize(s):
    txt = unicodedata.normalize('NFKD', str(s or '').casefold())
    txt = ''.join(c for c in txt if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9]+', ' ', txt)).strip()


def tokens(s):
    return frozenset(t for t in normalize(s).split() if len(t) >= 3 and t not in STOP)


def read_jsonl(path, origin):
    with path.open('r', encoding='utf-8') as stream:
        for n, line in enumerate(stream, 1):
            if not line.strip():
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict) or not isinstance(obj.get('iati_identifier'), str) \
                    or not obj['iati_identifier'].strip():
                raise ValueError(f'{path}:{n}: missing iati_identifier')
            # Tags only on a shallow copy: never mutate archival evidence.
            yield {**obj, '_origin': origin}


def country_set(row):
    c = {str(x.get('iso2') or '').upper() for x in row.get('recipient_countries') or []
         if isinstance(x, dict) and re.fullmatch(r'[A-Z]{2}', str(x.get('iso2') or '').upper())}
    if not c:
        c = {str(x).upper() for x in row.get('matched_query_countries') or []
             if re.fullmatch(r'[A-Z]{2}', str(x).upper())}
    return c


def planned_year(row):
    d = dates_of(row).get('3')
    return d if d else ''


def point_claims(rows):
    """Counts reported location claims, never a verified construction site."""
    claims = []
    for r in rows:
        for loc in r.get('locations') or []:
            p = loc.get('coordinates') or {}
            if not isinstance(p, dict) or p.get('lat') is None or p.get('lon') is None:
                continue
            try:
                lat, lon = float(p['lat']), float(p['lon'])
            except (TypeError, ValueError, OverflowError):
                continue
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            cl = str(loc.get('location_class_code') or '')
            reach = str(loc.get('reach_code') or '')
            exact = str(loc.get('exactness_code') or '')
            claims.append((cl, reach, exact))
    return claims


def id_index(rows):
    by = defaultdict(list)
    for r in rows:
        by[r['iati_identifier']].append(r)
    return by


def group_explicit_relations(rows, relations):
    """Parent/child connection means evidence-family, NOT one physical asset.

    A relation type 1 means source says target is its parent; type 2 means
    target is its child. Source pairs may be reciprocal; dedupe these edges.
    """
    by_id = id_index(rows)
    parent = {i: i for i in by_id}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parent[max(a, b)] = min(a, b)

    observed = set()
    for r in rows:
        for l in r.get('related_activities') or []:
            target = str(l.get('ref') or '').strip()
            code = str(l.get('type') or '')
            if target:
                observed.add((r['iati_identifier'], target, code, 'embedded'))
    for rel in relations:
        src, tgt = str(rel.get('source_id') or '').strip(), str(rel.get('target_id') or '').strip()
        code = str(rel.get('type_code') or '')
        if src and tgt:
            observed.add((src, tgt, code, 'relations_json'))

    seen_hierarchy = set()
    relations_out = []
    for src, target, code, evidence_form in sorted(observed):
        if code == '1':
            p, child = target, src
        elif code == '2':
            p, child = src, target
        else:
            p, child = '', ''
        both_present = src in by_id and target in by_id
        if p and child and both_present and p != child:
            union(p, child)
            seen_hierarchy.add((p, child))
        relations_out.append({
            'source_id': src, 'target_id': target, 'type_code': code,
            'meaning': RELATION_KIND.get(code, 'unrecognized'),
            'reported_in': evidence_form,
            'both_ids_in_inputs': int(both_present),
            'normalized_parent_id': p, 'normalized_child_id': child,
            'same_physical_asset_proven': 0,
        })
    grouped = defaultdict(list)
    for i in by_id:
        grouped[find(i)].append(i)
    family_for_id = {}
    families = {}
    for ids in grouped.values():
        key = min(ids)
        families[key] = sorted(ids)
        for i in ids:
            family_for_id[i] = key
    return family_for_id, families, relations_out, seen_hierarchy


def identity_rows(by_id):
    out = []
    for ident, evidence in sorted(by_id.items()):
        titles = {normalize(r.get('title')) for r in evidence if r.get('title')}
        statuses = {str(r.get('status_code')) for r in evidence if r.get('status_code')}
        plans = {planned_year(r) for r in evidence if planned_year(r)}
        countries = set().union(*(country_set(r) for r in evidence))
        origin_counts = Counter(r['_origin'] for r in evidence)
        datasets = {r.get('dataset_name') or 'unlabeled' for r in evidence}
        out.append({
            'iati_identifier': ident, 'source_records': len(evidence),
            'seen_in_bulk': int(origin_counts['bulk'] > 0),
            'seen_in_datastore': int(origin_counts['datastore'] > 0),
            'bulk_records': origin_counts['bulk'],
            'datastore_records': origin_counts['datastore'],
            'datasets': ';'.join(sorted(datasets)),
            'recipient_countries': ';'.join(sorted(countries)),
            'distinct_titles': len(titles),
            'distinct_statuses': len(statuses),
            'distinct_planned_ends': len(plans),
            'reported_identifier_conflict': int(any(r.get('identifier_conflict') for r in evidence)),
            'needs_source_reconciliation': int(len(statuses)>1 or len(plans)>1 or len(titles)>1 or
                                                any(r.get('identifier_conflict') for r in evidence)),
            'independent_investment_project_proven': 0,
        })
    return out


def family_rows(by_id, families, *, as_of):
    result = []
    for family, ids in sorted(families.items()):
        evidence = [r for i in ids for r in by_id[i]]
        future = [r for r in evidence if str(r.get('status_code')) in ('1','2')
                  and '2027' <= planned_year(r)[:4] <= '2036']
        sectors = set().union(*(set(available_sectors(r)) for r in evidence))
        if sectors & AIR_TOURISM: priority = 'P1_air_tourism'
        elif sectors & NETWORK: priority = 'P2_network'
        elif sectors & INDUSTRY: priority = 'P3_industry'
        else: priority = 'P4_context'
        primary = sorted(future or evidence,
                         key=lambda r: (r['iati_identifier'] != family,
                                        r.get('dataset_name') or '', r.get('title') or ''))[0]
        locs = point_claims(evidence)
        site_claims = sum(cl == '3' and reach == '1' and exact == '1'
                          for cl, reach, exact in locs)
        statuses = {str(r.get('status_code')) for r in evidence if r.get('status_code')}
        plans = {planned_year(r) for r in evidence if planned_year(r)}
        future_plans = sorted(planned_year(r) for r in future if planned_year(r))
        countries = set().union(*(country_set(r) for r in evidence))
        result.append({
            'family_key': family,
            'iati_ids': ';'.join(ids),
            'activity_ids': len(ids),
            'evidence_records': len(evidence),
            'source_datasets': ';'.join(sorted({r.get('dataset_name') or 'unlabeled' for r in evidence})),
            'recipient_countries': ';'.join(sorted(countries)),
            'representative_title': primary.get('title') or '',
            'priority': priority,
            'future_active_evidence': int(bool(future)),
            'earliest_future_planned_end': min(future_plans) if future_plans else '',
            'different_reported_statuses': int(len(statuses)>1),
            'different_reported_planned_ends': int(len(plans)>1),
            'geographic_points_reported': len(locs),
            'structure_site_claims_unverified': site_claims,
            'verified_site': 0,
            'is_single_physical_asset_proven': 0,
            'finances_aggregated': 0,
            'airports_assigned': 0,
            'historical_publication_verified': 0,
            'review_action': 'Verify scope (single facility vs programme), site, commissioning stage and publication date',
        })
    result.sort(key=lambda r: (not r['future_active_evidence'],r['priority'],r['earliest_future_planned_end'],r['family_key']))
    return result


def title_suggestions(by_id, family_for_id, *, max_pairs=100000):
    """Cross-*dataset* suggestions only. Same-title annual grants must not merge.

    Pairs are blocked on recipient country + rare substantive title tokens.
    A match is an invitation to inspect, not evidence of asset identity.
    """
    summaries = {}
    for ident, evs in by_id.items():
        titles = [r.get('title') or '' for r in evs]
        title = sorted(titles, key=lambda t: (-len(tokens(t)),len(t),t))[0] if titles else ''
        c = set().union(*(country_set(r) for r in evs))
        sec = set().union(*(set(available_sectors(r)) for r in evs))
        datasets = {r.get('dataset_name') for r in evs if r.get('dataset_name')}
        publishers = {r.get('reporting_org') for r in evs if r.get('reporting_org')}
        summaries[ident] = (title,tokens(title),c,sec,datasets,publishers)
    index = defaultdict(set)
    for ident, (_, tok, countries, _, _, _) in summaries.items():
        for country in countries:
            for term in tok:
                index[(country,term)].add(ident)
    pairs = set()
    for index_key, candidates in sorted(index.items()):
        if len(candidates) > 80:
            continue    # country + ubiquitous token is not a useful block
        for a,b in itertools.combinations(sorted(candidates), 2):
            if family_for_id[a] == family_for_id[b]:
                continue
            if summaries[a][4] & summaries[b][4]:
                continue    # same dataset: title repetition is often annual allocations
            pairs.add((a,b))
            if len(pairs) > max_pairs:
                raise ValueError('too many title candidates; narrow the dataset/period before review')
    proposals = []
    for a,b in sorted(pairs):
        title_a,tok_a,c_a,sec_a,ds_a,pub_a = summaries[a]
        title_b,tok_b,c_b,sec_b,ds_b,pub_b = summaries[b]
        shared = tok_a & tok_b
        if len(shared) < 2 or not c_a & c_b:
            continue
        if sec_a and sec_b and not sec_a & sec_b:
            continue
        overlap = 2 * len(shared) / (len(tok_a)+len(tok_b))
        lex = SequenceMatcher(None, normalize(title_a), normalize(title_b)).ratio()
        if max(overlap,lex) < 0.77 or overlap < 0.55:
            continue
        pair_id = hashlib.sha256((a+'\x1f'+b).encode()).hexdigest()[:16]
        same_publisher = bool(pub_a & pub_b)
        # Even a perfect text match can be two funding tranches, phases or
        # repeated annual programmes; it is NEVER an automated merge.
        link_type = ('same_publisher_repeat_or_component' if same_publisher else
                     'cross_publisher_shared_scope')
        proposals.append({
            'pair_id':pair_id,
            'iati_id_a':a,'iati_id_b':b,
            'family_key_a':family_for_id[a],'family_key_b':family_for_id[b],
            'title_a':title_a, 'title_b':title_b,
            'datasets_a':';'.join(sorted(ds_a)),'datasets_b':';'.join(sorted(ds_b)),
            'reporting_org_a':';'.join(sorted(pub_a)),'reporting_org_b':';'.join(sorted(pub_b)),
            'link_type': link_type,
            'countries_overlap':';'.join(sorted(c_a & c_b)),
            'sector_overlap':';'.join(sorted(sec_a & sec_b)),
            'shared_distinctive_tokens':';'.join(sorted(shared)),
            'token_overlap':round(overlap,4), 'title_similarity':round(lex,4),
            'suggestion_only':1, 'same_physical_asset_proven':0,
            'review_decision':'', 'evidence_url':'', 'review_note':'',
        })
    proposals.sort(key=lambda x:(x['link_type']!='cross_publisher_shared_scope',
                                 -x['token_overlap'],-x['title_similarity'],x['pair_id']))
    return proposals


def atomic_bytes(path, content):
    if path.is_symlink():
        raise ValueError(f'Output symlink refused: {path}')
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name,path)
        path.chmod(0o600)
    finally:
        if os.path.exists(name): os.unlink(name)


def write_table(path, rows, columns):
    sio = io.StringIO(newline='')
    w = csv.DictWriter(sio,fieldnames=columns,extrasaction='ignore')
    w.writeheader()
    w.writerows(rows)
    atomic_bytes(path,('\ufeff'+sio.getvalue()).encode('utf-8'))


def emit(out, rows, rels, *, as_of, max_pairs, input_fingerprints=None):
    date.fromisoformat(as_of)
    by_id = id_index(rows)
    family_for_id, families, relations_out, normalized_links = group_explicit_relations(rows,rels)
    identities = identity_rows(by_id)
    family_table = family_rows(by_id,families,as_of=as_of)
    proposals = title_suggestions(by_id,family_for_id,max_pairs=max_pairs)
    review = [r for r in family_table if r['future_active_evidence']]
    # Curation form is a review aid: no prefilled verification or provenance.
    curation = [{
        'family_key':r['family_key'], 'iati_ids':r['iati_ids'],
        'title':r['representative_title'], 'decision':'',
        'asset_scope':'', 'site_evidence_url':'', 'site_country':'',
        'site_lat':'', 'site_lon':'', 'site_location_role':'',
        'implementation_evidence_url':'', 'observed_stage':'',
        'stage_known_as_of':'', 'capacity_value':'', 'capacity_unit':'',
        'reviewer':'', 'reviewed_at':'', 'notes':'',
    } for r in review]
    out.mkdir(parents=True,exist_ok=True,mode=0o700)
    out.chmod(0o700)
    for filename,data,columns in (
        ('activity_identity.csv',identities,list(identities[0]) if identities else ['iati_identifier']),
        ('relation_evidence.csv',relations_out,list(relations_out[0]) if relations_out else ['source_id','target_id','type_code']),
        ('evidence_families.csv',family_table,list(family_table[0]) if family_table else ['family_key']),
        ('review_link_suggestions.csv',proposals,list(proposals[0]) if proposals else [
            'pair_id','iati_id_a','iati_id_b','review_decision','evidence_url']),
        ('future_asset_review.csv',review,list(family_table[0]) if family_table else ['family_key']),
        ('manual_curation_template.csv',curation,list(curation[0]) if curation else ['family_key','decision']),
    ):
        write_table(out/filename,data,columns)
    bulk_ids={r['iati_identifier'] for r in rows if r['_origin']=='bulk'}
    datastore_ids={r['iati_identifier'] for r in rows if r['_origin']=='datastore'}
    manifest={
        'as_of':as_of,
        'input_fingerprints':input_fingerprints or [],
        'source_rows':len(rows),'bulk_rows':sum(r['_origin']=='bulk' for r in rows),
        'datastore_rows':sum(r['_origin']=='datastore' for r in rows),
        'bulk_unique_ids':len(bulk_ids),'datastore_unique_ids':len(datastore_ids),
        'overlapping_iati_ids':len(bulk_ids & datastore_ids),
        'distinct_iati_ids':len(by_id),'iati_ids_needing_source_reconciliation':sum(
            r['needs_source_reconciliation'] for r in identities),
        'explicit_parent_child_edges':len(normalized_links),
        'evidence_families':len(families),
        'evidence_families_with_multiple_ids':sum(len(ids)>1 for ids in families.values()),
        'future_active_evidence_families':len(review),
        'review_link_suggestions':len(proposals),
        'cross_publisher_suggestions':sum(p['link_type']=='cross_publisher_shared_scope' for p in proposals),
        'same_publisher_repeat_or_component_suggestions':sum(p['link_type']=='same_publisher_repeat_or_component' for p in proposals),
        'physical_assets_verified':0,'finance_aggregation_performed':False,
        'airport_assignment_performed':False,'historical_as_of_validated':False,
        'note': 'Families are related IATI activities, not unique physical investment assets. All matches require separate evidence.',
    }
    atomic_bytes(out/'manifest.json',(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode())
    return manifest


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bulk',type=Path,required=True,help='0064-D structured candidates.jsonl')
    p.add_argument('--datastore',type=Path,action='append',default=[],help='previous 0063/0064-B candidates.jsonl; repeatable')
    p.add_argument('--relations',type=Path,required=True,help='0064-D relations.json')
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--as-of',required=True,help='explicit snapshot observation date YYYY-MM-DD; not historical publication proof')
    p.add_argument('--max-pairs',type=int,default=100000,help='fail closed on overly broad title blocks')
    args=p.parse_args(argv)
    if args.max_pairs<1: p.error('--max-pairs must be >=1')
    for path in [args.bulk,*args.datastore,args.relations]:
        if not path.is_file():p.error(f'Missing input: {path}')
    if args.out.is_symlink():p.error('Output symlink refused')
    rows=list(read_jsonl(args.bulk,'bulk'))
    for path in args.datastore:
        rows.extend(read_jsonl(path,'datastore'))
    relations = json.loads(args.relations.read_text(encoding='utf-8'))
    if not isinstance(relations,list):p.error('relations must be a JSON list')
    os.umask(0o077)
    inputs=[('bulk',args.bulk),*(('datastore',x) for x in args.datastore),('relations',args.relations)]
    fingerprints=[{'role':kind,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                   'bytes':path.stat().st_size} for kind,path in inputs]
    result=emit(args.out,rows,relations,as_of=args.as_of,max_pairs=args.max_pairs,
                input_fingerprints=fingerprints)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
