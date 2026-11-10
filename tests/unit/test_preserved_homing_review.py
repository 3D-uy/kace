"""Destination preservation must not silently undo reviewed homing decisions."""
import copy
import pytest

from core.managed_config import build_managed_config_plan, effective_hardware_text, preserved_homing_conflicts
from core.configuration_review import (
    _sections, build_configuration_review, render_configuration_review,
    render_configuration_change_details,
)
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.deployer import _interactive_preserved_homing_resolution
from core.translations import get_lang, set_lang, get_mode, set_mode
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_configuration_review import _hardware
from core.menu import _plain_label
from core.terminal import WARNING, RESET
from core.translations import t
from wcwidth import wcswidth
import os


def incident():
    old = _hardware(probe=True).replace(b'position_min: 0\nposition_max: 235\nposition_endstop: 0',
        b'position_min: -30\nposition_max: 300\nposition_endstop: -30').replace(
        b'position_min: 0\nposition_max: 235\nposition_endstop: 235',
        b'position_min: -8\nposition_max: 300\nposition_endstop: -8').replace(
        b'[probe]\npin: ^PB2', b'[probe]\npin: ^PB2\nz_offset: 0')
    old = old.replace(b'homing_positive_dir: True', b'homing_positive_dir: False')
    new = old.replace(b'position_min: -30\nposition_max: 300\nposition_endstop: -30',
        b'position_min: 0\nposition_max: 320\nposition_endstop: 320').replace(
        b'position_min: -8\nposition_max: 300\nposition_endstop: -8',
        b'position_min: -5\nposition_max: 300\nposition_endstop: -5').replace(
        b'endstop_pin: probe:z_virtual_endstop\nposition_min: 0',
        b'endstop_pin: probe:z_virtual_endstop\nposition_min: 0.5').replace(b'z_offset: 0', b'z_offset: 3')
    # Explicit directions follow the corresponding endpoint in both fixtures.
    new = new.replace(b'position_endstop: 320\nhoming_positive_dir: False', b'position_endstop: 320\nhoming_positive_dir: True')
    return new, {'printer.cfg': old, 'moonraker.conf': None}


def test_incident_preserves_by_default_and_rejects_the_mixed_geometry():
    generated, remote = incident()
    before = copy.deepcopy(remote)
    plan = build_managed_config_plan(generated, None, remote)
    assert {e.code for e in build_configuration_review(plan).validation.errors} == {
        'homing-x-geometry', 'homing-y-geometry', 'homing-z-geometry'}
    assert remote == before


@pytest.mark.parametrize('root_layout', [False, True])
def test_explicit_review_uses_coherent_questionnaire_values_without_altering_sources(root_layout):
    generated, remote = incident()
    if root_layout:
        remote['printer.cfg'] = b'# KACE layout: root-v1\n' + remote['printer.cfg']
    before = copy.deepcopy(remote)
    conflicts = preserved_homing_conflicts(generated, remote)
    assert {(c.section,c.option,c.existing,c.proposed) for c in conflicts} == {
        ('stepper_x','position_endstop','-30','320'),('stepper_y','position_endstop','-8','-5'),('probe','z_offset','0','3')}
    approved = frozenset((c.section,c.option) for c in conflicts)
    plan = build_managed_config_plan(generated,None,remote,replace_preserved=approved)
    assert build_configuration_review(plan).validation.valid
    effective = _sections(effective_hardware_text(plan))
    assert effective['stepper_x']['position_endstop']=='320'
    assert effective['stepper_y']['position_endstop']=='-5'
    assert effective['probe']['z_offset']=='3'
    assert remote==before
    assert any("position_endstop = '-30'" in w for w in plan.warnings)


@pytest.mark.parametrize('key', [('extruder','pid_kp'),('stepper_x','position_min'),('probe','pin')])
def test_replacement_authority_is_limited_to_observed_homing_conflicts(key):
    generated,remote=incident()
    with pytest.raises(ValueError):build_managed_config_plan(generated,None,remote,replace_preserved=frozenset({key}))


def test_save_config_calibration_is_never_removed_by_active_value_resolution():
    generated,remote=incident()
    remote['printer.cfg']=remote['printer.cfg'].replace(b'z_offset: 0\n',b'')+b'\n#*# <---------------------- SAVE_CONFIG ---------------------->\n#*# [probe]\n#*# z_offset = 0\n'
    conflicts=preserved_homing_conflicts(generated,remote)
    assert next(c for c in conflicts if c.section=='probe').saved_calibration
    with pytest.raises(ValueError,match='SAVE_CONFIG'):
        build_managed_config_plan(generated,None,remote,replace_preserved=frozenset({('probe','z_offset')}))
    assert b'#*# z_offset = 0' in next(a.content for a in build_managed_config_plan(generated,None,remote).artifacts if a.remote_name=='printer.cfg')


@pytest.mark.parametrize('language',['English','Español','Português'])
def test_normal_review_keeps_axis_fields_and_values_in_each_language(language):
    lang,mode=get_lang(),get_mode()
    try:
        set_lang(language);set_mode('Beginner')
        generated,remote=incident()
        output=render_configuration_review(build_configuration_review(build_managed_config_plan(generated,None,remote)), language=language)
        review = build_configuration_review(build_managed_config_plan(generated,None,remote))
        for text in ('[stepper_x]','[stepper_y]','[stepper_z]','position_endstop=-30','position_endstop=-8','probe.z_offset=0', '-30…300 → 0…320 mm'):
            assert text in output
        details = render_configuration_change_details(review, language=language, color=False)
        for text in ("'-30'", "'320'", '[stepper_x] position_min'):
            assert text in details
        if language != 'English':
            assert 'requires finite' not in output
            assert 'probe:z_virtual_endstop requires' not in output
    finally:set_lang(lang);set_mode(mode)


@pytest.mark.parametrize('answer,expected',[('1',frozenset()),('2','replace'),('3',None)])
def test_interactive_resolution_is_explicit_and_cancelable(monkeypatch,answer,expected):
    generated,remote=incident();conflicts=preserved_homing_conflicts(generated,remote)
    monkeypatch.setenv('KACE_AUTO','0');monkeypatch.setattr('builtins.input',lambda *a:answer)
    result=_interactive_preserved_homing_resolution(conflicts)
    assert result==(frozenset((c.section,c.option) for c in conflicts) if expected=='replace' else expected)


@pytest.mark.parametrize('resolution',[None,frozenset()])
def test_cancel_or_preserve_incompatible_values_never_writes(resolution,tmp_path):
    generated,remote=incident();transport=FakeTransport(remote)
    result=ConfigDeploymentTransaction(transport,generated,None,activation='none',
        resolve_preserved_homing=lambda conflicts:resolution,snapshot_root=str(tmp_path)).run()
    assert result.state is (ConfigTransactionState.CANCELLED if resolution is None else ConfigTransactionState.PRECONDITION_FAILED)
    assert not any(c[0] in {'upload','restart'} for c in transport.calls)
    assert transport.files==remote


def test_explicit_resolution_still_requires_final_review_and_concurrency_check(tmp_path):
    generated,remote=incident();transport=FakeTransport(remote)
    def resolve(conflicts):return frozenset((c.section,c.option) for c in conflicts)
    def review(plan):
        assert plan.validation.valid
        transport.files['printer.cfg']+=b'\n# external editor\n'
        return True
    result=ConfigDeploymentTransaction(transport,generated,None,activation='none',review=review,
        resolve_preserved_homing=resolve,snapshot_root=str(tmp_path)).run()
    assert result.state is ConfigTransactionState.PRECONDITION_FAILED
    assert not any(c[0] in {'upload','restart'} for c in transport.calls)


def test_accepted_coherent_proposal_is_snapshotted_and_published_only_after_final_review(tmp_path):
    generated,remote=incident();transport=FakeTransport(remote)
    reviews=[]
    def final_review(review):
        assert review.validation.valid
        assert transport.files==remote
        reviews.append(review)
        return True
    result=ConfigDeploymentTransaction(transport,generated,None,activation='none',review=final_review,
        resolve_preserved_homing=lambda conflicts:frozenset((c.section,c.option) for c in conflicts),
        snapshot_root=str(tmp_path)).run()
    assert result.state is ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    assert len(reviews)==1 and result.snapshot is not None
    assert result.snapshot.config_files['printer.cfg']==remote['printer.cfg']
    installed=_sections(effective_hardware_text(build_managed_config_plan(generated,None,transport.files)))
    assert installed['probe']['z_offset']=='3'
    assert installed['stepper_x']['position_endstop']=='320'
    assert not any(call[0]=='restart' for call in transport.calls)


def test_final_decline_after_value_selection_does_not_publish(tmp_path):
    generated,remote=incident();transport=FakeTransport(remote)
    result=ConfigDeploymentTransaction(transport,generated,None,activation='none',review=lambda _:False,
        resolve_preserved_homing=lambda conflicts:frozenset((c.section,c.option) for c in conflicts),
        snapshot_root=str(tmp_path)).run()
    assert result.state is ConfigTransactionState.CANCELLED
    assert transport.files==remote
    assert not any(call[0] in {'upload','restart'} for call in transport.calls)


def test_duplicate_active_value_does_not_remove_save_config_ownership():
    generated,remote=incident()
    remote['printer.cfg']+=b'\n#*# <---------------------- SAVE_CONFIG ---------------------->\n#*# [probe]\n#*# z_offset = 0\n'
    assert next(c for c in preserved_homing_conflicts(generated,remote) if c.section=='probe').saved_calibration
    with pytest.raises(ValueError,match='SAVE_CONFIG'):
        build_managed_config_plan(generated,None,remote,replace_preserved=frozenset({('probe','z_offset')}))


def test_automatic_mode_never_invents_replacement_consent(monkeypatch):
    generated,remote=incident()
    monkeypatch.setenv('KACE_AUTO','1')
    monkeypatch.setattr('builtins.input',lambda *a:pytest.fail('automatic mode prompted'))
    assert _interactive_preserved_homing_resolution(preserved_homing_conflicts(generated,remote))==frozenset()


@pytest.mark.parametrize('language', ['English', 'Español', 'Português'])
@pytest.mark.parametrize('columns', [40, 80, 114])
def test_conflict_comparison_explains_fields_and_wraps_without_losing_values(
        monkeypatch, capsys, language, columns):
    previous = get_lang()
    try:
        set_lang(language)
        generated, remote = incident()
        before = copy.deepcopy(remote)
        conflicts = preserved_homing_conflicts(generated, remote)
        monkeypatch.setenv('KACE_AUTO', '0')
        monkeypatch.setattr('shutil.get_terminal_size', lambda *a, **kw: os.terminal_size((columns, 30)))
        monkeypatch.setattr('builtins.input', lambda *a: '3')
        assert _interactive_preserved_homing_resolution(conflicts) is None
        raw = capsys.readouterr().out.splitlines()
        lines = [_plain_label(line) for line in raw]
        # The shared menu owns its own margins; the full screen must fit.
        assert all(wcswidth(line) <= columns for line in lines)
        unwrapped = ' '.join(' '.join(lines).split())
        for key in ('help', 'endstop_help', 'probe_help', 'review'):
            assert t('deploy.homing_conflict.' + key) in unwrapped
        rows = [line for line in raw if WARNING in line and line.endswith('mm' + RESET)]
        assert len(rows) == 6
        assert len({wcswidth(_plain_label(line).split(':')[0]) for line in rows}) == 1
        assert [_plain_label(line).split(':')[1].strip() for line in rows] == [
            '-30 mm', '320 mm', '-8 mm', '-5 mm', '0 mm', '3 mm']
        assert remote == before
    finally:
        set_lang(previous)


def test_endstop_only_review_does_not_suggest_a_probe_conflict(monkeypatch, capsys):
    generated, remote = incident()
    conflicts = tuple(c for c in preserved_homing_conflicts(generated, remote) if c.option == 'position_endstop')
    monkeypatch.setenv('KACE_AUTO', '0')
    monkeypatch.setattr('builtins.input', lambda *a: '1')
    assert _interactive_preserved_homing_resolution(conflicts) == frozenset()
    output = ' '.join(_plain_label(capsys.readouterr().out).split())
    assert t('deploy.homing_conflict.probe_help') not in output


def test_saved_calibration_is_explained_before_replacement_is_rejected(monkeypatch, capsys):
    generated, remote = incident()
    remote['printer.cfg'] += b'\n#*# <---------------------- SAVE_CONFIG ---------------------->\n#*# [probe]\n#*# z_offset = 0\n'
    monkeypatch.setenv('KACE_AUTO', '0')
    monkeypatch.setattr('builtins.input', lambda *a: '2')
    assert _interactive_preserved_homing_resolution(preserved_homing_conflicts(generated, remote)) is None
    output = ' '.join(_plain_label(capsys.readouterr().out).split())
    assert output.index(t('deploy.homing_conflict.calibration')) < output.index(t('deploy.homing_conflict.prompt'))
    assert t('deploy.homing_conflict.saved') in output
