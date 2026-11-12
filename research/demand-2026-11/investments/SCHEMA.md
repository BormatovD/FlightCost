# Investment evidence registry, FlightCost 0064-A

**Status: research-only, not a tariff fact, not production, not a route forecast.**
Implements first offline portion of `0064-global-investment-demand-architecture.md` as standalone Python stdlib scripts. The owner-approved spec is a separate document, `0064-global-investment-demand-architecture.md`; it need not be in the repository.

## Data contract

- `project`: IATI publisher identifier and project identifier treated as a *candidate grouping*, **not a financial sum**; multiple source versions may refer to the same IATI identifier. `variant_conflict=1` makes review mandatory.
- `project_source`: an **immutable** source variant keyed by `source_id:iati_identifier:source_variant_sha256`. Original normalized candidate JSON is retained. Original HTTP bodies live separately under `raw/` from `iati_fetch.py`, not copied into the database.
- `source_sighting`: the same variant seen at different snapshot times; new sightings do not overwrite old ones.
- `project_sector` and `project_country`: multi-valued per source variant. Missing vocabulary or location is not replaced with an invented fact.
- `project_event`: activity dates (`planned_start`, `actual_start`, `planned_end`, `actual_end`) and a **reported status observation**. `reported_activity_status` has `event_date=NULL`: status code 5 reports cancellation at observation time, but does not establish when cancellation occurred.
- `project_finance`: transactions and budgets as **separate rows**, with original decimal strings, currency, dates and transaction-kind code. There is intentionally **no aggregation** or currency conversion view; comparing, adding, or summing 2 publisher variants is disallowed pending review.
- `project_location`: preserve all reported locations, `location-reach`, `exactness`, `location-class`, method, and candidate list. A single recipient country with no locations produces a **country scope with NULL coordinates**, not a fake capital or centroid. A reported point is not a verified site.
- `project_airport_exposure`: **empty by design**. Future analysis must support multiple competing airports, ground access, passenger origin and uncertainty; nearest airport is not an accepted proxy.
- `forecast_feature`: **empty by design**. Only historical information with verified `available_as_of` can contribute to backtesting.

## Temporal integrity

`known_as_of = snapshot_at` for imported activity dates and financial items. An event date in 2018 is **not** evidence that the activity was publicly known in 2018: even `reported_last_updated_at` cannot prove it. Historical evaluation requires archival publication evidence, which the 0063 Kenya snapshot does not have.

## Geography quality

| Current quality | Meaning | Automatic assignment to airport |
| --- | --- | --- |
| `site_candidate_unverified` | IATI reports a structure, not externally verified | **No** |
| `settlement_resolved` | IATI settlement point, or unique country-scoped gazetteer name | **No** |
| `admin_region_unresolved` | IATI class 1 administrative area, possibly accompanied by point | **No** |
| `country_only` | Only single known recipient country, no point | **No** |
| `point_unclassified` | Coordinate without trusted location class | **No** |
| `unknown` / `unresolved` | No safe match, ambiguous or multiple countries | **No** |

Reach `2` means target beneficiaries; never interpret such a location as a building site. Reach `1` indicates an activity location, but is **not** a guarantee that the point represents a unique structure. A local gazetteer is optional CSV with `country_iso2,name,lat,lon[,id]`; duplicate names generate candidate ambiguity, never a first-result selection.

Official references: [IATI Location](https://iati-standard.readthedocs.io/en/latest/activity-standard/iati-activities/iati-activity/location.html), [GeographicLocationClass](https://iati-standard.readthedocs.io/en/latest/codelists/GeographicLocationClass.html).

### Reusing the current FlightCost city export

`gazetteer_from_tail.py` reads only the `geonames_cities` facts from the supplied
`demand-tail-20261112.jsonl.gz` and builds `analysis/investments/cities.csv`.
The current export yielded 34,120 unique city rows across 210 country codes;
122 belong to Kenya. These city coordinates are **not** the locations of
investment projects; they are only country-disambiguated candidate references.

```sh
python research/demand-2026-11/investments/gazetteer_from_tail.py \
  --tail analysis/demand-tail-20261112.jsonl.gz \
  --out analysis/investments/cities.csv
python research/demand-2026-11/investments/registry.py \
  --db analysis/investments/iati-evidence.sqlite \
  --candidates analysis/investments/kenya/candidates.jsonl \
  --gazetteer analysis/investments/cities.csv
```

## API and index budget

`catalogue.py` defaults to **offline**. Its only optional HTTP action is `--refresh-index`, which fetches the official JSON dataset index but **never downloads the worldwide bulk ZIP**. An index alone is generally insufficient to determine each activity's sector and country. The fetch operation is *not* an IATI Datastore v3 key-bearing request.

`usage_budget.py` is a **fail-closed shared ledger**, conservatively defaulting to 5 calls/minute, 100 calls/24 h and 100 calls/7 d. As of **0064-B** it is wired to `iati_fetch.py`: every real Datastore request, including `--probe` and failed requests, requires `--budget-db` and reserves an attempt beforehand. HTTP 429 respects `Retry-After`. The user MUST supply the same absolute private database path for all jobs; pre-0064-B calls and other API clients are not visible to the ledger. Unstable multi-page Datastore pagination remains disabled (`--max-pages 1`).

Neither this registry nor `usage_budget.py` copies any API key. Keep `analysis/` (database, cache and raw dumps) out of Git; do not put credentials under `/srv/fca/app` or in HTTP query strings. Keep systemd `LoadCredential` for key material.

## First smoke test (no network, no effect on production)

From the repository root with the 0063 IATI source scripts already installed:

```sh
python -m unittest discover -s research/demand-2026-11/investments -p 'test_*.py' -v
python research/demand-2026-11/investments/registry.py \
  --db analysis/investments/iati-evidence.sqlite \
  --candidates analysis/investments/kenya/candidates.jsonl
python research/demand-2026-11/investments/usage_budget.py \
  --db analysis/investments/iati-budget.sqlite
```

The second command needs the **already exported** Kenya `candidates.jsonl`, not a fresh API request. Repeating it is idempotent. Do not use `--reserve` when just inspecting usage.

## Not yet implemented

- Connecting `iati_fetch` and all future API clients to `usage_budget` (no live HTTP until connected).
- Checking the production shape of the IATI full/minimal index on a downloaded sample; the current JSON inspection supports a set of common index container formats but has not been validated against the large live response.
- Datasets delta download with ETag, safe XML iteration and validation; no global bulk download yet.
- Historical publication snapshots, private FDI/World Bank PPI/hotel capacity, on-ground catchment and causal route validation.

This deliberately implements the conservative *foundation*, not claims of complete global collection.
