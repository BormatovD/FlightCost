"""Карта рассуждений ТОиР: trace/*.jsonl + result/*.json + verify/*.json -> map.html."""
import json, pathlib, html
HERE = pathlib.Path(__file__).resolve().parent
steps = []
for p in sorted((HERE / "trace").glob("*.jsonl")):
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            s = json.loads(line)
        except ValueError:
            steps.append({"id": f"{p.stem}-bad", "kind": "gap", "note": "битая строка журнала: " + line[:200]})
            continue
        s.setdefault("agent", p.stem)
        steps.append(s)
results = {p.stem: json.loads(p.read_text()) for p in sorted((HERE / "result").glob("*.json"))}
for p in sorted((HERE / "fleet").glob("*.json")) if (HERE / "fleet").exists() else []:
    f = json.loads(p.read_text()); c = f.get("carrier") or p.stem
    r = results.setdefault(c, {"carrier": c})
    r["fleet_a4"] = f.get("fleet", [])
    r.setdefault("gaps", []).extend("парк: " + g for g in f.get("gaps", []))
if (HERE / "policy" / "a5.json").exists():
    NM = {"US": "US Airways", "HP": "America West", "CO": "Continental", "NW": "Northwest", "FL": "AirTran", "VX": "Virgin America",
          "XE": "ExpressJet", "OH_Comair": "Comair", "CP_Compass": "Compass", "XJ_Mesaba": "Mesaba", "S5_Shuttle_America": "Shuttle America",
          "RP_Chautauqua": "Chautauqua"}
    for k, v in json.loads((HERE / "policy" / "a5.json").read_text()).items():
        if k.startswith("_"): continue
        r = results.setdefault(k, {"carrier": k, "name": NM.get(k, k)})
        r["policy_periods"] = [{"годы": f"{p.get('from')}–{p.get('to')}", "policy": p.get("policy"), "detail": p.get("detail", ""), "evidence": p.get("evidence", [])} for p in v]
verify = {}
for p in sorted((HERE / "verify").glob("*.json")) if (HERE / "verify").exists() else []:
    for k, v in json.loads(p.read_text()).items():
        verify[k] = v
rows = json.loads((HERE / "f41_rows.json").read_text())
mature = json.loads((HERE / "mature.json").read_text()) if (HERE / "mature.json").exists() else None
fin = {k: (json.loads((HERE / f"model2_{k}.json").read_text()) if (HERE / f"model2_{k}.json").exists() else None) for k in ("ppi", "cpi")}
for f in fin.values():
    if f:
        f.pop("gamma", None)
        for t in f["types"].values():
            t["rows"] = [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in p.items()} for p in t["rows"]]
if fin["cpi"]:
    for t in fin["cpi"]["types"].values(): t["rows"] = []
pending = None if (HERE / "policy" / "a5.json").exists() else "Предварительно: учётная политика выбывших перевозчиков (US Airways, Continental, Northwest, AirTran, Virgin America, ExpressJet и др.) ещё проверяется — их строки пока в расчёте."
data = {"pending": pending, "final": fin["ppi"], "final_cpi": fin["cpi"], "steps": steps, "results": results, "verify": verify, "rows": rows, "mature": mature}
tpl = (HERE / "map_tpl.html").read_text()
out = tpl.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
(HERE / "map.html").write_text(out)
print("steps", len(steps), "results", len(results), "verify", len(verify))
