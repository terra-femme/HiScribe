"""Mirth Connect HTTP sink — POSTs a FHIR Bundle to the Note_Outbound channel.

This is the sink that makes the interface engine real. `local_file.py` writes
the bundle to disk; this hands it to Mirth, which performs the
FHIR Composition -> HL7 v2 MDM^T02 transformation and forwards the result over
MLLP to the receiving system.

Why the transform lives in Mirth and not here
---------------------------------------------
It would be easy to build the MDM^T02 in Python and let Mirth act as a dumb
pipe. That would be the wrong shape. In a real deployment the interface engine
is where mappings are owned, versioned, and changed by an integration analyst
without redeploying the clinical application. Keeping the transform in the
channel means the channel XML in `mirth/channels/` is the actual artifact, and
this module stays a transport concern.

Swap this in by changing one import line in `client.py`, per the adapter
convention used throughout `pipeline/adapters/`.
"""

from __future__ import annotations

import logging
import os

import httpx

from .logsafe import scrub

logger = logging.getLogger(__name__)

# Inside docker-compose the Mirth service is reachable by service name. The
# localhost default is for running the pipeline outside the compose network.
#
# The trailing slash is required. Mirth's HTTP listener answers a request to a
# context path without it with a 302 to the slashed form, and a redirected POST
# arrives with no body — which surfaces as a channel that received a message
# with empty content rather than as an obvious error.
_NOTE_URL = os.environ.get('MIRTH_NOTE_URL', 'http://localhost:8081/note/')
_CHARGE_URL = os.environ.get('MIRTH_CHARGE_URL', 'http://localhost:8082/charge/')
_TIMEOUT = float(os.environ.get('MIRTH_TIMEOUT_SECONDS', '30'))

# Declaring the charset is not optional. With no charset parameter Mirth falls
# back to the HTTP default of ISO-8859-1, and every non-ASCII character in the
# note (an em dash, an accented name) is mangled before the transformer sees it.
_CONTENT_TYPE = 'application/fhir+json; charset=utf-8'


def _post(url: str, channel: str, session_id: str, bundle_json: str) -> dict:
    """POST a serialized FHIR Bundle to a Mirth HTTP listener.

    Returns the sink-contract dict:
        {'status': 'sent'|'error', 'destination': str, 'detail': str|None}

    Never raises. Mirth being down must not fail a provider's approval — the
    bundle is already persisted in `fhir_bundles` and can be re-sent. This
    mirrors how a real interface runs: the clinical system commits its own
    state, and delivery is retried out of band.
    """
    logger.info(
        '[interop.mirth_http] %s POST session=%s bytes=%d -> %s',
        channel, scrub(session_id), len(bundle_json), scrub(url)
    )
    try:
        response = httpx.post(
            url,
            content=bundle_json.encode('utf-8'),
            headers={
                'Content-Type': _CONTENT_TYPE,
                # Echoed back by the channel into MSH-10 so a message in the
                # receiving system can be traced to the session that produced
                # it. Correlation IDs across an interface are the difference
                # between a debuggable integration and an opaque one.
                'X-HiScribe-Session': session_id,
            },
            timeout=_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        logger.error(
            '[interop.mirth_http] Delivery FAILED session=%s -> %s: %s '
            '(approval stands; bundle is persisted and can be re-sent)',
            scrub(session_id), scrub(url), scrub(exc), exc_info=True
        )
        return {'status': 'error', 'destination': url, 'detail': str(exc)}

    body = (response.text or '').strip()
    if response.status_code >= 400:
        logger.error(
            '[interop.mirth_http] Mirth rejected bundle session=%s status=%d body=%s',
            scrub(session_id), response.status_code, scrub(body)
        )
        return {
            'status': 'error',
            'destination': url,
            'detail': f'HTTP {response.status_code}: {body[:300]}',
        }

    # The channel returns the downstream ACK. MSA-1 = AA means the receiving
    # system committed the document; anything else is a delivery that looked
    # successful at the HTTP layer but failed at the application layer, which
    # is exactly the failure mode that silently loses clinical documents.
    ack_code = _ack_code(body)
    if ack_code and ack_code != 'AA':
        logger.error(
            '[interop.mirth_http] Downstream NACK session=%s MSA-1=%s body=%s',
            scrub(session_id), scrub(ack_code), scrub(body)
        )
        return {
            'status': 'error',
            'destination': url,
            'detail': f'downstream acknowledgement was {ack_code}, expected AA',
        }

    logger.info(
        '[interop.mirth_http] Bundle accepted session=%s ack=%s',
        scrub(session_id), scrub(ack_code or 'none')
    )
    return {'status': 'sent', 'destination': url, 'detail': ack_code}


def _ack_code(message: str) -> str | None:
    """Pull MSA-1 out of an HL7 v2 ACK.

    Returns None when the response is not an HL7 message, which is not an error
    here — a channel configured with a plain HTTP response instead of the ACK
    is a valid deployment choice.
    """
    for line in message.replace('\r\n', '\r').replace('\n', '\r').split('\r'):
        if line.startswith('MSA|'):
            fields = line.split('|')
            return fields[1] if len(fields) > 1 else None
    return None


def send_bundle(session_id: str, bundle_json: str) -> dict:
    """Send an approved clinical note to Mirth for MDM^T02 delivery."""
    return _post(_NOTE_URL, 'Note_Outbound', session_id, bundle_json)


def send_charge(session_id: str, bundle_json: str) -> dict:
    """Send a provider-confirmed charge to Mirth for DFT^P03 delivery."""
    return _post(_CHARGE_URL, 'Charge_Outbound', session_id, bundle_json)
