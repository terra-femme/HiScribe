"""Builds a FHIR R4B transaction Bundle from an approved HiScribe session.

Input contract
--------------
Consumes the dict returned by `db.sqlite.get_review_payload(session_id)`:

    {
      'session':    {...},   # one row from `sessions`
      'soap':       {'S': [seg], 'O': [seg], 'A': [seg], 'P': [seg],
                     'UNCLASSIFIED': [seg]},
      'amendments': [{...}]  # rows from `amendments`
    }

Nothing else is read. If that contract changes, this module must change with it.

Output
------
A `Bundle` (type=transaction) containing Patient, Practitioner, Encounter and
Composition. `Composition` is used rather than `DocumentReference` because SOAP
sections map one-to-one onto `Composition.section[]`; wrapping the note as an
opaque blob would discard the structure the LangGraph pipeline produced.

Release target is R4B — see `codes.py` for why.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone

from fhir.resources.R4B.bundle import Bundle
from fhir.resources.R4B.composition import Composition
from fhir.resources.R4B.encounter import Encounter
from fhir.resources.R4B.patient import Patient
from fhir.resources.R4B.practitioner import Practitioner

from . import codes

logger = logging.getLogger(__name__)

# FHIR ids are restricted to [A-Za-z0-9-.] with a max length of 64.
_ID_SAFE = re.compile(r'[^A-Za-z0-9\-.]')
_XHTML_NS = 'http://www.w3.org/1999/xhtml'


def _safe_id(prefix: str, raw: str) -> str:
    """Derive a spec-legal resource id from an arbitrary string.

    Ids are derived from the session id, never from MRN or NPI. Resource ids
    travel in URLs and logs, and identifiers are patient/provider identifiers —
    they belong in `identifier`, not in the id.
    """
    cleaned = _ID_SAFE.sub('-', raw or 'unknown')
    return f'{prefix}-{cleaned}'[:64]


def _narrative(text: str) -> dict:
    """Wrap plain text as a FHIR Narrative.

    `html.escape` is not cosmetic here — transcript text is arbitrary speech and
    an unescaped `&` or `<` produces XHTML that fails FHIR validation.
    """
    return {
        'status': 'generated',
        'div': f'<div xmlns="{_XHTML_NS}">{html.escape(text)}</div>',
    }


def _segments_to_text(segments: list[dict]) -> str:
    """Flatten segments into readable narrative text, preserving order."""
    parts: list[str] = []
    for seg in segments:
        speaker = seg.get('speaker') or 'UNKNOWN'
        body = (seg.get('text') or '').strip()
        if body:
            parts.append(f'{speaker}: {body}')
    return '\n'.join(parts)


def _iso_utc(value: str | None) -> str:
    """Normalise a stored timestamp to an ISO-8601 instant with an offset.

    FHIR `instant` requires a timezone. Rows written by `datetime.utcnow()`
    carry none, so a bare value is treated as UTC rather than guessed at.
    """
    if not value:
        return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    raw = value.strip().replace(' ', 'T')
    if raw.endswith('Z') or '+' in raw[10:]:
        return raw
    return f'{raw}Z'


def _build_patient(session: dict, pid: str) -> Patient:
    mrn = session.get('patient_mrn')
    if not mrn:
        logger.warning(
            '[interop.builder] Session %s has no patient_mrn — Patient will carry '
            'no identifier', session.get('id')
        )
    identifier = []
    if mrn:
        identifier.append({
            'type':   {'coding': [codes.IDENTIFIER_TYPE_MR]},
            'system': codes.HISCRIBE_MRN_SYSTEM,
            'value':  mrn,
        })
    return Patient(id=pid, identifier=identifier or None)


def _build_practitioner(session: dict, prid: str) -> Practitioner:
    npi = session.get('provider_npi')
    if not npi:
        logger.warning(
            '[interop.builder] Session %s has no provider_npi — Practitioner will '
            'carry no identifier', session.get('id')
        )
    identifier = [{'system': codes.NPI_SYSTEM, 'value': npi}] if npi else None
    return Practitioner(id=prid, identifier=identifier)


def _build_encounter(session: dict, eid: str, pid: str) -> Encounter:
    visit_type = session.get('visit_type')
    enc_type = codes.visit_type_coding(visit_type)

    period = {'start': _iso_utc(session.get('created_at'))}
    if session.get('ended_at'):
        period['end'] = _iso_utc(session['ended_at'])

    return Encounter(
        id=eid,
        status='finished',
        class_fhir=codes.encounter_class_for(visit_type),
        subject={'reference': f'Patient/{pid}'},
        period=period,
        type=[{'coding': [enc_type]}] if enc_type else None,
    )


def _build_sections(soap: dict, amendments: list[dict]) -> list[dict]:
    """Build Composition.section[] from the SOAP buckets plus amendments.

    Sections with no content are omitted — an empty section is noise, not
    information. Unclassified segments are kept in a titled but uncoded section
    rather than dropped, so nothing the provider approved disappears silently.
    """
    sections: list[dict] = []

    for key, (title, coding) in codes.SOAP_SECTION_MAP.items():
        segments = soap.get(key) or []
        text = _segments_to_text(segments)
        if not text:
            logger.debug('[interop.builder] Section %s empty — omitted', key)
            continue
        sections.append({
            'title': title,
            'code':  {'coding': [coding]},
            'text':  _narrative(text),
        })
        logger.debug(
            '[interop.builder] Section %s built — %d segments', key, len(segments)
        )

    unclassified = soap.get('UNCLASSIFIED') or []
    if unclassified:
        text = _segments_to_text(unclassified)
        if text:
            # Deliberately uncoded — no LOINC code honestly describes
            # "the pipeline could not place this".
            logger.warning(
                '[interop.builder] %d unclassified segments emitted as an uncoded '
                'section', len(unclassified)
            )
            sections.append({
                'title': codes.UNCLASSIFIED_SECTION_TITLE,
                'text':  _narrative(text),
            })

    if amendments:
        body = '\n'.join(
            f"[{a.get('soap_section', '?')}] {(a.get('content') or '').strip()}"
            for a in amendments
            if (a.get('content') or '').strip()
        )
        if body:
            # Amendments are new clinical information, not corrections of what
            # the ASR heard. HiScribe treats that distinction as legally
            # meaningful, so it survives into the FHIR output.
            sections.append({
                'title': codes.AMENDMENT_SECTION_TITLE,
                'text':  _narrative(body),
            })
            logger.info(
                '[interop.builder] %d amendments emitted as a distinct section',
                len(amendments)
            )

    return sections


def build_bundle(payload: dict) -> Bundle:
    """Build a FHIR R4B transaction Bundle from a review payload.

    Raises ValueError when the payload is unusable — a malformed bundle must
    never be written silently.
    """
    session = payload.get('session') or {}
    session_id = session.get('id')
    if not session_id:
        logger.error('[interop.builder] Payload has no session.id — cannot build')
        raise ValueError('payload.session.id is required to build a Bundle')

    soap = payload.get('soap') or {}
    amendments = payload.get('amendments') or []
    total_segments = sum(len(v or []) for v in soap.values())

    logger.info(
        '[interop.builder] Building bundle session=%s segments=%d amendments=%d',
        session_id, total_segments, len(amendments)
    )

    pid  = _safe_id('pat', session_id)
    prid = _safe_id('prac', session_id)
    eid  = _safe_id('enc', session_id)
    cid  = _safe_id('comp', session_id)

    patient      = _build_patient(session, pid)
    practitioner = _build_practitioner(session, prid)
    encounter    = _build_encounter(session, eid, pid)
    sections     = _build_sections(soap, amendments)

    if not sections:
        logger.error(
            '[interop.builder] Session %s produced zero sections — refusing to '
            'emit an empty Composition', session_id
        )
        raise ValueError(f'session {session_id} has no content to compose')

    composition = Composition(
        id=cid,
        status='final',
        type={'coding': [codes.DEFAULT_DOC_TYPE]},
        subject={'reference': f'Patient/{pid}'},
        encounter={'reference': f'Encounter/{eid}'},
        date=_iso_utc(session.get('approved_at')),
        author=[{'reference': f'Practitioner/{prid}'}],
        title=f'Clinical Note — session {session_id}',
        # The provider is the accountable author. `attester` records that
        # explicitly rather than leaving authorship implied by `author`.
        attester=[{
            'mode':  'legal',
            'time':  _iso_utc(session.get('approved_at')),
            'party': {'reference': f'Practitioner/{prid}'},
        }],
        section=sections,
    )

    # PUT rather than POST so re-running an approval is idempotent — the same
    # session always targets the same resource ids instead of creating
    # duplicates on every retry.
    bundle = Bundle(
        type='transaction',
        entry=[
            {'resource': patient,      'request': {'method': 'PUT', 'url': f'Patient/{pid}'}},
            {'resource': practitioner, 'request': {'method': 'PUT', 'url': f'Practitioner/{prid}'}},
            {'resource': encounter,    'request': {'method': 'PUT', 'url': f'Encounter/{eid}'}},
            {'resource': composition,  'request': {'method': 'PUT', 'url': f'Composition/{cid}'}},
        ],
    )

    logger.info(
        '[interop.builder] Bundle built session=%s entries=%d sections=%d',
        session_id, len(bundle.entry), len(sections)
    )
    return bundle
