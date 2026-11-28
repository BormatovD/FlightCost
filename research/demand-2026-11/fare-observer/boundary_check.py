"""Assert access boundaries in the actual service sandbox before processing observations."""
from errno import EACCES, EAFNOSUPPORT, ENOENT, EPERM, EROFS
import json
import os
from pathlib import Path
import pwd
import socket
import sys

from evidence import STREAMS

SPOOL = Path('/var/spool/fca-fare-observer')
CODE = Path(__file__).resolve().parent
ROOT_SECRET = Path('/etc/fca-fare-observer/ticket-token')
EXISTING_APP = (Path('/srv/fca'), Path('/etc/fca/bot.env'), Path('/etc/caddy/fca.caddy'))
DENIALS = {EACCES, EAFNOSUPPORT, ENOENT, EPERM, EROFS}


def denied(action, label):
    try:
        action()
    except OSError as error:
        if error.errno not in DENIALS:
            raise
        return
    raise PermissionError(f'unexpected access: {label}')


def open_without_reading(path, flags):
    os.close(os.open(path, flags))


def check_outbox_write(path):
    probe = path / f'.boundary-check-{os.getpid()}'
    fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    probe.unlink()


def check(role):
    uid = os.geteuid()
    if uid == 0 or pwd.getpwuid(uid).pw_name != 'fca-fo-' + role:
        raise RuntimeError('wrong observer account')
    for path in EXISTING_APP:
        denied(lambda: open_without_reading(path, os.O_RDONLY), 'existing application')
    denied(lambda: open_without_reading(ROOT_SECRET, os.O_RDONLY), 'root credential')
    credential_dir = os.environ.get('CREDENTIALS_DIRECTORY')
    if role == 'tickets':
        open_without_reading(Path(credential_dir) / 'ticket-token', os.O_RDONLY)
    elif credential_dir:
        raise RuntimeError('unexpected credential directory')
    if role != 'tickets':
        private_ticket = Path('/run/credentials/fca-fo@tickets.service/ticket-token')
        denied(lambda: open_without_reading(private_ticket, os.O_RDONLY), 'ticket runtime credential')
    for path in CODE.glob('*.py'):
        denied(lambda: open_without_reading(path, os.O_WRONLY), 'observer executable')
    for name in STREAMS:
        outbox = SPOOL / name
        if role not in (name, 'ingest'):
            denied(lambda: os.listdir(outbox), 'other outbox read')
        else:
            os.listdir(outbox)
        if role != name:
            denied(lambda: check_outbox_write(outbox), 'outbox write')
        else:
            check_outbox_write(outbox)
    for name in (*STREAMS, 'ingest'):
        if role != name:
            denied(lambda: os.listdir('/var/lib/fca-fo-' + name), 'other state directory')
    if role == 'ingest':
        denied(lambda: socket.socket(socket.AF_INET).close(), 'importer IP socket')
    print(json.dumps({'sandbox_boundary_verified': role, 'uid': uid,
                      'ticket_credential_scoped': role == 'tickets', 'networkless_importer': role == 'ingest'}))


if __name__ == '__main__':
    check(sys.argv[1])
