"""Tests for coded charge capture.

The behaviours worth protecting here are the ones with consequences: the
provider-confirmation gate, dual coding, and the refusal to invent a code.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from interop import charge_codes, cpt_config  # noqa: E402
from interop.charge import build_charge_bundle  # noqa: E402


SESSION = {
    'id': 'sess-test-001',
    'patient_mrn': 'MRN000111',
    'provider_npi': '1234567893',
    'approved_at': '2026-09-01 14:31:00',
}


@pytest.fixture(autouse=True)
def cpt_table(tmp_path, monkeypatch):
    """Point cpt_config at a temporary table.

    Real CPT descriptors are AMA-licensed and are not committed, so the test
    supplies its own placeholder table — which also proves the config path is
    genuinely the only source of CPT codes.
    """
    path = tmp_path / 'cpt_codes.json'
    path.write_text(json.dumps({
        '99213': {'display': 'Established patient, low level (test placeholder)'},
    }), encoding='utf-8')
    monkeypatch.setenv('CPT_CONFIG_PATH', str(path))
    monkeypatch.setattr(cpt_config, '_CONFIG_PATH', str(path))
    cpt_config.reset_cache()
    yield
    cpt_config.reset_cache()


def _resources(bundle, resource_type):
    return [e.resource for e in bundle.entry
            if e.resource.__class__.__name__ == resource_type]


# ── The confirmation gate ────────────────────────────────────────────────────

def test_unconfirmed_charge_is_planned_not_billable():
    bundle = build_charge_bundle(SESSION, ['J02.9'], '99213', confirmed_by=None)
    charge = _resources(bundle, 'ChargeItem')[0]
    assert charge.status == 'planned'
    assert charge.status != charge_codes.CHARGE_STATUS_BILLABLE


def test_confirmed_charge_is_billable_and_records_the_enterer():
    bundle = build_charge_bundle(SESSION, ['J02.9'], '99213', confirmed_by='dr-smith')
    charge = _resources(bundle, 'ChargeItem')[0]
    assert charge.status == 'billable'
    # Someone must be recorded as having taken responsibility for the level.
    assert charge.enterer is not None


def test_charge_id_is_stable_across_rebuilds():
    """FT1-2 idempotency: a retry must not become a second billable charge."""
    first = build_charge_bundle(SESSION, ['J02.9'], '99213', confirmed_by='dr-smith')
    second = build_charge_bundle(SESSION, ['J02.9'], '99213', confirmed_by='dr-smith')
    assert _resources(first, 'ChargeItem')[0].id == _resources(second, 'ChargeItem')[0].id


# ── Dual coding ──────────────────────────────────────────────────────────────

def test_condition_carries_both_snomed_and_icd10():
    bundle = build_charge_bundle(SESSION, ['J02.9'], '99213', confirmed_by='dr-smith')
    condition = _resources(bundle, 'Condition')[0]
    systems = {c.system for c in condition.code.coding}
    assert charge_codes.SNOMED_SYSTEM in systems, 'clinical meaning must survive'
    assert charge_codes.ICD10_CM_SYSTEM in systems, 'the claim needs ICD-10-CM'


def test_dual_coding_returns_none_for_unknown_code():
    """An unmapped diagnosis must not be guessed at."""
    assert charge_codes.dual_coding('ZZ99.9') is None


def test_unmappable_diagnosis_refuses_to_build():
    with pytest.raises(ValueError, match='no mappable diagnosis'):
        build_charge_bundle(SESSION, ['ZZ99.9'], '99213', confirmed_by='dr-smith')


def test_multiple_diagnoses_each_become_a_condition():
    bundle = build_charge_bundle(SESSION, ['J02.9', 'I10'], '99213',
                                 confirmed_by='dr-smith')
    assert len(_resources(bundle, 'Condition')) == 2


# ── CPT licensing boundary ───────────────────────────────────────────────────

def test_unconfigured_cpt_code_is_refused():
    with pytest.raises(ValueError, match='not in the configured code list'):
        build_charge_bundle(SESSION, ['J02.9'], '99999', confirmed_by='dr-smith')


def test_missing_cpt_config_disables_charge_capture(tmp_path, monkeypatch):
    """No CPT config is a normal state, not a crash."""
    monkeypatch.setattr(cpt_config, '_CONFIG_PATH', str(tmp_path / 'absent.json'))
    cpt_config.reset_cache()
    assert cpt_config.lookup_cpt('99213') is None


def test_no_cpt_codes_are_committed_to_the_repository():
    """CPT descriptors are AMA-licensed and must never enter source control."""
    repo = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
    committed = os.path.join(repo, 'config', 'cpt_codes.json')
    if os.path.exists(committed):
        with open(os.path.join(repo, '.gitignore'), encoding='utf-8') as fh:
            gitignore = fh.read()
        assert 'config/cpt_codes.json' in gitignore, (
            'config/cpt_codes.json exists but is not gitignored — CPT '
            'descriptors must never be committed'
        )


# ── Bundle shape ─────────────────────────────────────────────────────────────

def test_bundle_links_conditions_to_the_charge():
    bundle = build_charge_bundle(SESSION, ['J02.9', 'I10'], '99213',
                                 confirmed_by='dr-smith')
    charge = _resources(bundle, 'ChargeItem')[0]
    # reason carries the codes inline; supportingInformation carries references.
    assert len(charge.reason) == 2
    assert len(charge.supportingInformation) == 2


def test_session_without_id_is_rejected():
    with pytest.raises(ValueError, match='session.id is required'):
        build_charge_bundle({}, ['J02.9'], '99213', confirmed_by='dr-smith')
