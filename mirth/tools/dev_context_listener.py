"""Minimal stand-in for the pipeline's /fhir/patient-context endpoint.

The real endpoint lives in `pipeline/server.py`, but importing that module pulls
in the whole LangGraph pipeline — torch, tensorflow, pyannote — which is several
gigabytes and irrelevant to the interface work. This listener exercises the same
`db.sqlite.save_patient_context()` the real route calls, so the ADT_Inbound
channel can be tested end to end without standing up the ML stack.

    python mirth/tools/dev_context_listener.py --db data/hiscribe_dev.db

Development only. No authentication, single threaded, stdlib http.server.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'pipeline'))

from interop.logsafe import scrub  # noqa: E402

logging.basicConfig(level=logging.INFO, format='%(levelname)-5s %(message)s')
logger = logging.getLogger('dev_context_listener')


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path.rstrip('/') != '/fhir/patient-context':
            self.send_error(404, 'Not Found')
            return

        length = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(length).decode('utf-8')
        logger.info('[listener] POST %s (%d bytes)', scrub(self.path), length)

        try:
            context = json.loads(body)
        except json.JSONDecodeError as exc:
            logger.error('[listener] Body is not JSON: %s', scrub(exc))
            self.send_error(400, 'invalid JSON')
            return

        from db.sqlite import save_patient_context
        try:
            save_patient_context(context)
        except ValueError as exc:
            logger.error('[listener] Rejected: %s', scrub(exc))
            self.send_error(400, str(exc))
            return
        except Exception as exc:
            logger.error('[listener] Store FAILED: %s', scrub(exc), exc_info=True)
            self.send_error(500, 'could not store patient context')
            return

        logger.info('[listener] Stored mrn=%s event=%s',
                    scrub(context.get('mrn')), scrub(context.get('triggerEvent')))
        payload = json.dumps({'status': 'stored', 'mrn': context.get('mrn')}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        logger.debug('[listener] ' + fmt, *args)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # Loopback by default. Mirth runs in a container and reaches the host
    # through host.docker.internal, which does not resolve to 127.0.0.1 from
    # inside the container, so the Docker path needs --host 0.0.0.0. Binding
    # every interface is a deliberate choice, not a default.
    parser.add_argument('--host', default='127.0.0.1',
                        help='use 0.0.0.0 to accept connections from the Mirth container')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--db', default=None,
                        help='SQLite path; sets DB_PATH for db.sqlite')
    args = parser.parse_args()

    if args.db:
        os.environ['DB_PATH'] = os.path.abspath(args.db)

    from db.sqlite import init_db
    init_db()
    logger.info('[listener] Schema ready, listening on %s:%d', args.host, args.port)
    HTTPServer((args.host, args.port), Handler).serve_forever()
    return 0


if __name__ == '__main__':
    sys.exit(main())
