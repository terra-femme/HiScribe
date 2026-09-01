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
