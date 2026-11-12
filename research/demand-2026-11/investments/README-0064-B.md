# 0064-B — Start controlled IATI collection

**Scope:** Research-only. No new cron, service, paid geocoding, secrets, production DB, models, demand coefficients or calls to OpenAI. This patch follows **0061 → 0062 → 0063 → 0064-A**, and is independent of the airport-charge patches.

## Changes

- `iati_fetch.py`: every authenticated Datastore HTTP request (including `--probe`) **requires** `--budget-db` and reserves its quota *before* the network call. HTTP failures, timeouts and invalid payloads are counted; HTTP 429 records `Retry-After`, if supplied. Log messages never include the API key. No full-country claim without a stable sort: only `--max-pages 1` allowed for the pilot. The existing multi-country raw snapshots, variant hashes, conflict handling and strict private output rights remain.
- `usage_budget.py`: one shared SQLite ledger, exclusive locking across processes, atomic HTTP-429 embargo, `0600` ledger; reject symlinks or insecure existing files. Defaults: **5/min, 100/24h, 100/7d**. Hard cap: at most 5/min and 100/7d in `iati_fetch`, regardless of CLI parameters.
- The original `catalogue.py` from 0064-A already downloads the public official JSON index without an API key. This patch does not introduce a bulk ZIP downloader or infer project sectors from publisher metadata.
- Added offline regression tests, updated the old API README and SCHEMA.

**Limitations:** This ledger has no knowledge of requests sent before 0064-B or by other programs. Use the **same absolute ledger path for every future Datastore job**, and monitor the account's real quota in its API developer portal. The dataset index alone is not yet a list of relevant investment projects; it is a planning input for subsequent selective bulk XML source downloads. Downloaded Datastore pages are **partial samples** unless explicitly verified otherwise. No historical `as-of` evidence yet.

## 1. On Mac: apply the patch

From the repository root after 0064-A:

```bash
git apply --check ~/Downloads/0064-B-budgeted-collection.patch
git apply ~/Downloads/0064-B-budgeted-collection.patch
python -m unittest discover -s research/demand-2026-11/investments -p 'test_*.py' -q
git diff --check
```

Then commit, push, allow existing CI/deploy to complete; verify the server has the patch:

```bash
git add research/demand-2026-11/investments
git commit -m 'Budget IATI collection and start a controlled pilot'
git push origin main
ssh deploy@178.253.52.205 bash /srv/fca/app/deploy/deploy.sh
```

Do not re-run bootstrap and do not change permissions on `/etc/fca/iati.key`.

## 2. Server: prepare the research directory

Run on the **current Ubuntu server** with sudo (not on Mac):

```bash
sudo install -d -o agent -g agent -m 0700 /srv/fca/agent/research/iati
```

### First: fetch the *global metadata index*, no IATI key, no subscription calls

```bash
sudo systemd-run --wait --pipe --collect \
  --unit=fca-iati-catalogue-0064b \
  -p User=agent -p WorkingDirectory=/srv/fca/app \
  /srv/fca/venv/bin/python \
  /srv/fca/app/research/demand-2026-11/investments/catalogue.py \
  --cache /srv/fca/agent/research/iati/datasets-minimal.json --refresh-index
```

Expected: a JSON summary of the dataset count, known/unknown sector metadata, SHA256 and bytes. If the upstream index schema has changed, stop and show the error; do **not** automatically download the worldwide ZIP. Inspect only the shape, not the full 15+ MB file. This is a current publisher-file catalog, not an investment table.

### Then: 3-country API pilot, three requests at most

This intentionally does **not** repeat Kenya, whose partial sample was already archived. Test Tanzania (TZ), Morocco (MA) and Cabo Verde (CV), 80 rows per country (one page). A call with no `--budget-db` is refused. This command uses the existing systemd credential and does not reveal it to the model or command line.

```bash
sudo systemd-run --wait --pipe --collect \
  --unit=fca-iati-pilot-0064b \
  -p User=agent -p WorkingDirectory=/srv/fca/app \
  -p LoadCredential=iati:/etc/fca/iati.key \
  /bin/sh -c 'exec /srv/fca/venv/bin/python \
    /srv/fca/app/research/demand-2026-11/investments/iati_fetch.py \
    --key-file "$CREDENTIALS_DIRECTORY/iati" \
    --budget-db /srv/fca/agent/research/iati/api-budget.sqlite \
    --countries TZ,MA,CV --rows 80 --max-pages 1 --pause 13 \
    --out "/srv/fca/agent/research/iati/$(date -u +%Y%m%dT%H%M%SZ)-pilot"'
```

On HTTP 401/403/429 or budget exhaustion, **stop**; don't loop/retry. A failed run can leave raw pages but no manifest; it isn't a complete snapshot and must not be ingested as such.

Inspect the shared quota ledger (doesn't use a key or issue requests):

```bash
sudo -u agent /srv/fca/venv/bin/python \
  /srv/fca/app/research/demand-2026-11/investments/usage_budget.py \
  --db /srv/fca/agent/research/iati/api-budget.sqlite
```

The pilot output prints its folder path (e.g. `...-pilot`). Import its `candidates.jsonl` into a separate research registry, NOT into the production `flightcost.db`:

```bash
sudo -u agent /srv/fca/venv/bin/python \
  /srv/fca/app/research/demand-2026-11/investments/registry.py \
  --db /srv/fca/agent/research/iati/evidence.sqlite \
  --candidates /srv/fca/agent/research/iati/REPLACE_WITH_ACTUAL_PILOT_DIR/candidates.jsonl
```

In the final command, replace `REPLACE_WITH_ACTUAL_PILOT_DIR` with the folder name printed by the fetcher. If you have the earlier Kenya `candidates.jsonl`, import it **separately** with the same registry DB, without re-requesting the API. The registry deduplicates stable source variants.

## 3. Share outputs without credentials

The stdout from `catalogue.py`, `iati_fetch.py` and `usage_budget.py` is usually sufficient for a first health check. To analyse projects, export **only the new pilot snapshot** (no `/etc/fca` files):

```bash
sudo bash <<'SH'
set -euo pipefail
umask 077
base=/srv/fca/agent/research/iati
name=$(find "$base" -mindepth 1 -maxdepth 1 -type d -name '*-pilot' -printf '%f\n' | sort | tail -1)
[ -n "$name" ] && [ -s "$base/$name/manifest.json" ] || { echo 'No complete pilot'; exit 1; }
tar -czf /home/deploy/iati-0064b-pilot.tar.gz -C "$base" "$name"
chown deploy /home/deploy/iati-0064b-pilot.tar.gz
chmod 600 /home/deploy/iati-0064b-pilot.tar.gz
ls -lh /home/deploy/iati-0064b-pilot.tar.gz
SH
```

Then on Mac: `scp deploy@178.253.52.205:/home/deploy/iati-0064b-pilot.tar.gz ~/Downloads/` and upload it to the research chat. The full index is not needed for the initial project audit; share its metadata summary only. No key should appear in either archive.

## 4. What this does not prove

- 80 retrieved rows do not establish country completeness or financial totals.
- IATI aid/development finance ≠ the global private-investment universe.
- A country coordinate ≠ the project site; no automatic airport assignment.
- An IATI reporting activity's status or date ≠ guaranteed start/completion.
- No route passenger-demand prediction or calculator changes in this stage.

After reviewing the first three-country pilot and actual index metadata, implement selective cached XML downloads for the most relevant datasets; **no world-scale API enumeration** without stable sorting and a verified budget.
