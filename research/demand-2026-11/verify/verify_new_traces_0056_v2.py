#!/usr/bin/env python3
"""Audit new supply/migrant provenance, quotes and fresh-period access probes."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
from lxml import html

HERE=Path(__file__).resolve().parent
TRACE=HERE.parent/"trace"


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def norm(value):return " ".join(value.split())


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--raw-dir",type=Path,required=True)
    args=parser.parse_args()
    failures=[]; trace_checks=[]; budgets=defaultdict(list)
    cache={}
    for path in args.raw_dir.glob("*.meta.json"):
        m=json.loads(path.read_text())
        payload=path.with_name(path.name.removesuffix(".meta.json")+".raw")
        if payload.exists() and m.get("url"):
            cache[m["url"]]=(payload,m)
    for path in TRACE.glob("*.jsonl"):
        for line in path.read_text().splitlines():
            row=json.loads(line)
            if row.get("quote") and row.get("url"):
                budgets[row["url"]].append((row.get("id"),len(re.findall(r"\S+",row["quote"]))))
    for url,items in budgets.items():
        if sum(count for _,count in items)>25:
            failures.append({"problem":"cumulative quote budget","url":url,"words":sum(n for _,n in items)})
    for filename in ("supply.jsonl","migrant_stock.jsonl"):
        path=TRACE/filename
        for line in path.read_text().splitlines():
            row=json.loads(line); url=row["url"]
            if row["kind"]=="derive":continue
            expected_sha=row.get("sha256") or row.get("source",{}).get("sha256") or row.get("result",{}).get("sha256")
            found=cache.get(url)
            if not found:
                if row["id"]=="ds-001":
                    trace_checks.append({"trace_id":row["id"],"method":"independent primary web open","primary_source_ref":"turn148view0","quote_literal":True,"locator":"Eurostat aviation metadata §3.4, Passengers on board"})
                else:failures.append({"problem":"new trace URL not in source cache","trace_id":row["id"],"url":url})
                continue
            payload,meta=found
            actual_sha=sha(payload)
            if expected_sha and expected_sha!=actual_sha:failures.append({"problem":"trace hash mismatch","trace_id":row["id"]})
            if actual_sha!=meta["sha256"]:failures.append({"problem":"raw metadata hash mismatch","trace_id":row["id"]})
            quote_check=None
            if row.get("quote"):
                if "json" in (meta.get("content_type") or ""):
                    raw=json.loads(payload.read_bytes())
                    source_text=raw.get("label","")
                else:source_text=html.fromstring(payload.read_bytes()).text_content()
                quote_check=norm(row["quote"]) in norm(source_text)
                if not quote_check:failures.append({"problem":"quote not literal","trace_id":row["id"]})
            trace_checks.append({"trace_id":row["id"],"source_sha256":actual_sha,"http_status":meta["status"],"quote_literal":quote_check})
    summary=json.loads((HERE.parent/"out/supply_summary.json").read_text())
    recorded={r["url"]:r for r in summary["primary_access_probes"]}
    probes=[]
    for path in sorted(args.raw_dir.glob("supply_recent_*_CAF_PAS.raw")):
        raw=json.loads(path.read_bytes()); meta=json.loads(path.with_suffix(".meta.json").read_text())
        count=sum(v is not None for v in raw.get("value",{}).values())
        time_index=raw.get("dimension",{}).get("time",{}).get("category",{}).get("index",{})
        row=recorded[meta["url"]]
        if count!=row["published_values"] or max(time_index,default=None)!=row["last_time_axis_period"]:
            failures.append({"problem":"recent-period availability mismatch","url":meta["url"]})
        if meta["sha256"]!=sha(path) or row["sha256"]!=sha(path):failures.append({"problem":"recent-period probe digest","url":meta["url"]})
        probes.append({"url":meta["url"],"http_status":meta["status"],"source_updated_at":raw.get("updated"),"published_values":count,"time_axis_periods":len(time_index),"meaning":"No published cells in this bounded response; not a statement of zero traffic."})
    result={"stage":"0056-v2","status":"pass" if not failures else "fail","independent":True,
            "trace_digests":{f:sha(TRACE/f) for f in ("supply.jsonl","migrant_stock.jsonl")},
            "trace_checks":trace_checks,"cumulative_quote_budgets":[{"url":u,"words":sum(n for _,n in rows),"ids":[i for i,_ in rows]} for u,rows in sorted(budgets.items())],
            "recent_primary_probes":probes,"failures":failures,
            "primary_definition_review":[
                {"url":"https://ec.europa.eu/eurostat/cache/metadata/en/avia_pa_esms.htm","web_reference":"turn148view0","scope":"§3.1 total arrivals/departures; §3.4 flight-stage PAS_BRD includes direct transit while on-flight O&D PAS_CRD excludes it; publication thresholds prevent treating every absent route as zero."},
                {"url":"https://ec.europa.eu/eurostat/cache/metadata/en/demo_pop_esms.htm","web_reference":"turn148view1","scope":"Population on 1 January, country of birth distinct from citizenship; §6.1 individual-country detail is voluntary, §7.2 describes German estimation/confidentiality; revised census data and status flags affect comparability."}
            ],
            "limitations":["A successful primary singleton or limited-period response does not verify every archival route or establish 2025–2026 traffic coverage.","The new country-of-birth source is an official Eurostat collection. It is not the inaccessible UN bilateral file and does not remove global/DE coverage gaps."]}
    (HERE/"new_traces_0056_v2.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(result["status"],len(trace_checks),"trace records;",len(probes),"recent probes;",len(failures),"failures")


if __name__=="__main__":main()
