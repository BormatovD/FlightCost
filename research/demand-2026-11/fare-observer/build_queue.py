"""Build the free observation queue from the accepted route register and public charge sources."""
import csv
import gzip
import json
import re
from collections import Counter, defaultdict
from itertools import chain, zip_longest
from pathlib import Path
from urllib.parse import urlparse
import yaml

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'outputs/forecast-fare-observer'
COVERAGE = ROOT / 'outputs/forecast-network-audit/coverage/index.json'
OBSERVED = COVERAGE.with_name('routes.json.gz')
SCHEDULED_AIRPORTS = ROOT / 'analysis/demand-atlas-0064j/route-entry/airports.csv'
NONSTOP_EVIDENCE = ROOT / 'research/demand-2026-11/forecast-page/global_route_evidence.csv'
PASSENGER_SERVICE = {
    'segment_passengers', 'reported_route_passengers', 'segment_seats',
    'scheduled_seats', 'scheduled_weekly_roundtrips', 'scheduled_departures', 'service_confirmed',
}


def scheduled_airports():
    with SCHEDULED_AIRPORTS.open(encoding='utf-8', newline='') as file:
        return {(code, row['iso_country'], row['iata_code'])
                for row in csv.DictReader(file)
                if row['scheduled_service'] == 'yes'
                and row['type'] in {'small_airport', 'medium_airport', 'large_airport'}
                for code in (row['ident'], row.get('icao_code'), row['gps_code']) if code}


def published_nonstop_routes():
    with NONSTOP_EVIDENCE.open(encoding='utf-8', newline='') as file:
        for row in csv.DictReader(file):
            if row['evidence'] == 'nonstop_service' and re.match(r'^20[0-9]{2}', row['period']):
                yield {'a': row['airport_a'], 'b': row['airport_b'], 'observations': [{
                    'year': int(row['period'][:4]), 'metric': 'service_confirmed', 'value': 1,
                    'direction': 'both',
                }]}


def add_observed_routes(by_region, airports, regions, observed, blocked, scheduled):
    """Add physical airport pairs documented in 2024 or later.

    An undirected record makes both directions eligible for a cache lookup.
    City-level journeys and flight counts without passenger or schedule evidence
    do not establish a direct passenger service.
    """
    iata_counts = Counter(airport.get('iata') for airport in airports.values()
                          if airport.get('kind') == 'airport')
    known = {pair for routes in by_region.values() for pair in routes}
    for route in observed:
        a, b = route['a'], route['b']
        if frozenset((a, b)) in blocked:
            continue
        origin, destination = airports.get(a, {}), airports.get(b, {})
        if any(airport.get('kind') != 'airport' or airport.get('country') not in regions
               or not re.fullmatch(r'[A-Z]{3}', airport.get('iata') or '')
               or iata_counts[airport['iata']] != 1
               or (ident, airport['country'], airport['iata']) not in scheduled
               for ident, airport in ((a, origin), (b, destination))):
            continue
        directions = {
            point['direction'] for point in route['observations']
            if point.get('year', 0) >= 2024 and point['metric'] in PASSENGER_SERVICE and point['value'] > 0
        }
        for direction, home, away in (('a_to_b', origin, destination), ('b_to_a', destination, origin)):
            pair = home['iata'], away['iata']
            if pair in known or pair[0] == pair[1] or not {direction, 'both'} & directions:
                continue
            by_region[regions[home['country']]][pair] = 1
            known.add(pair)


def main():
    airports = json.loads(COVERAGE.read_bytes())['airports']
    regions = json.loads((ROOT / 'outputs/forecast-route-map/regions.json').read_bytes())['countryRegions']
    ranked = json.loads((ROOT / 'outputs/forecast-direct-world/rankings.json').read_bytes())
    priority = {}
    for year in ranked['years']:
        groups = ranked['rankings']['seats'][str(year)]['base']['countries']
        for panel in groups.values():
            for row in panel['top'] + panel['worst']:
                key = row['origin'], row['destination']
                priority[key] = min(priority.get(key, 2), int(row['fare_tier'] not in ('global_scenario', 'regional_carrier_scenario')))
    by_region = defaultdict(dict)
    blocked = set()
    with gzip.open(ROOT / 'outputs/forecast-country-full-final/market-candidate-pairs.csv.gz', 'rt') as file:
        for row in csv.DictReader(file):
            if row['provenance_or_reason'] == 'known_landing_closure':
                blocked.add(frozenset((row['airport_a'], row['airport_b'])))
            if row['status'] != 'candidate':
                continue
            for home, away in (('a', 'b'), ('b', 'a')):
                if row[home + '_home_allowed'].lower() not in ('true','1','yes'):
                    continue
                a, b = row['airport_' + home], row['airport_' + away]
                i, j = (airports.get(k, {}).get('iata', '') for k in (a, b))
                if not i or not j or i == j:
                    continue
                region = regions[row['country_' + home]]
                key = i, j
                level = priority.get((a,b),2)
                by_region[region][key] = min(level, by_region[region].get(key,2))
    with gzip.open(OBSERVED, 'rt') as file:
        observed = chain(json.load(file)['routes'], published_nonstop_routes())
        add_observed_routes(by_region, airports, regions, observed, blocked, scheduled_airports())
    routes = []
    for tier in range(3):
        streams = [[(i,j,region,tier) for (i,j),level in sorted(items.items()) if level==tier]
                   for region,items in sorted(by_region.items())]
        for group in zip_longest(*streams):
            routes.extend(x for x in group if x)
    docs = defaultdict(set)
    src = ROOT / 'data/charges'
    def add(icao, url):
        if isinstance(url,str) and urlparse(url).scheme=='https' and len(icao)==4:
            docs[url].add(icao)
    for path in sorted(src.glob('*.json')):
        entry = json.loads(path.read_bytes())
        add(entry.get('icao',''),entry.get('source_url'))
    todo = yaml.safe_load((src / '_todo.yaml').read_text())
    for collection in ('airports','wave_2026_10_29'):
        for code, entry in todo[collection].items():
            if isinstance(entry, dict):
                add(code,entry.get('url'))
    payload = dict(routes=routes, charge_sources=[(url,sorted(codes)) for url,codes in sorted(docs.items())])
    OUT.mkdir(exist_ok=True,parents=True)
    (OUT/'queue.json.gz').write_bytes(gzip.compress(json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode(),mtime=0))
    print(len(routes),'directional ticket markets;',len(by_region),'regions;',len(docs),'public charge sources')


if __name__ == '__main__':
    main()
