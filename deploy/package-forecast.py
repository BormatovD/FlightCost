"""Stage the public forecast edition by allowlist, with a content-addressed SHA256 manifest."""
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
from flightcostapp.serve import FORECAST_ASSETS


def package(source, destination):
    outputs = source / "outputs"
    files = {path: outputs / path for path in FORECAST_ASSETS}
    for path, target in forecast_site.SOURCE_ASSETS.items():
        files[target] = source / path.lstrip("/")
    report = files[forecast_site.NETWORK].read_text(encoding="utf-8")
    packed = re.search(r'<script[^>]+id="payload"[^>]*>([^<]+)</script>', report)
    if packed is None:
        raise ValueError("Network report has no embedded country index")
    index = json.loads(gzip.decompress(base64.b64decode(packed[1].strip())))
    chunks = set(re.findall(r'"\.\./(forecast-world-networks/map-data/(?:2029|2031|2036)-[A-Z]{2}\.[0-9a-f]{12}\.js)"',
                            json.dumps(index["world"]["countries"])))
    if not chunks:
        raise ValueError("The country index has no network chunks")
    files.update({path: outputs / path for path in chunks})
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination) as tmp:
        staged = Path(tmp) / "edition"
        manifest = []
        for name, path in sorted(files.items()):
            if path.resolve() != path or not path.is_file():
                raise ValueError(f"Missing file or symlink: {path}")
            target = staged / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            with target.open("rb") as fp:
                digest = hashlib.file_digest(fp, "sha256").hexdigest()
            if name in chunks and not digest.startswith(name.split(".")[-2]):
                raise ValueError(f"Network chunk differs from the index: {name}")
            manifest.append(f"{digest}  {name}\n")
        raw = "".join(manifest).encode()
        (staged / "SHA256SUMS").write_bytes(raw)
        output = destination / hashlib.sha256(raw).hexdigest()
        if output.exists():
            if (output / "SHA256SUMS").read_bytes() != raw:
                raise ValueError(f"Different contents in {output}")
        else:
            staged.rename(output)
        print(f"{output} ({len(files)} public files)")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("source", type=Path, help="Checkout containing the frozen report and its source notes")
    cli.add_argument("destination", type=Path, help="Parent of the content-addressed release directory")
    args = cli.parse_args()
    package(args.source.resolve(), args.destination.resolve())
