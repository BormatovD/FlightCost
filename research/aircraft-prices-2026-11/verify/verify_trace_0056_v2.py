#!/usr/bin/env python3
"""Check retained external-source audit hashes and new local-code quotations."""
from collections import defaultdict
import argparse
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TRACE = HERE.parent / "trace"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def norm(text):
    return " ".join(text.split())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--openap-root", type=Path, required=True)
    args = parser.parse_args()
    failures, quote_checks = [], []
    by_url = defaultdict(list)
    for path in TRACE.glob("*.jsonl"):
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if row.get("quote") and row.get("url"):
                by_url[row["url"]].append((path.name, row.get("id"), row["quote"]))
    budgets = []
    for url, rows in sorted(by_url.items()):
        count = sum(len(re.findall(r"\S+", quote)) for _, _, quote in rows)
        budgets.append({"url": url, "quote_words_total": count, "trace_ids": [x[1] for x in rows]})
        if count > 25:
            failures.append({"problem": "quote budget exceeded", "url": url, "words": count})
    path = TRACE / "model_reference.jsonl"
    for line in path.read_text().splitlines():
        row = json.loads(line)
        if "/blob/" in row["url"]:
            rel = row["url"].split("/blob/", 1)[1].split("/", 1)[1]
            source = ROOT / rel
            literal = norm(row["quote"]) in norm(source.read_text())
        elif row["url"] == "https://pypi.org/project/openap/2.6.2/":
            source = args.openap_root / "data/aircraft/a20n.yml"
            literal = norm(row["quote"]) in norm(source.read_text())
        else:
            literal = False
            source = None
        quote_checks.append({"id": row["id"], "literal_after_whitespace_normalization": literal,
                             "checked_against": rel if "/blob/" in row["url"] else "installed OpenAP 2.6.2 a20n.yml",
                             "source_sha256": sha(source) if source else None})
        if not literal:
            failures.append({"problem": "new quote not found", "id": row["id"]})
    retained = []
    prior = json.loads((HERE / "lease_economics_sources_0056.json").read_text())
    current = sha(TRACE / "lease_economics.jsonl")
    retained.append({"prior_audit": "lease_economics_sources_0056.json", "prior_status": prior["status"],
                     "trace_unchanged": current == prior["trace_sha256"], "trace_sha256": current})
    if current != prior["trace_sha256"]:
        failures.append({"problem": "external lease trace changed; prior source audit no longer sufficient"})
    result = {"stage": "0056-v2", "status": "pass" if not failures else "fail", "independent": True,
              "method": "Literal local-primary-code checks and cumulative quotation budget across all price-research traces. Prior external-source verification is retained only for the exact unchanged trace digest.",
              "new_trace_sha256": sha(path), "new_quote_checks": quote_checks,
              "url_quote_budgets": budgets, "retained_source_audits": retained, "failures": failures,
              "limitations": ["This update does not claim new HTTP retrieval of the unchanged 0056 financial source set.",
                              "The OpenAP quotation is checked against the pinned installed data file, not asserted to appear verbatim on the PyPI landing page."]}
    (HERE / "trace_0056_v2.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(result["status"], len(quote_checks), "new quotations;", len(budgets), "URL budgets;", failures)


if __name__ == "__main__":
    main()
