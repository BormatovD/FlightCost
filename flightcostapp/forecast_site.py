"""Mount the generated forecast alongside the editable FlightCost calculators."""
from __future__ import annotations

import hashlib
import json
import os
import re
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

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


def site_page(body: bytes, lang: str) -> bytes:
    from .seo import site_header

    head, marker, data = body.partition(b'<script id="core"')
    if not marker:
        raise ValueError("Forecast edition is missing its embedded model")
    attrs = f'<html lang="ru" data-site-lang="{lang}" data-report-base="/outputs/forecast-final/">'
    head = head.replace(b'<html lang="ru">', attrs.encode(), 1)
    head = head.replace(b'<style>', b'<link rel="stylesheet" href="/ui.css"><style>', 1)
    header = f'<div lang="{lang}">{site_header(lang, "forecast", "/forecast")}</div>'
    head = head.replace(b"<body>", b"<body>" + header.encode(), 1)
    if lang != "ru":
        notice = {"en": "This forecast is available in Russian.", "de": "Dieser Prognosebericht ist auf Russisch verfügbar."}[lang]
        head = head.replace(b"</h1>", f'</h1><p class="credit" lang="{lang}">{notice}</p>'.encode(), 1)
    head = head.replace(b'data-assets-root="../../"', b'data-assets-root="/"')
    # Static workbooks, including the noscript fallback, live beside the offline report.
    head = re.sub(rb'href="([^/:?#"]+\.(?:xlsx|zip))"', rb'href="/outputs/forecast-final/\1"', head)
    return head + marker + data
