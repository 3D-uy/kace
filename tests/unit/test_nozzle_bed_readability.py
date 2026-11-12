"""Regression for the detached markers/blank diagrams reported in the E2E."""
import copy
import os

import pytest
from wcwidth import wcswidth

from core.menu import _plain_label
from core.nozzle_bed_visualizer import print_nozzle_bed_preview
from core.translations import get_lang, set_lang, t


@pytest.fixture(autouse=True)
def restore_language():
    language = get_lang()
    yield
    set_lang(language)


def screenshot_geometry(**changes):
    values = dict(
        x_size=300, y_size=300,
        printable_x_min=0, printable_x_max=300,
        printable_y_min=0, printable_y_max=300,
        x_position_min=0, x_position_max=320,
        y_position_min=-5, y_position_max=300,
        x_position_endstop=320, y_position_endstop=-5,
    )
    values.update(changes)
    return values


@pytest.mark.parametrize('language', ['English', 'Español', 'Português'])
@pytest.mark.parametrize('columns', [28, 40, 60, 80, 120])
def test_preview_labels_bed_and_edges_without_detached_markers(language, columns, capsys, monkeypatch):
    set_lang(language)
    monkeypatch.setattr('shutil.get_terminal_size', lambda **kw: os.terminal_size((columns, 24)))
    data = screenshot_geometry()
    original = copy.deepcopy(data)
    print_nozzle_bed_preview(data)
    text = _plain_label(capsys.readouterr().out)
    normalized = ' '.join(text.split())
    assert '300 x 300 mm' in normalized
    # Both Y edges are directly named beside the one bed diagram.
    assert '+Y: 300 mm' in text
    assert '-Y: 0 mm' in text
    assert not any(line.strip() in {'', 'N', '^', 'v', '<', '>'} for line in text.splitlines())
    assert all(wcswidth(line) <= columns for line in text.splitlines())
    assert data == original


def test_shifted_bed_displays_absolute_edges_and_printable_size(capsys, monkeypatch):
    set_lang('Español')
    monkeypatch.setattr('shutil.get_terminal_size', lambda **kw: os.terminal_size((80, 24)))
    print_nozzle_bed_preview(screenshot_geometry(
        printable_x_min=20, printable_x_max=300,
        printable_y_min=-20, printable_y_max=280,
        y_position_min=-25,
    ))
    text = _plain_label(capsys.readouterr().out)
    assert '280 x 300 mm' in text  # Not x_size/y_size and not probe coordinates.
    assert '+Y: 280 mm' in text
    assert '-Y: -20 mm' in text
    assert '20 mm +' in text
    assert '+ 300 mm' in text


def test_e2e_example_is_compact_but_keeps_absolute_home_and_overhang(capsys, monkeypatch):
    set_lang('Español')
    monkeypatch.setattr('shutil.get_terminal_size', lambda **kw: os.terminal_size((120, 24)))
    print_nozzle_bed_preview(screenshot_geometry())
    text = _plain_label(capsys.readouterr().out)
    assert len(text.splitlines()) <= 25
    assert 'X = 320 mm; Y = -5 mm' in text
    assert '20 mm fuera de la cama' in text
    assert '5 mm fuera de la cama' in text
    assert '0 mm' in text


def test_long_edge_coordinates_use_readable_bounds_in_a_narrow_terminal(capsys, monkeypatch):
    set_lang('Español')
    monkeypatch.setattr('shutil.get_terminal_size', lambda **kw: os.terminal_size((28, 24)))
    print_nozzle_bed_preview(screenshot_geometry(
        printable_x_min=123456, printable_x_max=123756,
        x_position_min=123450, x_position_max=123780,
        x_position_endstop=123450,
    ))
    text = _plain_label(capsys.readouterr().out)
    normalized = ' '.join(text.split())
    assert t('nozzle_bed.bed_bounds', axis='X', low='123456', high='123756') in normalized
    assert t('nozzle_bed.bed_bounds', axis='Y', low='0', high='300') in normalized
    assert '+' + '-' * 5 not in text  # No clipped/misaligned fallback drawing.
    assert all(wcswidth(line) <= 28 for line in text.splitlines())


def test_probe_offsets_do_not_reposition_the_nozzle_or_bed(capsys):
    print_nozzle_bed_preview(screenshot_geometry())
    original = capsys.readouterr().out
    print_nozzle_bed_preview(screenshot_geometry(probe_x_offset=-38, probe_y_offset=30))
    assert capsys.readouterr().out == original
