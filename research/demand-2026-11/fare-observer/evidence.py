"""Restricted handoff format for the three FlightCost collection jobs."""
from datetime import date, datetime
from hashlib import sha256
from ipaddress import ip_address
import json
import math
import os
from pathlib import Path
import re
import socket
import stat
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit
from uuid import uuid4

from candidate_source import CURRENCIES, FORMATS, UNITS, document_fields

STREAMS = ('tickets', 'charges', 'discovery')
DOC_LIMIT = 16 * 1024 * 1024
JSON_LIMIT = 512 * 1024
API = 'https://api.travelpayouts.com/aviasales/v3/prices_for_dates'
IATA = re.compile(r'[A-Z0-9]{3}')
ICAO = re.compile(r'[A-Z0-9]{4}')
HASH = re.compile(r'[0-9a-f]{64}')
FILENAME = re.compile(r'[0-9a-f]{32}\.json')
STATUS = re.compile(r'(?:ok|empty|filtered|partial|http_[1-5][0-9]{2}|network_error|invalid_response|blocked_url|'
                    r'unsupported_content|unsupported_route|oversize)')
KINDS = {'paid_fare_statistics', 'advertised_fare_statistics', 'airport_charge_publication', 'unclassified'}
CANDIDATE_V1 = {'url', 'final_url', 'description', 'kind', 'sha256', 'bytes'}
CANDIDATE_V2 = CANDIDATE_V1 | {'status', 'publisher_domain', 'fetched_at', 'published_on', 'valid_from',
                              'valid_until', 'currency', 'unit', 'excerpt', 'format'}


def url_value(url):
    if not isinstance(url, str) or not 12 <= len(url) <= 2048 or any(c.isspace() or ord(c) < 32 for c in url):
        raise ValueError('invalid URL')
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.username or parts.password or parts.fragment or parts.port not in (443, None):
        raise ValueError('invalid URL scheme or authority')
    if not parts.hostname or '.' not in parts.hostname or '%' in parts.netloc:
        raise ValueError('invalid host')
    return parts.hostname


def public_host(url):
    host = url_value(url)
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not all(ip_address(info[4][0]).is_global for info in addresses):
        raise ValueError('nonpublic host')
    return host


def time_value(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError('invalid timestamp')
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError('timestamp without timezone')
    return stamp


def require(test, message):
    if not test:
        raise ValueError(message)


def read_regular(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        meta = os.fstat(stream.fileno())
        require(stat.S_ISREG(meta.st_mode) and meta.st_size <= limit, 'invalid outbox file size or type')
        data = stream.read(limit + 1)
        require(len(data) <= limit, 'outbox exceeds limit')
        return data


def atomic_write(directory, filename, data, mode):
    with NamedTemporaryFile(dir=directory, prefix='.writing-', delete=False) as stream:
        tmp = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            tmp.chmod(mode)
            tmp.replace(directory / filename)
        finally:
            tmp.unlink(missing_ok=True)


def publish(outbox, stream, timestamp, target, status, items, raw_count=None):
    payload = dict(version=2 if stream == 'discovery' else 1, stream=stream, checked_at=timestamp, target=target, status=status,
                   raw_count=len(items) if raw_count is None else raw_count, items=items)
    validate(payload, stream)
    serialized = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
    require(len(serialized) <= JSON_LIMIT, 'handoff too large')
    atomic_write(outbox, uuid4().hex + '.json', serialized, 0o640)


def validate(payload, stream):
    require(isinstance(payload, dict) and set(payload) ==
            {'version', 'stream', 'checked_at', 'target', 'status', 'raw_count', 'items'}, 'invalid envelope')
    version = payload['version']
    require(type(version) is int and (version == 1 or version == 2 and stream == 'discovery')
            and payload['stream'] == stream, 'wrong stream or version')
    time_value(payload['checked_at'])
    require(isinstance(payload['target'], str) and 0 < len(payload['target']) <= 2048, 'invalid target')
    require(isinstance(payload['status'], str) and STATUS.fullmatch(payload['status']), 'invalid outcome')
    items = payload['items']
    require(isinstance(items, list) and len(items) <= 1000, 'invalid item count')
    count = payload['raw_count']
    require(type(count) is int and len(items) <= count <= 1000, 'invalid raw count')
    require(bool(items) == (payload['status'] in ('ok', 'partial')), 'outcome disagrees with evidence')
    if payload['status'] == 'unsupported_route':
        require(stream == 'tickets' and count == 0, 'invalid unsupported route outcome')
    if stream == 'tickets':
        require(re.fullmatch(r'[A-Z0-9]{3}-[A-Z0-9]{3}', payload['target']), 'invalid market')
    elif stream == 'charges':
        url_value(payload['target'])
    for item in items:
        require(isinstance(item, dict), 'invalid evidence row')
        if stream == 'tickets':
            require(set(item) == {'origin_airport', 'destination_airport', 'carrier', 'flight_number',
                                  'departure_at', 'price_usd'}, 'invalid ticket fields')
            require(all(isinstance(item[k], str) and IATA.fullmatch(item[k])
                        for k in ('origin_airport', 'destination_airport')), 'invalid observed airport')
            require(all(isinstance(item[k], str) and len(item[k]) <= 8 and item[k].isalnum()
                        for k in ('carrier', 'flight_number')), 'invalid flight identification')
            time_value(item['departure_at'])
            price = item['price_usd']
            require(type(price) in (int, float) and math.isfinite(price) and 0 < price <= 1000000, 'invalid fare')
        elif stream == 'charges':
            require(set(item) == {'url', 'airports', 'sha256', 'format', 'bytes'}, 'invalid document fields')
            url_value(item['url'])
            require(isinstance(item['airports'], list) and item['airports'] and len(item['airports']) <= 100 and
                    all(isinstance(k, str) and ICAO.fullmatch(k) for k in item['airports']), 'invalid airports')
            require(isinstance(item['sha256'], str) and HASH.fullmatch(item['sha256']) and
                    item['format'] in ('pdf', 'html') and type(item['bytes']) is int and
                    0 < item['bytes'] <= DOC_LIMIT, 'invalid document metadata')
        else:
            validate_candidate(item, version)


def validate_candidate(item, version):
    require(set(item) == (CANDIDATE_V1 if version == 1 else CANDIDATE_V2), 'invalid candidate fields')
    url_value(item['url'])
    domain = url_value(item['final_url'])
    require(isinstance(item['description'], str) and 0 < len(item['description']) <= 300 and
            item['kind'] in KINDS and isinstance(item['sha256'], str) and HASH.fullmatch(item['sha256']) and
            type(item['bytes']) is int and 0 < item['bytes'] <= DOC_LIMIT, 'invalid candidate metadata')
    if version == 1:
        return
    require(item['status'] == 'candidate' and item['publisher_domain'] == domain,
            'invalid candidate status or publisher domain')
    time_value(item['fetched_at'])
    require(item['currency'] is None or item['currency'] in CURRENCIES, 'invalid candidate currency')
    require(item['unit'] is None or item['unit'] in UNITS, 'invalid candidate unit')
    require(item['format'] in FORMATS and isinstance(item['excerpt'], str) and 0 < len(item['excerpt']) <= 220
            and len(item['excerpt'].split()) <= 20, 'invalid candidate format or excerpt')
    for key in ('published_on', 'valid_from', 'valid_until'):
        value = item[key]
        require(value is None or isinstance(value, str) and date.fromisoformat(value).isoformat() == value,
                'invalid candidate date')


def stage_document(outbox, destination, item, candidate=False):
    filename = item['sha256'] + '.' + item['format']
    content = read_regular(outbox / filename, DOC_LIMIT)
    require(len(content) == item['bytes'] and sha256(content).hexdigest() == item['sha256'] and
            (item['format'] != 'pdf' or content.startswith(b'%PDF-')), 'document hash or type mismatch')
    if candidate:
        observed = document_fields(content, item['format'], item['kind'], item['final_url'])
        require(all(item[key] == value for key, value in observed.items()), 'candidate metadata differs from source')
    path = destination / filename
    if not path.exists():
        atomic_write(destination, filename, content, 0o600)
