#!/bin/sh
# Run on the VPS as root. It prints aggregate results and public source metadata only.
set -eu
spool=/var/spool/fca-fare-observer
secret=/etc/fca-fare-observer/ticket-token
staging=/var/lib/fca-fo-ingest
state=/opt/fca-fare-observer

deny() {
    if "$@"; then
        echo "Unexpected permission: $*" >&2
        exit 1
    fi
}

test "$(stat -c '%a %U:%G' "$secret")" = '600 root:root'
for stream in tickets charges discovery; do
    actor="fca-fo-$stream"
    runuser -u "$actor" -- test -w "$spool/$stream"
    for other in tickets charges discovery; do
        if [ "$other" != "$stream" ]; then
            deny runuser -u "$actor" -- test -r "$spool/$other"
            deny runuser -u "$actor" -- test -w "$spool/$other"
        fi
    done
    deny runuser -u "$actor" -- test -r "$secret"
    deny runuser -u "$actor" -- test -r "$staging"
done
setpriv --reuid=fca-fo-ingest --regid=fca-fo-ingest --groups=fca-fo-handoff /bin/sh -ec '
    for stream in tickets charges discovery; do
        test -r "/var/spool/fca-fare-observer/$stream"
        if test -w "/var/spool/fca-fare-observer/$stream"; then exit 1; fi
    done
    if test -r /etc/fca-fare-observer/ticket-token; then exit 1; fi
'
for service in fca-fo@charges.service fca-fo@discovery.service fca-fo-ingest.service; do
    if systemctl cat "$service" | grep -q '^LoadCredential='; then exit 1; fi
done
systemctl cat fca-fo@tickets.service | grep -q '^LoadCredential=ticket-token:'
test "$(systemctl show --value -p PrivateNetwork fca-fo-ingest.service)" = yes
printf 'Verified at %s UTC\n' "$(date -u +'%Y-%m-%d %H:%M:%S')"
printf 'Outbox ownership, credential permissions and import network isolation verified\n'
for stream in tickets charges discovery ingest; do
    timer="fca-fo-$stream.timer"
    test "$(systemctl is-enabled "$timer")" = enabled
    test "$(systemctl is-active "$timer")" = active
done
systemctl list-timers 'fca-fo-*.timer' --all --no-pager
systemctl start fca-fo-ingest.service
for service in fca-fo@tickets.service fca-fo@charges.service fca-fo@discovery.service fca-fo-ingest.service; do
    journalctl -u "$service" -n 300 --no-pager -o cat | grep sandbox_boundary_verified | tail -1 | grep sandbox_boundary_verified
done
/usr/bin/python3 -B "$state/observe.py" status --state "$staging"
/usr/bin/python3 -B - <<'PY'
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

dsn = "file:/var/lib/fca-fo-ingest/staging.sqlite3?mode=ro"
with sqlite3.connect(dsn, uri=True) as db:
    observed = dict(db.execute("SELECT stream, count(DISTINCT target) FROM evidence GROUP BY stream"))
    print("Distinct targets with evidence:", json.dumps(observed))
    assert set(observed) == {"tickets", "charges", "discovery"}
    versions = dict(db.execute("""SELECT json_extract(payload,'$.version'), count(*) FROM handoff
                                  WHERE stream='discovery' AND phase='staged' AND rows > 0 GROUP BY 1"""))
    assert versions.get(2, 0) > 0
    print("Accepted discovery envelopes with evidence by version:", json.dumps(versions))
    print("Latest source cards with verified snapshot:")
    latest = {}
    for (raw,) in db.execute("""SELECT item FROM evidence WHERE stream='discovery'
                               AND json_extract(item,'$.status') = 'candidate' ORDER BY checked_at"""):
        card = json.loads(raw)
        latest[card['url']] = card
    for card in latest.values():
        name = card['sha256'] + '.' + card['format']
        path = Path("/var/lib/fca-fo-ingest/candidate-documents") / name
        document = path.read_bytes()
        assert len(document) == card['bytes'] and sha256(document).hexdigest() == card['sha256']
        if '/consultations/' in card['final_url']:
            assert all(card[key] is None for key in ('valid_from', 'valid_until', 'currency', 'unit'))
        print(json.dumps(card, ensure_ascii=False))
PY
