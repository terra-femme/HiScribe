"""Sanitise untrusted values before they are written to a log line.

Why this exists
---------------
Almost everything this package logs originates outside the process: an MRN from
an ADT feed, an ICD-10 code from a request body, an error string from a remote
server. A value containing a newline can forge a complete, plausible log entry:

    mrn = "MRN1\\nINFO [approve] session=abc approved by dr-smith"

An operator reading the log, or a SIEM parsing it, sees an approval that never
happened. In a system whose audit trail is the point, a forgeable log is not a
cosmetic problem.

`scrub()` flattens control characters and bounds the length, so an untrusted
value can occupy at most one bounded log line.
"""

from __future__ import annotations

_MAX_LEN = 300


def scrub(value: object, max_len: int = _MAX_LEN) -> str:
    """Return `value` as a single-line, length-bounded string safe to log.

    Newlines and carriage returns become literal escapes rather than being
    dropped, so the fact that they were present stays visible instead of being
    silently normalised away.
    """
    if value is None:
        return 'None'
    text = str(value)
    text = text.replace('\\', '\\\\').replace('\r', '\\r').replace('\n', '\\n')
    # Any other C0 control character, including the ASCII escape that drives
    # terminal control sequences.
    text = ''.join(ch if ch >= ' ' and ch != '\x7f' else f'\\x{ord(ch):02x}'
                   for ch in text)
    if len(text) > max_len:
        text = f'{text[:max_len]}...[truncated {len(text) - max_len} chars]'
    return text


def scrub_all(*values: object) -> tuple[str, ...]:
    """Scrub several values at once, for multi-argument log calls."""
    return tuple(scrub(v) for v in values)
