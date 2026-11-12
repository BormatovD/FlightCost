"""Offline tests: no IATI key or network needed."""
import json
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import iati_fetch as f

FIXTURE = Path(__file__).parent / "fixtures" / "iati_synthetic_page.json"


class FakeResponse:
    def __init__(self, body):
        self.body = body
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def read(self, limit=None):
        return self.body[:limit] if limit is not None else self.body


class IatiResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.doc = cls.payload["response"]["docs"][0]

    def test_normalization_preserves_distinct_financial_stages(self):
        record = f.normalize_activity(self.doc, "2026-11-12T03:00:00+00:00")
        self.assertEqual(record["iati_identifier"], "XX-SYNTHETIC-AFRICA-1")
        self.assertEqual([t["kind"] for t in record["transactions"]],
                         ["outgoing_commitment", "disbursement", "expenditure"])
        self.assertEqual([t["amount"] for t in record["transactions"]],
                         ["35000000", "2500000", "400000"])
        self.assertEqual([t["currency"] for t in record["transactions"]],
                         ["USD", "USD", "EUR"])
        self.assertEqual(record["budgets"][0]["amount"], "5000000")
        self.assertEqual(len(record["recipient_countries"]), 2)
        self.assertEqual(record["locations"][0]["coordinates"], {"lat": -1.2833, "lon": 36.8167})
        self.assertEqual(record["sectors"][0]["category"], "air_transport")
        self.assertIsNone(record["sectors"][1]["category"], "Foreign sector vocabulary must not be misclassified")
        self.assertEqual(record["historically_available_before_snapshot"], "unverified")
        self.assertNotIn("capex_usd", record, "Unconverted transactions are not CAPEX")

    def test_iati_json_string_is_decoded_without_flat_array_pairing(self):
        doc = dict(self.doc)
        doc["iati_json"] = json.dumps(doc["iati_json"])
        self.assertEqual(f.normalize_activity(doc, "2026-11-12")["title"],
                         "SYNTHETIC: regional airport and tourism access")

    def test_missing_structured_activity_is_hard_error(self):
        with self.assertRaisesRegex(ValueError, "structured iati_json"):
            f.normalize_activity({"iati_identifier": "X", "transaction_value": [10, 20]}, "2026-11-12")

    def test_query_is_bounded_and_does_not_embed_key(self):
        url = f.query_url("KE", 30, 0)
        values = parse_qs(urlsplit(url).query)
        self.assertIn("recipient_country_code:KE", values["q"][0])
        self.assertEqual(values["rows"], ["30"])
        self.assertIn("iati_json", values["fl"][0])
        self.assertNotIn("sort", values)
        self.assertNotIn("activity_id", values["fl"][0])
        with self.assertRaises(ValueError):
            f.query_url("KE", 1001, 0)

    def test_key_is_http_header_not_url(self):
        seen = {}
        def opener(req, timeout):
            seen["key"] = dict(req.header_items()).get("Ocp-apim-subscription-key")
            seen["url"] = req.full_url
            return FakeResponse(json.dumps(self.payload).encode())
        response, checksum, _raw = f.request_page(f.query_url("KE", 1), "synthetic-secret-987", opener)
        self.assertEqual(response["numFound"], 1)
        self.assertEqual(len(checksum), 64)
        self.assertEqual(seen["key"], "synthetic-secret-987")
        self.assertNotIn("synthetic-secret-987", seen["url"])

    def test_http_403_message_does_not_dump_secret(self):
        def failing(req, timeout):
            raise HTTPError(req.full_url, 403, "Forbidden", {}, None)
        with self.assertRaisesRegex(RuntimeError, "quota or permission denied") as caught:
            f.request_page(f.query_url("KE", 1), "my-very-private-key", failing)
        self.assertNotIn("my-very-private-key", str(caught.exception))

    def test_http_400_explains_solr_failure_without_leaking_secret(self):
        secret = "secret-123"
        body = json.dumps({"error": {"msg": "sort field activity_id invalid, " + secret}}).encode()
        def failing(req, timeout):
            raise HTTPError(req.full_url, 400, "Bad Request", {}, io.BytesIO(body))
        with self.assertRaisesRegex(RuntimeError, "HTTP 400.*sort field") as caught:
            f.request_page(f.query_url("KE", 1), secret, failing)
        self.assertNotIn(secret, str(caught.exception))
        self.assertIn("[redacted]", str(caught.exception))

    def test_probe_makes_exactly_one_call_and_no_output_files(self):
        calls = []
        with tempfile.TemporaryDirectory() as folder:
            def opener(req, timeout):
                calls.append(req.full_url)
                return FakeResponse(json.dumps(self.payload).encode())
            with patch.dict(os.environ, {"FCA_IATI_API_KEY": "fake-key"}):
                f.run(["--probe", "--countries", "KE,TZ", "--out", str(Path(folder) / "unused")],
                      opener=opener)
            self.assertEqual(len(calls), 1)
            self.assertFalse((Path(folder) / "unused").exists())

    def test_full_pilot_flags_truncation_and_outputs_no_secrets(self):
        payload = json.loads(json.dumps(self.payload))
        payload["response"]["numFound"] = 3  # only one page collected
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "research"
            calls = []
            def opener(req, timeout):
                calls.append(req.full_url)
                return FakeResponse(json.dumps(payload).encode())
            with patch.dict(os.environ, {"FCA_IATI_API_KEY": "should-never-be-written"}):
                manifest = f.run(["--countries", "KE,TZ", "--rows", "1",
                                  "--out", str(output), "--pause", "0"], opener=opener)
            self.assertEqual(manifest["unique_activities"], 1)
            self.assertTrue(all(c["truncated"] for c in manifest["countries"]))
            self.assertEqual(len(calls), 2)
            self.assertNotIn("should-never-be-written", (output / "manifest.json").read_text())
            self.assertNotIn("should-never-be-written", (output / "candidates.jsonl").read_text())

    def test_secret_file_not_world_readable(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "key"
            p.write_text("test-key\n")
            p.chmod(0o644)
            with patch.dict(os.environ, {"FCA_IATI_API_KEY": ""}):
                with self.assertRaisesRegex(RuntimeError, "other users"):
                    f.read_key(p)
                p.chmod(0o640)
                self.assertEqual(f.read_key(p), "test-key")

    def test_coordinates_validate_and_type(self):
        self.assertIsNone(f.parse_coordinates("100 22"))
        self.assertIsNone(f.parse_coordinates("12"))
        self.assertEqual(f.parse_coordinates("0 0"), {"lat": 0.0, "lon": 0.0})


if __name__ == "__main__":
    unittest.main()
