"""Derive an excerpt and narrowly supported metadata from the downloaded source."""

from datetime import date, datetime
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

FORMATS = {"html", "csv", "pdf"}
BLOCKS = {"h1", "title", "p", "td", "th"}
DESCRIPTION_META = {"description", "og:description", "twitter:description"}
PUBLICATION_META = {"article:published_time", "datepublished", "govuk:first-published-at"}
DATE_VALUE = r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Za-z]+\s+\d{4}|[A-Za-z]+\s+\d{1,2},\s+\d{4})"
CURRENCIES = {
    "USD": r"(?:USD|U\.?S\.? dollars?|US\$)",
    "BRL": r"(?:BRL|Brazilian reais|reais|R\$)",
    "GBP": r"(?:GBP|pounds? sterling)",
    "EUR": r"(?:EUR|euros?)",
    "CAD": r"(?:CAD|Canadian dollars?)",
    "AUD": r"(?:AUD|Australian dollars?)",
}
UNITS = {
    "per_passenger": r"(?:per passenger\b|por passageiro\b)",
    "per_ticket": r"(?:per ticket\b|por bilhete\b)",
    "per_coupon": r"(?:per (?:flight )?coupon\b|on a coupon origin.destination basis)",
    "per_landing": r"per landing\b",
    "per_tonne": r"per (?:metric )?tonne\b",
    "per_departure": r"per departure\b",
}


def normalize(text):
    return " ".join(text.split())


class SourceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.blocks = {}
        self.pending = None
        self.parts = []
        self.descriptions = []
        self.published = []

    def handle_starttag(self, tag, attrs):
        if tag in BLOCKS:
            self.pending = tag
            self.parts = []
        if tag == "meta":
            fields = dict(attrs)
            name = (fields.get("property") or fields.get("name") or fields.get("itemprop") or "").lower()
            value = normalize(fields.get("content") or "")
            if name in DESCRIPTION_META and value:
                self.descriptions.append(value)
            if name in PUBLICATION_META and value:
                self.published.append(value)

    def handle_endtag(self, tag):
        if tag == self.pending:
            value = normalize(" ".join(self.parts))
            if value:
                self.blocks.setdefault(tag, []).append(value)
            self.pending = None

    def handle_data(self, data):
        if self.pending:
            self.parts.append(data)


def get_date(text):
    for fmt in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def published_date(values):
    dates = set()
    for value in values:
        match = re.match(r"\d{4}-\d{2}-\d{2}(?:T|$)", value)
        if match:
            try:
                dates.add(date.fromisoformat(value[:10]).isoformat())
            except ValueError:
                pass
    return next(iter(dates)) if len(dates) == 1 else None


def match_one(options, text, prefix):
    found = [code for code, capture in options.items() if re.search(prefix + capture, text, re.I)]
    return found[0] if len(found) == 1 else None


def explicit_date(text, qualifier):
    expression = rf"\b(?:tariffs?|rates?|charges?|schedule of charges)\s+(?:are\s+)?{qualifier}\s+({DATE_VALUE})"
    values = {get_date(match.group(1)) for match in re.finditer(expression, text, re.I)}
    values.discard(None)
    return next(iter(values)) if len(values) == 1 else None


def source_text(body):
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return body.decode("cp1252", errors="replace")


def document_fields(body, format_name, kind, final_url):
    if format_name == "html":
        parser = SourceParser()
        parser.feed(source_text(body))
        headings = parser.blocks.get("h1", [])
        paragraphs = parser.blocks.get("p", [])
        titles = parser.blocks.get("title", [])
        phrase = r"\b(?:fare|fares|charges?|tarifas?|tariffs?|consultation)\b"
        blocks = [*headings, *parser.descriptions, *paragraphs, *titles]
        relevant = [text for text in blocks if re.search(phrase, text, re.I)]
        lines = relevant or headings or titles
        context = "\n".join([*parser.descriptions, *headings, *paragraphs,
                             *parser.blocks.get("th", []), *parser.blocks.get("td", [])])
        published_on = published_date(parser.published)
    elif format_name == "csv":
        lines = [normalize(line) for line in source_text(body).splitlines()[:1]]
        context = "\n".join(lines)
        published_on = None
    else:
        match = re.search(rb"/Title\s*\(([^()\\\x00-\x1f]{5,200})\)", body)
        lines = [normalize(match.group(1).decode("latin-1"))] if match else []
        context = "\n".join(lines)
        published_on = None
    if not lines or not lines[0]:
        raise ValueError("no readable first-source excerpt")
    excerpt = " ".join(lines[0].split()[:20])[:220]
    consultation = "/consultations/" in urlsplit(final_url).path or any(
        re.search(r"\bconsultation\b", text, re.I) for text in lines[:2])
    currency = unit = valid_from = valid_until = None
    if kind != "unclassified" and not consultation:
        currency = match_one(
            CURRENCIES, context,
            r"\b(?:(?:currency|moeda)\s*[:=]\s*|valor nominal em\s+|(?:fare|tariff|charge)s?\s+(?:(?:are|is|values?)\s+)?"
            r"(?:denominated|reported|expressed|measured|quoted|stated)?\s*in\s+)",
        )
        unit = match_one(
            UNITS, context, r"\b(?:fare|tariff|charge)s?\s+(?:(?:is|are|calculated|paid|reported)\s+)?",
        )
        if kind == "paid_fare_statistics" and unit is None and re.search(
                r"valor do serviço de transporte aéreo[^.\n]{0,60}da passagem", context, re.I):
            unit = "per_ticket"
        if kind == "airport_charge_publication":
            valid_from = explicit_date(context, r"(?:valid|effective)\s+from")
            valid_until = explicit_date(context, r"(?:valid|effective)\s+(?:until|through)")
            if valid_from and valid_until and valid_until < valid_from:
                valid_from = valid_until = None
    return dict(excerpt=excerpt, published_on=published_on,
                valid_from=valid_from, valid_until=valid_until, currency=currency, unit=unit)
