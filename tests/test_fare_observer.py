from contextlib import closing, redirect_stdout
from io import BytesIO, StringIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

OBSERVER = Path(__file__).resolve().parents[1] / 'research' / 'demand-2026-11' / 'fare-observer'
sys.path.insert(0, str(OBSERVER))

import observe


def error_body(message, success=False):
    return json.dumps({'success': success, 'error': message}).encode()


def http_error(status, body):
    return HTTPError(observe.API, status, 'API error', None, BytesIO(body))


class TicketRouteRejection(unittest.TestCase):
    def test_exact_signatures_and_only_http_400(self):
        for target, status, body, expected in (
            ('JFK-OPP', 400, error_body('bad request: unknown location code `OPP`'), 'unsupported_route'),
            ('AIN-JFK', 400, error_body('bad request: airport AIN: not flightable'), 'unsupported_route'),
            ('JFK-LGA', 400, error_body(observe.EQUAL_TICKET_CITIES), 'unsupported_route'),
            ('JFK-AIN', 429, error_body('bad request: airport AIN: not flightable'), 'http_429'),
            ('JFK-AIN', 400, error_body('bad request: airport AIN: not flightable.'), 'http_400'),
            ('JFK-DFW', 400, error_body('bad request: airport AIN: not flightable'), 'http_400'),
            ('JFK-AIN', 400, error_body(observe.EQUAL_TICKET_CITIES, success=True), 'http_400'),
            ('JFK-AIN', 400, b'not-json', 'http_400'),
            ('JFK-AIN', 400, b'\xff', 'http_400'),
            ('JFK-AIN', 400, error_body(observe.EQUAL_TICKET_CITIES) + b' ' * 4096, 'http_400'),
        ):
            with self.subTest(target=target, status=status, body=body[:120]):
                failure = http_error(status, body)
                with patch.object(observe, 'fetch', side_effect=failure):
                    self.assertEqual(observe.observed_tickets(target, 'TestCredential'), (expected, [], 0))
                self.assertTrue(failure.fp.closed)

    def test_legacy_queue_excludes_permanent_rejections_until_successful_probe(self):
        with TemporaryDirectory() as temp, redirect_stdout(StringIO()) as output:
            state = Path(temp)
            outbox = state / 'outbox'
            outbox.mkdir()
            (state / 'ticket-token').write_text('TestCredential')
            with closing(observe.connect(state / 'queue.sqlite3')) as db:
                db.execute('''CREATE TABLE targets (target TEXT PRIMARY KEY, metadata TEXT, priority INTEGER,
                            seq INTEGER, due INTEGER DEFAULT 0, status TEXT)''')
                db.executemany('INSERT INTO targets VALUES (?,?,?,?,?,?)', (
                    ('JFK-OPP', 'region', 0, 0, 0, None), ('JFK-LHR', 'region', 0, 1, 0, 'http_400'),
                ))
                db.commit()

                def queued():
                    return dict((target, (status, due)) for target, status, due in
                                db.execute('SELECT target,status,due FROM targets'))

                now = 10_000
                with (patch.dict(observe.os.environ, {'CREDENTIALS_DIRECTORY': temp}),
                      patch.object(observe, 'time', return_value=now), patch.object(observe, 'sleep'),
                      patch.object(observe, 'fetch') as fetch):
                    fetch.side_effect = [http_error(400, error_body('bad request: unknown location code `OPP`')),
                                         http_error(400, error_body('arbitrary TestCredential error'))]
                    observe.queue_run(state, outbox, 'tickets', 2, None)
                    self.assertEqual(queued(), {'JFK-OPP': ('unsupported_route', None),
                                                'JFK-LHR': ('http_400', now + 3 * 3600)})
                    fetch.reset_mock()
                    observe.queue_run(state, outbox, 'tickets', 2, None)
                    fetch.assert_not_called()

                    fetch.side_effect = http_error(400, b'not-json')
                    observe.queue_run(state, outbox, 'tickets', 2, 'JFK-OPP')
                    fetch.assert_called_once()
                    self.assertEqual(queued()['JFK-OPP'], ('unsupported_route', None))

                    fetch.side_effect = None
                    fetch.return_value = (b'{"success": true, "data": []}', observe.API, 'application/json')
                    observe.queue_run(state, outbox, 'tickets', 2, 'JFK-OPP')
                    self.assertEqual(queued()['JFK-OPP'], ('empty', now + observe.DAY))

            snapshots = [path.read_text() for path in outbox.glob('*.json')]
            outcomes = [(row['status'], row['raw_count']) for row in map(json.loads, snapshots)]
            self.assertCountEqual(outcomes, [('unsupported_route', 0), ('http_400', 0),
                                             ('http_400', 0), ('empty', 0)])
            self.assertNotIn('TestCredential', output.getvalue() + ''.join(snapshots))
