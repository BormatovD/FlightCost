"""Verify historic inputs against the installed passenger-segment forecast."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZipFile


V01 = "forecast-releases/FlightCost-forecast-v0.1.zip"
V02 = "forecast-releases/FlightCost-forecast-v0.2.zip"
ARC = "outputs/forecast-v02-trial/lines/forward/icao-arc-2024-table-1.csv"
FORWARD = "outputs/forecast-v02-trial/lines/forward/"
PROTOCOL = "outputs/forecast-v02-trial/world/protocol.ru.txt"
ANNUAL = "outputs/forecast-global-calibration/regional/scenario-annual.csv"
_READ_ERRORS = (OSError, ValueError, KeyError, TypeError, RuntimeError, BadZipFile, csv.Error)


def _file_version(path: Path) -> tuple | None:
    try:
        stat = path.stat()
        if path.is_file() and path.resolve() == path:
            return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns
    except OSError:
        pass
    return None


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _archive_members(root: Path, relative: str, version: str, members: tuple[str, ...],
                     archive_version: tuple | None, checksums_version: tuple | None) -> dict:
    archive_path = root / relative
    if archive_version is None:
        raise ValueError("Forecast release archive unavailable")
    checksums = root / "SHA256SUMS"
    if checksums.exists():
        if checksums_version is None:
            raise ValueError("Invalid installed forecast checksums")
        expected = [fields[0] for line in checksums.read_text().splitlines()
                    if len(fields := line.split(maxsplit=1)) == 2 and fields[1].lstrip("*") == relative]
        with archive_path.open("rb") as stream:
            if expected != [hashlib.file_digest(stream, "sha256").hexdigest()]:
                raise ValueError("Forecast release differs from its installed checksum")
    with ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("VERSION.json"))
        if manifest["version"] != version:
            raise ValueError("Unexpected forecast release version")
        files = {item["path"]: item for item in manifest["files"]}
        result = {}
        for name in members:
            data = archive.read(name)
            metadata = files[name]
            if len(data) != metadata["bytes"] or _sha256(data) != metadata["sha256"]:
                raise ValueError("Forecast source differs from the release manifest")
            result[name] = data
    return result


def _rows(data: bytes) -> csv.DictReader:
    return csv.DictReader(data.decode("utf-8-sig").splitlines())


@lru_cache(maxsize=4)
def _world_source(root: Path, archive_version: tuple | None, checksums_version: tuple | None) -> dict:
    inputs = _archive_members(root, V02, "0.2", (ARC, FORWARD + "README.ru.md", FORWARD + "build.py", PROTOCOL),
                              archive_version, checksums_version)
    observations = {int(row["year"]): int(row["passengers_millions"]) * 1_000_000
                    for row in _rows(inputs[ARC])}
    if sorted(observations) != list(range(2015, 2025)) or min(observations.values()) <= 0:
        raise ValueError("Incomplete ICAO ARC series")
    method = inputs[FORWARD + "build.py"]
    if (b"factor = (arc[2024] / arc[2015]) ** (1 / 9)" not in method
            or b"world_v02 = arc[2024] * factor ** (year - 2024)" not in method):
        raise ValueError("Forecast release uses another world trend")
    notes = inputs[FORWARD + "README.ru.md"].decode()
    source = re.search(r"\[ARC 2024, Table 1, стр\. 1\]\((https://www\.icao\.int/[^)]+)\)", notes)
    if source is None:
        raise ValueError("ICAO source absent from release notes")
    start, end = 2015, 2024
    intervals = end - start
    return dict(observations=observations, startYear=start, endYear=end, intervals=intervals,
                factor=(observations[end] / observations[start]) ** (1 / intervals),
                evidence=dict(title="ICAO Annual Report of the Council 2024", url=source[1] + "#page=1",
                              locator="Table 1, p. 1, Passengers carried, world total, 2015–2024",
                              period="2015–2024", unit="millions of passengers carried",
                              field="passengers_millions × 1 000 000",
                              archive=V02, member=ARC, sha256=_sha256(inputs[ARC])),
                method=dict(archive=V02, member=FORWARD + "build.py", sha256=_sha256(method),
                            formula="observations[endYear] × factor^(year − endYear)",
                            protocol=PROTOCOL, protocolSha256=_sha256(inputs[PROTOCOL]),
                            regionalAllocation=b"float(v01[year, m49][\"local_business\"]) / world_v01" in method))


@lru_cache(maxsize=4)
def _region_source(root: Path, archive_version: tuple | None, checksums_version: tuple | None) -> tuple:
    data = _archive_members(root, V01, "0.1", (ANNUAL,), archive_version, checksums_version)[ANNUAL]
    annual = {}
    for row in _rows(data):
        key = int(row["target"]), row["m49"]
        value = float(row["local_business"])
        if key in annual or not math.isfinite(value) or value <= 0:
            raise ValueError("Invalid v0.1 regional series")
        annual[key] = value
    return annual, dict(title="FlightCost global calibration v0.1", url=f"/outputs/{V01}",
                        locator="scenario-annual.csv, m49 (001 = world) and target (year), local_business column",
                        period="2025–2036", unit="passenger segments", field="local_business",
                        archive=V01, member=ANNUAL, sha256=_sha256(data))


def _published(region: dict) -> dict[int, float]:
    return {int(year): value for year, value in (region["baseline"] | region["forecast"]).items()}


def _matches(value: float, reference: float) -> bool:
    return math.isclose(value, reference, rel_tol=1e-12, abs_tol=1e-5)


def historical_provenance(root: Path, series: dict) -> dict:
    """Return independently verifiable evidence. The installed model always remains authoritative."""
    if series.get("version") != "0.2":
        return {}
    checksums = _file_version(root / "SHA256SUMS")
    try:
        trend = _world_source(root, _file_version(root / V02), checksums)
        regions = series["regions"]
        world_region = regions["world"]
        world_model = _published(world_region)
        source = trend["evidence"]["url"].split("#")[0]
        if any(world_region["fact"].get(str(year)) != value
               or world_region["fact_meta"].get(str(year), {}).get("source") != source
               for year, value in trend["observations"].items()):
            return {}
        end = trend["endYear"]
        if not world_model or any(not _matches(trend["observations"][end] * trend["factor"] ** (year - end), value)
                                  for year, value in world_model.items()):
            return {}
    except _READ_ERRORS:
        return {}

    result = {"worldTrend": trend}
    if not trend["method"]["regionalAllocation"]:
        return result
    try:
        annual, evidence = _region_source(root, _file_version(root / V01), checksums)
        world = {year: annual[year, regions["world"]["m49"]] for year in world_model}
        regional = {}
        for name, region in regions.items():
            if name == "world":
                continue
            m49 = region["m49"]
            local = {year: annual[year, m49] for year in world}
            shares = {year: local[year] / world[year] for year in world}
            reference = _published(region)
            if shares.keys() != reference.keys() or any(
                not _matches(world_model[year] * share, reference[year]) for year, share in shares.items()
            ):
                return result
            regional[name] = dict(m49=m49, localBusiness=local, shares=shares)
        if not regional or any(not _matches(math.fsum(region["shares"][year] for region in regional.values()), 1.0)
                               for year in world):
            return result
    except _READ_ERRORS:
        return result
    result["regionalShares"] = dict(world=world, regions=regional, evidence=evidence)
    return result

def joint_provenance(core: dict) -> dict | None:
    """Check the printed calculation against every shared forecast horizon."""
    if "jointForecast" not in core:
        return None
    data = core["jointForecast"]
    series = core["series"]
    forecast = series["regions"]["world"]["forecast"]

    def number(value, *, positive=False):
        if type(value) not in (int, float) or not math.isfinite(value) or (positive and value <= 0):
            raise ValueError("Invalid numeric forecast input")
        return value

    def equal(left, right):
        if not _matches(number(left), number(right)):
            raise ValueError("Joint forecast calculation does not reproduce the installed baseline")

    def source(address, hostname):
        url = urlsplit(address)
        if url.scheme != "https" or url.netloc != hostname:
            raise ValueError("Unexpected joint forecast source")

    try:
        anchor = data["icao_anchor"]
        iata = data["iata_inputs"][-1]
        arc = data["arc"]
        source(anchor["source_url"], "www.icao.int")
        source(arc["source_url"], "www.icao.int")
        source(iata["source_url"], "www.iata.org")
        issue = int(series["issue_year"])
        if (data["forecast_year"] != issue or anchor["year"] + 1 != issue
                or not re.fullmatch(rf"{issue}-(?:0[1-9]|1[0-2])", iata["period"])
                or not 0 < data["weight"] < 1
                or arc["endYear"] <= arc["startYear"]):
            raise ValueError("Unexpected joint forecast dates or route weight")
        evidence = urlsplit(data["evidence_url"])
        if (evidence.scheme or evidence.netloc
                or not (re.fullmatch(r"/(?:(?:ru|en|de)/)?forecast", evidence.path)
                        or evidence.path.startswith("/outputs/"))):
            raise ValueError("Unexpected joint forecast evidence link")
        rate = number(iata["rpk_ytd_yoy_pct"]) / 100
        opening = number(anchor["segments"], positive=True) * (1 + rate)
        growth = (number(arc["last"], positive=True) / number(arc["first"], positive=True)) ** (
            1 / (arc["endYear"] - arc["startYear"]))
        equal(opening, data["forecast_year_segments"])
        equal(opening, forecast[str(issue)])
        equal(growth - 1, data["growth_after_forecast_year"])
        for year in series["years"]:
            label = str(year)
            row = data["horizons"][label]
            base = number(row["covered_base"], positive=True)
            own_route = number(row["covered_route"], positive=True)
            equal(base + number(row["uncovered"], positive=True), row["v02_rebased"])
            equal(opening * growth ** (year - issue), row["v02_rebased"])
            equal(data["weight"] * (own_route - base), row["route_adjustment"])
            equal(row["v02_rebased"] + row["route_adjustment"], row["updated"])
            equal(row["updated"], forecast[label])
            equal(row["updated"], math.fsum(region["forecast"][label] for name, region
                                            in series["regions"].items() if name != "world"))
    except (IndexError, KeyError, TypeError, AttributeError, OverflowError) as error:
        raise ValueError("Incomplete joint forecast provenance") from error

    return data
