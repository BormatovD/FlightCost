"""Run one bounded collection job or import validated observations into private staging."""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import gzip
from hashlib import sha256
from http.client import HTTPException
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sqlite3
from time import sleep, time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import build_opener, HTTPRedirectHandler, ProxyHandler, Request
from xml.etree import ElementTree

from candidate_source import document_fields
from evidence import (API, DOC_LIMIT, FILENAME, IATA, JSON_LIMIT, STREAMS, atomic_write,
                      public_host, publish, read_regular, stage_document, time_value, url_value, validate)

try:
    from ticket_controls import select_tickets, ticket_controls
except ModuleNotFoundError:
    from flightcostapp.ticket_controls import select_tickets, ticket_controls

DAY = 86400
TICKET_ERROR_LIMIT = 4096
UNKNOWN_TICKET_CODE = re.compile(r'bad request: unknown location code `([A-Z0-9]{3})`')
NONFLIGHTABLE_AIRPORT = re.compile(r'bad request: airport ([A-Z0-9]{3}): not flightable')
EQUAL_TICKET_CITIES = 'bad request: origin_city_iata and destination_city_iata are equal: invalid params'
AGENT = 'FlightCost research/1.0 (+https://flightcost.app)'
BASE = Path(__file__).resolve().parent

OFFICIAL = (
    ('https://www.transportation.gov/policy/aviation-policy/domestic-airfare-consumer-report',
     'paid_fare_statistics', 'US DOT, average domestic city-pair fares from submitted itinerary records'),
    ('https://data.transportation.gov/Aviation/Consumer-Airfare-Report-Table-1-Top-1-000-Contiguo/4f3n-jbg2/about_data',
     'paid_fare_statistics', 'US DOT Consumer Airfare Report Table 1, paid fares on domestic city pairs'),
    ('https://www.anac.gov.br/acesso-a-informacao/dados-abertos/areas-de-atuacao/voos-e-operacoes-aereas/tarifas-aereas-domesticas/46-tarifas-aereas-domesticas',
     'paid_fare_statistics', 'ANAC, commercially sold domestic tickets, microdata and coverage exclusions'),
    ('https://www.gov.br/anac/pt-br/assuntos/dados-e-estatisticas/mercado-de-transporte-aereo/consulta-interativa/tarifas_aereas_domesticas',
     'paid_fare_statistics', 'ANAC, interactive reports on sold domestic fares'),
    ('https://www150.statcan.gc.ca/n1/pub/51-004-x/51-004-x2019011-eng.htm',
     'paid_fare_statistics', 'Statistics Canada, historical base fares from the Canadian Fare Basis Survey'),
    ('https://www.bitre.gov.au/resource/aviation/domestic-airfares',
     'advertised_fare_statistics', 'BITRE, lowest available advertised return fares and index'),
)
QUERIES = (
    ('paid_fare_statistics', 'domestic airline average paid fares origin destination public data'),
    ('airport_charge_publication', 'airport charges'),
)
SEARCH_HOSTS = ('gov', 'gc.ca', 'europa.eu', 'aero')
REGIONS = ('Eastern Africa', 'Middle Africa', 'Northern Africa', 'Southern Africa', 'Western Africa',
           'Caribbean', 'Central America', 'South America', 'Northern America',
           'Central Asia', 'Eastern Asia', 'South-Eastern Asia', 'Southern Asia', 'Western Asia',
           'Eastern Europe', 'Northern Europe', 'Southern Europe', 'Western Europe',
           'Australia and New Zealand', 'Melanesia', 'Micronesia', 'Polynesia')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class PublicRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_host(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = set()
        self.address = None
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.address = dict(attrs).get('href')
            self.text = []

    def handle_data(self, data):
        if self.address:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.address:
            self.links.add((self.address, ' '.join(' '.join(self.text).split())))
            self.address = None


def fetch(url, limit=DOC_LIMIT, token=None):
    if token is not None:
        if url.split('?', 1)[0] != API:
            raise ValueError('invalid token destination')
    else:
        public_host(url)
    opener = build_opener(ProxyHandler({}), NoRedirect() if token else PublicRedirect())
    headers = {'User-Agent': AGENT}
    if token:
        headers['X-Access-Token'] = token
    with opener.open(Request(url, headers=headers), timeout=12) as response:
        content = response.read(limit + 1)
        if len(content) > limit:
            raise OverflowError('response too large')
        return content, response.geturl(), response.headers.get_content_type()


def error_status(exc):
    if isinstance(exc, HTTPError):
        return 'http_' + str(exc.code)
    if isinstance(exc, OverflowError):
        return 'oversize'
    if isinstance(exc, (URLError, OSError)):
        return 'network_error'
    return 'invalid_response'


def ticket_http_status(exc, origin, destination):
    status = error_status(exc)
    if exc.code != 400:
        return status
    try:
        body = exc.read(TICKET_ERROR_LIMIT + 1)
        if len(body) > TICKET_ERROR_LIMIT:
            return status
        reply = json.loads(body)
    except (HTTPException, OSError, ValueError, RecursionError):
        return status
    if not isinstance(reply, dict) or reply.get('success') is not False:
        return status
    message = reply.get('error')
    if not isinstance(message, str):
        return status
    if message == EQUAL_TICKET_CITIES:
        return 'unsupported_route'
    match = UNKNOWN_TICKET_CODE.fullmatch(message) or NONFLIGHTABLE_AIRPORT.fullmatch(message)
    if match and match[1] in (origin, destination):
        return 'unsupported_route'
    return status


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def connect(path):
    db = sqlite3.connect(path, timeout=30)
    db.execute('PRAGMA journal_mode=WAL')
    return db


def initialize_queue(db, stream):
    db.execute('''CREATE TABLE IF NOT EXISTS targets (target TEXT PRIMARY KEY, metadata TEXT, priority INTEGER,
                seq INTEGER, due INTEGER DEFAULT 0, status TEXT)''')
    db.execute('CREATE INDEX IF NOT EXISTS queue_due ON targets(due, priority, seq)')
    if stream == 'tickets':
        db.execute("CREATE INDEX IF NOT EXISTS ix_queue_admin_unsupported ON targets(status) WHERE status='unsupported_route'")
    if db.execute('SELECT count(*) FROM targets').fetchone()[0]:
        return
    with gzip.open(BASE / 'queue.json.gz', 'rt') as source:
        queue = json.load(source)
    if stream == 'tickets':
        targets = ((a + '-' + b, region, priority, i) for i, (a, b, region, priority) in enumerate(queue['routes']))
    else:
        # Alternate providers to prevent a single publisher from consuming the first batch.
        from collections import defaultdict, deque
        groups = defaultdict(deque)
        for url, codes in queue['charge_sources']:
            try:
                groups[url_value(url)].append((url, json.dumps(codes)))
            except ValueError:
                continue
        sources = [groups[host] for host in sorted(groups)]
        order = []
        while any(sources):
            order.extend(group.popleft() for group in sources if group)
        targets = ((url, codes, 0, i) for i, (url, codes) in enumerate(order))
    with db:
        db.executemany('INSERT OR IGNORE INTO targets(target,metadata,priority,seq) VALUES (?,?,?,?)', targets)


def observed_tickets(target, token):
    origin, destination = target.split('-')
    params = dict(origin=origin, destination=destination, one_way='true', direct='true', unique='false',
                  currency='usd', sorting='price', limit=1000, page=1)
    try:
        body, _, _ = fetch(API + '?' + urlencode(params), limit=4 * 1024 * 1024, token=token)
    except HTTPError as exc:
        with exc:
            return ticket_http_status(exc, origin, destination), [], 0
    reply = json.loads(body)
    if not isinstance(reply, dict) or reply.get('success') is not True:
        return 'invalid_response', [], 0
    values = reply.get('data')
    if not isinstance(values, list) or len(values) > 1000 or str(reply.get('currency', 'usd')).lower() != 'usd':
        return 'invalid_response', [], 0
    items = []
    now = datetime.now(timezone.utc)
    for item in values:
        if not isinstance(item, dict) or item.get('return_at') or item.get('transfers') != 0:
            continue
        if str(item.get('currency', 'usd')).lower() != 'usd':
            continue
        airports = tuple(str(item.get(side + '_airport') or '') for side in ('origin', 'destination'))
        if not all(IATA.fullmatch(airport) for airport in airports):
            continue
        try:
            departure = str(item.get('departure_at'))
            price = float(item.get('price'))
            airline, flight = str(item.get('airline') or ''), str(item.get('flight_number') or '')
            if time_value(departure) <= now or not 0 < price <= 1000000 or not all(
                    x.isalnum() and len(x) <= 8 for x in (airline, flight)):
                continue
        except (TypeError, ValueError):
            continue
        items.append(dict(origin_airport=airports[0], destination_airport=airports[1], carrier=airline,
                          flight_number=flight, departure_at=departure, price_usd=price))
    status = 'partial' if items and len(values) == 1000 else 'ok' if items else 'filtered' if values else 'empty'
    return status, items, len(values)


def observed_charge(target, metadata, outbox):
    body, final, mime = fetch(target)
    kind = 'pdf' if body.startswith(b'%PDF-') else 'html'
    if kind == 'html' and (mime not in ('text/html', 'application/xhtml+xml') or len(body) < 400):
        return 'unsupported_content', [], 0
    digest = sha256(body).hexdigest()
    name = digest + '.' + kind
    if not (outbox / name).exists():
        atomic_write(outbox, name, body, 0o640)
    return 'ok', [dict(url=final, airports=json.loads(metadata), sha256=digest, format=kind, bytes=len(body))], 1


def queue_run(state, outbox, stream, limit, probe):
    token = None
    if stream == 'tickets':
        credentials = Path(os.environ['CREDENTIALS_DIRECTORY']) / 'ticket-token'
        token = credentials.read_text().strip()
        if not token or not token.isascii() or not token.isalnum():
            raise ValueError('invalid ticket credential')
    with closing(connect(state / 'queue.sqlite3')) as db:
        initialize_queue(db, stream)
        if probe:
            targets = db.execute('SELECT target,metadata FROM targets WHERE target=?', (probe,)).fetchall()
            if not targets and stream == 'tickets' and re.fullmatch(r'[A-Z0-9]{3}-[A-Z0-9]{3}', probe):
                targets = [(probe, 'verification-only')]
        elif stream == 'tickets':
            controls = ticket_controls(outbox.parent / 'ticket-admin' / 'overrides.json')
            targets = [(route, metadata) for route, metadata, _ in select_tickets(db, limit, int(time()), controls)]
        else:
            targets = db.execute('''SELECT target,metadata FROM targets WHERE due<=? AND status IS NOT 'unsupported_route'
                                 ORDER BY due,priority,seq LIMIT ?''', (int(time()), limit)).fetchall()
        results = Counter()
        for target, metadata in targets:
            checked = utc_now()
            try:
                if stream == 'tickets':
                    status, items, raw_count = observed_tickets(target, token)
                else:
                    status, items, raw_count = observed_charge(target, metadata, outbox)
            except (HTTPError, URLError, OSError, OverflowError, ValueError) as exc:
                status, items, raw_count = error_status(exc), [], 0
            publish(outbox, stream, checked, target, status, items, raw_count)
            results[status] += 1
            interval = (2 if stream == 'tickets' else 7) * DAY if items else DAY
            if status.startswith('http_') and stream == 'tickets':
                interval = 3 * 3600
            due = None if status == 'unsupported_route' else int(time()) + interval
            restored = status in ('ok', 'partial', 'empty', 'filtered')
            with db:
                db.execute('''UPDATE targets SET due=?,status=? WHERE target=?
                           AND (status IS NOT 'unsupported_route' OR ?)''', (due, status, target, restored))
            if stream == 'tickets' and status in ('http_401', 'http_403', 'http_429'):
                break
            sleep(.30 if stream == 'tickets' else 1)
        print(json.dumps({'stream':stream,'queue_size':db.execute('SELECT count(*) FROM targets').fetchone()[0],
                          'outcomes':results}))


def check_candidate(url, kind, description, outbox):
    body, final, mime = fetch(url)
    fetched_at = utc_now()
    formats = {'text/html': 'html', 'application/xhtml+xml': 'html', 'text/csv': 'csv'}
    format_name = 'pdf' if body.startswith(b'%PDF-') else formats.get(mime)
    if len(body) < 400 or format_name is None:
        raise ValueError('candidate document format')
    facts = document_fields(body, format_name, kind, final)
    digest = sha256(body).hexdigest()
    filename = digest + '.' + format_name
    if not (outbox / filename).exists():
        atomic_write(outbox, filename, body, 0o640)
    return dict(url=url, final_url=final, description=' '.join(description.split())[:300], kind=kind,
                sha256=digest, bytes=len(body), format=format_name, publisher_domain=url_value(final),
                status='candidate', fetched_at=fetched_at, **facts)


def public_search(kind, query):
    # The search backend is interchangeable. Source links are checked with a separate request.
    if query == QUERIES[1][1]:
        endpoint = 'https://www.gov.uk/api/search.json?' + urlencode({'q':query,'count':8})
        body, _, _ = fetch(endpoint, limit=JSON_LIMIT)
        results = json.loads(body)['results']
        return [(urljoin('https://www.gov.uk', row['link']), row['title'], kind)
                for row in results if row['link'].startswith('/government/')
                and 'airport' in row['title'].lower() and 'charges' in row['title'].lower()
                and 'network rail' not in row['title'].lower()]
    endpoint = 'https://www.bing.com/search?' + urlencode({'format':'rss','q':query})
    body, _, _ = fetch(endpoint, limit=JSON_LIMIT)
    return [(row.findtext('link',''),row.findtext('title',''),kind)
            for row in ElementTree.fromstring(body).findall('./channel/item')][:8]


def catalog_links(url):
    body, _, _ = fetch(url)
    parser = LinkParser()
    parser.feed(body.decode(errors='replace'))
    candidates = []
    for href, title in sorted(parser.links):
        hint = (href + ' ' + title).lower()
        if not any(key in hint for key in ('table 1', 'city-pair market', 'air-fare', 'airfare',
                                           'aviation-data', 'tarifas aéreas', 'fare basis')):
            continue
        address = urljoin(url, href).split('#')[0]
        if address != url and source_allowed(address):
            candidates.append((address, title))
    return list(dict(candidates).items())[:6]


def source_allowed(url):
    try:
        host = url_value(url)
    except ValueError:
        return False
    return any(host.endswith('.' + suffix) for suffix in SEARCH_HOSTS) or bool(
        re.search(r'\.(?:gov|gob|gouv)\.[a-z]{2}$', host))


def discovery_run(outbox):
    count = Counter()
    for url, kind, description in OFFICIAL:
        discovery_candidate(outbox, url, kind, description, count)
    region = REGIONS[datetime.now(timezone.utc).toordinal() % len(REGIONS)]
    extra = ('airport_charge_publication', f'{region} airport schedule aeronautical charges landing fees')
    for kind, query in (*QUERIES, extra):
        source = 'Search: ' + query
        stamp = utc_now()
        try:
            results = public_search(kind, query)
        except (HTTPError, URLError, OSError, OverflowError, ValueError, ElementTree.ParseError, KeyError) as exc:
            outcome = error_status(exc)
            publish(outbox, 'discovery', stamp, source, outcome, [])
            count[outcome] += 1
            continue
        publish(outbox, 'discovery', stamp, source, 'filtered' if results else 'empty', [], min(len(results), 1000))
        for url, title, _ in results:
            if not title.strip() or not source_allowed(url):
                continue
            discovery_candidate(outbox, url, 'unclassified', title, count)
    for url, _, description in OFFICIAL[:4]:
        checked = utc_now()
        try:
            candidates = catalog_links(url)
        except (HTTPError, URLError, OSError, OverflowError, ValueError) as exc:
            outcome = error_status(exc)
            publish(outbox, 'discovery', checked, 'Catalog: ' + url, outcome, [])
            count[outcome] += 1
            continue
        publish(outbox, 'discovery', checked, 'Catalog: ' + url, 'filtered' if candidates else 'empty', [], len(candidates))
        for candidate, title in candidates:
            discovery_candidate(outbox, candidate, 'unclassified', title or ('Linked by ' + description), count)
    print(json.dumps({'stream':'discovery','outcomes':count}))


def discovery_candidate(outbox, url, kind, description, count):
    try:
        items, outcome = [check_candidate(url, kind, description, outbox)], 'ok'
    except (HTTPError, URLError, OSError, OverflowError, ValueError) as exc:
        items, outcome = [], error_status(exc)
    publish(outbox, 'discovery', utc_now(), url, outcome, items)
    count[outcome] += 1


def initialize_staging(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS handoff (
            stream TEXT, filename TEXT, phase TEXT, checked_at TEXT, target TEXT, status TEXT, raw_count INTEGER,
            rows INTEGER, payload TEXT, PRIMARY KEY(stream,filename));
        CREATE INDEX IF NOT EXISTS stage_summary ON handoff(stream,phase,status);
        CREATE INDEX IF NOT EXISTS ix_handoff_ticket_target_rows ON handoff(target,rows)
            WHERE stream='tickets' AND phase='staged';
        CREATE INDEX IF NOT EXISTS ix_handoff_ticket_recent ON handoff(stream,phase,checked_at DESC,target,rows)
            WHERE stream='tickets' AND phase='staged' AND rows>0;
        CREATE VIEW IF NOT EXISTS evidence AS
            SELECT stream,checked_at,target,status,json_each.value AS item FROM handoff,json_each(payload,'$.items')
            WHERE phase='staged';
    ''')


def ingest(state, spool):
    destination = state / 'documents'
    destination.mkdir(mode=0o700, exist_ok=True)
    candidate_documents = state / 'candidate-documents'
    candidate_documents.mkdir(mode=0o700, exist_ok=True)
    counts = Counter()
    with closing(connect(state / 'staging.sqlite3')) as db:
        initialize_staging(db)
        for stream in STREAMS:
            outbox = spool / stream
            known = {row[0] for row in db.execute('SELECT filename FROM handoff WHERE stream=?', (stream,))}
            for path in sorted(outbox.iterdir()):
                if not FILENAME.fullmatch(path.name) or path.name in known:
                    continue
                try:
                    data = read_regular(path, JSON_LIMIT)
                    batch = json.loads(data)
                    validate(batch, stream)
                    if stream == 'charges':
                        for item in batch['items']:
                            stage_document(outbox, destination, item)
                    if stream == 'discovery' and batch['version'] == 2:
                        for item in batch['items']:
                            stage_document(outbox, candidate_documents, item, candidate=True)
                except (OSError, ValueError, UnicodeError, RecursionError, OverflowError, TypeError) as exc:
                    row = ('rejected', utc_now(), '', type(exc).__name__, 0, 0, None)
                else:
                    row = ('staged', batch['checked_at'], batch['target'], batch['status'], batch['raw_count'],
                           len(batch['items']), data.decode())
                with db:
                    db.execute('INSERT OR IGNORE INTO handoff VALUES (?,?,?,?,?,?,?,?,?)', (stream,path.name,*row))
                counts[stream + ':' + row[0]] += 1
    print(json.dumps(dict(ingested=counts)))


def summarize(state):
    with closing(connect(state / 'staging.sqlite3')) as db:
        initialize_staging(db)
        rows = [dict(stream=s, phase=p, status=status, attempts=n, staged_rows=count) for s,p,status,n,count in
                db.execute('SELECT stream,phase,status,count(*),sum(rows) FROM handoff GROUP BY stream,phase,status')]
        print(json.dumps({'counts':rows}, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=(*STREAMS,'ingest','status'))
    parser.add_argument('--state', required=True, type=Path)
    parser.add_argument('--spool', type=Path, default=Path('/var/spool/fca-fare-observer'))
    parser.add_argument('--limit', type=int, default=6)
    parser.add_argument('--probe')
    args = parser.parse_args()
    if args.command == 'status':
        summarize(args.state)
    elif args.command == 'ingest':
        ingest(args.state, args.spool)
    elif args.command == 'discovery':
        discovery_run(args.spool / args.command)
    else:
        queue_run(args.state, args.spool / args.command, args.command, args.limit, args.probe)


if __name__ == '__main__':
    main()
