"""Local-disk FHIR sink — writes bundles to a directory as JSON.

The default sink. It has no network dependency, so the emitter can be developed
and tested before a FHIR server or Mirth channel exists. Swap it for a real
destination by changing the import in `client.py`.
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

_OUTPUT_DIR = os.environ.get(
    'FHIR_OUTPUT_DIR',
    os.path.join(os.path.dirname(__file__), '../../data/fhir')
)


def send_bundle(session_id: str, bundle_json: str) -> dict:
    """Write a serialized bundle to disk.

    Returns a result dict matching the sink contract:
        {'status': 'written'|'error', 'destination': str, 'detail': str|None}

    Never raises. A failure to deliver the bundle must not roll back an approval
    the provider already made — the caller records the outcome in the audit log
    and the bundle can be re-emitted later.
    """
    path = os.path.normpath(os.path.join(_OUTPUT_DIR, f'{session_id}.json'))
    logger.info(
        '[interop.local_file] Writing bundle session=%s bytes=%d -> %s',
        session_id, len(bundle_json), path
    )
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(bundle_json)
    except OSError as exc:
        logger.error(
            '[interop.local_file] FAILED to write bundle session=%s path=%s: %s',
            session_id, path, exc, exc_info=True
        )
        return {'status': 'error', 'destination': path, 'detail': str(exc)}

    logger.info('[interop.local_file] Bundle written session=%s', session_id)
    return {'status': 'written', 'destination': path, 'detail': None}


def load_bundle(session_id: str) -> dict | None:
    """Read a previously written bundle back. Used by tests and re-emission."""
    path = os.path.normpath(os.path.join(_OUTPUT_DIR, f'{session_id}.json'))
    if not os.path.exists(path):
        logger.debug('[interop.local_file] No bundle on disk at %s', path)
        return None
    with open(path, encoding='utf-8') as f:
        return json.load(f)
