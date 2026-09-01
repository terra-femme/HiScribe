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

from .mirth_http import send_bundle  # noqa: F401

# Offline fallback — writes the bundle to data/fhir/ with no network dependency.
# Useful when developing the pipeline without Mirth running. Emission is
# non-fatal either way, so leaving this commented out only means a bundle is
# persisted in `fhir_bundles` and logged as undelivered rather than saved to a
# second location.
# from .local_file import send_bundle  # noqa: F401

# Still open — POST to a HAPI FHIR test server so an external validator, rather
# than our own models, is the correctness gate on the bundle:
# from .hapi_server import send_bundle  # noqa: F401
