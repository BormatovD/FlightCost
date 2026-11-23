"""Integration boundaries between an offline release, the site and private editorial files."""
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from flightcostapp import forecast_site


class ForecastSite(unittest.TestCase):
    def test_release_visibility(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for path in (forecast_site.INDEX, forecast_site.NETWORK):
                asset = root / path
                asset.parent.mkdir()
                asset.touch()
            with patch.object(forecast_site, "OUTPUTS", root), patch.dict(os.environ):
                os.environ.pop("FCA_FORECAST_OUTPUTS", None)
                token = forecast_site.local_review.set(False)
                try:
                    self.assertFalse(forecast_site.forecast_available())
                    forecast_site.local_review.set(True)
                    self.assertTrue(forecast_site.forecast_available())
                    forecast_site.local_review.set(False)
                    os.environ["FCA_FORECAST_OUTPUTS"] = directory
                    self.assertTrue(forecast_site.forecast_available())
                    (root / forecast_site.NETWORK).unlink()
                    self.assertFalse(forecast_site.forecast_available())
                finally:
                    forecast_site.local_review.reset(token)

    def test_report_mount_preserves_fragment_links_and_embedded_data(self):
        model = b'<script id="core" type="application/json">{"text":"<body>"}</script>'
        body = (b'<html lang="ru"><head><style></style></head><body><main><h1>Title</h1>'
                b'<a href="#operations">Map</a><a href="demand.xlsx">Workbook</a>'
                b'<section data-assets-root="../../"></section></main>' + model)
        with patch.object(forecast_site, "forecast_available", return_value=True):
            result = forecast_site.site_page(body, "de")
        self.assertIn(b'data-site-lang="de"', result)
        self.assertIn(b'href="/de/forecast"', result)
        self.assertIn(b'lang="de">Dieser', result)
        self.assertIn(b'href="#operations"', result)
        self.assertIn(b'href="/outputs/forecast-final/demand.xlsx"', result)
        self.assertIn(b'data-assets-root="/"', result)
        self.assertNotIn(b"<base ", result)
        self.assertTrue(result.endswith(model))
