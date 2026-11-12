#!/usr/bin/env python3
"""Read a dated public investment snapshot. Research only; never infer air traffic.

Example: python research/demand-2026-11/investments/pilot.py --as-of 2026-11-12
Do NOT run this as a forecast of passenger demand or aggregate it by airport.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SNAPSHOT = ROOT / "hotel_pipeline_africa_2026.csv"


def load_hotels(path: Path = SNAPSHOT) -> list[dict[str, Any]]:
    """Validate aggregate country observations, keeping *publication date*."""
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    seen = set()
    cleaned = []
    for index, item in enumerate(rows, start=2):
        country = item["country_iso3"].strip()
        if len(country) != 3 or not country.isalpha() or country != country.upper():
            raise ValueError(f"row {index}: invalid ISO3 country")
        if country in seen:
            raise ValueError(f"row {index}: duplicate country {country}")
        seen.add(country)
        fields = {}
        for name in ("hotels_pipeline", "rooms_pipeline", "rooms_under_construction"):
            fields[name] = int(item[name])
            if fields[name] < 0:
                raise ValueError(f"row {index}: negative {name}")
        if fields["rooms_under_construction"] > fields["rooms_pipeline"]:
            raise ValueError(f"row {index}: construction exceeds pipeline")
        published = date.fromisoformat(item["source_published_at"])
        if not item["source_url"].startswith("https://"):
            raise ValueError(f"row {index}: source must be public https URL")
        cleaned.append({
            "country_iso3": country,
            "country_name_en": item["country_name_en"],
            **fields,
            "source_published_at": published.isoformat(),
            "source_url": item["source_url"],
        })
    if not cleaned:
        raise ValueError("empty hotel data")
    return cleaned


def snapshot_as_of(as_of: date, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Only facts *published* by as_of. A later snapshot is never backfilled."""
    visible = [row for row in rows if date.fromisoformat(row["source_published_at"]) <= as_of]
    by_country = sorted(({
        **row,
        "under_construction_fraction": round(
            row["rooms_under_construction"] / row["rooms_pipeline"], 4
        ) if row["rooms_pipeline"] else None,
    } for row in visible), key=lambda row: row["rooms_pipeline"], reverse=True)
    return {
        "as_of": as_of.isoformat(),
        "kind": "country_hotel_pipeline_public_top10_not_route_forecast",
        "scope_note": "Published top 10 country aggregates, not all Africa and not individual projects",
        "countries": by_country,
        "country_count": len(by_country),
        "top10_rooms_pipeline": sum(row["rooms_pipeline"] for row in visible),
        "top10_rooms_under_construction": sum(row["rooms_under_construction"] for row in visible),
        "effect_on_air_passengers": None,
        "airport_mapping_available": False,
        "notes": [
            "Snapshot's publication date controls visibility; do not use 2026 revisions to backtest 2020.",
            "Construction status is not proof of active work or future opening.",
            "Country totals cannot be directly attributed to airport catchment areas or origin markets.",
            "Pipeline rooms can replace existing hotels and do not equal induced passenger demand.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, help="Information cut-off date YYYY-MM-DD")
    parser.add_argument("--out", type=Path, help="Optional JSON output path")
    args = parser.parse_args()
    output = snapshot_as_of(date.fromisoformat(args.as_of), load_hotels())
    content = json.dumps(output, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(content, encoding="utf-8")
    else:
        print(content, end="")


if __name__ == "__main__":
    main()
