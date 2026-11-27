"""Verify the GitHub forecast delta and atomically materialize an immutable edition."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tarfile
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flightcostapp.forecast_release import ARCHIVE_SHA256, BASE, EDITION, RELEASES
from flightcostapp.probe import probe_url
from urllib.request import urlopen

PAGES = {"forecast-final/report.html", "forecast-web/forecast.html", "forecast-web/manifest.json"}
CHUNK = re.compile(r"forecast-web/([a-f0-9]{64})\.json\.gz")


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def manifest(data, expected):
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("Forecast manifest checksum mismatch")
    files = {}
    for line in data.decode().splitlines():
        digest, name = line.split("  ", 1)
        path = Path(name)
        if (not re.fullmatch(r"[a-f0-9]{64}", digest) or path.is_absolute() or ".." in path.parts
                or path.as_posix() != name or not path.parts or name in files or name == "SHA256SUMS"):
            raise ValueError(f"Invalid forecast manifest entry: {name}")
        files[name] = digest
    return files


def check_file(path, digest):
    if path.is_symlink() or not path.is_file() or file_hash(path) != digest:
        raise ValueError(f"Forecast file differs from its manifest: {path}")


def unpack(archive, archive_hash, edition_hash, stage=None):
    check_file(archive, archive_hash)
    with tarfile.open(archive, "r:gz") as bundle:
        listed = bundle.getmembers()
        names = {entry.name for entry in listed}
        if (len(names) != len(listed) or not PAGES | {"SHA256SUMS"} <= names
                or any(not entry.isfile() or (entry.name not in PAGES | {"SHA256SUMS"} and not CHUNK.fullmatch(entry.name))
                       for entry in listed)):
            raise ValueError("Unexpected files in forecast release")
        sums = bundle.extractfile("SHA256SUMS").read()
        files = manifest(sums, edition_hash)
        for entry in listed:
            payload = bundle.extractfile(entry).read()
            name = entry.name
            digest = edition_hash if name == "SHA256SUMS" else files[name]
            chunk = CHUNK.fullmatch(name)
            if hashlib.sha256(payload).hexdigest() != digest or (chunk and chunk[1] != digest):
                raise ValueError(f"Invalid forecast release content: {name}")
            if name == "forecast-web/manifest.json":
                overlay = json.loads(payload)
                reports = ("forecast-final/report.html", "forecast-leased-network/report.html")
                if (overlay["base"] != {report: files[report] for report in reports}
                        or any(files.get(asset) != sha for asset, sha in overlay["assets"].items())):
                    raise ValueError("Forecast web and offline editions disagree")
            if stage:
                dest = stage / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(payload)
                dest.chmod(0o444)
    return files, names - {"SHA256SUMS"}


def install(base_dir: Path, archive: Path, base_hash: str, edition_hash: str, archive_hash: str) -> Path:
    original = base_dir / base_hash
    destination = base_dir / edition_hash
    if destination.exists():
        for name, digest in manifest((destination / "SHA256SUMS").read_bytes(), edition_hash).items():
            check_file(destination / name, digest)
        return destination

    previous = manifest((original / "SHA256SUMS").read_bytes(), base_hash)
    with tempfile.TemporaryDirectory(dir=base_dir, prefix=".forecast-") as temp:
        stage = Path(temp) / "edition"
        stage.mkdir()
        current, shipped = unpack(archive, archive_hash, edition_hash, stage)
        changed = {name for name, digest in current.items() if previous.get(name) != digest}
        if not previous.keys() <= current.keys() or shipped != changed or changed & previous.keys() != PAGES:
            raise ValueError("Forecast delta does not match its parent edition")
        for name in previous.keys() - changed:
            src, dest = original / name, stage / name
            check_file(src, current[name])
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(src, dest)
            except PermissionError:
                shutil.copyfile(src, dest)
                dest.chmod(0o444)
        stage.chmod(0o755)
        stage.rename(destination)
    return destination


def check_live():
    host = "http://127.0.0.1:8000"
    web = (RELEASES / EDITION / "forecast-web/forecast.html").read_bytes()
    index = json.loads(web.split(b"window.unifiedRelease=", 1)[1].split(b";</script>", 1)[0])
    asset = index["assets"]["world"]["2031"]
    for lang in ("ru", "en", "de"):
        with urlopen(probe_url(f"{host}/{lang}/forecast"), timeout=15) as response:
            if asset.encode() not in response.read():
                raise ValueError(f"{lang}: published forecast does not match Git edition")
    with urlopen(probe_url(host + asset), timeout=15) as response:
        if hashlib.sha256(response.read()).hexdigest() != Path(asset).name.split(".")[0]:
            raise ValueError("World forecast data was not served from the installed edition")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--check", action="store_true", help="Verify the tracked release bundle in CI")
    cli.add_argument("--live", action="store_true", help="Check the running site after a GitHub deployment")
    args = cli.parse_args()
    archive = Path(__file__).resolve().parent / "forecast" / "edition.tar.gz"
    if args.check:
        files, shipped = unpack(archive, ARCHIVE_SHA256, EDITION)
        print(f"Verified {len(shipped)} forecast files against edition {EDITION}")
    elif args.live:
        check_live()
    else:
        print(install(RELEASES, archive, BASE, EDITION, ARCHIVE_SHA256))
