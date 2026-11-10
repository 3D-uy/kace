"""Probe values, units and explanations keep columns independent of ANSI bytes."""
import copy
import os

import pytest
from wcwidth import wcswidth

from core.firmware_workflow import persistable_wizard_data, restore_wizard_data
from core.menu import _plain_label
from core.terminal import RESET, SECTION, WARNING
from core.translations import get_lang, set_lang, t
from core.wizard.steps import sensors
from tests.unit.test_probe_review_navigation import guided_user


@pytest.mark.parametrize('language', ['English', 'Español', 'Português'])
@pytest.mark.parametrize('columns', [80, 120, 180])
@pytest.mark.parametrize('restored', [False, True])
def test_probe_columns_and_colours_preserve_all_values(monkeypatch, capsys, language, columns, restored):
    previous = get_lang()
    try:
        set_lang(language)
        monkeypatch.setenv('KACE_AUTO', '0')
        monkeypatch.setattr('shutil.get_terminal_size', lambda **kw: os.terminal_size((columns, 29)))
        monkeypatch.setattr(sensors, 'numbered_select', lambda *a, **kw: 'continue')
        user = guided_user()
        user.update(custom_probe_pin='P1.27', custom_probe_x_offset='-9', custom_probe_y_offset='30')
        assert sensors._step_custom_probe(user) == 'done'
        if restored:
            user = restore_wizard_data(persistable_wizard_data(user))
        before = copy.deepcopy(user)
        assert sensors._step_custom_probe_review(user) == 'done'
        raw = capsys.readouterr().out.splitlines()
        fields = {'pin': '^P1.27', 'x_offset': '-9', 'y_offset': '30', 'z_offset': '0',
                  'samples': '2', 'samples_result': 'median', 'samples_tolerance': '0.5',
                  'samples_tolerance_retries': '3', 'speed': '7', 'sample_retract_dist': '5'}
        rows = []
        for name, value in fields.items():
            row = next(row for row in raw if _plain_label(row).strip().startswith(name + ':'))
            left, right = row.split(WARNING, 1)
            assert SECTION in left and RESET in left
            assert right.startswith(value) and right.endswith(RESET)
            rows.append(row)
        assert len({wcswidth(_plain_label(row.split(WARNING)[0])) for row in rows}) == 1
        assert len({_plain_label(row).index('—') for row in rows}) == 1
        assert all(wcswidth(_plain_label(row)) <= columns for row in raw)
        normalized = ' '.join(_plain_label('\n'.join(raw)).split())
        for name in fields:
            assert t('wizard.probe_parameter.' + name) in normalized
        assert t('wizard.review_probe.provisional') in normalized
        for group in ('connection', 'offsets', 'measurements'):
            row = next(row for row in raw if _plain_label(row).strip() == t('wizard.probe_review.group_' + group))
            assert SECTION in row and WARNING not in row
        assert user == before
    finally:
        set_lang(previous)
