"""Mount the generated forecast alongside the editable FlightCost calculators."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

from .forecast_provenance import historical_provenance, joint_provenance
from .forecast_release import published_outputs

OUTPUTS = published_outputs(Path(os.environ.get("FCA_FORECAST_OUTPUTS") or Path(__file__).resolve().parents[1] / "outputs"))
local_review = ContextVar("forecast_local_review", default=False)
INDEX = "forecast-final/report.html"
NETWORK = "forecast-leased-network/report.html"
_SOURCE_ROOT = "/research/demand-2026-11/atlas/forecast/final/"
SOURCE_ASSETS = {
    _SOURCE_ROOT + name: "forecast-source-notes/" + name
    for name in ("fleet-observed-additions.csv", "fleet-type-directory.csv", "deliveries/world/README.md")
}
WEB_MANIFEST = "forecast-web/manifest.json"
WEB_INDEX = "forecast-web/forecast.html"
WEB_NETWORK = "forecast-web/network.html"
WEB_CHUNK = re.compile(r"forecast-web/[0-9a-f]{64}\.json\.gz")
MAP_CHUNK = re.compile(r"forecast-world-networks/map-data/(?:2029|2031|2036)-[A-Z]{2}\.[0-9a-f]{12}\.js")

MAP_PATH = "/forecast/map"
MAP_TEMPLATE = Path(__file__).resolve().parent / "web/forecast-map.html"
MAP_ASSETS = {
    "/forecast-map.css": "text/css; charset=utf-8",
    "/forecast-map.js": "application/javascript; charset=utf-8",
    "/forecast-map-numbers.js": "application/javascript; charset=utf-8",
    "/forecast-map-model.js": "application/javascript; charset=utf-8",
    "/forecast-map-evidence.js": "application/javascript; charset=utf-8",
    "/forecast-map-scene.js": "application/javascript; charset=utf-8",
}
_VERIFICATION = re.compile(rb'<script id="forecast-verification" type="application/json">([^<]*)</script>')
_SCRIPT = re.compile(rb"<script\b([^>]*)>(.*?)</script>", re.S | re.I)
_REPORT_API = b"  const api = BriefModel.create(core, initial);"
_MAP_LINK_TEXT = {
    "ru": "Как это рассчитано",
    "en": "How this is calculated",
    "de": "So wurde das berechnet",
}
_MAP_LINK_FALLBACK = b"""<script>(() => {
  const link = document.getElementById('forecast-map-link');
  const url = new URL(link.href);
  const params = new URLSearchParams(location.search);
  for (const key of ['year', 'region', 'country', 'hub']) {
    if (params.has(key)) url.searchParams.set(key, params.get(key));
  }
  if (params.getAll('probe').includes('dev')) url.searchParams.set('probe', 'dev');
  const scenario = new URLSearchParams(location.hash.slice(1)).get('scenario');
  if (scenario) url.hash = 'scenario=' + encodeURIComponent(scenario);
  link.href = url.href;
})();</script>"""

_MAP_STATE = b"""
  let mapState;
  try {
    mapState = JSON.parse(new URLSearchParams(location.hash.slice(1)).get('scenario'));
  } catch (error) {
    mapState = null;
  }
  if (mapState && typeof mapState === 'object') {
    if (mapState.region !== 'world' && Object.hasOwn(core.series.regions, mapState.region)) initial.region = mapState.region;
    if (core.series.years.includes(mapState.year)) initial.year = mapState.year;
    if (['pessimistic', 'base', 'optimistic'].includes(mapState.demand)) initial.demand = mapState.demand;
    if (mapState.scenarios && typeof mapState.scenarios === 'object' && !Array.isArray(mapState.scenarios)) {
      initial.scenarios = mapState.scenarios;
    }
  }
"""

_MAP_LINK = b"""
  const forecastMapLink = document.getElementById('forecast-map-link');
  const updateForecastMapLink = () => {
    const url = new URL(forecastMapLink.pathname, location.href);
    const current = new URLSearchParams(location.search);
    if (current.getAll('probe').includes('dev')) url.searchParams.set('probe', 'dev');
    const country = current.get('country');
    if (country && Object.hasOwn(core.countries[api.state.region] || {}, country)) {
      url.searchParams.set('country', country);
      if (current.has('hub')) url.searchParams.set('hub', current.get('hub'));
    }
    url.searchParams.set('year', api.state.year);
    url.searchParams.set('region', api.state.region);
    url.hash = 'scenario=' + encodeURIComponent(JSON.stringify(api.state));
    forecastMapLink.href = url.href;
  };
  if (forecastMapLink) {
    updateForecastMapLink();
    api.onChange(updateForecastMapLink);
  }
"""


@lru_cache(maxsize=4)
def _overlay_assets(manifest: Path, manifest_version: tuple, base: Path, base_version: tuple) -> frozenset[str]:
    try:
        overlay = json.loads(manifest.read_bytes())
        base_hashes = {}
        for line in base.read_text(encoding="utf-8").splitlines():
            digest, name = line.split("  ", 1)
            if name in (INDEX, NETWORK):
                base_hashes[name] = digest
        if set(base_hashes) != {INDEX, NETWORK} or base_hashes != overlay["base"]:
            return frozenset()
        assets = overlay["assets"]
        if not {WEB_INDEX, WEB_NETWORK}.issubset(assets):
            return frozenset()
        if any(not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or
               (name not in (WEB_INDEX, WEB_NETWORK) and
                (not WEB_CHUNK.fullmatch(name) or name.rsplit("/", 1)[-1] != digest + ".json.gz"))
               for name, digest in assets.items()):
            return frozenset()
        return frozenset(assets)
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        return frozenset()


def overlay_assets(root: Path) -> frozenset[str]:
    """Allow a content-addressed overlay only for the exact original edition."""
    manifest, base = root / WEB_MANIFEST, root / "SHA256SUMS"
    try:
        versions = []
        for path in (manifest, base):
            if path.resolve() != path:
                return frozenset()
            stat = path.stat()
            versions.append((stat.st_ino, stat.st_mtime_ns, stat.st_size))
        return _overlay_assets(manifest, versions[0], base, versions[1])
    except OSError:
        return frozenset()


@lru_cache(maxsize=6)
def web_page(asset: Path, site_lang: str | None, version: tuple) -> tuple[bytes, str]:
    """Hold the small localized page and its current validator per installed edition."""
    body = asset.read_bytes()
    if site_lang:
        body = site_page(body, site_lang)
    if b'name="robots"' not in body:
        body = body.replace(b"</head>", b'<meta name="robots" content="noindex,nofollow"></head>', 1)
    return body, 'W/"' + hashlib.sha256(body).hexdigest() + '"'


def matches_etag(offered: str, etag: str) -> bool:
    return any(candidate.strip() == "*" or candidate.strip().removeprefix("W/") == etag.removeprefix("W/")
               for candidate in offered.split(","))


def forecast_available() -> bool:
    """An installation without the generated reports keeps its normal navigation."""
    if not local_review.get() and not os.environ.get("FCA_FORECAST_OUTPUTS"):
        return False
    return all((OUTPUTS / path).is_file() for path in (INDEX, NETWORK))


def forecast_map_available() -> bool:
    return MAP_TEMPLATE.is_file() and forecast_available()


def _version(path: Path) -> tuple:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


@lru_cache(maxsize=4)
def _map_model(root: Path, edition: Path, version: tuple) -> tuple[dict, bytes]:
    report = edition.read_bytes()
    source = None
    core = None
    for block in _SCRIPT.finditer(report):
        if b'id="core"' in block[1] and block[2].strip():
            core = json.loads(block[2])
        if report.find(b"window.BriefScenario = {create};", block.start(2), block.end(2)) >= 0:
            if source is not None:
                raise ValueError("Forecast edition has more than one BriefScenario script")
            source = block[2]
        if source is not None and core is not None:
            break
    if core is None:
        # The split web edition names its exact, content-addressed model input.
        asset = re.search(rb'\bconst forecastAssets\s*=\s*\{\s*"core"\s*:\s*"/outputs/([^"]+)"', report)
        if asset is not None:
            relative = asset[1].decode("ascii")
            chunk = root / relative
            if (not WEB_CHUNK.fullmatch(relative) or relative not in overlay_assets(root)
                    or chunk.resolve() != chunk):
                raise ValueError("Invalid forecast core asset")
            compressed = chunk.read_bytes()
            if hashlib.sha256(compressed).hexdigest() != chunk.name.split(".")[0]:
                raise ValueError("Forecast core does not match the installed edition")
            core = json.loads(gzip.decompress(compressed))
    if core is None or source is None:
        raise ValueError("Forecast edition has no core or BriefScenario")
    world = core["extras"]["world"]
    return {
        "jointForecast": joint_provenance(core),
        "series": core["series"],
        "countries": core["countries"],
        "extras": {"world": {key: world[key] for key in ("demandFactors", "shocks", "population", "sources")
                             if key in world}},
    }, source


def forecast_map_page(lang: str, *, probe: bool = False) -> bytes:
    from .seo import site_header

    root = OUTPUTS.resolve()
    web = root / WEB_INDEX
    use_web = WEB_INDEX in overlay_assets(root) and web.resolve() == web and web.is_file()
    edition = web if use_web else root / INDEX
    if edition.resolve() != edition:
        raise ValueError("Invalid forecast edition")
    core, scenario = _map_model(root, edition, _version(edition))
    data = dict(lang=lang, core=core, provenance={} if core["jointForecast"] else historical_provenance(root, core["series"]),
                forecastUrl=f"/{lang}/forecast", networkUrl=f"/outputs/{NETWORK}")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    payload = payload.replace(b"<", br"\u003c")
    page = MAP_TEMPLATE.read_bytes()
    marker = b"<!--FORECAST_MAP_DATA-->"
    if page.count(marker) != 1:
        raise ValueError("Forecast map template is missing its data marker")
    page = re.sub(rb'(<html\b[^>]*\blang=")[^"]+(")', rb"\g<1>" + lang.encode() + rb"\2", page, count=1)
    page = page.replace(b"<!--SITE_HEADER:forecast-map-->", site_header(lang, "forecast_map", MAP_PATH).encode(), 1)
    back = f"/{lang}/forecast" + ("?probe=dev" if probe else "")
    page = page.replace(b'href="../forecast', f'href="{back}'.encode())
    if b'name="robots"' not in page:
        page = page.replace(b"</head>", b'<meta name="robots" content="noindex,nofollow"></head>', 1)
    if probe:
        for path in ("/ui.css", "/favicon.svg", *MAP_ASSETS):
            url = path.encode()
            page = page.replace(b'"' + url + b'"', b'"' + url + b'?probe=dev"')
    scripts = b"<script>" + scenario + b"</script>\n<script>window.ForecastMapPageData = " + payload + b";</script>"
    return page.replace(marker, scripts, 1)


def site_page(body: bytes, lang: str) -> bytes:
    from .seo import site_header

    is_map_link = forecast_map_available() and body.count(_REPORT_API) == 1
    if is_map_link:
        body = body.replace(_REPORT_API, _MAP_STATE + _REPORT_API + _MAP_LINK, 1)
    head, marker, data = body.partition(b'<script id="core"')
    if not marker:
        raise ValueError("Forecast edition is missing its embedded model")
    attrs = f'<html lang="{lang}" data-site-lang="{lang}" data-report-base="/outputs/forecast-final/">'
    head = head.replace(b'<html lang="ru">', attrs.encode(), 1)
    head = head.replace(b'<style>', b'<link rel="stylesheet" href="/ui.css"><style>', 1)
    if lang in ("en", "de"):
        from .forecast_language import localize_intro
        head = localize_intro(head, lang)
    verification = _VERIFICATION.search(head)
    if verification is not None:
        from .forecast_accuracy import ACCURACY_LABEL, render_accuracy

        placeholder = b'<section id="scenario-methods"'
        if placeholder in head:
            section = render_accuracy(json.loads(verification[1]), lang)
            if section:
                head = head.replace(placeholder, section + placeholder, 1)
                before, nav, after = head.partition(b'<nav class="brief-nav"')
                link = f'<a href="#forecast-accuracy">{ACCURACY_LABEL[lang]}</a>'.encode()
                if nav:
                    head = before + nav + after.replace(b"</nav>", link + b"</nav>", 1)
    header = f'<div lang="{lang}">{site_header(lang, "forecast", "/forecast")}</div>'
    head = head.replace(b"<body>", b"<body>" + header.encode(), 1)
    if is_map_link:
        link = (f'<p class="brief-files" lang="{lang}"><a id="forecast-map-link" '
                f'href="/{lang}{MAP_PATH}">{_MAP_LINK_TEXT[lang]}</a></p>').encode() + _MAP_LINK_FALLBACK
        before, heading, after = head.partition(b'<header class="brief-head">')
        if heading and b"</header>" in after:
            head = before + heading + after.replace(b"</header>", link + b"</header>", 1)
        else:
            head = head.replace(b"</h1>", b"</h1>" + link, 1)
    head = head.replace(b'data-assets-root="../../"', b'data-assets-root="/"')
    # Static workbooks, including the noscript fallback, live beside the offline report.
    head = re.sub(rb'href="([^/:?#"]+\.(?:xlsx|zip))"', rb'href="/outputs/forecast-final/\1"', head)
    return head + marker + data
