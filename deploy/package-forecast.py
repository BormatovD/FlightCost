"""Package a forecast edition or add a web overlay to an installed edition."""
import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flightcostapp import forecast_site
from forecast_web import build_web

REPORTS = (forecast_site.INDEX, forecast_site.NETWORK)


def file_hash(path):
    if path.resolve() != path or not path.is_file():
        raise ValueError(f"Missing file or symlink: {path}")
    with path.open("rb") as fp:
        return hashlib.file_digest(fp, "sha256").hexdigest()


def read_reports(paths):
    reports = {}
    for name in REPORTS:
        path = paths[name]
        if path.resolve() != path or not path.is_file():
            raise ValueError(f"Missing file or symlink: {path}")
        reports[name] = path.read_bytes()
    return reports


def report_hashes(reports):
    return {name: hashlib.sha256(value).hexdigest() for name, value in reports.items()}


def network_chunks(report):
    packed = re.search(rb'<script[^>]+id="payload"[^>]*>([^<]+)</script>', report)
    if packed is None:
        raise ValueError("Network report has no embedded country index")
    index = json.loads(gzip.decompress(base64.b64decode(packed[1].strip())))
    chunks = set(re.findall(r'"\.\./(forecast-world-networks/map-data/(?:2029|2031|2036)-[A-Z]{2}\.[0-9a-f]{12}\.js)"',
                            json.dumps(index["world"]["countries"])))
    if not chunks:
        raise ValueError("The country index has no network chunks")
    return chunks


def add_web(staged, reports):
    build_web(staged, *(reports[name] for name in REPORTS))
    assets = {}
    for path in sorted((staged / "forecast-web").iterdir()):
        name = path.relative_to(staged).as_posix()
        digest = file_hash(path)
        if name not in (forecast_site.WEB_INDEX, forecast_site.WEB_NETWORK):
            if not forecast_site.WEB_CHUNK.fullmatch(name) or path.name != digest + ".json.gz":
                raise ValueError(f"Unexpected web asset or checksum: {path}")
        assets[name] = digest
    manifest = staged / forecast_site.WEB_MANIFEST
    manifest.write_text(json.dumps({"base": report_hashes(reports), "assets": assets},
                                   sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return {**assets, forecast_site.WEB_MANIFEST: file_hash(manifest)}


def publish(staged, destination, hashes):
    raw = "".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items())).encode()
    (staged / "SHA256SUMS").write_bytes(raw)
    output = destination / hashlib.sha256(raw).hexdigest()
    if output.exists():
        if (output / "SHA256SUMS").read_bytes() != raw or any(
                file_hash(output / name) != digest for name, digest in hashes.items()):
            raise ValueError(f"Different contents in {output}")
    else:
        staged.rename(output)
    print(f"{output} ({len(hashes)} public files)")


def package_overlay(source, destination):
    """Read the active edition's two originals and manifest. Stage only web assets."""
    original_manifest = source / "SHA256SUMS"
    if original_manifest.resolve() != original_manifest or not original_manifest.is_file():
        raise ValueError(f"Missing manifest or symlink: {original_manifest}")
    original_manifest_bytes = original_manifest.read_bytes()
    base = {}
    for line in original_manifest_bytes.decode().splitlines():
        digest, name = line.split("  ", 1)
        if name in base or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"Invalid manifest row: {name}")
        if name.startswith("forecast-web/"):
            raise ValueError("Source already contains a web overlay")
        base[name] = digest
    reports = read_reports({name: source / name for name in REPORTS})
    if any(base.get(name) != digest for name, digest in report_hashes(reports).items()):
        raise ValueError("A standalone report differs from the installed manifest")
    for chunk in network_chunks(reports[forecast_site.NETWORK]):
        if not base.get(chunk, "").startswith(chunk.split(".")[-2]):
            raise ValueError(f"Network chunk absent from or inconsistent with the installed manifest: {chunk}")
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination) as tmp:
        staged = Path(tmp)
        hashes = add_web(staged, reports)
        if original_manifest.read_bytes() != original_manifest_bytes or any(
                file_hash(source / name) != report_hashes(reports)[name] for name in REPORTS):
            raise ValueError("The source edition changed during packaging")
        publish(staged, destination, hashes)


def package(source, destination):
    from flightcostapp.serve import FORECAST_ASSETS

    files = {path: source / "outputs" / path for path in FORECAST_ASSETS}
    for path, target in forecast_site.SOURCE_ASSETS.items():
        files[target] = source / path.lstrip("/")
    reports = read_reports(files)
    chunks = network_chunks(reports[forecast_site.NETWORK])
    files.update({path: source / "outputs" / path for path in chunks})
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination) as tmp:
        staged = Path(tmp)
        hashes = {}
        for name, path in sorted(files.items()):
            target = staged / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if name in reports:
                target.write_bytes(reports[name])
            else:
                file_hash(path)
                shutil.copyfile(path, target)
            digest = file_hash(target)
            if name in chunks and not digest.startswith(name.split(".")[-2]):
                raise ValueError(f"Network chunk differs from the index: {name}")
            hashes[name] = digest
        hashes.update(add_web(staged, reports))
        publish(staged, destination, hashes)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--web-overlay", action="store_true",
                     help="Take the two reports and SHA256SUMS from the active edition; package only web files")
    cli.add_argument("source", type=Path, help="Checkout or active installed edition with --web-overlay")
    cli.add_argument("destination", type=Path, help="Parent of the content-addressed output directory")
    args = cli.parse_args()
    builder = package_overlay if args.web_overlay else package
    builder(args.source.resolve(), args.destination.resolve())
