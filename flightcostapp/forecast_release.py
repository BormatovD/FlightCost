"""Public forecast edition shipped by this application revision."""
from pathlib import Path

BASE = "fdbb33d8682c1ea399b96ac1309e9d5e64f015a186aeb4c387265c721e3db270"
EDITION = "5886e8d48851d15d7b16fbb26d51e7f284067ac1367113688db3bc28a24a36cc"
ARCHIVE_SHA256 = "292dde5998a4623704ae8e5432abe313865c988ba77b12e6b53d9458f78eda04"
RELEASES = Path("/srv/fca/site/forecast-releases")


def published_outputs(configured: Path) -> Path:
    # Managed installations select their edition with the Git revision.
    # An explicit local review path still points at the reviewer's own files.
    if configured == RELEASES / BASE:
        return RELEASES / EDITION
    return configured
