import copy
import os

import pytest
from wcwidth import wcswidth

from core.menu import _plain_label
from core.nozzle_bed_visualizer import print_nozzle_bed_preview
from core.translations import get_lang, set_lang, t


def geometry(**overrides):
    data = dict(x_size=220, y_size=220,
                printable_x_min=0, printable_x_max=220, printable_y_min=0, printable_y_max=220,
                x_position_min=-10, x_position_max=230, y_position_min=-5, y_position_max=235,
                x_position_endstop=-10, y_position_endstop=-5)
    data.update(overrides)
    return data


@pytest.fixture(autouse=True)
def restore_language():
    previous = get_lang()
    yield
    set_lang(previous)


@pytest.mark.parametrize('language', ['English', 'Español', 'Português'])
@pytest.mark.parametrize('columns', [40, 60, 80])
def test_homing_and_travel_are_distinct_localized_readonly_views(language, columns, capsys, monkeypatch):
    set_lang(language)
    monkeypatch.setattr('shutil.get_terminal_size', lambda **kw: os.terminal_size((columns, 24)))
    data = geometry()
    before = copy.deepcopy(data)
    print_nozzle_bed_preview(data)
    text = _plain_label(capsys.readouterr().out)
    normalized = ' '.join(text.split())
    for key in ('homing','travel','homing_note','schematic'):
        assert ' '.join(t('nozzle_bed.'+key).split()) in normalized
    assert t('nozzle_bed.outside',axis='X',distance='10',side=t('nozzle_bed.left')) in normalized
    assert t('nozzle_bed.outside',axis='Y',distance='5',side=t('nozzle_bed.front')) in normalized
    assert t('nozzle_bed.travel_axis',axis='X',low='10',high='10',low_side=t('nozzle_bed.left'),high_side=t('nozzle_bed.right')) in normalized
    assert t('nozzle_bed.travel_axis',axis='Y',low='5',high='15',low_side=t('nozzle_bed.front'),high_side=t('nozzle_bed.back')) in normalized
    assert all(wcswidth(line) <= columns for line in text.splitlines())
    assert data == before


@pytest.mark.parametrize('x,y,x_side,y_side', [
    (-.01,-.01,'left','front'),(-.1,1.1,'left','back'),
    (1.1,-.1,'right','front'),(1.1,1.1,'right','back'),
    (0,0,None,None),(1,1,None,None),(.5,.5,None,None),
])
def test_nozzle_side_is_stated_in_mm_even_for_small_overhang(x,y,x_side,y_side,capsys):
    # No point is projected onto a schematic: retain the exact distance and side.
    print_nozzle_bed_preview(geometry(
        x_position_min=-25, y_position_min=-25,
        x_position_max=250, y_position_max=250,
        x_position_endstop=x*220, y_position_endstop=y*220,
    ))
    text = ' '.join(_plain_label(capsys.readouterr().out).split())
    for axis, value, side in [('X', x*220, x_side), ('Y', y*220, y_side)]:
        if side:
            distance = abs(value) if value < 0 else value-220
            assert t('nozzle_bed.outside', axis=axis, distance=f'{distance:g}',
                     side=t('nozzle_bed.'+side)) in text
        else:
            assert t('nozzle_bed.inside', axis=axis) in text


def test_shifted_bed_uses_its_edges_not_zero_or_probe_offsets(capsys):
    data = geometry(printable_x_min=20,printable_x_max=240,x_position_max=250,
                    x_position_endstop=250, printable_y_min=-20,printable_y_max=200,
                    y_position_min=-25,y_position_max=210,y_position_endstop=210,
                    probe_x_offset=-38,probe_y_offset=12)
    print_nozzle_bed_preview(data)
    text = ' '.join(_plain_label(capsys.readouterr().out).split())
    assert t('nozzle_bed.outside',axis='X',distance='10',side=t('nozzle_bed.right')) in text
    assert t('nozzle_bed.outside',axis='Y',distance='10',side=t('nozzle_bed.back')) in text
    assert t('nozzle_bed.travel_axis',axis='X',low='30',high='10',low_side=t('nozzle_bed.left'),high_side=t('nozzle_bed.right')) in text


@pytest.mark.parametrize('point', [0,110,220])
def test_inside_and_edge_are_zero_not_negative_distance(point,capsys):
    print_nozzle_bed_preview(geometry(x_position_endstop=point,y_position_endstop=point))
    text = ' '.join(_plain_label(capsys.readouterr().out).split())
    assert t('nozzle_bed.inside',axis='X') in text
    assert t('nozzle_bed.inside',axis='Y') in text


@pytest.mark.parametrize('key,value', [('printable_x_min',None),('y_position_max',''),('printable_x_max','nan'),('x_position_max',-10)])
def test_incomplete_or_invalid_geometry_never_produces_a_distance(key,value,capsys):
    print_nozzle_bed_preview(geometry(**{key:value}))
    text = _plain_label(capsys.readouterr().out)
    assert t('nozzle_bed.travel') not in text
    assert t('nozzle_bed.position',x='-10',y='-5') not in text


def test_missing_endstop_does_not_hide_known_travel_or_invent_home(capsys):
    data = geometry()
    del data['x_position_endstop']
    print_nozzle_bed_preview(data)
    text = ' '.join(_plain_label(capsys.readouterr().out).split())
    assert t('nozzle_bed.unknown_home',axis='X') in text
    assert t('nozzle_bed.travel') in text
    assert t('nozzle_bed.position',x='-10',y='-5') not in text
