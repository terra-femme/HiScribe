"""FHIR sink adapter — re-export only.

Follows the same convention as `pipeline/adapters/llm.py`: swapping the
destination means changing one commented import, and no calling code moves.

Sink contract — any implementation must expose:

    send_bundle(session_id: str, bundle_json: str) -> dict
        {'status': 'written'|'sent'|'error', 'destination': str,
         'detail': str | None}
        Must not raise. Delivery failure is reported, never thrown.

Active sink:
"""

from .local_file import send_bundle  # noqa: F401

# Phase A9 — POST to a HAPI FHIR test server for real validation:
# from .hapi_server import send_bundle  # noqa: F401

# Phase B — POST to the Mirth Note_Outbound channel's HTTP listener:
# from .mirth_http import send_bundle  # noqa: F401
