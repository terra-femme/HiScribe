"""Tests for the FHIR emission layer.

Covers the two things most likely to break silently: the payload -> Bundle
mapping, and the persistence contract (bundle row replaced, audit row appended).
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


@pytest.fixture
def payload():
    return {
        'session': {
            'id': 'sess-1',
            'provider_npi': '1234567893',
            'patient_mrn': 'MRN-9001',
            'visit_type': 'follow_up',
            'created_at': '2026-08-10 14:00:00',
            'ended_at': '2026-08-10 14:18:00',
            'approved_at': '2026-08-10 14:25:00',
        },
        'soap': {
            'S': [{'speaker': 'PATIENT', 'text': 'cough for 3 days'}],
            'O': [{'speaker': 'DOCTOR', 'text': 'lungs clear'}],
            'A': [{'speaker': 'DOCTOR', 'text': 'viral URI'}],
            'P': [{'speaker': 'DOCTOR', 'text': 'fluids and rest'}],
            'UNCLASSIFIED': [],
        },
        'amendments': [],
    }


def _as_dict(bundle):
    return json.loads(bundle.model_dump_json(exclude_none=True))


def _resource(bundle_dict, resource_type):
    return next(
        e['resource'] for e in bundle_dict['entry']
        if e['resource']['resourceType'] == resource_type
    )


# ── Builder ──────────────────────────────────────────────────────────────────

def test_bundle_has_all_four_resources(payload):
    from interop.builder import build_bundle
    d = _as_dict(build_bundle(payload))
    types = {e['resource']['resourceType'] for e in d['entry']}
    assert types == {'Patient', 'Practitioner', 'Encounter', 'Composition'}
    assert d['type'] == 'transaction'


def test_soap_sections_carry_verified_loinc_codes(payload):
    from interop.builder import build_bundle
    comp = _resource(_as_dict(build_bundle(payload)), 'Composition')
    got = {
        s['title']: s['code']['coding'][0]['code']
        for s in comp['section'] if 'code' in s
    }
    assert got == {
        'Subjective': '61150-9',
        'Objective':  '61149-1',
        'Assessment': '51848-0',
        'Plan':       '18776-5',
    }


def test_empty_sections_are_omitted(payload):
    from interop.builder import build_bundle
    payload['soap']['P'] = []
    comp = _resource(_as_dict(build_bundle(payload)), 'Composition')
    assert 'Plan' not in [s['title'] for s in comp['section']]


def test_unclassified_segments_are_kept_but_uncoded(payload):
    """Unplaced segments must survive into the note, without a fabricated code."""
    from interop.builder import build_bundle
    payload['soap']['UNCLASSIFIED'] = [{'speaker': 'UNKNOWN', 'text': 'crosstalk'}]
    comp = _resource(_as_dict(build_bundle(payload)), 'Composition')
    section = next(s for s in comp['section'] if 'Unclassified' in s['title'])
    assert 'code' not in section
    assert 'crosstalk' in section['text']['div']


def test_amendments_become_a_distinct_section(payload):
    from interop.builder import build_bundle
    payload['amendments'] = [{'soap_section': 'P', 'content': 'Return if fever'}]
    comp = _resource(_as_dict(build_bundle(payload)), 'Composition')
    section = next(s for s in comp['section'] if 'Amendment' in s['title'])
    assert 'Return if fever' in section['text']['div']


def test_narrative_escapes_xml_special_characters(payload):
    """Unescaped transcript text produces XHTML that fails FHIR validation."""
    from interop.builder import build_bundle
    payload['soap']['S'] = [{'speaker': 'PATIENT', 'text': 'pain <sharp> & cold'}]
    comp = _resource(_as_dict(build_bundle(payload)), 'Composition')
    div = comp['section'][0]['text']['div']
    assert '&amp;' in div and '&lt;sharp&gt;' in div
    assert '<sharp>' not in div


def test_telehealth_maps_to_virtual_encounter_class(payload):
    from interop.builder import build_bundle
    payload['session']['visit_type'] = 'telehealth'
    enc = _resource(_as_dict(build_bundle(payload)), 'Encounter')
    assert enc['class']['code'] == 'VR'


def test_other_visit_types_map_to_ambulatory(payload):
    from interop.builder import build_bundle
    for vt in ('new_patient', 'follow_up', 'urgent_care'):
        payload['session']['visit_type'] = vt
        enc = _resource(_as_dict(build_bundle(payload)), 'Encounter')
        assert enc['class']['code'] == 'AMB', vt


def test_identifiers_are_not_used_as_resource_ids(payload):
    """MRN and NPI belong in `identifier`, never in an id that travels in URLs."""
    from interop.builder import build_bundle
    d = _as_dict(build_bundle(payload))
    for entry in d['entry']:
        assert 'MRN-9001' not in entry['resource']['id']
        assert '1234567893' not in entry['resource']['id']
    assert _resource(d, 'Patient')['identifier'][0]['value'] == 'MRN-9001'
    assert _resource(d, 'Practitioner')['identifier'][0]['value'] == '1234567893'


def test_provider_recorded_as_legal_attester(payload):
    from interop.builder import build_bundle
    comp = _resource(_as_dict(build_bundle(payload)), 'Composition')
    assert comp['attester'][0]['mode'] == 'legal'


def test_bundle_uses_put_so_reemission_is_idempotent(payload):
    from interop.builder import build_bundle
    d = _as_dict(build_bundle(payload))
    assert all(e['request']['method'] == 'PUT' for e in d['entry'])


def test_missing_session_id_raises(payload):
    from interop.builder import build_bundle
    payload['session'].pop('id')
    with pytest.raises(ValueError, match='session.id'):
        build_bundle(payload)


def test_note_with_no_content_raises_rather_than_emitting_empty(payload):
    from interop.builder import build_bundle
    payload['soap'] = {k: [] for k in payload['soap']}
    payload['amendments'] = []
    with pytest.raises(ValueError, match='no content'):
        build_bundle(payload)


# ── Persistence ──────────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv('DB_PATH', str(tmp_path / 'test.db'))
    for mod in ('db.sqlite',):
        sys.modules.pop(mod, None)
    import db.sqlite as sqlite_mod
    sqlite_mod._DB_PATH = str(tmp_path / 'test.db')
    sqlite_mod.init_db()
    with sqlite_mod._conn() as c:
        c.execute("INSERT INTO sessions (id, status) VALUES ('sess-1', 'recording')")
    return sqlite_mod


def test_reemission_replaces_bundle_but_appends_audit(db):
    """Bundle is derived state (replace); audit is history (append-only)."""
    db.save_fhir_bundle('sess-1', '{"a":1}', destination='/tmp/a.json')
    db.save_fhir_bundle('sess-1', '{"b":2}', destination='/tmp/b.json')

    with db._conn() as c:
        bundles = c.execute(
            "SELECT COUNT(*) FROM fhir_bundles WHERE session_id='sess-1'"
        ).fetchone()[0]
        audits = c.execute(
            "SELECT COUNT(*) FROM audit_log WHERE event_type='fhir_generated'"
        ).fetchone()[0]

    assert bundles == 1
    assert audits == 2
    assert db.get_fhir_bundle('sess-1')['bundle_json'] == '{"b":2}'


def test_audit_payload_excludes_bundle_body(db):
    """The append-only log must not accumulate PHI or megabytes of JSON."""
    body = '{"secret":"' + 'x' * 5000 + '"}'
    db.save_fhir_bundle('sess-1', body, destination='/tmp/a.json')
    with db._conn() as c:
        payload = c.execute(
            "SELECT payload FROM audit_log WHERE event_type='fhir_generated'"
        ).fetchone()[0]
    assert 'secret' not in payload
    assert json.loads(payload)['bytes'] == len(body)
