"""Mount the generated forecast alongside the editable FlightCost calculators."""
from __future__ import annotations

import os
import re
from contextvars import ContextVar
from pathlib import Path

OUTPUTS = Path(os.environ.get("FCA_FORECAST_OUTPUTS") or Path(__file__).resolve().parents[1] / "outputs")
local_review = ContextVar("forecast_local_review", default=False)
INDEX = "forecast-final/report.html"
NETWORK = "forecast-leased-network/report.html"

_SOURCE_ROOT = "/research/demand-2026-11/atlas/forecast/final/"
SOURCE_ASSETS = {
    _SOURCE_ROOT + name: "forecast-source-notes/" + name
    for name in ("fleet-observed-additions.csv", "fleet-type-directory.csv", "deliveries/world/README.md")
}


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
