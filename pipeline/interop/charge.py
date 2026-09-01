"""Builds the FHIR charge bundle a provider has confirmed for billing.

The human-in-the-loop constraint
--------------------------------
Selecting an evaluation-and-management level is a BILLING DETERMINATION with
legal and financial consequence. Upcoding is fraud; undercoding is lost revenue
the clinician earned. It is not a judgement a language model gets to make.

So this module never emits a billable charge on its own:

    suggest_charge()  produces a PLANNED ChargeItem — a proposal, nothing more
    confirm_charge()  turns a provider's explicit confirmation into a BILLABLE one

`Charge_Outbound` in Mirth skips any ChargeItem whose status is not 'billable',
so a suggestion that was never confirmed cannot reach a billing system even if
something upstream tried to send it. The gate is enforced twice, in two
different systems, because a single check is a single point of failure for
something this consequential.

This mirrors the approve gate the project already has for the note itself, and
follows the same principle as Guardrail #1: the provider is the accountable
author.
"""

from __future__ import annotations

import logging

from fhir.resources.R4B.bundle import Bundle
from fhir.resources.R4B.chargeitem import ChargeItem
from fhir.resources.R4B.condition import Condition
from fhir.resources.R4B.patient import Patient
from fhir.resources.R4B.practitioner import Practitioner

from . import charge_codes, codes
from .builder import _iso_utc, _safe_id
from .cpt_config import lookup_cpt

logger = logging.getLogger(__name__)


def _build_conditions(session_id: str, pid: str, icd10_codes: list[str]) -> list[Condition]:
    """One Condition per diagnosis, each dual-coded SNOMED + ICD-10-CM."""
    conditions = []
    for index, icd10 in enumerate(icd10_codes, start=1):
        concept = charge_codes.dual_coding(icd10)
        if not concept:
            # Skip rather than emit a Condition with an unmapped code. The
            # warning is raised in charge_codes.dual_coding.
            continue
        conditions.append(Condition(
            id=_safe_id(f'cond{index}', session_id),
            clinicalStatus={'coding': [{
                'system': charge_codes.CONDITION_CLINICAL_SYSTEM,
                'code': 'active',
            }]},
            verificationStatus={'coding': [{
                'system': charge_codes.CONDITION_VERIFICATION_SYSTEM,
                'code': 'confirmed',
            }]},
            code=concept,
            subject={'reference': f'Patient/{pid}'},
        ))
    if not conditions:
        logger.error(
            '[interop.charge] Session %s produced no codeable Condition from %s',
            session_id, icd10_codes
        )
    return conditions


def build_charge_bundle(session: dict, icd10_codes: list[str], cpt_code: str,
                        *, confirmed_by: str | None) -> Bundle:
    """Build the charge bundle for a session.

    `confirmed_by` is the provider identifier that confirmed the charge. When it
    is None the ChargeItem is emitted as `planned` and is NOT billable.

    Raises ValueError when the inputs cannot produce a postable charge, rather
    than emitting a bundle that would be silently dropped downstream.
    """
    session_id = session.get('id')
    if not session_id:
        raise ValueError('session.id is required to build a charge bundle')

    procedure = lookup_cpt(cpt_code)
    if not procedure:
        raise ValueError(
            f'CPT code {cpt_code!r} is not in the configured code list. '
            'See pipeline/interop/cpt_config.py — CPT is AMA-licensed and is '
            'supplied by configuration, never committed.'
        )

    pid  = _safe_id('pat', session_id)
    prid = _safe_id('prac', session_id)
    eid  = _safe_id('enc', session_id)
    cid  = _safe_id('charge', session_id)

    patient = Patient(id=pid, identifier=[{
        'type':   {'coding': [codes.IDENTIFIER_TYPE_MR]},
        'system': codes.HISCRIBE_MRN_SYSTEM,
        'value':  session.get('patient_mrn'),
    }] if session.get('patient_mrn') else None)

    practitioner = Practitioner(id=prid, identifier=[{
        'system': codes.NPI_SYSTEM, 'value': session['provider_npi'],
    }] if session.get('provider_npi') else None)

    conditions = _build_conditions(session_id, pid, icd10_codes)
    if not conditions:
        raise ValueError(
            f'session {session_id} has no mappable diagnosis — a charge without '
            'an ICD-10-CM diagnosis cannot be adjudicated'
        )

    status = (charge_codes.CHARGE_STATUS_BILLABLE if confirmed_by
              else charge_codes.CHARGE_STATUS_PLANNED)

    charge_item = ChargeItem(
        # The id is derived from the session, which makes it stable across
        # retries. It becomes FT1-2, the transaction id a billing system uses
        # to reject a duplicate instead of double-billing the patient.
        id=cid,
        status=status,
        code={'coding': [{
            'system':  charge_codes.CPT_SYSTEM,
            'code':    procedure['code'],
            'display': procedure['display'],
        }]},
        subject={'reference': f'Patient/{pid}'},
        context={'reference': f'Encounter/{eid}'},
        occurrenceDateTime=_iso_utc(session.get('approved_at')),
        quantity={'value': 1},
        performer=[{'actor': {'reference': f'Practitioner/{prid}'}}],
        # R4B ChargeItem.reason is a CodeableConcept, not a Reference — there is
        # no reasonReference on this resource. The diagnosis codes are carried
        # inline so the charge is self-describing to a billing system that does
        # not resolve references, and the Condition resources are linked through
        # supportingInformation for a consumer that does.
        reason=[c.code for c in conditions],
        supportingInformation=[
            {'reference': f'Condition/{c.id}'} for c in conditions
        ],
        enterer={'reference': f'Practitioner/{prid}'} if confirmed_by else None,
    )

    entries = [
        {'resource': patient,      'request': {'method': 'PUT', 'url': f'Patient/{pid}'}},
        {'resource': practitioner, 'request': {'method': 'PUT', 'url': f'Practitioner/{prid}'}},
    ]
    entries += [
        {'resource': c, 'request': {'method': 'PUT', 'url': f'Condition/{c.id}'}}
        for c in conditions
    ]
    entries.append(
        {'resource': charge_item, 'request': {'method': 'PUT', 'url': f'ChargeItem/{cid}'}}
    )

    logger.info(
        '[interop.charge] Built charge bundle session=%s status=%s cpt=%s '
        'conditions=%d confirmed_by=%s',
        session_id, status, procedure['code'], len(conditions), confirmed_by or 'NOT CONFIRMED'
    )
    if status != charge_codes.CHARGE_STATUS_BILLABLE:
        logger.warning(
            '[interop.charge] Session %s charge is %s, not billable — it will be '
            'skipped by Charge_Outbound', session_id, status
        )

    return Bundle(type='transaction', entry=entries)
