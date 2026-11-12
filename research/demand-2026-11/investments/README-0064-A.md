# 0064-A — Global investment evidence foundation (offline)

This research patch adds `registry.py`, `georesolve.py`, `gazetteer_from_tail.py`, `catalogue.py`, `usage_budget.py`, `SCHEMA.md`, and offline tests. It is independent of the previously discussed airport-tariff patches 0065/0066 and does **not** change the site, production database, calculators, the existing IATI fetcher, API key location, systemd timers or OpenClaw.

### Kenya outcome already tested, from the owner's 12 Nov snapshot

Input: 30 candidate source rows, 29 distinct identifiers, one conflicting identifier. Output from `registry.py`: 30 variants / 29 projects / one conflict / zero automatic airport assignments. It also preserved 225 finance/budget records and 115 event rows (85 reported activity dates plus 30 status observations). As all source variants are retained, there is no de-duplicated sum of finance.

### Run

```sh
python -m unittest discover -s research/demand-2026-11/investments -p 'test_*.py' -q
mkdir -p analysis/investments/kenya
# Put previously downloaded candidates.jsonl here (do not re-query IATI).
python research/demand-2026-11/investments/registry.py \
  --db analysis/investments/evidence.sqlite \
  --candidates analysis/investments/kenya/candidates.jsonl
```

`catalogue.py --cache analysis/investments/catalogue-minimal.json` requires a previously saved index. Only `--refresh-index` downloads the **index**, never the giant worldwide ZIP.

The uploaded `demand-tail-20261112.jsonl.gz` is used **only** to build an offline
34,120-row GeoNames city gazetteer (no routes or user data are copied into this
register). Use:

```sh
python research/demand-2026-11/investments/gazetteer_from_tail.py \
  --tail analysis/demand-tail-20261112.jsonl.gz \
  --out analysis/investments/cities.csv
```

`usage_budget.py` can inspect and reserve a shared budget, but the old IATI client is not yet wired to it; **do not launch a multi-country collection relying on these limits**.
