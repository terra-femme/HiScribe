"""Terminology for coded charge capture.

Three code systems meet here and they are not interchangeable:

  SNOMED CT   what the clinician meant       Condition.code, clinical systems
  ICD-10-CM   what the payer adjudicates     Condition.code, the claim, DG1/FT1-19
  CPT         what was done, for billing     ChargeItem.code, FT1-7/FT1-25

Emitting both SNOMED and ICD-10 on the same Condition is deliberate. FHIR
prefers SNOMED CT for clinical meaning; US claims require ICD-10-CM. A system
that carries only one of them either loses clinical nuance or cannot bill.

Licensing — read before adding anything here
--------------------------------------------
  ICD-10-CM   public domain (CMS/CDC)          safe to vendor
  LOINC       free, registration required      safe to reference specific codes
  SNOMED CT   UMLS licence, free for US users  reference codes, never vendor the release
  CPT         AMA-licensed, redistribution     PROHIBITED — no CPT table in this repo

CPT is why `cpt_config.py` reads codes from a gitignored file instead of a
constant in source control. Committing even a short CPT table to a public
repository is a licence violation, and it is the kind of violation that is
trivially greppable.
"""

from __future__ import annotations

import logging

from .logsafe import scrub

logger = logging.getLogger(__name__)

# ── Code system URIs ─────────────────────────────────────────────────────────
# Canonical FHIR system URIs. These are the identifiers a receiving system
# matches on, so a typo here silently produces codes nobody can interpret.
ICD10_CM_SYSTEM = 'http://hl7.org/fhir/sid/icd-10-cm'
SNOMED_SYSTEM   = 'http://snomed.info/sct'
CPT_SYSTEM      = 'http://www.ama-assn.org/go/cpt'

# ChargeItem.status — FHIR required binding. 'billable' is the only status this
# project ever posts downstream; see charge.py for the confirmation gate.
CHARGE_STATUS_PLANNED  = 'planned'
CHARGE_STATUS_BILLABLE = 'billable'

# Condition clinical/verification status, FHIR required bindings.
CONDITION_CLINICAL_SYSTEM     = 'http://terminology.hl7.org/CodeSystem/condition-clinical'
CONDITION_VERIFICATION_SYSTEM = 'http://terminology.hl7.org/CodeSystem/condition-ver-status'


# ── ICD-10-CM <-> SNOMED CT crosswalk ────────────────────────────────────────
#
# ⚠️  TODO VERIFY — every pair below was written from general knowledge and has
#     NOT been confirmed against a primary source. Before this is used for
#     anything beyond local demonstration, check each against:
#       ICD-10-CM  https://www.cms.gov/medicare/coding-billing/icd-10-codes
#       SNOMED CT  the NLM UMLS browser
#       the mapping itself: the NLM ICD-10-CM to SNOMED CT map
#
#     This module follows the same convention as codes.py: unverified values are
#     marked, not quietly trusted. Wrong codes on a claim are not a cosmetic
#     defect — they are a denied claim or, worse, a wrong one that pays.
#
# Deliberately small. This is a demonstration of the dual-coding mechanism, not
# an attempt to ship a terminology server.
CONDITION_CROSSWALK: dict[str, dict] = {
    'J02.9': {
        'icd10_display': 'Acute pharyngitis, unspecified',
        'snomed':        '405737000',
        'snomed_display': 'Pharyngitis',
        'verified':      False,
    },
    'J06.9': {
        'icd10_display': 'Acute upper respiratory infection, unspecified',
        'snomed':        '54150009',
        'snomed_display': 'Upper respiratory infection',
        'verified':      False,
    },
    'I10': {
        'icd10_display': 'Essential (primary) hypertension',
        'snomed':        '59621000',
        'snomed_display': 'Essential hypertension',
        'verified':      False,
    },
    'E11.9': {
        'icd10_display': 'Type 2 diabetes mellitus without complications',
        'snomed':        '44054006',
        'snomed_display': 'Type 2 diabetes mellitus',
        'verified':      False,
    },
    'M54.50': {
        'icd10_display': 'Low back pain, unspecified',
        'snomed':        '279039007',
        'snomed_display': 'Low back pain',
        'verified':      False,
    },
}


def dual_coding(icd10_code: str) -> dict | None:
    """Build a CodeableConcept carrying BOTH an ICD-10-CM and a SNOMED coding.

    Returns None for an unknown code rather than guessing. A Condition with a
    fabricated code is worse than a Condition with no code — the first is a
    wrong claim, the second is a visible gap.
    """
    entry = CONDITION_CROSSWALK.get(icd10_code)
    if not entry:
        logger.warning(
            '[interop.charge_codes] No crosswalk entry for ICD-10 %s — refusing '
            'to guess a SNOMED equivalent', scrub(icd10_code)
        )
        return None

    if not entry.get('verified'):
        logger.warning(
            '[interop.charge_codes] ICD-10 %s / SNOMED %s is marked UNVERIFIED. '
            'Do not rely on this mapping outside local demonstration.',
            scrub(icd10_code), scrub(entry['snomed'])
        )

    return {
        'coding': [
            # SNOMED first: FHIR prefers it for Condition.code because it
            # carries the clinical meaning.
            {
                'system':  SNOMED_SYSTEM,
                'code':    entry['snomed'],
                'display': entry['snomed_display'],
            },
            # ICD-10-CM second: this is the coding a claim is adjudicated on,
            # and the one the DFT^P03 transformer selects for FT1-19 and DG1.
            {
                'system':  ICD10_CM_SYSTEM,
                'code':    icd10_code,
                'display': entry['icd10_display'],
            },
        ],
        'text': entry['icd10_display'],
    }
