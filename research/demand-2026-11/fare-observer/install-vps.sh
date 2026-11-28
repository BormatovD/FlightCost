#!/bin/sh
# Run as root from a private directory containing only the observer release.
set -eu
cd "$(dirname "$0")"
getent group fca-fo-handoff >/dev/null || groupadd --system fca-fo-handoff
for stream in tickets charges discovery ingest; do
    user="fca-fo-$stream"
    id "$user" >/dev/null 2>&1 || useradd --system --user-group --no-create-home --shell /usr/sbin/nologin "$user"
done
install -d -m 0755 /opt/fca-fare-observer /var/spool/fca-fare-observer
install -d -m 0700 /etc/fca-fare-observer
for stream in tickets charges discovery; do
    install -d -o "fca-fo-$stream" -g fca-fo-handoff -m 2750 "/var/spool/fca-fare-observer/$stream"
done
install -m 0644 evidence.py observe.py candidate_source.py boundary_check.py queue.json.gz /opt/fca-fare-observer/
ticket_controls=ticket_controls.py
if [ ! -f "$ticket_controls" ]; then
    ticket_controls=../../../flightcostapp/ticket_controls.py
fi
install -m 0644 "$ticket_controls" /opt/fca-fare-observer/ticket_controls.py
if id fcabot >/dev/null 2>&1; then
    install -d -o fcabot -g fca-fo-tickets -m 2750 /var/spool/fca-fare-observer/ticket-admin
fi
for unit in units/*.service units/*.timer; do
    install -m 0644 "$unit" /etc/systemd/system/
done
for stream in tickets charges; do
    install -d -m 0755 "/etc/systemd/system/fca-fo@$stream.service.d"
    install -m 0644 "units/$stream.conf" "/etc/systemd/system/fca-fo@$stream.service.d/observer.conf"
done
systemctl daemon-reload
systemd-analyze verify fca-fo@tickets.service fca-fo@charges.service fca-fo@discovery.service fca-fo-ingest.service \
    fca-fo-tickets.timer fca-fo-charges.timer fca-fo-discovery.timer fca-fo-ingest.timer
