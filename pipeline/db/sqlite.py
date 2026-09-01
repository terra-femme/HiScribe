import sqlite3
import json
import os
from datetime import datetime


# Shared DB — same file the Node gateway writes to
_DB_PATH = os.environ.get(
    'DB_PATH',
    os.path.join(os.path.dirname(__file__), '../../data/hiscribe.db')
)
_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), '../../schema.sql')


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(os.path.normpath(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL') # this is the journal mode to use for the database
    conn.execute('PRAGMA foreign_keys=ON') # this is the foreign keys to use for the database
    return conn


def init_db():
    os.makedirs(os.path.dirname(os.path.normpath(_DB_PATH)), exist_ok=True)
    if os.path.exists(_SCHEMA_PATH):
        with open(_SCHEMA_PATH) as f:
            schema = f.read()
        with _conn() as conn:
            conn.executescript(schema)
        print(f'[db] Schema initialized at {_DB_PATH}')


def get_segments(session_id: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            'SELECT * FROM segments WHERE session_id = ? AND is_final = 1 ORDER BY start_ms ASC',
            (session_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def update_segment_diarization(segment_id: str, speaker: str, role_flag: bool):
    with _conn() as conn:
        conn.execute(
            'UPDATE segments SET speaker = ?, role_flag = ? WHERE segment_id = ?',
            (speaker, 1 if role_flag else 0, segment_id)
        )


def update_segment_mapping(segment_id: str, soap_section: str):
    with _conn() as conn:
        conn.execute(
            'UPDATE segments SET soap_section = ? WHERE segment_id = ?',
            (soap_section, segment_id)
        )


def update_segment_score(segment_id: str, reliability_score: float, confidence_flag: bool):
    with _conn() as conn:
        conn.execute(
            'UPDATE segments SET reliability_score = ?, confidence_flag = ? WHERE segment_id = ?',
            (reliability_score, 1 if confidence_flag else 0, segment_id)
        )


def get_review_payload(session_id: str) -> dict | None:
    with _conn() as conn:
        session = conn.execute(
            'SELECT * FROM sessions WHERE id = ?', (session_id,)
        ).fetchone()
        if not session:
            return None
        segments = conn.execute(
            'SELECT * FROM segments WHERE session_id = ? AND is_final = 1 ORDER BY start_ms ASC',
            (session_id,)
        ).fetchall()
        amendments = conn.execute(
            'SELECT * FROM amendments WHERE session_id = ?', (session_id,)
        ).fetchall()

    soap: dict = {'S': [], 'O': [], 'A': [], 'P': [], 'UNCLASSIFIED': []}
    for seg in segments:
        s = dict(seg)
        section = s.get('soap_section') or 'UNCLASSIFIED'
        soap.setdefault(section, []).append(s)

    return {
        'session': dict(session),
        'soap': soap,
        'amendments': [dict(a) for a in amendments]
    }


def approve_session(session_id: str, provider_npi: str, patient_mrn: str, visit_type: str):
    now = datetime.utcnow().isoformat()
    with _conn() as conn:
        conn.execute(
            '''UPDATE sessions SET status = 'approved', provider_npi = ?, patient_mrn = ?,
               visit_type = ?, approved_at = ? WHERE id = ?''',
            (provider_npi, patient_mrn, visit_type, now, session_id)
        )
        _append_audit(conn, session_id, 'session_approved', payload={
            'provider_npi': provider_npi,
            'patient_mrn': patient_mrn,
            'visit_type': visit_type,
            'approved_at': now
        })


def save_fhir_bundle(session_id: str, bundle_json: str, destination: str | None,
                     status: str = 'generated', fhir_version: str = 'R4B'):
    """Persist a generated FHIR bundle and record the fact in the audit log.

    The bundle row is replaced on re-emission (derived state), while the audit
    entry is appended (history). The audit payload deliberately carries only
    metadata — never the bundle body, which contains PHI and would bloat the
    append-only log.
    """
    with _conn() as conn:
        conn.execute(
            '''INSERT INTO fhir_bundles (session_id, bundle_json, fhir_version, status, destination)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET
                 bundle_json  = excluded.bundle_json,
                 fhir_version = excluded.fhir_version,
                 status       = excluded.status,
                 destination  = excluded.destination''',
            (session_id, bundle_json, fhir_version, status, destination)
        )
        _append_audit(conn, session_id, 'fhir_generated', payload={
            'status':       status,
            'fhir_version': fhir_version,
            'destination':  destination,
            'bytes':        len(bundle_json),
        })


def get_fhir_bundle(session_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            'SELECT * FROM fhir_bundles WHERE session_id = ?', (session_id,)
        ).fetchone()
    return dict(row) if row else None


def remap_segment(segment_id: str, session_id: str, from_section: str, to_section: str, provider_id: str):
    with _conn() as conn:
        conn.execute(
            'UPDATE segments SET soap_section = ? WHERE segment_id = ?',
            (to_section, segment_id)
        )
        _append_audit(conn, session_id, 'segment_remapped', segment_id=segment_id, provider_id=provider_id,
                      payload={'from_section': from_section, 'to_section': to_section})


def edit_segment(segment_id: str, session_id: str, corrected_text: str, provider_id: str):
    with _conn() as conn:
        original = conn.execute(
            'SELECT text FROM segments WHERE segment_id = ?', (segment_id,)
        ).fetchone()
        original_text = original['text'] if original else ''

        conn.execute(
            'UPDATE segments SET text = ? WHERE segment_id = ?',
            (corrected_text, segment_id)
        )
        _append_audit(conn, session_id, 'segment_edited', segment_id=segment_id, provider_id=provider_id,
                      payload={'original_text': original_text, 'corrected_text': corrected_text})


def delete_segment(segment_id: str, session_id: str, provider_id: str, reason: str = ''):
    with _conn() as conn:
        row = conn.execute(
            'SELECT text FROM segments WHERE segment_id = ?', (segment_id,)
        ).fetchone()
        deleted_text = row['text'] if row else ''

        conn.execute('DELETE FROM segments WHERE segment_id = ?', (segment_id,))
        _append_audit(conn, session_id, 'segment_deleted', segment_id=segment_id, provider_id=provider_id,
                      payload={'deleted_text': deleted_text, 'reason': reason})


def add_amendment(session_id: str, content: str, soap_section: str, provider_id: str):
    with _conn() as conn:
        conn.execute(
            'INSERT INTO amendments (session_id, content, soap_section, provider_id) VALUES (?, ?, ?, ?)',
            (session_id, content, soap_section, provider_id)
        )
        _append_audit(conn, session_id, 'amendment_added', provider_id=provider_id,
                      payload={'content': content, 'soap_section': soap_section})


def _append_audit(conn, session_id: str, event_type: str, segment_id: str = None,
                  provider_id: str = None, payload: dict = None):
    conn.execute(
        '''INSERT INTO audit_log (session_id, event_type, segment_id, provider_id, payload)
           VALUES (?, ?, ?, ?, ?)''',
        (session_id, event_type, segment_id, provider_id, json.dumps(payload or {}))
    )


def save_patient_context(context: dict) -> None:
    """Upsert patient context received from an inbound ADT message.

    Keyed on MRN, not session id: registration happens at the front desk before
    any HiScribe session exists. The row is current-state and is replaced on
    each update; the append-only history of what arrived lives in audit_log.

    The audit row is written against the MRN rather than a session id because
    there is no session yet. That is a deliberate widening of the audit_log
    convention, not an accident — an inbound demographic update is an auditable
    event even when it does not belong to an encounter.
    """
    mrn = context.get('mrn')
    if not mrn:
        raise ValueError('patient context requires an MRN')

    with _conn() as conn:
        conn.execute(
            '''INSERT INTO patient_context
                 (mrn, assigning_authority, family_name, given_name, birth_date,
                  administrative_sex, patient_class, attending_npi, visit_number,
                  trigger_event, message_control_id, received_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(mrn) DO UPDATE SET
                 assigning_authority = excluded.assigning_authority,
                 family_name         = excluded.family_name,
                 given_name          = excluded.given_name,
                 birth_date          = excluded.birth_date,
                 administrative_sex  = excluded.administrative_sex,
                 patient_class       = excluded.patient_class,
                 attending_npi       = excluded.attending_npi,
                 visit_number        = excluded.visit_number,
                 trigger_event       = excluded.trigger_event,
                 message_control_id  = excluded.message_control_id,
                 received_at         = datetime('now')''',
            (mrn, context.get('assigningAuthority'), context.get('familyName'),
             context.get('givenName'), context.get('birthDate'),
             context.get('administrativeSex'), context.get('patientClass'),
             context.get('attendingNpi'), context.get('visitNumber'),
             context.get('triggerEvent'), context.get('messageControlId'))
        )
        # Demographics are PHI. The audit payload records that an update landed
        # and which message carried it — never the demographic values.
        _append_audit(conn, mrn, 'patient_context_received', payload={
            'trigger_event':      context.get('triggerEvent'),
            'message_control_id': context.get('messageControlId'),
            'patient_class':      context.get('patientClass'),
            'has_attending':      bool(context.get('attendingNpi')),
        })


def get_patient_context(mrn: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            'SELECT * FROM patient_context WHERE mrn = ?', (mrn,)
        ).fetchone()
    return dict(row) if row else None


def save_charge(session_id: str, cpt_code: str, icd10_codes: list, status: str,
                confirmed_by: str = None, bundle_json: str = None,
                destination: str = None) -> None:
    """Persist a charge and audit the transition.

    `charge_suggested` and `charge_confirmed` are distinct events on purpose.
    A suggestion is the model proposing a level; a confirmation is a provider
    accepting legal and financial responsibility for it. Collapsing them into
    one event would destroy the only evidence of who made the determination.
    """
    event = 'charge_confirmed' if confirmed_by else 'charge_suggested'
    with _conn() as conn:
        conn.execute(
            '''INSERT INTO charges
                 (session_id, cpt_code, icd10_codes, status, confirmed_by,
                  confirmed_at, bundle_json, destination)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET
                 cpt_code     = excluded.cpt_code,
                 icd10_codes  = excluded.icd10_codes,
                 status       = excluded.status,
                 confirmed_by = excluded.confirmed_by,
                 confirmed_at = excluded.confirmed_at,
                 bundle_json  = excluded.bundle_json,
                 destination  = excluded.destination''',
            (session_id, cpt_code, json.dumps(icd10_codes), status, confirmed_by,
             datetime.utcnow().isoformat() if confirmed_by else None,
             bundle_json, destination)
        )
        _append_audit(conn, session_id, event, provider_id=confirmed_by, payload={
            'cpt_code':    cpt_code,
            'icd10_codes': icd10_codes,
            'status':      status,
            'destination': destination,
        })


def get_charge(session_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            'SELECT * FROM charges WHERE session_id = ?', (session_id,)
        ).fetchone()
    return dict(row) if row else None
