"""Integration boundaries between an offline release, the site and private editorial files."""
import gzip
import hashlib
import json
import os
import re
import tarfile
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from flightcostapp import forecast_provenance, forecast_site, seo, serve


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
        ru_title = "Где вырастут перевозки и сколько самолётов потребуется"
        ru_fallback = "Скачать расчёт пассажиропотока в Excel"
        body = (f'<html lang="ru"><head><title>{ru_title} · FlightCost</title><style></style></head>'
                f'<body><main><h1>{ru_title}</h1><a href="#operations">Map</a>'
                f'<noscript><a href="Пассажиропоток.xlsx">{ru_fallback}</a></noscript>'
                '<section data-assets-root="../../"></section></main>').encode() + model
        local = {
            "ru": (ru_title, ru_fallback, ""),
            "en": ("Where will passenger traffic grow, and how many aircraft will it take?",
                   "Download the passenger traffic calculation in Excel", "seats"),
            "de": ("Wo wächst der Luftverkehr und wie viele Flugzeuge werden gebraucht?",
                   "Berechnung zum Passagierverkehr als Excel-Datei herunterladen", "Sitze"),
        }
        for lang, (title, fallback, seat_label) in local.items():
            with self.subTest(lang=lang), patch.object(forecast_site, "forecast_available", return_value=True):
                result = forecast_site.site_page(body, lang).decode()
                self.assertIn(f'<html lang="{lang}" data-site-lang="{lang}"', result)
                self.assertIn(f'href="/{lang}/forecast"', result)
                self.assertIn(f'<title>{title} · FlightCost</title>', result)
                self.assertIn(f'<h1>{title}</h1>', result)
                self.assertIn(f'<noscript><a href="/outputs/forecast-final/Пассажиропоток.xlsx">'
                              f'{fallback}</a></noscript>', result)
                self.assertIn('href="#operations"', result)
                self.assertIn('data-assets-root="/"', result)
                self.assertNotIn("<base ", result)
                self.assertTrue(result.endswith(model.decode()))
                if lang != "ru":
                    payload = re.search(r'<script id="forecast-messages" type="application/json">(.+?)</script>',
                                        result, re.S)
                    self.assertIsNotNone(payload)
                    label = json.loads(payload[1])["text"]["−10 т и +20 мест · МВМ 116 т"]
                    self.assertIn(seat_label, label)
                    self.assertIn("116", label)
                    self.assertNotRegex(label, "[А-Яа-яЁё]")

    def test_regular_entry_defaults_to_current_modernization_in_both_published_reports(self):
        archive = Path(__file__).resolve().parents[1] / "deploy/forecast/edition.tar.gz"
        with tarfile.open(archive, "r:gz") as bundle:
            for report in (forecast_site.WEB_INDEX, forecast_site.INDEX):
                with self.subTest(report=report):
                    page = bundle.extractfile(report).read()
                    self.assertIn(b"UnifiedForecast.mount(", page)
                    # The offline edition also carries an earlier renderer. Test the mounted one.
                    module = page.split(b"window.UnifiedForecast =", 1)[1].split(b"return {mount};", 1)[0]
                    selector = re.search(rb"let\s+study\s*=([^;]+);", module)
                    self.assertIsNotNone(selector)
                    self.assertRegex(selector[1], rb"Object\.hasOwn\(studies,\s*params\.get\('mr_study'\)\)"
                                                   rb"\s*\?\s*params\.get\('mr_study'\)\s*:\s*'ten_116'")

    def test_map_uses_the_reports_verified_core(self):
        archive = Path(__file__).resolve().parents[1] / "deploy/forecast/edition.tar.gz"
        with TemporaryDirectory() as directory, tarfile.open(archive, "r:gz") as bundle:
            root = Path(directory).resolve()
            web = bundle.extractfile(forecast_site.WEB_INDEX).read()
            chunk = re.search(rb'const forecastAssets\s*=\s*\{\s*"core"\s*:\s*"/outputs/([^"]+)"', web)[1].decode()
            offline = bundle.extractfile(forecast_site.INDEX).read()
            overlay = json.loads(bundle.extractfile(forecast_site.WEB_MANIFEST).read())
            if chunk in bundle.getnames():
                compressed = bundle.extractfile(chunk).read()
            else:
                # Older deltas inherit the core from the immutable server base.
                contents = re.search(rb'<script id="core"[^>]*>(.*?)</script>', offline, re.S)[1]
                compressed = gzip.compress(contents, mtime=0)
                digest = hashlib.sha256(compressed).hexdigest()
                replacement = f"forecast-web/{digest}.json.gz"
                web = web.replace(chunk.encode(), replacement.encode(), 1)
                chunk = replacement
                overlay["assets"][chunk] = digest
                overlay["assets"][forecast_site.WEB_INDEX] = hashlib.sha256(web).hexdigest()
            for name, contents in {
                forecast_site.INDEX: offline,
                forecast_site.WEB_INDEX: web,
                forecast_site.WEB_MANIFEST: json.dumps(overlay).encode(),
                chunk: compressed,
                "SHA256SUMS": bundle.extractfile("SHA256SUMS").read(),
            }.items():
                path = root / name
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(contents)
            report_core = json.loads(gzip.decompress(compressed))

            network = root / forecast_site.NETWORK
            network.parent.mkdir()
            network.touch()
            with patch.object(forecast_site, "OUTPUTS", root), patch.dict(os.environ, FCA_FORECAST_OUTPUTS=directory):
                page = forecast_site.forecast_map_page("de", probe=True)
                data = json.loads(re.search(rb'window.ForecastMapPageData = (.*?);</script>', page)[1])
                self.assertEqual(data["core"]["series"], report_core["series"])
                self.assertEqual(data["core"]["jointForecast"], report_core.get("jointForecast"))
                self.assertEqual(data["forecastUrl"], "/de/forecast")
                self.assertIn(b'window.BriefScenario = {create};', page)
                self.assertIn(b'src="/forecast-map-model.js?probe=dev"', page)
                self.assertIn(b'href="/de/forecast?probe=dev#scenario-methods"', page)
                for name, source in ((forecast_site.WEB_INDEX, web), (forecast_site.INDEX, offline)):
                    with self.subTest(report=name):
                        report = forecast_site.site_page(source, "de")
                        self.assertIn(b'id="forecast-map-link" href="/de/forecast/map"', report)
                        if b'id="forecast-verification"' in source:
                            self.assertEqual(report.count(b'id="forecast-accuracy"'), 1)
                            self.assertIn(b'<details id="forecast-accuracy" lang="de" translate="no">', report)
                            self.assertIn(b'<details class="fa-quarterly"><summary>', report)
                            self.assertIn(b'href="#forecast-accuracy"', report)
                            self.assertIn(b'mountForecastComparison(world, api);', report)
                            self.assertLess(report.index(b'id="forecast-accuracy"'), report.index(b'<section id="flow-fleet"'))
                for lang in ("ru", "en", "de"):
                    self.assertIn(f'href="/{lang}/forecast/map"', seo.site_header(lang, "data"))
                if report_core.get("jointForecast"):
                    report_core["jointForecast"]["horizons"]["2029"]["route_adjustment"] += 1
                    with self.assertRaises(ValueError):
                        forecast_provenance.joint_provenance(report_core)

                (root / forecast_site.WEB_MANIFEST).unlink()
                # A missing or stale manifest selects the same standalone report the site serves.
                fallback = forecast_site.forecast_map_page("ru")
                data = json.loads(re.search(rb'window.ForecastMapPageData = (.*?);</script>', fallback)[1])
                self.assertEqual(data["core"]["series"], report_core["series"])

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

            validators = set()
            served = set()
            for lang in ("ru", "en", "de"):
                with self.subTest(lang=lang):
                    code, headers, page = request(root, forecast_site.INDEX, lang=lang)
                    self.assertEqual(code, 200)
                    self.assertIn(b"<h1>Web</h1>", page)
                    self.assertEqual(headers["Cache-Control"], "public, no-cache")
                    etag = headers["ETag"]
                    for previous in validators:
                        status, current, other_page = request(root, forecast_site.INDEX, lang=lang,
                                                              validator=previous)
                        self.assertEqual((status, current["ETag"], other_page), (200, etag, page))
                    status, cached, empty = request(root, forecast_site.INDEX, lang=lang, validator=etag)
                    self.assertEqual((status, cached["ETag"], empty), (304, etag, b""))
                    validators.add(etag)
                    served.add(page)
            self.assertEqual(len(validators), 3)
            self.assertEqual(len(served), 3)
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
