import logging
import os
import tempfile

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from db.enrollment import delete_enrollment, get_active_enrollments, save_enrollment
from db.sqlite import (add_amendment, approve_session, delete_segment,
                       edit_segment, get_review_payload, init_db,
                       remap_segment, save_charge, save_fhir_bundle,
                       get_patient_context, save_patient_context)
from graph.pipeline import run_pipeline
from adapters.enrollment_embedding import build_enrollment_profile, encrypt_embedding
from interop.builder import build_bundle
from interop.logsafe import scrub
from interop.charge import build_charge_bundle
from interop.client import send_bundle
from interop.charge_client import send_charge

logger = logging.getLogger(__name__)

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'))

app = FastAPI(title='HiScribe Pipeline', version='1.0.0')

_client_url = os.environ.get('CLIENT_URL', 'http://localhost:5173')
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_client_url],
    allow_methods=['GET', 'POST', 'DELETE'],
    allow_headers=['Authorization', 'Content-Type']
)

init_db()


@app.get('/health')
def health():
    return {'status': 'ok', 'service': 'hiscribe-pipeline'}


# --- Pipeline ---

class PipelineRequest(BaseModel):
    session_id: str

@app.post('/pipeline/run')
async def trigger_pipeline(req: PipelineRequest):
    result = await run_pipeline(req.session_id)
    return result


# --- Note retrieval ---

@app.get('/session/{session_id}/note')
def get_note(session_id: str):
    payload = get_review_payload(session_id)
    if not payload:
        raise HTTPException(status_code=404, detail='Session not found')
    return payload


# --- Provider CRUD ---

class ApproveRequest(BaseModel):
    provider_npi: str
    patient_mrn: str
    visit_type: str

@app.post('/session/{session_id}/approve')
def approve(session_id: str, req: ApproveRequest):
    approve_session(session_id, req.provider_npi, req.patient_mrn, req.visit_type)

    # FHIR emission is deliberately non-fatal. The provider has already
    # approved the note and the approval is committed; a serialisation or
    # delivery failure must not undo that or surface as a failed approval.
    # The bundle is derived state and can always be rebuilt from the DB.
    fhir: dict = {'status': 'skipped', 'detail': None}
    try:
        payload = get_review_payload(session_id)
        if not payload:
            logger.error(
                '[approve] No review payload for session=%s — FHIR skipped',
                scrub(session_id)
            )
            fhir = {'status': 'error', 'detail': 'review payload not found'}
        else:
            bundle_json = build_bundle(payload).model_dump_json(exclude_none=True)
            result = send_bundle(session_id, bundle_json)
            save_fhir_bundle(
                session_id,
                bundle_json,
                destination=result.get('destination'),
                status=result.get('status', 'generated'),
            )
            fhir = {'status': result.get('status'), 'detail': result.get('detail')}
            logger.info(
                '[approve] FHIR bundle emitted session=%s status=%s dest=%s',
                scrub(session_id), scrub(fhir['status']), scrub(result.get('destination'))
            )
    except Exception as exc:
        logger.error(
            '[approve] FHIR generation FAILED session=%s: %s — approval stands, '
            'bundle can be re-emitted', scrub(session_id), scrub(exc), exc_info=True
        )
        fhir = {'status': 'error', 'detail': str(exc)}

    return {'status': 'approved', 'session_id': session_id, 'fhir': fhir}


class RemapRequest(BaseModel):
    session_id: str
    from_section: str
    to_section: str
    provider_id: str

@app.post('/segment/{segment_id}/remap')
def remap(segment_id: str, req: RemapRequest):
    remap_segment(segment_id, req.session_id, req.from_section, req.to_section, req.provider_id)
    return {'status': 'remapped'}


class EditRequest(BaseModel):
    session_id: str
    corrected_text: str
    provider_id: str

@app.post('/segment/{segment_id}/edit')
def edit(segment_id: str, req: EditRequest):
    edit_segment(segment_id, req.session_id, req.corrected_text, req.provider_id)
    return {'status': 'edited'}


class DeleteRequest(BaseModel):
    session_id: str
    provider_id: str
    reason: str = ''

@app.delete('/segment/{segment_id}')
def delete(segment_id: str, req: DeleteRequest):
    delete_segment(segment_id, req.session_id, req.provider_id, req.reason)
    return {'status': 'deleted'}


class AmendmentRequest(BaseModel):
    content: str
    soap_section: str
    provider_id: str

@app.post('/session/{session_id}/amendment')
def amendment(session_id: str, req: AmendmentRequest):
    add_amendment(session_id, req.content, req.soap_section, req.provider_id)
    return {'status': 'amendment_added'}


# --- Enrollment --------------------------------------------------------------

@app.post('/enrollment/enroll')
async def enroll_provider(
    provider_id: str = Form(...),
    name: str = Form(...),
    audio: UploadFile = File(...),
):
    tmp_path = None
    try:
        suffix = os.path.splitext(audio.filename or '.wav')[1] or '.wav'
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await audio.read())
            tmp_path = tmp.name

        logger.info('[enroll] Processing enrollment for provider_id=%s name=%s file=%s',
                    provider_id, name, tmp_path)

        profile = build_enrollment_profile(tmp_path)
        encrypted = encrypt_embedding(profile['embedding'])
        save_enrollment(provider_id, name, encrypted, profile['quality_score'], profile['sample_count'])

        logger.info('[enroll] Enrollment saved provider_id=%s quality=%.3f samples=%d',
                    provider_id, profile['quality_score'], profile['sample_count'])

        return {
            'provider_id': provider_id,
            'quality_score': profile['quality_score'],
            'sample_count': profile['sample_count'],
        }

    except ValueError as exc:
        logger.warning('[enroll] Rejected enrollment for %s: %s', provider_id, exc)
        raise HTTPException(status_code=400, detail=str(exc))

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
            logger.debug('[enroll] Deleted temp audio %s', tmp_path)


@app.get('/enrollment/providers')
def list_providers():
    records = get_active_enrollments()
    # Strip encrypted_embedding — never expose raw biometric bytes over the wire
    return [
        {
            'provider_id': r['provider_id'],
            'name': r['name'],
            'quality_score': r['quality_score'],
            'sample_count': r['sample_count'],
            'enrolled_at': r['enrolled_at'],
            'updated_at': r['updated_at'],
        }
        for r in records
    ]


@app.delete('/enrollment/{provider_id}')
def remove_enrollment(provider_id: str):
    deleted = delete_enrollment(provider_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f'Provider {provider_id!r} not found')
    return {'status': 'deleted', 'provider_id': provider_id}


# ── Interop: inbound ADT ─────────────────────────────────────────────────────

class PatientContext(BaseModel):
    """Patient context posted by the Mirth ADT_Inbound channel.

    Field names mirror the JSON that `mirth/transformers/adt_inbound.js`
    produces. Everything except `mrn` is optional because a real ADT feed is
    inconsistent about what it populates, and rejecting a whole message for a
    missing middle name would be worse than storing what did arrive.
    """
    mrn: str
    assigningAuthority: str | None = None
    familyName: str | None = None
    givenName: str | None = None
    birthDate: str | None = None
    administrativeSex: str | None = None
    patientClass: str | None = None
    attendingNpi: str | None = None
    visitNumber: str | None = None
    triggerEvent: str | None = None
    messageControlId: str | None = None


@app.post('/fhir/patient-context')
def receive_patient_context(ctx: PatientContext):
    """Accept patient demographics derived from an inbound ADT message.

    Called by Mirth, not by a browser. Returning 4xx here makes the ADT_Inbound
    channel record an error, which is the correct behaviour: a demographic
    update that could not be stored must not be silently acknowledged.
    """
    logger.info(
        '[patient-context] %s mrn=%s class=%s control=%s',
        scrub(ctx.triggerEvent), scrub(ctx.mrn), scrub(ctx.patientClass),
        scrub(ctx.messageControlId)
    )
    try:
        save_patient_context(ctx.model_dump())
    except ValueError as exc:
        # The message is logged in full but not returned. Echoing an exception
        # string to a caller leaks internal structure, and this endpoint is
        # reachable by anything that can talk to the interface engine.
        logger.error('[patient-context] Rejected: %s', scrub(exc))
        raise HTTPException(status_code=400,
                            detail='patient context rejected: missing or invalid MRN')
    except Exception as exc:
        logger.error('[patient-context] FAILED to store mrn=%s: %s',
                     scrub(ctx.mrn), scrub(exc), exc_info=True)
        raise HTTPException(status_code=500, detail='could not store patient context')
    return {'status': 'stored', 'mrn': ctx.mrn}


@app.get('/fhir/patient-context/{mrn}')
def read_patient_context(mrn: str):
    context = get_patient_context(mrn)
    if not context:
        raise HTTPException(status_code=404, detail=f'No patient context for MRN {mrn!r}')
    return context


# ── Interop: coded charge capture ────────────────────────────────────────────

# Returned instead of the exception text. The reasons a charge is refused
# (unmapped diagnosis, unconfigured CPT) are actionable to an operator reading
# the log, not to an arbitrary caller.
_CHARGE_REJECTED = ('charge rejected: the diagnosis could not be mapped to '
                    'ICD-10-CM, or the CPT code is not configured')


class ChargeRequest(BaseModel):
    cpt_code: str
    icd10_codes: list[str]
    # Present only on confirmation. Its absence is what keeps a charge planned.
    confirmed_by: str | None = None


@app.post('/session/{session_id}/charge/suggest')
def suggest_charge(session_id: str, req: ChargeRequest):
    """Record a proposed charge. Never billable, never sent downstream.

    The provider is the accountable party for an E/M level. This endpoint exists
    so a suggestion is captured and auditable, not so it can be billed.
    """
    payload = get_review_payload(session_id)
    if not payload:
        raise HTTPException(status_code=404, detail=f'Unknown session {session_id!r}')
    try:
        bundle = build_charge_bundle(
            payload['session'], req.icd10_codes, req.cpt_code, confirmed_by=None
        )
    except ValueError as exc:
        logger.error('[charge.suggest] session=%s rejected: %s',
                     scrub(session_id), scrub(exc))
        raise HTTPException(status_code=400, detail=_CHARGE_REJECTED)

    save_charge(session_id, req.cpt_code, req.icd10_codes, status='planned')
    logger.info('[charge.suggest] session=%s cpt=%s icd10=%s (NOT billable)',
                scrub(session_id), scrub(req.cpt_code), scrub(req.icd10_codes))
    return {'status': 'planned', 'session_id': session_id,
            'bundle': bundle.model_dump(exclude_none=True)}


@app.post('/session/{session_id}/charge/confirm')
def confirm_charge(session_id: str, req: ChargeRequest):
    """Provider confirms the charge; only now is it billable and posted.

    `confirmed_by` is required. Without it there is no accountable author for a
    billing determination, and the charge stays planned.
    """
    if not req.confirmed_by:
        raise HTTPException(
            status_code=400,
            detail='confirmed_by is required — a charge cannot be billed without '
                   'an identified provider taking responsibility for the level'
        )
    payload = get_review_payload(session_id)
    if not payload:
        raise HTTPException(status_code=404, detail=f'Unknown session {session_id!r}')

    try:
        bundle = build_charge_bundle(
            payload['session'], req.icd10_codes, req.cpt_code,
            confirmed_by=req.confirmed_by
        )
    except ValueError as exc:
        logger.error('[charge.confirm] session=%s rejected: %s',
                     scrub(session_id), scrub(exc))
        raise HTTPException(status_code=400, detail=_CHARGE_REJECTED)

    bundle_json = bundle.model_dump_json(exclude_none=True)
    # Delivery is non-fatal for the same reason note emission is: the provider's
    # confirmation is a recorded fact, and a billing system being unreachable
    # must not erase it. The charge is persisted and can be re-posted.
    result = send_charge(session_id, bundle_json)
    save_charge(session_id, req.cpt_code, req.icd10_codes, status='billable',
                confirmed_by=req.confirmed_by, bundle_json=bundle_json,
                destination=result.get('destination'))

    logger.info('[charge.confirm] session=%s cpt=%s by=%s delivery=%s',
                scrub(session_id), scrub(req.cpt_code), scrub(req.confirmed_by),
                scrub(result.get('status')))
    return {'status': 'billable', 'session_id': session_id,
            'confirmed_by': req.confirmed_by, 'delivery': result}
