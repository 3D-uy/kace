"""Switching away from a managed probe must not revive its old GPIO consumer."""
import copy

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import (
    ConfigurationReview, ReviewMessage, SemanticValidation,
    _sections, build_configuration_review, render_configuration_review,
)
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.translations import get_mode, set_mode
from tests.unit.test_configuration_review import _hardware
from tests.unit.test_config_transaction import FakeTransport


def sources():
    old = _hardware(probe=True) + b"""[safe_z_home]
home_xy_position: 100,100
z_hop: 10
[bed_mesh]
mesh_min: 10,10
mesh_max: 200,200
probe_count: 5,5
algorithm: bicubic
"""
    previous = build_managed_config_plan(old, None, {'printer.cfg': None})
    return _hardware(probe=False), {a.remote_name: a.content for a in previous.artifacts}


def test_physical_z_retires_only_previous_managed_probe_branch_and_is_idempotent():
    generated, remote = sources()
    remote['printer.cfg'] += b'\n[gcode_macro USER_MACRO]\ngcode:\n    M117 Keep me\n'
    original = copy.deepcopy(remote)
    plan = build_managed_config_plan(generated, None, remote)
    sections = _sections(effective_hardware_text(plan))
    assert not {'probe', 'bltouch', 'safe_z_home', 'bed_mesh'} & sections.keys()
    assert sections['stepper_z']['endstop_pin'] == 'PB2'
    assert sections['stepper_z']['position_endstop'] == '0'
    assert sections['gcode_macro user_macro']['gcode'] == ''
    assert b'M117 Keep me' in plan.artifacts[0].content
    review = build_configuration_review(plan)
    assert review.validation.valid
    for field in ('[probe] pin', '[bed_mesh] mesh_min', '[safe_z_home] home_xy_position'):
        assert any(field in warning.message and 'removed' in warning.message
                   for warning in review.validation.warnings)
    updated = {a.remote_name: a.content for a in plan.artifacts}
    assert not build_managed_config_plan(generated, None, updated).changed_artifacts
    assert remote == original


@pytest.mark.parametrize('nested', [False, True])
def test_probe_in_user_root_or_include_is_preserved_and_conflict_still_blocks(nested):
    generated, remote = sources()
    user_probe = b'\n[probe]\npin: ^PB2\nz_offset: 2\n'
    if nested:
        remote['printer.cfg'] += b'\n[include user-probe.cfg]\n'
        remote['user-probe.cfg'] = user_probe
    else:
        remote['printer.cfg'] += user_probe
    plan = build_managed_config_plan(generated, None, remote)
    assert _sections(effective_hardware_text(plan))['probe']['z_offset'] == '2'
    errors = build_configuration_review(plan).validation.errors
    assert any(item.code == 'probe-pin-conflict' for item in errors)
    if nested:
        assert remote['user-probe.cfg'] == user_probe


def test_independent_probe_with_physical_z_is_not_retired():
    generated, remote = sources()
    old = remote['printer.cfg'].replace(b'probe:z_virtual_endstop', b'PB3')
    remote['printer.cfg'] = old
    plan = build_managed_config_plan(generated, None, remote)
    assert 'probe' in _sections(effective_hardware_text(plan))
    assert any(item.code == 'probe-pin-conflict' for item in build_configuration_review(plan).validation.errors)


def test_probe_to_probe_update_keeps_selected_probe():
    _, remote = sources()
    generated = _hardware(probe=True).replace(b'^PB2', b'^PB3')
    plan = build_managed_config_plan(generated, None, remote)
    assert _sections(effective_hardware_text(plan))['probe']['pin'] == '^PB3'


def test_save_config_bytes_are_preserved_and_orphan_probe_still_rejected():
    generated, remote = sources()
    saved = (b'#*# <---------------------- SAVE_CONFIG ---------------------->\r\n'
             b'#*# [probe]\r\n#*# z_offset = 1.725  \r\n')
    remote['printer.cfg'] += saved
    plan = build_managed_config_plan(generated, None, remote)
    assert plan.artifacts[0].content.endswith(saved)
    review = build_configuration_review(plan)
    assert not review.validation.valid
    assert any(e.code == 'saved-probe-calibration' for e in review.validation.errors)
    text = render_configuration_review(review, language='Español')
    assert 'SAVE_CONFIG [probe] z_offset=1.725' in text


@pytest.mark.parametrize('accept', [False, True])
def test_transaction_reviews_removal_before_publication_and_preserves_cancel(tmp_path, accept):
    generated, remote = sources()
    transport = FakeTransport(remote)
    def review(proposal):
        assert not any(c[0] == 'upload' for c in transport.calls)
        assert proposal.validation.valid
        assert any('[probe] pin' in w.message for w in proposal.validation.warnings)
        return accept
    result = ConfigDeploymentTransaction(
        transport, generated, None, activation='none', review=review,
        snapshot_root=str(tmp_path), output=lambda _: None,
    ).run()
    if accept:
        assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
        assert result.snapshot is not None
        assert result.snapshot.config_files['printer.cfg'] == remote['printer.cfg']
        assert 'probe' not in _sections(effective_hardware_text(build_managed_config_plan(generated, None, transport.files)))
    else:
        assert result.state == ConfigTransactionState.CANCELLED
        assert transport.files == remote
        assert not any(c[0] in ('upload', 'restart') for c in transport.calls)


@pytest.mark.parametrize('language', ['Español', 'Português'])
def test_normal_localized_review_retains_real_probe_error_and_unknown_causes(language):
    mode = get_mode()
    try:
        set_mode('Beginner')
        errors = (ReviewMessage('probe-pin-conflict', 'Probe pin validation failed: Probe pin conflicts with [stepper_z] endstop_pin: !P1.27'),
                  ReviewMessage('unmapped-gate', 'Exact failure: [custom] required_option is absent'))
        review = ConfigurationReview(SemanticValidation(errors, ()), (), (), (), '')
        text = render_configuration_review(review, language=language, color=True)
        for detail in ('[stepper_z] endstop_pin: !P1.27', '[unmapped-gate]', '[custom] required_option'):
            assert detail in text
        assert 'modo avanzado' not in text and 'modo avançado' not in text
        assert '\033[1m' not in text
    finally:
        set_mode(mode)
