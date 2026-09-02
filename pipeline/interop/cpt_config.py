"""Loads CPT codes from a gitignored configuration file.

Why this module exists instead of a constant
--------------------------------------------
CPT is copyrighted by the American Medical Association and licensed. The code
descriptors may not be redistributed. Committing a CPT table to a repository —
even five evaluation-and-management codes for a demo — is a licence violation,
and it is trivially greppable in a public repo.

So the codes live in `config/cpt_codes.json`, which is gitignored, and the
repository ships `config/cpt_codes.example.json` carrying the file's SHAPE with
placeholder values and no real descriptors.

This is not defensive paperwork. Knowing that ICD-10-CM is free and CPT is not
is one of the more reliable signals that someone has actually worked with
healthcare code sets rather than read about them.

Format of config/cpt_codes.json:

    {
      "99213": {"display": "<descriptor from your AMA-licensed source>"},
      "99214": {"display": "<descriptor from your AMA-licensed source>"}
    }
"""

from __future__ import annotations

import json
import logging
import os

from .logsafe import scrub

logger = logging.getLogger(__name__)

_CONFIG_PATH = os.environ.get(
    'CPT_CONFIG_PATH',
    os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'cpt_codes.json')
)

_cache: dict[str, dict] | None = None


def _load() -> dict[str, dict]:
    global _cache
    if _cache is not None:
        return _cache

    path = os.path.normpath(_CONFIG_PATH)
    if not os.path.exists(path):
        # Not an error. A checkout without a CPT config is the expected state,
        # and every caller handles an empty table by refusing to build a charge.
        logger.warning(
            '[interop.cpt_config] No CPT config at %s — charge capture is '
            'disabled. Copy config/cpt_codes.example.json and populate it from '
            'your own AMA-licensed source.', path
        )
        _cache = {}
        return _cache

    try:
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error('[interop.cpt_config] Could not read %s: %s', path, exc)
        _cache = {}
        return _cache

    table = {}
    for code, entry in raw.items():
        if isinstance(entry, dict) and entry.get('display'):
            table[str(code)] = {'code': str(code), 'display': entry['display']}
        else:
            logger.warning('[interop.cpt_config] Skipping malformed entry %r', code)

    logger.info('[interop.cpt_config] Loaded %d CPT codes from %s', len(table), path)
    _cache = table
    return _cache


def lookup_cpt(code: str) -> dict | None:
    """Return {'code', 'display'} for a configured CPT code, or None."""
    table = _load()
    entry = table.get(str(code))
    if not entry:
        logger.warning(
            '[interop.cpt_config] CPT %s not configured — refusing to emit a '
            'charge for an unknown procedure code', scrub(code)
        )
    return entry


def reset_cache() -> None:
    """Drop the cached table. Used by tests that write a temporary config."""
    global _cache
    _cache = None
