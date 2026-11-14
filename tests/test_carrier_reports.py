"""Verified source drafts and explicit acceptance, without network or model calls."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml
from flightcostapp import carrier_reports as C
from flightcostapp import agent_run as A


def report():
    values = {key: {"value": value, "currency": "EUR", "basis": key, "quote": "Annual results 100 20 1000 800 1", "page": "1"}
              for key, value in {"opex_eur": 100, "fuel_cost_eur": 20, "ask_km": 1000, "rpk_km": 800, "pax": 1}.items()}
    return dict(carrier="XX", name="Test airline", year=2025, entity_id="XX", segment="lowcost", segment_basis="Published business model", report_id="XX2025v1", period_start="2025-01-01", period_end="2025-12-31", published_at="2026-02-01", source="Annual results", source_url="https://example.org/report.pdf", scope="passenger airline", values=values,
                evidence={"url": "https://example.org/report.pdf", "text": "Annual results 100 20 1000 800 1", "sha256": "abc"})


class Reports(unittest.TestCase):
    def test_quote_and_period_validation(self):
        doc = report()
        self.assertEqual(C.check_report(doc), [])
        doc["values"]["pax"]["quote"] = "a fabricated quote"
        self.assertTrue(any("quote" in x for x in C.check_report(doc)))
        doc = report()
        doc["period_start"] = "2025-10-01"
        self.assertTrue(any("annual" in x for x in C.check_report(doc)))

    def test_mean_fx_is_not_a_monetary_expense(self):
        doc = report()
        for key in ("opex_eur", "fuel_cost_eur"):
            doc["values"][key]["currency"] = "USD"
        doc["values"]["fx_per_eur"] = {"value": 1.1, "basis": "mean period USD per EUR", "page": "1", "quote": "Annual results"}
        self.assertEqual(C.check_report(doc), [])

    def test_accept_preserves_other_contour_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "XX-2025.yaml"
            other = {"carrier": "XY", "year": 2025, "values": {}}
            old = report()
            path.write_text(yaml.safe_dump_all([old, other]))
            new = report()
            new["report_id"] = "XX2025v2"
            C.accept(new, directory)
            first = path.read_bytes()
            C.accept(new, directory)
            self.assertEqual(first, path.read_bytes())
            self.assertEqual(list(yaml.safe_load_all(path.read_text()))[1], other)
            self.assertNotIn("evidence", list(yaml.safe_load_all(path.read_text()))[0])

    def test_reject_old_publication_replacing_new(self):
        with tempfile.TemporaryDirectory() as directory:
            C.accept(report(), directory)
            old = report()
            old["published_at"] = "2026-01-01"
            with self.assertRaises(ValueError):
                C.accept(old, directory)

    def test_collection_evidence_draft_acceptance_and_parser(self):
        from flightcostapp.parsers.carrier_benchmark import parse
        from flightcostapp import master
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = A.Runner(home=root)
            doc = report()
            trusted_evidence = doc.pop("evidence")
            # A fabricated model evidence field must be replaced by independent download.
            doc["evidence"] = {"text": "fabricated"}
            def execute(job, ws, task, model):
                draft = {"reports": [doc], "search_results": [{"carrier": "XX", "status": "new_report", "url": doc["source_url"]}],
                         "discovery_results": [{"carrier": "ZZ", "name": "New airline", "source_url": "https://example.org/new-report"}], "discovery_completed": True}
                (ws / "out" / "reports.json").write_text(json.dumps(draft))
                return {"status": "ok"}
            with patch.object(runner, "exec", side_effect=execute), patch.object(runner, "say"), patch.object(C, "evidence", return_value=trusted_evidence), patch.object(C, "catalog", return_value=[{"carrier": "XX", "name": "XX"}]):
                self.assertEqual(runner.reports(), 1)
            draft_path = next((root / "out").glob("reports-*.json"))
            draft = json.loads(draft_path.read_text())
            self.assertEqual(draft["reports"][0]["evidence"], trusted_evidence)
            self.assertEqual(draft["reports"][0]["validation_errors"], [])
            state = json.loads((root / "reports_state.json").read_text())
            self.assertTrue(state["discovery_month"])
            self.assertEqual(state["candidates"][0]["carrier"], "ZZ")
            self.assertNotIn("segment", state["candidates"][0])
            def search_followup(job, ws, task, model):
                assigned = json.loads((ws / "in" / "carriers.json").read_text())
                self.assertIn("ZZ", [row["carrier"] for row in assigned])
                next_draft = {"reports": [], "search_results": [{"carrier": row["carrier"], "status": "unchanged"} for row in assigned]}
                (ws / "out" / "reports.json").write_text(json.dumps(next_draft))
                return {"status": "ok"}
            with patch.object(runner, "exec", side_effect=search_followup), patch.object(runner, "say"), patch.object(C, "evidence", return_value=trusted_evidence), patch.object(C, "catalog", return_value=[{"carrier": "XX", "name": "XX"}]):
                self.assertEqual(runner.reports(), 0)
            with patch.object(master, "DRAFTS_INBOX", root / "out"), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(master._reports_drafts(set()), 2)
            self.assertIn("--accept XX/2025", output.getvalue())
            accepted = C.accept(draft["reports"][0], root / "accepted")
            ctx = {"source_id": "carrier_benchmark"}
            facts = parse(accepted.read_bytes(), ctx)
            self.assertEqual(len(facts), 5)
            self.assertTrue(all(json.loads(f.value_text)["segment"] == "lowcost" for f in facts))
            self.assertTrue(all(json.loads(f.value_text)["report_id"] == "XX2025v1" for f in facts))

    def test_targeted_run_prepares_known_documents_and_reuses_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = A.Runner(home=root)
            doc = report()
            known = [{"carrier": "XX", "name": "Test airline (описание)", "source_url": doc["source_url"]},
                     {"carrier": "YY", "name": "Not assigned"}]
            def execute(job, ws, task, model):
                prepared = json.loads((ws / "in" / "prepared_reports.json").read_text())
                self.assertEqual(len(prepared), 1)
                self.assertEqual(prepared[0]["carrier"], "XX")
                self.assertEqual((ws / prepared[0]["text_file"]).read_text(), doc["evidence"]["text"])
                queries = json.loads((ws / "in" / "search_urls.json").read_text())
                self.assertEqual(len(queries), 2)
                self.assertNotIn("описание", " ".join(queries))
                self.assertIn("СНАЧАЛА", task)
                draft = {"reports": [doc], "search_results": [{"carrier": "XX", "status": "new_report"}]}
                (ws / "out" / "reports.json").write_text(json.dumps(draft))
                return {"status": "ok"}
            with patch.object(runner, "exec", side_effect=execute), patch.object(runner, "say"), patch.object(C, "catalog", return_value=known), patch.object(C, "evidence", return_value=doc["evidence"]) as fetch:
                self.assertEqual(runner.reports(only="XX"), 1)
                self.assertEqual(fetch.call_count, 1)
            state = json.loads((root / "reports_state.json").read_text())
            self.assertNotIn("discovery_month", state)
            self.assertEqual(set(state["checked"]), {"XX"})

    def test_official_supporting_fx_document_is_prepared_and_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = A.Runner(home=root)
            doc = report()
            fx_url = "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?startPeriod=2025-01-01&endPeriod=2025-12-31&format=csvdata"
            fx_text = "FREQ,CURRENCY,CURRENCY_DENOM,TIME_PERIOD,OBS_VALUE\nD,USD,EUR,2025-01-02,1.1\nD,USD,EUR,2025-12-31,1.2"
            for key in ("opex_eur", "fuel_cost_eur"):
                doc["values"][key]["currency"] = "USD"
            doc["values"]["fx_per_eur"] = {"value": 1.15, "basis": "mean USD per EUR, 2 observations for fiscal period", "page": "CSV rows", "quote": "2025-01-02,1.1", "source_url": fx_url}
            known = [{"carrier": "XX", "name": "Test airline", "source_url": doc["source_url"], "supporting_sources": [fx_url]}]
            def fetch(url, directory):
                if url == fx_url:
                    return {"url": url, "text": fx_text, "sha256": "fx-sha"}
                return doc["evidence"]
            def execute(job, ws, task, model):
                prepared = json.loads((ws / "in" / "prepared_reports.json").read_text())
                support = prepared[0]["supporting_sources"][0]
                computed = json.loads((ws / "in" / "prepared_rates.json").read_text())
                self.assertEqual(computed[0]["carrier"], "XX")
                self.assertAlmostEqual(computed[0]["value"], 1.15)
                self.assertEqual(support["source_url"], fx_url)
                self.assertEqual((ws / support["text_file"]).read_text(), fx_text)
                draft = {"reports": [doc], "search_results": [{"carrier": "XX", "status": "new_report"}]}
                (ws / "out" / "reports.json").write_text(json.dumps(draft))
                return {"status": "ok"}
            with patch.object(runner, "exec", side_effect=execute), patch.object(runner, "say"), patch.object(C, "catalog", return_value=known), patch.object(C, "evidence", side_effect=fetch) as fetch_mock:
                self.assertEqual(runner.reports(only="XX"), 1)
                self.assertEqual(fetch_mock.call_count, 2)
            draft = json.loads(next(runner.out.glob("reports-*.json")).read_text())
            self.assertEqual(draft["reports"][0]["validation_errors"], [])
            self.assertEqual(draft["reports"][0]["values"]["fx_per_eur"]["evidence"]["url"], fx_url)

    def test_ecb_fiscal_daily_mean_and_published_annual_mean(self):
        fiscal = "https://data-api.ecb.europa.eu/service/data/EXR/D.GBP.EUR.SP00.A?startPeriod=2024-10-01&endPeriod=2025-09-30&format=csvdata"
        header = "FREQ,CURRENCY,CURRENCY_DENOM,TIME_PERIOD,OBS_VALUE\n"
        text = header + "D,GBP,EUR,2024-10-01,0.8\nD,GBP,EUR,2025-09-30,0.9\n"
        rate = C.ecb_period_mean(fiscal, text)
        self.assertAlmostEqual(rate["value"], 0.85)
        self.assertEqual(rate["count"], 2)
        self.assertEqual(rate["period_start"], "2024-10-01")
        self.assertIn(rate["quote"], text)
        annual = "https://data-api.ecb.europa.eu/service/data/EXR/A.USD.EUR.SP00.A?startPeriod=2025&endPeriod=2025&format=csvdata"
        rate = C.ecb_period_mean(annual, header + "A,USD,EUR,2025,1.13\n")
        self.assertEqual(rate["value"], 1.13)
        self.assertEqual(rate["frequency"], "A")
        dated_annual = annual.replace("startPeriod=2025&endPeriod=2025", "startPeriod=2025-01-01&endPeriod=2025-12-31")
        self.assertEqual(C.ecb_period_mean(dated_annual, header + "A,USD,EUR,2025,1.13\n")["value"], 1.13)
        with self.assertRaises(ValueError):
            C.ecb_period_mean(fiscal, text.replace("GBP,EUR", "GBP,USD"))
        with self.assertRaises(ValueError):
            C.ecb_period_mean(fiscal, text.replace("2025-09-30", "2025-05-30"))

    def test_new_release_without_extraction_stays_due(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = A.Runner(home=root)
            url = "https://example.org/new-report.pdf"
            def execute(job, ws, task, model):
                draft = {"reports": [], "search_results": [{"carrier": "XX", "status": "new_report", "url": url}]}
                (ws / "out" / "reports.json").write_text(json.dumps(draft))
                return {"status": "ok"}
            with patch.object(runner, "exec", side_effect=execute), patch.object(runner, "say"), patch.object(C, "catalog", return_value=[{"carrier": "XX", "name": "Test"}]):
                self.assertEqual(runner.reports(only="XX"), 0)
            state = json.loads((root / "reports_state.json").read_text())
            self.assertNotIn("XX", state["checked"])
            self.assertEqual(state["pending_reports"]["XX"]["url"], url)
            draft = json.loads(next(runner.out.glob("reports-*.json")).read_text())
            self.assertEqual(draft["search_results"][0]["status"], "extraction_failed")

    def test_acceptance_retains_per_value_source_provenance(self):
        from flightcostapp.parsers.carrier_benchmark import parse
        with tempfile.TemporaryDirectory() as directory:
            doc = report()
            fx_url = "https://example.org/official-fx.csv"
            doc["values"]["fx_per_eur"] = {"value": 1.13, "basis": "published annual mean", "page": "CSV 2025", "quote": "2025,1.13", "source_url": fx_url,
                                            "evidence": {"url": fx_url, "text": "year,rate\n2025,1.13", "sha256": "separate-fx-sha"}}
            path = C.accept(doc, directory)
            accepted = yaml.safe_load(path.read_text())
            self.assertEqual(accepted["values"]["fx_per_eur"]["source_sha256"], "separate-fx-sha")
            self.assertNotIn("evidence", accepted["values"]["fx_per_eur"])
            facts = parse(path.read_bytes(), {"source_id": "carrier_benchmark"})
            fx = next(f for f in facts if f.key.endswith("/fx_per_eur"))
            metadata = json.loads(fx.value_text)
            self.assertEqual(metadata["source_url"], fx_url)
            self.assertEqual(metadata["source_sha256"], "separate-fx-sha")
            self.assertEqual(metadata["report_source_url"], doc["source_url"])
            row = next(row for row in C.catalog(directory) if row["carrier"] == "XX")
            self.assertEqual(row["supporting_sources"], [fx_url])

    def test_index_keeps_original_rows_with_line_numbers_and_bounded_windows(self):
        rows = []
        for i in range(100):
            rows.extend([f"Operating expenses {1000 + i} 2025 2024", f"Aircraft fuel {100 + i} 2025 2024",
                         f"Available seat miles {10000 + i} 2025 2024", f"Revenue passenger miles {8000 + i} 2025 2024",
                         f"Passengers carried {100 + i} 2025 2024", "Year ended December 31 2025"])
        text = "\n".join(rows)
        index = C.report_index(text)
        self.assertLessEqual(index.count("=== ") // 2, 30)
        self.assertIn("original lines", index)
        for window in index.split("\n\n"):
            body = window.split("\n", 1)[1]
            self.assertIn(body, text)
            self.assertLessEqual(len(body.splitlines()), 8)

    def test_partial_reports_are_saved_but_not_counted_as_complete_benchmarks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = A.Runner(home=root)
            doc = report()
            del doc["values"]["ask_km"]
            self.assertEqual(C.check_report(doc), [])
            self.assertFalse(C.benchmark_ready(doc))
            def execute(job, ws, task, model):
                prepared = json.loads((ws / "in" / "prepared_reports.json").read_text())
                self.assertTrue((ws / prepared[0]["index_file"]).exists())
                draft = {"reports": [doc], "search_results": [{"carrier": "XX", "status": "new_report", "url": doc["source_url"]}]}
                (ws / "out" / "reports.json").write_text(json.dumps(draft))
                return {"status": "ok"}
            with patch.object(runner, "exec", side_effect=execute), patch.object(runner, "say") as say, patch.object(C, "catalog", return_value=[{"carrier": "XX", "name": "XX", "source_url": doc["source_url"]}]), patch.object(C, "evidence", return_value=doc["evidence"]):
                self.assertEqual(runner.reports(only="XX"), 0)
                self.assertIn("0 полных выписок для CASK, 1 частичных", say.call_args.args[0])
            draft = json.loads(next(runner.out.glob("reports-*.json")).read_text())
            self.assertFalse(draft["reports"][0]["benchmark_ready"])
            self.assertEqual(draft["search_results"][0]["status"], "extraction_failed")
            self.assertIn("XX", json.loads((root / "reports_state.json").read_text())["pending_reports"])

    def test_already_accepted_document_does_not_create_another_report(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = A.Runner(home=Path(directory))
            doc = report()
            known = {key: doc[key] for key in ("carrier", "name", "report_id", "period_end")}
            known["source_sha256"] = doc["evidence"]["sha256"]
            def execute(job, ws, task, model):
                draft = {"reports": [doc], "search_results": [{"carrier": "XX", "status": "unchanged"}],
                         "discovery_results": [], "discovery_completed": True}
                (ws / "out" / "reports.json").write_text(json.dumps(draft))
                return {"status": "ok"}
            with patch.object(runner, "exec", side_effect=execute), patch.object(runner, "say"), patch.object(C, "evidence", return_value=doc["evidence"]), patch.object(C, "catalog", return_value=[known]):
                self.assertEqual(runner.reports(), 0)
            draft = json.loads(next(runner.out.glob("reports-*.json")).read_text())
            self.assertEqual(draft["reports"], [])
            self.assertEqual(len(draft["duplicates"]), 1)

    def test_agent_does_not_advance_unsearched_companies(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = A.Runner(home=Path(directory))
            def execute(job, ws, task, model):
                (ws / "out" / "reports.json").write_text(json.dumps({"reports": [], "search_results": []}))
                return {"status": "ok"}
            with patch.object(runner, "exec", side_effect=execute), patch.object(runner, "say"), patch.object(C, "catalog", return_value=[{"carrier": "XX", "name": "XX"}]):
                self.assertEqual(runner.reports(), 0)
            self.assertFalse((Path(directory) / "reports_state.json").exists())


if __name__ == "__main__":
    unittest.main()
