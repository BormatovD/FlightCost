"""Public forecast edition shipped by this application revision."""
from pathlib import Path

BASE = "fdbb33d8682c1ea399b96ac1309e9d5e64f015a186aeb4c387265c721e3db270"
EDITION = "4d520efdc61028ac138406299d79a90bd57f48afaf3526961797e39782535797"
ARCHIVE_SHA256 = "41535bd659038c42fda6edebad97d5ac1b4fcba5bf24847d5b0a0f23363c7849"
RELEASES = Path("/srv/fca/site/forecast-releases")


def published_outputs(configured: Path) -> Path:
    # Managed installations select their edition with the Git revision.
    # An explicit local review path still points at the reviewer's own files.
    if configured == RELEASES / BASE:
        return RELEASES / EDITION
    return configured
