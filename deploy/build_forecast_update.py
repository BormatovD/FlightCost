"""Build the review edition of the ICAO–IATA forecast on the approved site archive."""

import argparse
import csv
import gzip
import hashlib
import io
import json
from math import fsum, isclose
from pathlib import Path
import re
import tarfile
import tempfile

from forecast_edition import CHUNK, PAGES, manifest, unpack
from flightcostapp.forecast_release import ARCHIVE_SHA256, BASE, EDITION


ROOT = Path(__file__).resolve().parents[1]
OFFLINE = "forecast-final/report.html"
WEB = "forecast-web/forecast.html"
OVERLAY = "forecast-web/manifest.json"
CORE = re.compile(rb'(<script id="core" type="application/json">)(.*?)(</script>)', re.S)
WEB_CORE = re.compile(rb'const forecastAssets\s*=\s*\{"core":"/outputs/(forecast-web/[0-9a-f]{64}\.json\.gz)"')
HORIZONS = (2029, 2031, 2036)
VISIBLE = ("joint_segments", "updated_joint_segments", "icao_observed_segments", "airbus_equivalent_segments",
           "boeing_equivalent_segments", "updated_fleet_covered_segments")


def sha(content):
    return hashlib.sha256(content).hexdigest()


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def script_data(value):
    return compact(value).replace(b"<", b"\\u003c")


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def check_close(actual, expected, label):
    if not isclose(actual, expected, rel_tol=1e-11, abs_tol=0.01):
        raise ValueError(f"{label}: {actual} differs from {expected}")


def pack(path, entries):
    with path.open("wb") as dest, gzip.GzipFile(
        filename="", fileobj=dest, mode="wb", mtime=0, compresslevel=6,
    ) as compressed, tarfile.open(fileobj=compressed, mode="w", format=tarfile.GNU_FORMAT) as bundle:
        for name, payload in sorted(entries.items()):
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(payload), 0o444
            bundle.addfile(info, io.BytesIO(payload))


def source_data(root):
    joint_dir = root / "outputs/forecast-route-joint"
    quarterly_dir = joint_dir / "quarterly"
    # Use the fixed, dated publication cutoff rather than a later live IATA report.
    release = json.loads((quarterly_dir / "releases/2026-09.json").read_bytes())
    if release["issued_on"] != "2026-11-28" or release["data_through"] != "2026-09":
        raise ValueError("Expected the 28 November 2026 release")
    annual = [
        {"year": int(row["year"]), "icao_series": row["icao_series"], "point_type": row["point_type"],
         **{key: float(row[key]) if row[key] else None for key in VISIBLE}}
        for row in read_rows(quarterly_dir / "world-outlook-2005-2036-icao-iata.csv")
    ]
    if [row["year"] for row in annual] != list(range(2005, 2037)):
        raise ValueError("Incomplete annual chart")
    result = [row for row in annual if row["updated_joint_segments"] is not None]
    if [row["year"] for row in result] != list(range(2026, 2037)):
        raise ValueError("Incomplete world projection")
    check_close(result[0]["updated_joint_segments"], release["forecast_year_segments"], "IATA 2026 adjustment")
    check_close(next(row["icao_observed_segments"] for row in annual if row["year"] == 2025),
                release["icao_anchor"]["segments"], "ICAO 2025 anchor")
    quarterly = []
    for row in read_rows(quarterly_dir / "quarterly-rpk.csv"):
        quarterly.append({
            key: (float(value) if value else None) if key.endswith(("_billion", "_error_pct")) else value
            for key, value in row.items() if key != "actual_sources"
        })
    locked = next(row for row in quarterly if row["quarter"] == "2026Q4")
    for key in ("updated", "current"):
        check_close(locked[key + "_rpk_billion"], release["projections"]["2026Q4"][key], "locked Q4 forecast")
    if locked["scoring"] != "pending" or locked["actual_rpk_billion"] is not None:
        raise ValueError("A fact is not part of the original Q4 release")

    prior = {int(row["target"]): row for row in read_rows(joint_dir / "world-forecasts.csv")
             if int(row["target"]) in HORIZONS and row["cutoff"] == "2026-11-21"}
    weight, = {float(row["weight"]) for row in prior.values()}
    scale = result[0]["updated_joint_segments"] / result[0]["joint_segments"]
    horizons = release["horizons"]
    for year in HORIZONS:
        detail, original = horizons[str(year)], prior[year]
        detail["covered_base"] = float(original["covered_base"]) * scale
        detail["covered_route"] = float(original["covered_route"])
        detail["uncovered"] = float(original["uncovered"]) * scale
        detail["route_adjustment"] = weight * (detail["covered_route"] - detail["covered_base"])
        check_close(detail["covered_base"] + detail["uncovered"], detail["v02_rebased"], "world baseline")
        check_close(detail["v02_rebased"] + detail["route_adjustment"], detail["updated"], f"route blend in {year}")
        check_close(next(row["updated_joint_segments"] for row in result if row["year"] == year),
                    detail["updated"], f"world chart in {year}")
    arc = {int(row["year"]): int(row["passengers_millions"]) * 1_000_000
           for row in read_rows(root / "outputs/forecast-v02-trial/lines/forward/icao-arc-2024-table-1.csv")}
    start, end = min(arc), max(arc)
    check_close((arc[end] / arc[start]) ** (1 / (end - start)) - 1,
                release["growth_after_forecast_year"], "structural growth")
    detail = {key: release[key] for key in ("issued_on", "icao_anchor", "iata_inputs", "forecast_year",
                                           "forecast_year_segments", "growth_after_forecast_year", "horizons")}
    detail.update(weight=weight, arc={
        "startYear": start, "endYear": end, "first": arc[start], "last": arc[end],
        "source_url": "https://www.icao.int/sites/default/files/annual-report-2024/World%20of%20Air%20Transport/ARC_2024_Tables_final_EN.pdf#page=1",
    }, evidence_url="/ru/forecast#forecast-accuracy")
    return detail, {"issued_on": release["issued_on"], "annual": annual, "quarterly": quarterly}


def revise_core(core, detail, series):
    regions = core["series"]["regions"]
    regional = [value for region, value in regions.items() if region != "world"]
    world = regions["world"]
    if len(regional) != 22 or core["series"]["issue_year"] != detail["forecast_year"]:
        raise ValueError("Unexpected published geographic basis")
    if core["series"]["version"] != "0.2" or "jointForecast" in core:
        raise ValueError("Build over the archived v0.2 site edition")
    check_close(world["fact"]["2025"], detail["icao_anchor"]["segments"], "published ICAO 2025 anchor")
    for point in series["annual"]:
        total = point["updated_joint_segments"]
        if total is None:
            continue
        year = str(point["year"])
        published = world["forecast"][year]
        check_close(fsum(row["forecast"][year] for row in regional), published, "original regional forecast")
        # The live atlas and fleet use carrier registration. Preserve their shares.
        for row in regional:
            row["forecast"][year] *= total / published
        world["forecast"][year] = total
        check_close(fsum(row["forecast"][year] for row in regional), total, "updated regional forecast")
    world["forecast_coverage"] = "Единая модель FlightCost от факта ИКАО за 2025 год с обновлением IATA за девять месяцев 2026 года."
    for row in regional:
        row["forecast_coverage"] = "Географические доли по месту регистрации перевозчика для сопоставления с парком."
    core["series"]["version"] = "2026-11-28"
    core["jointForecast"] = detail
    return compact(core)


def revise_page(page, old_path, new_path, new_core, figures):
    marker = CORE.search(page)
    if not marker or len(CORE.findall(page)) != 1 or b'id="forecast-verification"' in page:
        raise ValueError("Expected one core and no previously inserted forecast charts")
    data = b'<script id="forecast-verification" type="application/json">' + script_data(figures) + b'</script>\n'
    core = script_data(json.loads(new_core)) if marker[2].strip() else b""
    page = page[:marker.start()] + data + marker[1] + core + marker[3] + page[marker.end():]
    if not core:
        if page.count(old_path.encode()) != 1:
            raise ValueError("Expected one split model reference")
        page = page.replace(old_path.encode(), new_path.encode(), 1)
    for original, revised in (
        ("Базовый сценарий использует прогноз FlightCost v0.2.", "Базовый сценарий использует обновлённый прогноз FlightCost."),
        ("База v0.2 для этой географии", "База текущего прогноза для этой географии"),
        ("в прогнозе v0.2.`", "в базовом прогнозе.`"),
        (">Годовые траектории v0.2<", ">Архивные годовые траектории v0.2<"),
        ("Пассажиропоток · Excel", "Архив v0.2 · Excel"),
        ("Скачать расчёт пассажиропотока в Excel", "Скачать архив v0.2 в Excel"),
        (">Пассажиропоток.xlsx<", ">Архив пассажиропотока v0.2<"),
    ):
        page = page.replace(original.encode(), revised.encode())
    return page


def build(research, old_core_file, base_archive, output):
    archive = ROOT / "deploy/forecast/edition.tar.gz"
    previous, shipped = unpack(archive, ARCHIVE_SHA256, EDITION)
    with tarfile.open(base_archive) as bundle:
        original = manifest(bundle.extractfile("SHA256SUMS").read(), BASE)
    with tarfile.open(archive) as bundle:
        entries = {member.name: bundle.extractfile(member).read() for member in bundle if member.name in shipped}
    bundle_overlay = json.loads(entries[OVERLAY])
    old_path = WEB_CORE.search(entries[WEB])[1].decode()
    model = old_core_file.read_bytes()
    if sha(model) != previous[old_path] or bundle_overlay["assets"][old_path] != previous[old_path]:
        raise ValueError("Archived split core differs from the verified release")
    compressed_core = json.loads(gzip.decompress(model))
    offline_core = json.loads(CORE.search(entries[OFFLINE])[2])
    if offline_core != compressed_core:
        raise ValueError("Web and offline source editions disagree")

    detail, figures = source_data(research)
    new_core = revise_core(offline_core, detail, figures)
    new_chunk = gzip.compress(new_core, compresslevel=4, mtime=0)
    new_path = f"forecast-web/{sha(new_chunk)}.json.gz"
    if not CHUNK.fullmatch(new_path) or new_path in previous:
        raise ValueError("Expected a new content-addressed chunk")
    entries[new_path] = new_chunk
    for name in (OFFLINE, WEB):
        entries[name] = revise_page(entries[name], old_path, new_path, new_core, figures)
    bundle_overlay["base"][OFFLINE] = sha(entries[OFFLINE])
    bundle_overlay["assets"][WEB] = sha(entries[WEB])
    bundle_overlay["assets"][new_path] = sha(new_chunk)
    entries[OVERLAY] = compact(bundle_overlay) + b"\n"

    after = previous | {name: sha(payload) for name, payload in entries.items()}
    delta = {name for name, digest in after.items() if original.get(name) != digest}
    if not original.keys() <= after.keys() or delta != entries.keys() or delta & original.keys() != PAGES:
        raise ValueError("Updated forecast delta does not match the permanent base")
    sums = "".join(f"{digest}  {name}\n" for name, digest in sorted(after.items())).encode()
    entries["SHA256SUMS"] = sums
    archive_dest = output / "edition.tar.gz"
    output.mkdir(parents=True, exist_ok=True)
    pack(archive_dest, entries)
    edition, digest = sha(sums), sha(archive_dest.read_bytes())
    with tempfile.TemporaryDirectory() as directory:
        repeat = Path(directory) / "repeat.tar.gz"
        pack(repeat, entries)
        if sha(repeat.read_bytes()) != digest or unpack(archive_dest, digest, edition) != (after, delta):
            raise ValueError("Release archive does not reproduce")
    identity = (ROOT / "flightcostapp/forecast_release.py").read_text()
    identity = identity.replace(EDITION, edition).replace(ARCHIVE_SHA256, digest)
    (output / "forecast_release.py").write_text(identity)
    public_manifest = {"edition": edition, "archive": digest, "previous": EDITION, "base": BASE,
                       "changed_files": sorted(PAGES | {new_path}), "public_files": len(after),
                       "shipped_files": len(delta)}
    (output / "identity.json").write_text(json.dumps(public_manifest, indent=2) + "\n")
    print(json.dumps(public_manifest))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--research", required=True, type=Path, help="Research checkout with frozen publication inputs")
    cli.add_argument("--old-core", required=True, type=Path, help="Prior edition's content-addressed core")
    cli.add_argument("--base-archive", required=True, type=Path, help="Archive carrying the permanent base manifest")
    cli.add_argument("--output", required=True, type=Path, help="Place generated review files here")
    args = cli.parse_args()
    build(args.research, args.old_core, args.base_archive, args.output)
