"""Terminology constants for FHIR resource construction.

Single source of truth for every code system URI and coded value the FHIR
emitter writes. Nothing in `builder.py` may hardcode a code — it imports from
here so that terminology changes happen in exactly one place and stay auditable.

FHIR release target: **R4B**, not R5.
US Core profiles are built on R4, CMS interoperability rules mandate R4, and the
major EHR vendors expose R4 APIs. R5 is published but not meaningfully deployed.

Every LOINC code below was verified against a primary source on 2026-08-10.
Codes marked `TODO VERIFY` were NOT confirmed against a primary source and must
be checked before this module is relied on for anything beyond local testing.
"""

from __future__ import annotations

# ── Code system URIs ─────────────────────────────────────────────────────────

LOINC_SYSTEM = 'http://loinc.org'

# TODO VERIFY — standard by convention, not confirmed against a primary source.
NPI_SYSTEM        = 'http://hl7.org/fhir/sid/us-npi'
V2_0203_SYSTEM    = 'http://terminology.hl7.org/CodeSystem/v2-0203'
V3_ACTCODE_SYSTEM = 'http://terminology.hl7.org/CodeSystem/v3-ActCode'

# Local system for values that have no standard code. Using a project-scoped URI
# is valid FHIR and is honest — it does not dress a local value up as a standard
# one. Consumers can recognise and ignore it.
HISCRIBE_VISIT_TYPE_SYSTEM = 'http://hiscribe.local/CodeSystem/visit-type'

# MRNs are assigned by an issuing organisation, so a real deployment must
# replace this with that organisation's assigning-authority URI or OID. A
# project-local placeholder is correct for synthetic data and honest about
# what it is.
HISCRIBE_MRN_SYSTEM = 'http://hiscribe.local/identifier/mrn'


def _coding(system: str, code: str, display: str) -> dict:
    """Build a FHIR Coding. Kept as a plain dict — R4B models accept these."""
    return {'system': system, 'code': code, 'display': display}


# ── Composition.type — what kind of document this is ─────────────────────────
# Drawn from the FHIR `doc-typecodes` value set (LOINC where SCALE_TYP = Doc).
# Source: https://www.hl7.org/fhir/valueset-doc-typecodes.html
#
# Deliberately NOT keyed on `visit_type`. Document type and visit type are
# different axes: Composition.type says "this is a progress note"; the character
# of the visit belongs on the Encounter. Conflating them is a modelling error.
DOC_TYPE_PROGRESS_NOTE = _coding(LOINC_SYSTEM, '11506-3', 'Progress note')
DOC_TYPE_CONSULT_NOTE  = _coding(LOINC_SYSTEM, '11488-4', 'Consult note')

DEFAULT_DOC_TYPE = DOC_TYPE_PROGRESS_NOTE


# ── Composition.section.code — SOAP sections ─────────────────────────────────
# All four verified present in the FHIR `doc-section-codes` value set (LOINC
# v2.73 expansion). Source: https://www.hl7.org/fhir/valueset-doc-section-codes.html
#
# These are the semantically exact SOAP codes — 61150-9 and 61149-1 are literally
# named "Subjective Narrative" and "Objective Narrative".
#
# Alternate mapping, if a downstream consumer expects C-CDA-conventional
# sections instead (both are in the same value set):
#   S -> 10164-2 "History of Present illness Narrative"
#   O -> 29545-1 "Physical findings Narrative"
SECTION_SUBJECTIVE = _coding(LOINC_SYSTEM, '61150-9', 'Subjective Narrative')
SECTION_OBJECTIVE  = _coding(LOINC_SYSTEM, '61149-1', 'Objective Narrative')
SECTION_ASSESSMENT = _coding(LOINC_SYSTEM, '51848-0', 'Evaluation note')
SECTION_PLAN       = _coding(LOINC_SYSTEM, '18776-5', 'Plan of care note')

# Maps HiScribe's internal SOAP section keys to (title, coding).
# Keys mirror SOAP_SECTIONS in gateway/src/routes/note.ts:4.
SOAP_SECTION_MAP: dict[str, tuple[str, dict]] = {
    'S': ('Subjective', SECTION_SUBJECTIVE),
    'O': ('Objective',  SECTION_OBJECTIVE),
    'A': ('Assessment', SECTION_ASSESSMENT),
    'P': ('Plan',       SECTION_PLAN),
}

# 'UNCLASSIFIED' is intentionally absent. Segments the pipeline could not place
# have no clinical section, and inventing a LOINC code for them would be a lie.
# The builder emits them as a separate uncoded section so they remain visible
# rather than being silently dropped.
UNCLASSIFIED_SECTION_TITLE = 'Unclassified — provider review required'

# Amendments are new clinical information added after the recording, not a
# correction of what was heard. HiScribe treats this distinction as legally
# meaningful, so it survives into the FHIR output as its own titled section.
AMENDMENT_SECTION_TITLE = 'Amendments — added after recording'


# ── Identifier type codings ──────────────────────────────────────────────────
# TODO VERIFY — 'MR' (Medical record number) from HL7 v2 table 0203.
IDENTIFIER_TYPE_MR = _coding(V2_0203_SYSTEM, 'MR', 'Medical record number')


# ── Encounter.class ──────────────────────────────────────────────────────────
# TODO VERIFY — v3 ActCode AMB (ambulatory) / VR (virtual).
ENCOUNTER_CLASS_AMBULATORY = _coding(V3_ACTCODE_SYSTEM, 'AMB', 'ambulatory')
ENCOUNTER_CLASS_VIRTUAL    = _coding(V3_ACTCODE_SYSTEM, 'VR', 'virtual')

# Keys mirror VISIT_TYPES in gateway/src/routes/note.ts:5.
VISIT_TYPE_TO_ENCOUNTER_CLASS: dict[str, dict] = {
    'new_patient': ENCOUNTER_CLASS_AMBULATORY,
    'follow_up':   ENCOUNTER_CLASS_AMBULATORY,
    'urgent_care': ENCOUNTER_CLASS_AMBULATORY,
    'telehealth':  ENCOUNTER_CLASS_VIRTUAL,
}


def encounter_class_for(visit_type: str | None) -> dict:
    """Resolve a HiScribe visit_type to an Encounter.class coding.

    Falls back to ambulatory for unknown values — the safest default for an
    office-visit scribe, and it keeps the bundle valid rather than omitting a
    required element.
    """
    return VISIT_TYPE_TO_ENCOUNTER_CLASS.get(
        visit_type or '', ENCOUNTER_CLASS_AMBULATORY
    )


def visit_type_coding(visit_type: str | None) -> dict | None:
    """Represent the raw visit_type under the project-local code system.

    Returns None when there is no visit_type, so the caller can omit the element
    entirely rather than emitting an empty CodeableConcept.
    """
    if not visit_type:
        return None
    return _coding(
        HISCRIBE_VISIT_TYPE_SYSTEM, visit_type, visit_type.replace('_', ' ')
    )
