"""Public forecast edition shipped by this application revision."""
from pathlib import Path

BASE = "fdbb33d8682c1ea399b96ac1309e9d5e64f015a186aeb4c387265c721e3db270"
EDITION = "3d1d72fa360b6dcdbdf93c2eaf632e5574f95fc9cbcf4bbc4ee2be2847c51759"
ARCHIVE_SHA256 = "96d6aee5c954b3dbe14fd17ca6c93c77f250841a225ce61ec7b1dc07e2c5d415"
RELEASES = Path("/srv/fca/site/forecast-releases")


def published_outputs(configured: Path) -> Path:
    # Managed installations select their edition with the Git revision.
    # An explicit local review path still points at the reviewer's own files.
    if configured == RELEASES / BASE:
        return RELEASES / EDITION
    return configured
