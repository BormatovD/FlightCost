"""Public forecast edition shipped by this application revision."""
from pathlib import Path

BASE = "fdbb33d8682c1ea399b96ac1309e9d5e64f015a186aeb4c387265c721e3db270"
EDITION = "8820c70904373d4a9bce3d1f570a863f0924fcc8db124b3ed1c2b42858163f09"
ARCHIVE_SHA256 = "8d16872fcb0a21780b3e1700f88bab4bcffee6b7276fe484a9f9025bc1200331"
RELEASES = Path("/srv/fca/site/forecast-releases")


def published_outputs(configured: Path) -> Path:
    # Managed installations select their edition with the Git revision.
    # An explicit local review path still points at the reviewer's own files.
    if configured == RELEASES / BASE:
        return RELEASES / EDITION
    return configured
