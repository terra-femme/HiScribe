"""Charge sink adapter — re-export only.

Same convention as `client.py`: the destination for a confirmed charge is
swapped by changing one commented import, and no calling code moves.

Sink contract — any implementation must expose:

    send_charge(session_id: str, bundle_json: str) -> dict
        {'status': 'sent'|'written'|'error', 'destination': str,
         'detail': str | None}
        Must not raise. A billing system being unreachable is an operational
        problem, not a reason to discard a provider's confirmation.

Active sink:
"""

from .mirth_http import send_charge  # noqa: F401

# Local disk, for development without a running Mirth:
# from .local_file import send_bundle as send_charge  # noqa: F401
