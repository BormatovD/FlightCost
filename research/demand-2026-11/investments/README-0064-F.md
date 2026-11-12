# 0064-F — Reconciling IATI evidence without inventing physical assets

**Research only.** Does not touch FlightCost production, Datastore API, SSH secrets, the airport charges database or the route calculator. The code is a standalone stdlib Python script; no new service.

## Why this exists

IATI identifiers are **activity reports**, not necessarily independent physical investment sites. The exporter in 0064-D provided 240 activities and 48 directed parent/child relations (24 distinct parent/child edges). The 0063/0064-B Datastore pilot has 242 reported versions of 239 identifiers. Matching these two snapshots yields 27 common identifiers and 452 unique IATI IDs.

The difference matters for financial interpretation: two disbursements under parent/child activities, two publishers discussing the same port, and two unrelated stages of construction must **never** be blindly summed or collapsed.

IATI related-activity type definitions: 1 = parent; 2 = child; 3 = sibling; 4 = co-funded; 5 = third-party report of an activity. The script creates *evidence families* only from explicit 1/2 relations; families are not verified unique construction sites. Type 3/4/5 are retained as relationship evidence, **not automatically merged**.

References: https://reference.iatistandard.org/en/iati-standard/203/codelists/relatedactivitytype/ and https://reference.iatistandard.org/en/iati-standard/203/activity-standard/iati-activities/iati-activity/location/

## Outputs

- `manifest.json`: counts, SHA-256 fingerprints of all inputs, and explicit negative claims (`physical_assets_verified: 0`, `finance_aggregation_performed: false`, `airport_assignment_performed: false`, `historical_as_of_validated: false`). The as-of date is the supplied observation date **not** historical availability proof.
- `activity_identity.csv`: one row per IATI identifier; records which source(s) reported it; source-version conflicts and discrepancies in title, status or planned end.
- `relation_evidence.csv`: IATI relation codes and source evidence (embedded or relations.json), **no assumption of physical sameness**.
- `evidence_families.csv`: connected components of explicit parent/child edges; a family can represent one programme, several financing components or several physical facilities.
- `future_asset_review.csv`: families with status 1/2 and an *unverified* planned end in 2027–2036. Do not interpret these as confirmed new assets or automatically valid projects.
- `review_link_suggestions.csv`: candidates inferred from shared country, sector and distinctive name tokens; only two different-publisher title suggestions in the four-country pilot; all require human review. Similar titles can refer to a port and the adjacent business park, two stages, different grants etc.
- `manual_curation_template.csv`: blank human-review fields for asset scope, *externally supported* location, construction stage, capacity, date, reviewer and citations. The script **never accepts or applies** these fields.

All outputs are created in a private directory (0700) with file mode 0600; no key handling. No network calls. No business data included in the patch.

## Apply (on Mac)

The 0064-F patch **adds only three files** under `research/demand-2026-11/investments/`; it should apply on top of the owner-tested 0064-E.

```sh
git apply --check ~/Downloads/0064-F-project-linkage.patch
git apply ~/Downloads/0064-F-project-linkage.patch
python -m unittest discover -s research/demand-2026-11/investments -p 'test_*.py' -q
git diff --check
git add research/demand-2026-11/investments/project_linkage.py \
        research/demand-2026-11/investments/test_project_linkage.py \
        research/demand-2026-11/investments/README-0064-F.md
git commit -m 'Build conservative IATI project linkage review'
git push origin main
```

## Server — no API usage, after green CI deployment

Run as `agent`, based on the *existing* downloaded files, not a fresh IATI fetch:

```sh
sudo systemd-run --wait --pipe --collect \
  --unit=fca-iati-linkage-0064f \
  -p User=agent \
  -p WorkingDirectory=/srv/fca/app \
  /bin/sh -c '
set -eu
base=/srv/fca/agent/research/iati
bulk=$(find "$base/bulk" -maxdepth 1 -type d -name "structured-*" | sort | tail -n 1)
test -n "$bulk"
exec /srv/fca/venv/bin/python \
  /srv/fca/app/research/demand-2026-11/investments/project_linkage.py \
  --bulk "$bulk/candidates.jsonl" \
  --relations "$bulk/relations.json" \
  --datastore "$base/20261112T193852Z-pilot/candidates.jsonl" \
  --datastore "$base/20261112T065143Z-KE/candidates.jsonl" \
  --as-of 2026-11-12 \
  --out "$base/linked-0064f"'
```

Expected summary for the *current* snapshots: 482 source records, 452 unique IDs, 27 cross-source overlapping IDs, 428 evidence families, 17 non-singleton families, 68 future-active evidence families, 45 title suggestions (2 cross-publisher; 43 same-publisher). All counts are snapshot-specific; do not blindly assert them for newer data.

The generator does **not** write to `/srv/fca/master/flightcost.db` or the investment evidence.sqlite; that is intentional. Review and accept facility claims as a separate step when **independent published evidence** is attached. Output is research, not an announcement of passenger demand.

To copy only the small report artifacts from the server, as root:

```sh
sudo bash <<'SH'
set -euo pipefail
umask 077
base=/srv/fca/agent/research/iati/linked-0064f
out=/home/deploy/iati-linked-0064f.tar.gz
tar -czf "$out" -C "$base" manifest.json activity_identity.csv \
    relation_evidence.csv evidence_families.csv future_asset_review.csv \
    review_link_suggestions.csv manual_curation_template.csv
chown deploy:deploy "$out"
chmod 600 "$out"
SH
```

On Mac: `scp deploy@178.253.52.205:/home/deploy/iati-linked-0064f.tar.gz ~/Downloads/`.

## Next (0064-G, not in this patch)

For the most relevant future candidates, find independent project construction notices, asset location (point, area, or unknown), phased commissioning and published capacity; create an approved manual decision ledger with *known_as_of*. Only then explore ground travel times to **multiple** competing airports. Compare investment-derived features to route baseline on historical holdouts before using them in the 2029/2031/2036 forecast.
