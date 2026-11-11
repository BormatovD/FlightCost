#!/usr/bin/env python3
"""Export the existing calculator's independent rent reference for the article.

No network calls, server database, market fitting or calculator changes. Aircraft
inputs pass through the production parsers into an in-memory Store. The historical
USD display uses the same helper as the public aircraft-type pages.

Reproduce with openap==2.6.2 and the repository dependencies, then run:
    python research/aircraft-prices-2026-11/model_reference.py
    python research/aircraft-prices-2026-11/model_reference.py --check
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from flightcostapp import fleet, seo
from flightcostapp.overrides import Resolver
from flightcostapp.parsers import aircraft_user, openap_aircraft
from flightcostapp.store import Store

AS_OF = "2026-11-11"
BASE_COMMIT = "2ffe474b05db38d146150bebfa800fe0855a555c"
OPENAP_VERSION = "2.6.2"
YEARS = range(2016, 2027)
OUTPUT = HERE / "out/model_reference.json"
CODE_INPUTS = (
    "flightcostapp/fleet.py",
    "flightcostapp/seo.py",
    "flightcostapp/serve.py",
    "flightcostapp/overrides.py",
    "flightcostapp/store.py",
    "flightcostapp/parsers/openap_aircraft.py",
    "flightcostapp/parsers/aircraft_user.py",
    "data/macro/_us_cpi.yaml",
    "data/fleet/reference.yaml",
    "research/_fx.json",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict:
    import openap

    version = importlib.metadata.version("openap")
    if version != OPENAP_VERSION:
        raise RuntimeError(
            f"Reference uses openap=={OPENAP_VERSION}; installed {version}. "
            "Do not silently replace the aircraft input snapshot."
        )
    history_path = HERE / "out/segments_history.json"
    history = json.loads(history_path.read_text(encoding="utf-8"))
    studied = {a["icao"] for a in history["aircraft"]}
    if len(studied) != len(history["aircraft"]):
        raise ValueError("Duplicate aircraft in the historical-panel selection")
    inputs_sha = {rel: sha(ROOT / rel) for rel in CODE_INPUTS}
    inputs_sha[str(history_path.relative_to(ROOT))] = sha(history_path)
    inputs_sha[str(Path(__file__).resolve().relative_to(ROOT))] = sha(Path(__file__))

    # This is a public source snapshot, not a copy or claim about production's DB.
    store = Store(":memory:")
    source_inputs: dict[str, dict] = {}
    package_root = Path(openap.__file__).resolve().parent
    package_inputs_sha: dict[str, str] = {}
    facts = openap_aircraft.parse(b"", {"source_id": "aircraft_openap", "today": AS_OF})
    store.commit_facts(f for f in facts if f.key.split("/", 1)[0] in studied)
    for icao in studied:
        if store.value("aircraft", f"{icao}/mtow_t", AS_OF) is None:
            continue
        rel = f"data/aircraft/{icao.lower()}.yml"
        package_inputs_sha[rel] = sha(package_root / rel)
        source_inputs[icao] = {
            "source": "aircraft_openap",
            "package": "openap",
            "package_version": version,
            "package_path": rel,
            "sha256": package_inputs_sha[rel],
            "url": f"https://pypi.org/project/openap/{version}/",
            "method": "production openap_aircraft.parse",
        }

    # The four study types absent from OpenAP use the accepted repository cards.
    # Fail rather than guessing how overlapping sources would win on a server.
    for icao in sorted(studied):
        card_path = ROOT / "data/aircraft/catalog" / f"{icao}.json"
        if not card_path.exists():
            if icao not in source_inputs:
                raise ValueError(f"No public aircraft input for {icao}")
            continue
        if icao in source_inputs:
            raise ValueError(f"Overlapping OpenAP and catalogue inputs for {icao}; review priority")
        card = json.loads(card_path.read_text(encoding="utf-8"))
        rel = str(card_path.relative_to(ROOT))
        inputs_sha[rel] = sha(card_path)
        ctx = {"source_id": "aircraft_catalog", "today": AS_OF, "sha": inputs_sha[rel]}
        store.commit_facts(aircraft_user.parse(card_path.read_bytes(), ctx))
        if ctx.get("rejected"):
            raise ValueError(ctx["rejected"])
        source_inputs[icao] = {
            "source": "aircraft_catalog",
            "repository_path": rel,
            "sha256": inputs_sha[rel],
            "url": card["source_url"],
            "publisher": card["publisher"],
            "source_title": card["source"],
            "method": "production aircraft_user.parse",
        }

    cpi = seo.us_cpi()
    last_cpi = max(cpi)
    cpi_growth = cpi[last_cpi] / cpi[last_cpi - 1] if last_cpi - 1 in cpi else 1.03

    def cpi_value(year: int) -> float:
        return cpi[year] if year in cpi else cpi[last_cpi] * cpi_growth ** (year - last_cpi)

    aircraft = []
    for h in history["aircraft"]:
        icao = h["icao"]
        mtow = store.value("aircraft", f"{icao}/mtow_t", AS_OF)
        seats = (store.value("aircraft", f"{icao}/seats_typical", AS_OF)
                 or store.value("aircraft", f"{icao}/seats_max", AS_OF))
        raw = fleet.parametric(icao, mtow, seats)
        res = Resolver(store, AS_OF)
        effective = fleet.load(res, icao, as_of=AS_OF, operator="*", mtow_t=mtow, seats=seats)
        gen = fleet.generation(icao)
        new = gen == "new"
        points = [{
            "year": int(x),
            "x": x,
            "lease_usd_month": value * 1000,
            "lease_thousand_usd_month": value,
            "cpi": cpi_value(int(x)),
            "cpi_extrapolated": int(x) not in cpi,
        } for x, value in seo.param_lease_usd(raw.lease_eur_month, YEARS)]
        aircraft.append({
            "icao": icao,
            "label": h["label"],
            "segment": h["segment"],
            "mtow_t": mtow,
            "seats_for_public_default": seats,
            "aircraft_input": source_inputs[icao],
            "generation": gen,
            "generation_label_ru": fleet.GENERATIONS[gen]["label"],
            "model_age_years": 0 if new else 12,
            "model_age_is_approximate": not new,
            "model_age_is_continuous_input": False,
            "comparable_with_new_aircraft": new,
            "age_comparison_note": (
                "New-aircraft basis matches the main history panel; calendar/condition/contract differences remain."
                if new else
                "Calculator basis is approximately 12 years old. The main history panel is new aircraft; "
                "do not interpret their gap as model error. No age normalization is invented."
            ),
            "reference_lease_eur_month": fleet.GENERATIONS[gen]["lease_ref_eur_month"],
            "raw_parametric_lease_eur_month": raw.lease_eur_month,
            "effective_public_default_lease_eur_month": effective.lease_eur_month,
            "effective_public_default_provenance": effective.field_prov["lease_eur_month"],
            "effective_public_default_source": effective.field_ref.get("lease_eur_month"),
            "effective_scope": "public input snapshot; operator='*'; no scenario or market observation selected",
            "public_default_equals_raw_parametric": effective.lease_eur_month == raw.lease_eur_month,
            "nominal_usd_points": points,
            "purchase_price_reference": None,
            "market_observation_selected": False,
        })
    store.db.close()

    research_fx = json.loads((ROOT / "research/_fx.json").read_text(encoding="utf-8"))
    return {
        "meta": {
            "schema_version": 1,
            "as_of": AS_OF,
            "base_commit": BASE_COMMIT,
            "scope": "research_only; existing calculator assumptions, no production change",
            "method": "production fleet.parametric; isolated fleet.load; production seo.param_lease_usd",
            "openap_version": version,
            "inputs_sha256": inputs_sha,
            "openap_package_inputs_sha256": dict(sorted(package_inputs_sha.items())),
            "aircraft_count": len(aircraft),
            "new_aircraft_comparable_count": sum(a["comparable_with_new_aircraft"] for a in aircraft),
            "formula": "lease_EUR_month = L_ref(generation) * (MTOW_t / 78)^1.10",
            "reference_mtow_t": fleet.DEFAULTS["lease_ref_mtow_t"],
            "mtow_exponent": fleet.DEFAULTS["lease_mtow_exponent"],
            "generation_reference_eur_month": {
                name: props["lease_ref_eur_month"] for name, props in fleet.GENERATIONS.items()
            },
            "lease_uses_seats": False,
            "lease_uses_segment_coefficient": False,
            "lease_uses_continuous_age_curve": False,
            "purchase_price_model_available": False,
            "historical_display": {
                "currency": "USD",
                "unit": "USD per month (nominal dollars of each year)",
                "calculator_base_currency": "EUR",
                "calculator_base_period": "2026-10",
                "base_year": seo.PARAM_YEAR,
                "usd_per_eur": seo.PARAM_USD_PER_EUR,
                "fx_kind": "fixed calibration convention from production type-page comparator, not live spot FX",
                "formula": "USD_y = EUR_2026 * 1.16 * CPI_y / CPI_2026",
                "cpi_series": "data/macro/_us_cpi.yaml; US CPI-U annual averages",
                "cpi_last_observed_year": last_cpi,
                "cpi_last_annual_growth_factor": cpi_growth,
                "cpi_base_year_value": cpi_value(seo.PARAM_YEAR),
                "cpi_base_year_is_extrapolated": seo.PARAM_YEAR not in cpi,
                "years": list(YEARS),
                "point_position": "year + 0.5, annual display convention; not a source observation month",
                "meaning": "A static current-model rent expressed in each year's nominal USD, not a historical prediction.",
                "not_a_lease_contract_index": True,
                "research_currency_widget_usd_per_eur": research_fx["rates"]["USD"],
                "research_currency_widget_as_of": research_fx["as_of"],
                "currency_widget_note": "The general research money widget uses a separate FX snapshot; charts stay in explicitly labelled USD.",
            },
            "plot_rules": [
                "Use raw_parametric_lease_eur_month for the independent model benchmark; never fit it to the plotted market observations.",
                "Draw model references only on lease-rate charts. There is no production purchase-price model to draw on value charts.",
                "Label every model reference with its type and age basis; a current-generation line is approximately age 12, not new.",
                "For current-generation types, show the line as contextual only or use a separate aged panel; do not calculate a new-aircraft over/underpricing claim.",
                "A user-selected market midpoint is an explicit calculator override, not an independent reference line.",
                "Currency conversion and CPI normalization do not correct aircraft-age or contract-condition differences.",
            ],
            "load_precedence": [
                "Explicit scenario/manual lease override; operator-specific before wildcard. A deliberately selected accepted market observation creates this override only when no manual lease is supplied.",
                "A complete six-field fleet_economics bundle is selected operator-first, wildcard-second, retaining explicit overrides.",
                "If no complete bundle exists: individual fleet_economics fields operator-first, wildcard-second.",
                "Aircraft-card fleet_lease_eur_month if present and the higher layers lack a lease value.",
                "Parametric generation/MTOW fallback. The age input affects TOiR maintenance, not this lease fallback.",
            ],
            "public_default_limit": "This reproducible public source snapshot cannot establish operator, user or server-only overrides in a live calculation.",
        },
        "segments": history["segments"],
        "aircraft": aircraft,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Compare the regenerated result without writing")
    args = parser.parse_args()
    result = build()
    text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != text:
            raise SystemExit("model_reference.json differs from a fresh production-code calculation")
        print(f"OK: {len(result['aircraft'])} model references reproduce exactly")
        return
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}: {len(result['aircraft'])} aircraft")


if __name__ == "__main__":
    main()
