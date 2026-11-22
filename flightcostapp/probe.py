"""Метка тестовых HTTP-запросов к витрине."""

from urllib.parse import parse_qs, unquote_plus, urlsplit, urlunsplit

PROBE_PARAM = "probe"
PROBE_VALUE = "dev"


def is_probe(query: str) -> bool:
    return PROBE_VALUE in parse_qs(query).get(PROBE_PARAM, ())


def probe_url(url: str) -> str:
    parts = urlsplit(url)
    query = [field for field in parts.query.split("&")
             if field and unquote_plus(field.split("=", 1)[0]) != PROBE_PARAM]
    query.append(f"{PROBE_PARAM}={PROBE_VALUE}")
    return urlunsplit(parts._replace(query="&".join(query)))
