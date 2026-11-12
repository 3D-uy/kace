"""The editor stays compact without changing values or probe-menu semantics."""
import copy
import os
import re

import pytest
from wcwidth import wcswidth

from core import menu
from core.firmware_workflow import persistable_wizard_data, restore_wizard_data
from core.motor_direction import set_motor_direction
from core.scraper import parse_config
from core.translations import get_lang, get_mode, set_lang, set_mode, t
from core.wizard.steps import motion, sensors
from tests.unit.test_motor_directions import data
from tests.unit.test_probe_review_navigation import guided_user


@pytest.fixture(autouse=True)
def interactive(monkeypatch):
    language, mode = get_lang(), get_mode()
    monkeypatch.setenv('KACE_AUTO', '0')
    monkeypatch.setenv('KACE_QUIET', '1')
    monkeypatch.setattr(menu, '_MOCK_PROMPTS_ACTIVE', False)
    monkeypatch.setattr(motion, '_INTERACTIVE_MODE', False)
    yield
    set_lang(language)
    set_mode(mode)


def assert_single_line_options(output, columns, count):
    plain = menu._plain_label(output)
    lines = plain.splitlines()
    rows = [i for i, line in enumerate(lines) if re.match(r'^\s+\d+\)', line)]
    assert len(rows) == count
    for line in lines[rows[0]:rows[-1] + 1]:
        assert not line.strip() or re.match(r'^\s+(?:\d+\)|─+\s*$)', line), line
        assert wcswidth(line) < columns, line
    assert 'motor_keep_all' not in plain
    assert 'profile.editor.' not in plain
    return plain


@pytest.mark.parametrize('language', ['English', 'Español', 'Português'])
@pytest.mark.parametrize('mode', ['Beginner', 'Advanced'])
@pytest.mark.parametrize('columns', [40, 60, 80, 114, 160])
@pytest.mark.parametrize('kinematics', ['cartesian', 'corexy'])
def test_real_editor_one_line_per_option_at_each_width(monkeypatch, capsys, language, mode, columns, kinematics):
    set_lang(language)
    set_mode(mode)
    monkeypatch.setattr('shutil.get_terminal_size', lambda **kw: os.terminal_size((columns, 29)))
    user = data(4, kinematics)
    set_motor_direction(user, user['board_parsed'], 'stepper_x', 'invert')
    original = copy.deepcopy(user)
    defaults, parsed = copy.deepcopy(user), {}
    choices_seen = []
    def select(prompt, choices, **kwargs):
        choices_seen.extend(choices)
        return menu.numbered_select(prompt, choices, **kwargs)
    monkeypatch.setattr(motion, 'numbered_select', select)
    monkeypatch.setattr('builtins.input', lambda prompt: 'back')
    assert motion._step_profile_editor_inner(defaults, parsed, user) == 'back'
    output = assert_single_line_options(capsys.readouterr().out, columns, 26)
    values = [getattr(choice, 'value', None) for choice in choices_seen]
    assert values[:3] == ['kinematics', 'volume', 'printable_bounds']
    assert 'motor_keep_all' not in values
    assert values[-2:] == ['save', 'back']
    for motor in ('stepper_x', 'stepper_y', 'stepper_z', 'stepper_z1', 'stepper_z2', 'stepper_z3', 'extruder'):
        assert 'motor_direction_' + motor in values
    if columns >= 60:
        assert '!PA2' in output and '!PC2' in output
        assert ' x '.join(user[f'{axis}_size'] for axis in ('x', 'y', 'z')) + ' mm' in output
    assert user == original and defaults == original and parsed == {}


@pytest.mark.parametrize('widths', [(60, 160), (160, 60)])
def test_editor_recalculates_rows_after_terminal_resize(monkeypatch, capsys, widths):
    user = data(2)
    original = copy.deepcopy(user)
    current = [widths[0]]
    monkeypatch.setattr('shutil.get_terminal_size', lambda **kw: os.terminal_size((current[0], 29)))
    captured = []
    answers = iter(['x_position_max', '300', 'back'])
    def answer(prompt):
        output = capsys.readouterr().out
        if 'Enter X position_max' in menu._plain_label(prompt):
            current[0] = widths[1]
        else:
            captured.append(output)
        return next(answers)
    monkeypatch.setattr('builtins.input', answer)
    assert motion._step_profile_editor_inner(copy.deepcopy(user), {}, user) == 'back'
    assert len(captured) == 2
    for width, output in zip(widths, captured):
        assert_single_line_options(output, width, 24)
    assert user == original


def test_long_unicode_value_is_abbreviated_only_in_row_and_shown_when_editing(monkeypatch, capsys):
    user = data()
    full_value = '熱センサー' * 18
    user['hotend_thermistor'] = full_value
    original = copy.deepcopy(user)
    monkeypatch.setattr('shutil.get_terminal_size', lambda **kw: os.terminal_size((60, 29)))
    menus, details = [], []
    answers = iter(['hotend_thermistor', '<', 'back'])
    def answer(prompt):
        output = capsys.readouterr().out
        if 'Select Hotend Thermistor' in output:
            details.append(output)
        else:
            menus.append(output)
        return next(answers)
    monkeypatch.setattr('builtins.input', answer)
    assert motion._step_profile_editor_inner(copy.deepcopy(user), {}, user) == 'back'
    assert full_value in menu._plain_label(details[0])
    for output in menus:
        assert '…' in assert_single_line_options(output, 60, 23)
    assert user == original


@pytest.mark.parametrize('language', ['English', 'Español', 'Português'])
@pytest.mark.parametrize('pullup', [False, True])
def test_compact_probe_help_keeps_exact_menu_and_unknown_provisional(monkeypatch, capsys, language, pullup):
    set_lang(language)
    user = guided_user()
    user.update(custom_probe_pullup=pullup, custom_probe_inverted=True)
    before = copy.deepcopy(user)
    menus = []
    def select(prompt, choices, **kwargs):
        menus.append((choices, kwargs))
        return menu.numbered_select(prompt, choices, **kwargs)
    monkeypatch.setattr(sensors, 'numbered_select', select)
    monkeypatch.setattr('builtins.input', lambda prompt: '3')
    assert sensors._step_custom_probe_signal_option(user, 'inverted') == 'done'
    choices, options = menus[0]
    assert [choice['value'] for choice in choices] == ['normal', 'inverted', 'unknown', '__back__', '__quit__']
    assert [choice['name'] for choice in choices[:3]] == [
        t('wizard.probe_signal.normal'), t('wizard.probe_signal.inverted'), t('wizard.probe_signal.unknown')]
    if language == 'Español':
        assert [choice['name'] for choice in choices] == [
            'Normal (sin !)', 'Invertida (con !)', 'Todavía no lo sé — verificar antes de mover', 'Volver', 'Salir']
    assert options['require_explicit']
    guide = t('wizard.probe_signal.guide')
    assert len(guide) <= 200 and '\n' not in guide
    assert all(token in guide for token in ('!', 'QUERY_PROBE', 'open', 'TRIGGERED'))
    assert user == dict(before, custom_probe_inverted=False, custom_probe_polarity_unverified=True)
    assert sensors._step_custom_probe(user) == 'done'
    assert parse_config(user['custom_probe'].config_text)['probe']['pin'] == ('^' if pullup else '') + 'PB8'
    restored = restore_wizard_data(persistable_wizard_data(user))
    assert restored['custom_probe_polarity_unverified'] is True
    assert restored['custom_probe'].config_text == user['custom_probe'].config_text
    assert 'QUERY_PROBE' in restored['custom_probe'].config_text
    assert 'QUERY_PROBE' in capsys.readouterr().out
