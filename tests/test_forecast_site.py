"""Integration boundaries between an offline release, the site and private editorial files."""
import hashlib
import json
import os
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from flightcostapp import forecast_site, serve


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

    def test_web_overlay_requires_matching_manifest_and_revalidates(self):
        def request(root, path, *, lang=None, query="", validator=""):
            handler = object.__new__(serve._Handler)
            handler.path = "/forecast?probe=dev" + query
            handler.command = "GET"
            handler.headers = {"If-None-Match": validator}
            handler.wfile = BytesIO()
            handler.send_response = lambda code: setattr(handler, "status", code)
            headers = {}
            handler.send_header = lambda name, value: headers.update({name: value})
            handler.end_headers = lambda: None
            with patch.object(serve, "FORECAST_OUTPUTS", root):
                handler._forecast_asset(path, site_lang=lang)
            return handler.status, headers, handler.wfile.getvalue()

        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            original = (b'<html lang="ru"><head><style></style></head><body><h1>Offline</h1>'
                        b'<script id="core"></script></body></html>')
            web = original.replace(b"Offline", b"Web")
            report_paths = (forecast_site.INDEX, forecast_site.NETWORK)
            web_paths = (forecast_site.WEB_INDEX, forecast_site.WEB_NETWORK)
            base = {name: hashlib.sha256(original).hexdigest() for name in report_paths}
            base_manifest = "".join(f"{digest}  {name}\n" for name, digest in base.items())
            for names, body in ((report_paths, original), (web_paths, web)):
                for name in names:
                    asset = root / name
                    asset.parent.mkdir(exist_ok=True)
                    asset.write_bytes(body)

            digest = hashlib.sha256(b"payload").hexdigest()
            chunk = f"forecast-web/{digest}.json.gz"
            (root / chunk).write_bytes(b"payload")
            assets = {name: hashlib.sha256(web).hexdigest() for name in web_paths}
            assets[chunk] = digest
            (root / forecast_site.WEB_MANIFEST).write_text(json.dumps({"base": base, "assets": assets}))
            (root / "SHA256SUMS").write_text(base_manifest)

            code, headers, body = request(root, forecast_site.INDEX, lang="de")
            self.assertEqual(code, 200)
            self.assertIn(b"<h1>Web</h1>", body)
            self.assertEqual(headers["Cache-Control"], "public, no-cache")
            status, headers_304, body = request(root, forecast_site.INDEX, lang="de", validator=headers["ETag"])
            self.assertEqual((status, headers_304["ETag"], body), (304, headers["ETag"], b""))
            self.assertIn(b"<h1>Offline</h1>", request(root, forecast_site.INDEX)[2])
            self.assertIn(b"<h1>Web</h1>", request(root, forecast_site.NETWORK)[2])
            self.assertIn(b"<h1>Offline</h1>", request(root, forecast_site.NETWORK, query="&download=1")[2])

            code, headers, content = request(root, chunk)
            self.assertEqual((code, content), (200, b"payload"))
            self.assertEqual(headers["Cache-Control"], "public, max-age=31536000, immutable")
            self.assertEqual(request(root, chunk, validator=headers["ETag"])[0], 304)
            rogue = "forecast-web/" + hashlib.sha256(b"unlisted").hexdigest() + ".json.gz"
            (root / rogue).write_bytes(b"unlisted")
            self.assertEqual(request(root, rogue)[0], 404)

            stale = root / "SHA256SUMS.new"
            stale.write_text(base_manifest.replace(base[forecast_site.INDEX], "0" * 64, 1))
            stale.replace(root / "SHA256SUMS")
            code, headers, body = request(root, forecast_site.INDEX, lang="de")
            self.assertEqual(code, 200)
            self.assertIn(b"<h1>Offline</h1>", body)
            self.assertNotIn("ETag", headers)
            self.assertEqual(request(root, chunk)[0], 404)


if __name__ == "__main__":
    unittest.main()
