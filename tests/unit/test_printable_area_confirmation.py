"""Printable coordinates require a decision distinct from travel/profile acceptance."""
import copy

import pytest

from core.motion_model import printable_xy_confirmation_matches
from core.wizard.steps import printable_area as step
from core.translations import get_lang, set_lang, t
from core.exceptions import GenerationError
from core.menu import _plain_label


def proposal():
    return dict(x_size='250', y_size='230', x_position_min='-10', x_position_max='250',
                y_position_min='-5', y_position_max='230', x_position_endstop='-10',
                y_position_endstop='-5', profile_loaded=True)


def test_accepting_area_preserves_travel_and_marks_explicit_bounds(monkeypatch):
    data = proposal()
    before = copy.deepcopy(data)
    calls = []
    def confirm(prompt, **kwargs):
        calls.append(kwargs)
        return 'confirm'
    monkeypatch.setattr(step, 'numbered_select', confirm)
    assert step._step_printable_area(data) == 'confirmed'
    assert printable_xy_confirmation_matches(data)
    assert all(data[key] == value for key, value in before.items())
    assert data['printable_x_max'] == '250'
    assert data['_value_provenance']['printable_x_max'] == 'USER_OVERRIDE'
    assert calls[0]['require_explicit'] is True
    assert not any(key.startswith('physical_bed') for key in data)


def test_profile_proposal_is_not_itself_confirmed():
    assert not printable_xy_confirmation_matches(proposal())


def test_fixed_artifact_review_cannot_offer_editing(monkeypatch, capsys):
    data = proposal()
    def confirm(prompt, **kwargs):
        assert kwargs["require_explicit"] is True
        assert "edit" not in [choice.get("value") for choice in kwargs["choices"]]
        return "confirm"
    monkeypatch.setattr(step, "numbered_select", confirm)
    monkeypatch.setattr(step, "simple_input", lambda *a, **k: pytest.fail("artifact geometry cannot be edited"))
    assert step._step_printable_area(data, allow_edit=False) == "confirmed"
    assert printable_xy_confirmation_matches(data)
    assert "wizard" in capsys.readouterr().out.lower()


def test_confirmation_survives_checkpoint_roundtrip_without_becoming_a_measurement(monkeypatch):
    from core.firmware_workflow import persistable_wizard_data, restore_wizard_data
    data = proposal()
    monkeypatch.setattr(step, "numbered_select", lambda *a, **kw: "confirm")
    step._step_printable_area(data)
    restored = restore_wizard_data(persistable_wizard_data(data))
    assert printable_xy_confirmation_matches(restored)
    assert not any(key.startswith("physical_bed") for key in restored)
    restored["x_position_max"] = "260"
    assert not printable_xy_confirmation_matches(restored)


def test_fixed_invalid_geometry_fails_before_confirmation(monkeypatch):
    data = dict(proposal(), printable_x_min="-20", printable_x_max="250")
    monkeypatch.setattr(step, "numbered_select", lambda *a, **kw: pytest.fail("invalid geometry cannot be confirmed"))
    with pytest.raises(GenerationError):
        step._step_printable_area(data, allow_edit=False)


def test_fixed_confirmation_does_not_round_away_artifact_coordinates(monkeypatch, capsys):
    low, high = 20.123456789, 240.987654321
    data = dict(proposal(), printable_x_min=low, printable_x_max=high)
    monkeypatch.setattr(step, "numbered_select", lambda *a, **kw: "confirm")
    assert step._step_printable_area(data, allow_edit=False) == "confirmed"
    assert float(data["printable_x_min"]) == low
    assert float(data["printable_x_max"]) == high
    output = capsys.readouterr().out
    assert str(low) in output and str(high) in output
    assert data["_printable_xy_confirmation"]["printable_x_min"] == low
    assert data["_printable_xy_confirmation"]["printable_x_max"] == high


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
def test_fixed_artifact_instructions_are_localized(language, monkeypatch, capsys):
    previous = get_lang()
    try:
        set_lang(language)
        monkeypatch.setattr(step, "numbered_select", lambda *a, **kw: "confirm")
        step._step_printable_area(proposal(), allow_edit=False)
        text = " ".join(_plain_label(capsys.readouterr().out).split())
        assert " ".join(t("geometry.fixed_artifact").split()) in text
        assert " ".join(t("geometry.explanation").split()) not in text
    finally:
        set_lang(previous)


@pytest.mark.parametrize('key', ['x_position_max', 'printable_x_max', 'printable_y_min'])
def test_confirmation_invalidated_by_geometry_change(key, monkeypatch):
    data = proposal()
    monkeypatch.setattr(step, 'numbered_select', lambda *a, **kw: 'confirm')
    step._step_printable_area(data)
    data[key] = str(float(data[key]) - 1)
    assert not printable_xy_confirmation_matches(data)


def test_shifted_printable_area_does_not_shift_machine_or_infer_bed(monkeypatch):
    data = proposal()
    selections = iter(['edit', 'confirm'])
    answers = iter(['20', '240', '-5', '215'])
    monkeypatch.setattr(step, 'numbered_select', lambda *a, **kw: next(selections))
    monkeypatch.setattr(step, 'simple_input', lambda *a, **kw: next(answers))
    assert step._step_printable_area(data) == 'confirmed'
    assert (data['printable_x_min'], data['printable_x_max']) == ('20', '240')
    assert data['x_position_min'] == '-10'
    assert data['x_position_max'] == '250'
    assert data['x_size'] == '250'  # legacy nominal size is not a physical measurement


def test_cancelled_edit_leaves_original_data_untouched(monkeypatch):
    data = proposal(); before = copy.deepcopy(data)
    selections = iter(['edit', '__back__'])
    answers = iter(['20', '__back__'])
    monkeypatch.setattr(step, 'numbered_select', lambda *a, **kw: next(selections))
    monkeypatch.setattr(step, 'simple_input', lambda *a, **kw: next(answers))
    assert step._step_printable_area(data) == '__back__'
    assert data == before


def test_invalid_bounds_cannot_be_confirmed(monkeypatch):
    data = dict(proposal(), printable_x_min='-40', printable_x_max='280')
    def back(prompt, **kwargs):
        assert not any(c.get('value') == 'confirm' for c in kwargs['choices'])
        return '__back__'
    monkeypatch.setattr(step, 'numbered_select', back)
    assert step._step_printable_area(data) == '__back__'


def test_automatic_mode_cannot_confirm_inferred_profile_geometry(monkeypatch):
    monkeypatch.setenv('KACE_AUTO', '1')
    with pytest.raises(GenerationError, match='printable'):
        step._step_printable_area(proposal())


@pytest.mark.parametrize('language', ['English', 'Español', 'Português'])
def test_preview_discloses_proposal_and_unknown_physical_geometry(language, monkeypatch, capsys):
    from core.nozzle_bed_visualizer import print_nozzle_bed_preview
    previous = get_lang()
    try:
        set_lang(language)
        data = dict(proposal(), printable_x_min=0, printable_x_max=250,
                    printable_y_min=0, printable_y_max=230)
        print_nozzle_bed_preview(data)
        text = ' '.join(_plain_label(capsys.readouterr().out).split())
        assert ' '.join(t('geometry.physical_unknown').split()) in text
        assert ' '.join(t('geometry.proposal').split()) in text
        monkeypatch.setattr(step, 'numbered_select', lambda *a, **kw: 'confirm')
        step._step_printable_area(data)
        capsys.readouterr()
        print_nozzle_bed_preview(data)
        text = ' '.join(_plain_label(capsys.readouterr().out).split())
        assert ' '.join(t('geometry.confirmed').split()) in text
        assert ' '.join(t('geometry.physical_unknown').split()) in text
    finally:
        set_lang(previous)
