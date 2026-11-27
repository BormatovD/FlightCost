"""Public forecast edition shipped by this application revision."""
from pathlib import Path

BASE = "fdbb33d8682c1ea399b96ac1309e9d5e64f015a186aeb4c387265c721e3db270"
EDITION = "577abea67bbc3900b34504d9c5bb2c0363292e8bd53960bd1afc9e39e393f85d"
ARCHIVE_SHA256 = "3e266ae1fed15dc2750db3c4be6b1dd73c761316a40f0ac5c4b2ec130890d8e6"
RELEASES = Path("/srv/fca/site/forecast-releases")


def published_outputs(configured: Path) -> Path:
    # Managed installations select their edition with the Git revision.
    # An explicit local review path still points at the reviewer's own files.
    if configured == RELEASES / BASE:
        return RELEASES / EDITION
    return configured
