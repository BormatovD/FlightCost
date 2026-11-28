"""Public forecast edition shipped by this application revision."""
from pathlib import Path

BASE = "fdbb33d8682c1ea399b96ac1309e9d5e64f015a186aeb4c387265c721e3db270"
EDITION = "13fcb01474010903fad957fd24871aec87e6930cc3a6160b95bb312608edf96c"
ARCHIVE_SHA256 = "1845d18066ac74ae2a73d5bc7a57ab163db7e8ad152b2f9f7fb638ca55ac8605"
RELEASES = Path("/srv/fca/site/forecast-releases")


def published_outputs(configured: Path) -> Path:
    # Managed installations select their edition with the Git revision.
    # An explicit local review path still points at the reviewer's own files.
    if configured == RELEASES / BASE:
        return RELEASES / EDITION
    return configured
