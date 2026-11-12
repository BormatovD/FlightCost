# 0064-C: bounded IATI Bulk XML pilot (no Datastore API)

This is an **additional research layer**, not a production integration or a world-wide scraper. It is intended to follow 0064-A and 0064-B; airport charges patches 0065–0066 are independent.

## Findings from the owner's real pilot archive (12 November 2026)

- Minimal dataset index: **13,803 publication files**, 2,139 reporting publisher short names, **zero explicit recipient-country/sector fields**. Every entry has `short_name`, `reporting_org_short_name`, `last_known_good_dataset.cached_dataset_url_xml`, `hash_excluding_generated_timestamp` and a source link.
- The four-country Datastore snapshots: **242 raw activity versions**, **239 distinct IATI identifiers**, **three conflicting IDs** (KE 1, CV 2). They do *not* represent 239 verified investment objects.
- **132/242** activity versions have any `location`; **110/242** have none. **Zero** locations explicitly labelled IATI class 3 (`Structure`). Of the 242 versions, **28** have at least one candidate populated place with coordinates and not classified as beneficiary-only; this does not verify a physical project site.
- **52** current `Implementation` rows have a *planned* end date before the snapshot. Status and dates require consistency checks.
- Project-specific duplicates across **different** IATI IDs occur, e.g. Morocco RER/LGV (AFD parent/child), Cabo Verde Port Ingles/Palmeira (different publishers), Kenya Mombasa SEZ (two components). Do not aggregate these financial figures by naive ID.
- **2,381** budget entries and **2,958** transaction entries are separate financial records in mixed currencies, periods and stages, not combined project budgets.

## What this patch adds

- `bulk_seed.py` accepts an **explicit list of exact dataset short_names** from the locally cached minimal index; it refuses a missing, duplicate or ambiguous dataset.
- By default it prints a plan and **does not connect to the network**.
- With `--download`, it fetches only the official HTTPS `bulk-data.iatistandard.org/...xml` cache, at most **3** named datasets by default and at most **25 MB per file / 60 MB per invocation**. It rejects redirects away from the approved host and keeps partial downloads out of the cache.
- Only on a successfully received XML document, it locally scans IATI activity identifiers, country codes, sector vocabulary and codes, status, dates, locations, related IATI activities; source XML remains archived private. The scanner does NOT assign airports, convert money, guess missing countries, or claim a full market inventory.
- Repeated runs with unchanged upstream `hash_excluding_generated_timestamp` and unchanged local SHA256 reuse local files without network transfer.
- Added offline tests; no key, OpenClaw, new service, system timer, third-party modules or Datastore quota.

## Exact publisher files present in the reviewed index

The short names below were checked against the owner's actual 13,803-row index, **not inferred by replacing country codes in a pattern**:

| Publisher | Kenya | Tanzania | Morocco | Cabo Verde |
|---|---|---|---|---|
| African Development Bank | `afdb-kenya` | `afdb-tanzania` | `afdb-morocco` | `afdb-capeverde` |
| AFD | `afd-ke` | `afd-tz` | `afd-ma` | `afd-cv` |
| World Bank | `worldbank-ke` | `worldbank-tz` | `worldbank-ma` | `worldbank-cv` |
| EC-INTPA | `ec-intpa-ke` | `ec-intpa-tz` | *no exact file found* | `ec-intpa-cv` |

**These filenames are publisher hints, not proof of recipient country or completeness.** Projects may also be in multinational or differently named publications; the scanner uses the XML recipient-country fields, not the filename, to assign country-level coverage. It does not silently exclude records in other sector code vocabularies.

## Apply on Mac

From the repository root, after 0064-B:

```bash
git apply --check ~/Downloads/0064-C-bulk-seed.patch
git apply ~/Downloads/0064-C-bulk-seed.patch
python -m unittest discover -s research/demand-2026-11/investments -p 'test_*.py' -q
git diff --check
git add research/demand-2026-11/investments/
git commit -m "Add bounded IATI Bulk source XML scanner"
git push origin main
```

Wait for CI and the existing deploy. Do not repeat `bootstrap.sh`.

## Server: first plan (offline, no key)

Run from an admin session. The `agent` user already owns `/srv/fca/agent/research/iati`.

```bash
sudo systemd-run --wait --pipe --collect \
  --unit=fca-iati-bulk-plan-0064c \
  -p User=agent -p WorkingDirectory=/srv/fca/app \
  /srv/fca/venv/bin/python \
  /srv/fca/app/research/demand-2026-11/investments/bulk_seed.py \
  --index /srv/fca/agent/research/iati/datasets-minimal.json \
  --out /srv/fca/agent/research/iati/bulk \
  --names afdb-morocco,afd-tz,worldbank-cv
```

Examine the URLs and hashes in the printed JSON. This must report `network_requested: false` and **must not** create a `bulk` directory or use the IATI subscription.

## Server: bounded 3-file pilot (public XML GET, no API key)

After a successful plan, use the **same** invocation with `--download`:

```bash
sudo systemd-run --wait --pipe --collect \
  --unit=fca-iati-bulk-pilot-0064c \
  -p User=agent -p WorkingDirectory=/srv/fca/app \
  /srv/fca/venv/bin/python \
  /srv/fca/app/research/demand-2026-11/investments/bulk_seed.py \
  --index /srv/fca/agent/research/iati/datasets-minimal.json \
  --out /srv/fca/agent/research/iati/bulk \
  --names afdb-morocco,afd-tz,worldbank-cv \
  --countries KE,TZ,MA,CV --download
```

Source XML files are private in `bulk/raw/*.xml`. Extracted records are saved as `<short_name>.scan.json` **only after a complete XML scan**. Each file includes the publisher dataset ID, IATI ID, countries, sectors, stages, dates, location descriptors, and relationships to other IATI IDs, but no financial totals. A missing recipient country is counted separately; it is not inferred from the publisher filename.

If the download hits the 25 MB per-file limit, stop. Do not blindly increase caps or loop through all 13,803 datasets; use smaller seed files first.

## Important limitations before any demand estimate

- No historical `as-of` replay: this is a 12 Nov 2026 snapshot, not evidence that all attributes were public on historical forecast dates.
- Publisher datasets overlap and may contain IATI activities also returned by the Datastore. They are **additional sources/versions**, not new investments until canonical reconciliation.
- Raw XML has financial and geocoding structures that this small scanner intentionally leaves untouched. The next step is to match IATI IDs to the existing `evidence.sqlite`, resolve parent/child/source relationships, and then inspect source-confirmed locations and project states.
- This source-index selection only covers an **explicit allowlist**, not all projects in the four countries or the world.
