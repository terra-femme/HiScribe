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
                       remap_segment, save_fhir_bundle)
from graph.pipeline import run_pipeline
from adapters.enrollment_embedding import build_enrollment_profile, encrypt_embedding
from interop.builder import build_bundle
from interop.client import send_bundle

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
                session_id
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
                session_id, fhir['status'], result.get('destination')
            )
    except Exception as exc:
        logger.error(
            '[approve] FHIR generation FAILED session=%s: %s — approval stands, '
            'bundle can be re-emitted', session_id, exc, exc_info=True
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
