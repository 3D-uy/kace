"""Both questionnaire and generated review retain the same declared geometry."""
import copy
import os

import pytest

from core.menu import _plain_label
from core.summary import print_summary
from core.translations import get_lang, set_lang, t
from core.wizard.steps.motion import print_detected_profile_summary


@pytest.mark.parametrize('language', ['English', 'Español', 'Português'])
@pytest.mark.parametrize('columns', [40, 80])
def test_profile_and_generated_summary_show_same_edges_and_home(language, columns, monkeypatch, capsys):
    previous = get_lang()
    data = dict(kinematics='cartesian', probe='None', x_size=300, y_size=300,
                z_size=350, printable_x_min=20, printable_x_max=300,
                printable_y_min=-20, printable_y_max=280,
                x_position_min=0, x_position_max=320,
                y_position_min=-25, y_position_max=300,
                x_position_endstop=320, y_position_endstop=-25)
    original = copy.deepcopy(data)
    monkeypatch.setattr('shutil.get_terminal_size', lambda **kw: os.terminal_size((columns, 24)))
    try:
        set_lang(language)
        print_detected_profile_summary({}, {}, data)
        profile = ' '.join(_plain_label(capsys.readouterr().out).split())
        print_summary(data)
        generated = ' '.join(_plain_label(capsys.readouterr().out).split())
        for view in (profile, generated):
            assert '280 x 300 mm' in view
            assert '+Y: 280 mm' in view and '-Y: -20 mm' in view
            assert t('nozzle_bed.position', x='320', y='-25') in view
            assert t('nozzle_bed.outside', axis='X', distance='20', side=t('nozzle_bed.right')) in view
            assert t('nozzle_bed.outside', axis='Y', distance='5', side=t('nozzle_bed.front')) in view
            assert ' '.join(t('nozzle_bed.homing_note').split()) in view
            assert ' '.join(t('nozzle_bed.travel_note').split()) in view
        assert data == original
    finally:
        set_lang(previous)
