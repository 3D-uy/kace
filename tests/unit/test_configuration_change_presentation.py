"""Readable change summaries must retain review evidence and explicit consent."""
import copy
import os
from dataclasses import replace

import pytest
from wcwidth import wcswidth

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import (
    ConfigurationReview, ReviewMessage, SemanticValidation,
    build_configuration_review, render_configuration_change_details,
    render_configuration_review,
)
from core.deployer import _interactive_configuration_review
from core.managed_config import build_managed_config_plan, preserved_homing_conflicts
from core.menu import _plain_label
from core.translations import get_lang, get_mode, set_lang, set_mode
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_probe_retirement import sources


@pytest.fixture(autouse=True)
def locale():
    previous = get_lang(), get_mode()
    yield
    set_lang(previous[0])
    set_mode(previous[1])


def incident():
    generated, remote = sources()
    remote['printer.cfg'] = remote['printer.cfg'].replace(
        b'position_min: 0\nposition_max: 235\nposition_endstop: 0',
        b'position_min: -30\nposition_max: 300\nposition_endstop: -30').replace(
        b'position_min: 0\nposition_max: 235\nposition_endstop: 235\nhoming_positive_dir: True',
        b'position_min: -8\nposition_max: 300\nposition_endstop: -8\nhoming_positive_dir: False')
    generated = generated.replace(
        b'position_max: 235\nposition_endstop: 0\nhoming_positive_dir: False',
        b'position_max: 320\nposition_endstop: 320\nhoming_positive_dir: True').replace(
        b'position_min: 0\nposition_max: 235\nposition_endstop: 235\nhoming_positive_dir: True',
        b'position_min: -5\nposition_max: 300\nposition_endstop: -5\nhoming_positive_dir: False')
    approved = frozenset((c.section, c.option) for c in preserved_homing_conflicts(generated, remote))
    plan = build_managed_config_plan(generated, None, remote, replace_preserved=approved)
    return generated, remote, plan, approved


@pytest.mark.parametrize('language', ['English', 'Español', 'Português'])
@pytest.mark.parametrize('columns', [40, 80, 114])
def test_planned_changes_are_compact_but_all_details_remain_available(monkeypatch, language, columns):
    set_lang(language)
    set_mode('Beginner')
    monkeypatch.setattr('shutil.get_terminal_size', lambda *a, **kw: os.terminal_size((columns, 30)))
    _, remote, plan, _ = incident()
    before = copy.deepcopy(remote)
    review = build_configuration_review(plan)
    assert review.validation.valid
    summary = render_configuration_review(review, language=language, color=True)
    plain = _plain_label(summary)
    details = render_configuration_change_details(review, language=language, color=False)
    # Core numeric decisions stay on the main screen, with highlighted values.
    assert '-30…300 → 0…320 mm' in ' '.join(plain.split())
    assert '\033[93m-30…300' in summary
    direction = {'English': 'toward minimum → toward maximum',
                 'Español': 'hacia el mínimo → hacia el máximo',
                 'Português': 'em direção ao mínimo → em direção ao máximo'}[language]
    assert direction in ' '.join(plain.split())
    assert 'probe:z_virtual_endstop → PB2' in ' '.join(plain.split())
    for section in ('probe', 'safe_z_home', 'bed_mesh'):
        assert plain.count('[' + section + ']') == 1
    assert 'samples' not in plain and 'mesh_min' not in plain
    assert '0 warning(s)' in plain or '0 advertencia(s)' in plain or '0 aviso(s)' in plain
    assert '\033[' not in details
    assert all(wcswidth(line) <= columns - 2 for line in details.splitlines())
    unwrapped = ' '.join(details.split())
    for item in review.validation.warnings:
        if item.code == 'managed-plan':
            # Every changed/removed setting retains its exact source, identity and old value.
            identity = item.message.split(' will be ')[0]
            assert identity in unwrapped
    assert remote == before
    assert review.diff == plan.dry_run_diff()


def test_real_and_unknown_warnings_and_blockers_are_not_hidden_or_reclassified():
    review = ConfigurationReview(SemanticValidation(
        (ReviewMessage('unmapped-gate', 'Missing [custom] required_option'),),
        (ReviewMessage('managed-plan', 'Unexpected planner warning format'),
         ReviewMessage('managed-plan', "printer.cfg: [stepper_x] position_min = '-30' will be replaced with '0'."),
         ReviewMessage('actual-warning', 'Keep this warning visible'))), (), ('printer.cfg',), (), '')
    for language in ('English', 'Español', 'Português'):
        text = render_configuration_review(review, language=language, color=True)
        for cause in ('Unexpected planner warning format', 'Keep this warning visible', 'Missing [custom] required_option'):
            assert cause in text
        assert '\033[91m' in text
        assert '2 warning(s)' in text or '2 advertencia(s)' in text or '2 aviso(s)' in text
    assert not review.validation.valid
    assert len(review.validation.warnings) == 3


def test_sources_are_not_merged_and_partial_removal_does_not_hide_other_changes():
    messages = (
        "printer.cfg: [probe] pin = '^PB2' will be replaced with '^PB3'.",
        "printer.cfg: [probe] speed = '10' will be removed.",
        "kace/generated-hardware.cfg: [probe] pin = '^PB4' will be replaced with '^PB3'.",
        "printer.cfg: [unused] will be removed.",
    )
    review = ConfigurationReview(SemanticValidation((), tuple(ReviewMessage('managed-plan', m) for m in messages)), (), (), (), '')
    text = render_configuration_review(review, color=False)
    for text_part in ('^PB2 → ^PB3', '^PB4 → ^PB3', '[probe] speed', '[unused]', 'kace/generated-hardware.cfg'):
        assert text_part in text


@pytest.mark.parametrize('mode', ['Beginner', 'Advanced'])
@pytest.mark.parametrize('show_details', [False, True])
def test_details_are_optional_in_both_modes_and_do_not_replace_final_consent(mode, show_details, capsys):
    set_mode(mode)
    set_lang('Español')
    _, _, plan, _ = incident()
    review = build_configuration_review(plan)
    prompts = []
    def answer(prompt, default=False):
        assert default is False
        prompts.append(prompt)
        return show_details if 'detalles técnicos' in prompt else False
    assert not _interactive_configuration_review(review, answer)
    output = ' '.join(capsys.readouterr().out.split())
    assert '¿Ver los detalles técnicos de estos cambios?' in prompts
    assert prompts[-1] == '¿Aplicar esta configuración a Klipper?'
    assert ('[probe] pin' in output) is show_details
    if mode == 'Advanced':
        assert any('diff técnico completo' in p for p in prompts)


def test_opening_details_then_cancelling_keeps_live_files_and_snapshot_untouched(tmp_path, capsys):
    set_lang('English')
    set_mode('Beginner')
    generated, remote, _, approved = incident()
    transport = FakeTransport(remote)
    before = copy.deepcopy(remote)
    result = ConfigDeploymentTransaction(
        transport, generated, None, activation='none', snapshot_root=str(tmp_path),
        resolve_preserved_homing=lambda _: approved,
        review=lambda r: _interactive_configuration_review(r, lambda prompt, **kw: 'technical details' in prompt),
    ).run()
    assert result.state is ConfigTransactionState.CANCELLED
    assert transport.files == before
    assert result.snapshot is None
    assert not any(call[0] in {'upload', 'restart'} for call in transport.calls)
    assert '[probe] pin' in ' '.join(capsys.readouterr().out.split())


def test_invalid_review_remains_blocked_after_opening_details(capsys):
    _, _, plan, _ = incident()
    review = build_configuration_review(plan)
    review = replace(review, validation=replace(review.validation, errors=(ReviewMessage('custom-error', 'Blocked cause'),)))
    prompts = []
    def answer(prompt, **kw):
        prompts.append(prompt)
        return True
    set_mode('Beginner')
    assert not _interactive_configuration_review(review, answer)
    assert len(prompts) == 1
    assert 'Blocked cause' in capsys.readouterr().out
