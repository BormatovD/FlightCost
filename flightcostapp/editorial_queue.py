"""Private handoff of approved Russian originals; never publishes or executes HTML.

A queue item is NOT a release. EN/DE, content review and local Git approval are
required in the next stage. No command in this module changes the repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import selectors
import stat
import subprocess
import tempfile
import time
from pathlib import Path

SCHEMA = "flightcost.editorial.original.v1"
FILES = ("manifest.json", "report.html")
MAX_MANIFEST = 64 * 1024
MAX_REPORT = 15_000_000
REMOTE_ROOT = "/srv/fca/editorial/publication_queue"
LOCAL_ROOT = Path.home() / ".local/share/flightcost/editorial_queue"
ID_RE = re.compile(r"(?:0[2-9]|1[0-8])-r(?:00[1-9]|0[1-9][0-9]|[1-9][0-9][0-9])\Z")


def bundle_id(article: int, revision: int) -> str:
    if type(article) is not int or type(revision) is not int:
        raise ValueError("Invalid article/revision")
    value = f"{article:02d}-r{revision:03d}"
    if not ID_RE.fullmatch(value):
        raise ValueError("Invalid article/revision")
    return value


def check_id(value: str) -> str:
    if not ID_RE.fullmatch(value):
        raise ValueError("Invalid queue ID")
    return value


def encode_manifest(meta: dict) -> bytes:
    return (json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def make_manifest(article, revision, title, lede, report):
    return {
        "schema": SCHEMA,
        "id": bundle_id(article, revision),
        "article": article,
        "revision": revision,
        "slug": f"demand-series-{article:02d}-2026-11",
        "status": "approved_original_needs_translation",
        "available_languages": ["ru"],
        "required_languages": ["ru", "en", "de"],
        "title": title,
        "lede": lede,
        "files": {"report.html": {"bytes": len(report), "sha256": hashlib.sha256(report).hexdigest()}},
    }


def validate_bytes(identifier, manifest, report):
    """Validate fixed schema and bytes only. SHA256 is not a trust signature."""
    check_id(identifier)
    if not 0 < len(manifest) <= MAX_MANIFEST or not 0 < len(report) <= MAX_REPORT:
        raise ValueError("Invalid bundle size")
    meta = json.loads(manifest.decode("utf-8"))
    if not isinstance(meta, dict):
        raise ValueError("Invalid manifest")
    for field, maximum in (("title", 240), ("lede", 1800)):
        value = meta.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise ValueError(f"Invalid {field}")
    expected = make_manifest(meta.get("article"), meta.get("revision"), meta["title"], meta["lede"], report)
    if expected != meta or meta["id"] != identifier:
        raise ValueError("Manifest, queue ID or SHA256 mismatch")
    report.decode("utf-8")  # Never render/execute the downloaded document.
    return meta


def read_regular(path, limit):
    if path.is_symlink():
        raise ValueError(f"Symlink forbidden: {path.name}")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError(f"Expected regular file: {path.name}")
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise ValueError(f"File too large: {path.name}")
    return value


def read_bundle(root, identifier):
    path = Path(root) / check_id(identifier)
    if path.is_symlink() or not path.is_dir() or {p.name for p in path.iterdir()} != set(FILES):
        raise ValueError("Missing/invalid bundle directory")
    manifest = read_regular(path / FILES[0], MAX_MANIFEST)
    report = read_regular(path / FILES[1], MAX_REPORT)
    validate_bytes(identifier, manifest, report)
    return manifest, report


def store_bundle(root, identifier, manifest, report, *, server=False):
    """Atomic, idempotent handoff; never overwrite another revision or bytes."""
    validate_bytes(identifier, manifest, report)
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Queue directory must be provisioned first")
    target = root / identifier
    if target.exists() or target.is_symlink():
        if read_bundle(root, identifier) != (manifest, report):
            raise ValueError("Different immutable bundle already exists")
        return False
    with tempfile.TemporaryDirectory(dir=root, prefix=".queue-") as temp:
        stage = Path(temp) / "bundle"
        stage.mkdir(mode=0o700)
        if server:
            stage.chmod(0o2750)
        for name, content in zip(FILES, (manifest, report)):
            with (stage / name).open("xb") as out:
                os.fchmod(out.fileno(), 0o640 if server else 0o600)
                out.write(content)
                out.flush()
                os.fsync(out.fileno())
        stage.rename(target)
    return True


def remote_read(host, command, limit):
    # Fixed commands and validated IDs only. No shell locally, no agent forwarding.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:\-]{0,253}", host or ""):
        raise ValueError("Use a trusted SSH host/alias, e.g. deploy@server")
    args = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ForwardAgent=no", "-o", "ClearAllForwardings=yes", "-o", "PermitLocalCommand=no",
            "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=2",
            "--", host, command]
    # Bound both output size and wall-clock duration, including a slow server.
    deadline = time.monotonic() + 90
    with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:
        try:
            value = bytearray()
            with selectors.DefaultSelector() as selector:
                selector.register(proc.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise ValueError("SSH response timed out")
                    chunk = os.read(proc.stdout.fileno(), min(65536, limit + 1 - len(value)))
                    if not chunk:
                        break
                    value.extend(chunk)
                    if len(value) > limit:
                        raise ValueError("Remote response too large")
            if proc.wait(timeout=max(0.1, deadline - time.monotonic())):
                raise ValueError("SSH failed; check host, permissions and known_hosts")
            return bytes(value)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("FCA_DEPLOY_HOST"))
    parser.add_argument("--directory", type=Path, default=LOCAL_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    for action in ("pull", "validate"):
        sub.add_parser(action).add_argument("id")
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            raw = remote_read(args.host, f"find {REMOTE_ROOT} -mindepth 1 -maxdepth 1 -type d -printf '%f\\n'", 65536)
            ids = sorted({line for line in raw.decode("ascii").splitlines() if ID_RE.fullmatch(line)})
            print("Approved originals awaiting EN/DE (not published):")
            for identifier in ids:
                print(identifier)
            print(f"Total: {len(ids)}")
            return 0
        identifier = check_id(args.id)
        if args.command == "pull":
            manifest = remote_read(args.host, f"cat -- {REMOTE_ROOT}/{identifier}/manifest.json", MAX_MANIFEST)
            report = remote_read(args.host, f"cat -- {REMOTE_ROOT}/{identifier}/report.html", MAX_REPORT)
            validate_bytes(identifier, manifest, report)
            args.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            store_bundle(args.directory, identifier, manifest, report)
        manifest, report = read_bundle(args.directory, identifier)
        meta = validate_bytes(identifier, manifest, report)
        # Escape control characters from untrusted server metadata in terminal output.
        print(json.dumps({"id": identifier, "title": meta["title"], "sha256": meta["files"]["report.html"]["sha256"],
                          "status": meta["status"]}, ensure_ascii=True))
        print(f"Saved: {args.directory / identifier}")
        print("SHA256 OK. NOT READY TO PUBLISH: EN and DE missing; HTML not security-reviewed.")
        return 0
    except (ValueError, OSError, UnicodeError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
