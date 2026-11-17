"""Tariff evidence and documented charges that cannot yet be priced."""
import copy
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest

from flightcostapp import charges
from flightcostapp.parsers import airport_charges
from flightcostapp.store import Store


class TariffMetadataTests(unittest.TestCase):
    def document(self):
        return {
            "icao": "KLAX", "valid_from": "2026-07-01",
            "source": "Airport tariff 2026", "source_url": "https://example.com/tariff.pdf",
            "map_node": "src_airport_tariff", "icao_note": "Airport operator",
            "rules": [{"code": "landing", "base": "per_turnaround", "rate": 25,
                       "currency": "USD", "source_note": "Section 1"}],
        }

    def parse(self, doc, ctx=None):
        return airport_charges.parse(json.dumps(doc).encode(), ctx if ctx is not None else {
            "source_id": "airport_charges_tier1", "sha": "artifact-sha",
            "extracted_by": "parser:test", "node": "src_airport_tariff"})

    def unpriced(self, **changes):
        entry = {"code": "terminal", "when": {"terminal": "A", "carrier_type": "passenger"},
                 "reason": "Requires leased area and operator invoice"}
        entry.update(changes)
        return entry

    def test_rule_source_override_round_trip_and_stable_identity(self):
        doc = self.document()
        original = self.parse(doc)[0]
        doc["rules"][0].update(source="Separate terminal tariff",
                                source_url="http://example.com/terminal.pdf", minimum=30)
        facts = self.parse(doc)
        rule = charges.Rule.from_fact(asdict(facts[0]))
        self.assertEqual(rule.rate, 25)
        self.assertEqual(rule.source_note, "Section 1")
        self.assertEqual(facts[0].key, original.key)
        self.assertEqual(facts[0].note,
                         "Section 1 | Separate terminal tariff | http://example.com/terminal.pdf")
        self.assertEqual(facts[1].note, facts[0].note)
        self.assertNotIn("source", json.loads(facts[0].value_text))
        self.assertNotIn("source_url", json.loads(facts[0].value_text))

    def test_rule_source_default_unchanged_and_individual_fallback(self):
        doc = self.document()
        self.assertEqual(self.parse(doc)[0].note,
                         "Section 1 | Airport tariff 2026 | https://example.com/tariff.pdf")
        doc["rules"][0]["source_url"] = "https://example.com/other.pdf"
        self.assertEqual(self.parse(doc)[0].note,
                         "Section 1 | Airport tariff 2026 | https://example.com/other.pdf")

    def test_invalid_record_evidence_rejects_document(self):
        for field, values in (("source_url", (None, "", "   ", "ftp://example.com/file",
                                               "https:///file", "https://example.com/a b", 42)),
                              ("source", (None, "", "  ", 42))):
            for value in values:
                with self.subTest(field=field, value=value):
                    doc = self.document()
                    doc["rules"][0][field] = value
                    with self.assertRaisesRegex(ValueError, field):
                        self.parse(doc)

    def test_rule_constructor_and_unknown_record_fields_remain_strict(self):
        for field in ("source", "source_url", "evidence"):
            with self.subTest(field=field):
                with self.assertRaises(TypeError):
                    charges.Rule(code="landing", base="per_turnaround", rate=25, **{field: "x"})
        doc = self.document()
        doc["rules"][0]["evidence"] = "unrecognized"
        with self.assertRaisesRegex(ValueError, "evidence"):
            self.parse(doc)

    def test_unpriced_round_trip_provenance_and_date_without_zero_rule(self):
        doc = self.document()
        doc["unpriced"] = [self.unpriced()]
        facts = self.parse(doc)
        meta = next(f for f in facts if f.unit == "unpriced_charge")
        self.assertTrue(meta.key.startswith("KLAX/_unpriced/"))
        self.assertEqual((meta.value, meta.value_text, meta.currency), (0.0, "", None))
        self.assertEqual(json.loads(meta.note), {
            **self.unpriced(), "source": doc["source"], "source_url": doc["source_url"]})
        self.assertEqual((meta.source_id, meta.artifact_sha, meta.extracted_by,
                          meta.node, meta.source_note),
                         ("airport_charges_tier1", "artifact-sha", "parser:test",
                          "src_airport_tariff", "Airport operator"))
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "facts.db")
            try:
                store.commit_facts(facts)
                self.assertIsNone(store.get("airport_charge", meta.key, "2026-06-30"))
                row = store.get("airport_charge", meta.key, "2026-07-01")
                self.assertEqual(json.loads(row["note"]), json.loads(meta.note))
                self.assertEqual(row["valid_from"], doc["valid_from"])
                self.assertEqual([r.code for r in charges.load_rules(store, "KLAX", "2026-07-01")],
                                 ["landing"])
            finally:
                store.db.close()

    def test_unpriced_source_override_and_identity_ignore_order_or_reason(self):
        doc = self.document()
        doc["unpriced"] = [self.unpriced(source="Lease schedule",
                                         source_url="https://example.com/lease.pdf")]
        original = self.parse(doc)[1]
        self.assertEqual(json.loads(original.note)["source"], "Lease schedule")
        self.assertEqual(json.loads(original.note)["source_url"], "https://example.com/lease.pdf")
        entry = doc["unpriced"][0]
        entry["when"] = dict(reversed(list(entry["when"].items())))
        entry["reason"] = "Updated explanation"
        self.assertEqual(self.parse(doc)[1].key, original.key)
        entry["when"]["terminal"] = "B"
        self.assertNotEqual(self.parse(doc)[1].key, original.key)
        entry["code"] = "other_terminal"
        self.assertNotEqual(self.parse(doc)[1].key, original.key)

    def test_unpriced_invalid_fields_conditions_or_reason_reject_document(self):
        for changes in ({"reason": ""}, {"reason": "  "}, {"code": ""},
                        {"when": {"unknown": "A"}}, {"when": {"carrier_type": "holiday"}},
                        {"when": []}, {"rate": 0}, {"source_url": "file:///tmp/tariff"}):
            with self.subTest(changes=changes):
                doc = self.document()
                doc["unpriced"] = [self.unpriced(**changes)]
                with self.assertRaises(ValueError):
                    self.parse(doc)

    def test_unpriced_only_document_does_not_count_as_priced(self):
        doc = self.document()
        doc["rules"] = []
        doc["unpriced"] = [self.unpriced()]
        with self.assertRaisesRegex(ValueError, "правил 0"):
            self.parse(doc)

    def test_invalid_unpriced_document_does_not_leak_facts_to_other_document(self):
        valid = self.document()
        invalid = copy.deepcopy(valid)
        invalid["icao"] = "KLAS"
        invalid["unpriced"] = [self.unpriced(reason="")]
        ctx = {"source_id": "airport_charges_tier1", "node": "src_airport_tariff"}
        facts = airport_charges.parse(
            (json.dumps(invalid) + "\n" + json.dumps(valid)).encode(), ctx)
        self.assertTrue(all(f.key.startswith("KLAX/") for f in facts))
        self.assertEqual(ctx["parsed_docs"], 1)
        self.assertEqual(ctx["parsed_prefixes"], ["KLAX"])
        self.assertIn("KLAS", ctx["rejected"][0])


if __name__ == "__main__":
    unittest.main()
