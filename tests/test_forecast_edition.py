"""Install a forecast delta twice or reject it without modifying its base edition."""
import gzip
import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from deploy.forecast_edition import install
from flightcostapp.forecast_release import BASE, EDITION, RELEASES, published_outputs


REPORT = "forecast-final/report.html"
NETWORK = "forecast-leased-network/report.html"
WEB = "forecast-web/forecast.html"
WEB_NETWORK = "forecast-web/network.html"
WEB_MANIFEST = "forecast-web/manifest.json"


def digest(content):
    return hashlib.sha256(content).hexdigest()


def sums(files):
    return "".join(f"{digest(files[path])}  {path}\n" for path in sorted(files)).encode()


def web_manifest(files):
    return json.dumps({
        "base": {p: digest(files[p]) for p in (REPORT, NETWORK)},
        "assets": {p: digest(data) for p, data in files.items()
                   if p.startswith("forecast-web/") and p != WEB_MANIFEST},
    }, sort_keys=True).encode()


class ForecastEditionTest(unittest.TestCase):
    def test_explicit_forecast_paths_survive_a_new_release(self):
        self.assertEqual(published_outputs(RELEASES / BASE), RELEASES / EDITION)
        for path in (RELEASES / EDITION, RELEASES / ("a" * 64), Path("/tmp/review")):
            self.assertEqual(published_outputs(path), path)

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        work = Path(temp.name).resolve()
        self.editions = work / "releases"
        self.archive = work / "edition.tar.gz"
        self.original = {REPORT: b"Original report", WEB: b"Original web page",
                         NETWORK: b"Network report", WEB_NETWORK: b"Network web page"}
        self.original[WEB_MANIFEST] = web_manifest(self.original)
        previous_sums = sums(self.original)
        self.base_hash = digest(previous_sums)
        self.original["SHA256SUMS"] = previous_sums
        for name, payload in self.original.items():
            path = self.editions / self.base_hash / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)

        payload = gzip.compress(b'{"routes":[]}', mtime=0)
        chunk = f"forecast-web/{digest(payload)}.json.gz"
        self.updated = {name: data for name, data in self.original.items() if name != "SHA256SUMS"}
        self.updated.update({REPORT: b"New report", WEB: b"New web page", chunk: payload})
        self.updated[WEB_MANIFEST] = web_manifest(self.updated)
        self.updated["SHA256SUMS"] = sums(self.updated)
        self.edition_hash = digest(self.updated["SHA256SUMS"])
        self.delta = {name: data for name, data in self.updated.items() if data != self.original.get(name)}
        self.archive_hash = self.write_archive(self.delta)

    def write_archive(self, contents):
        with tarfile.open(self.archive, "w:gz") as archive:
            for name, payload in sorted(contents.items()):
                member = tarfile.TarInfo(name)
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))
        return digest(self.archive.read_bytes())

    def check_files(self, root, expected):
        actual = {path.relative_to(root).as_posix(): path.read_bytes()
                  for path in root.rglob("*") if path.is_file()}
        self.assertDictEqual(actual, expected)

    def install(self, archive_hash):
        return install(self.editions, self.archive, self.base_hash, self.edition_hash, archive_hash)

    def test_installs_and_reuses_verified_edition(self):
        result = self.install(self.archive_hash)
        self.assertEqual(result, self.editions / self.edition_hash)
        self.check_files(result, self.updated)
        base = self.editions / self.base_hash
        self.check_files(base, self.original)
        for name in (REPORT, WEB, WEB_MANIFEST, "SHA256SUMS"):
            self.assertFalse((base / name).samefile(result / name))
        self.assertEqual(self.install(self.archive_hash), result)
        self.check_files(result, self.updated)
        self.check_files(self.editions / self.base_hash, self.original)

    def test_rejects_wrong_archive_checksum(self):
        with self.assertRaises(ValueError):
            self.install("0" * 64)
        self.assertFalse((self.editions / self.edition_hash).exists())
        self.check_files(self.editions / self.base_hash, self.original)

    def test_rejects_member_with_wrong_checksum(self):
        archive_hash = self.write_archive({**self.delta, WEB: b"Unexpected web page"})
        with self.assertRaises(ValueError):
            self.install(archive_hash)
        self.assertFalse((self.editions / self.edition_hash).exists())
        self.check_files(self.editions / self.base_hash, self.original)
