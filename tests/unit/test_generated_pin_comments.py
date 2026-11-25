"""Pin explanations stay local, translated and separate from configuration."""
import copy
import re
from pathlib import Path

import pytest
from jinja2 import Template

from core.generator import generate_config, _postprocess_generated_output
from core.translations import get_lang, set_lang, translate_comment
from tests.unit.test_motor_directions import data
from tests.unit.test_tmc_closure_paths import original_inputs


@pytest.fixture(autouse=True)
def restore_language():
    previous = get_lang()
    yield
    set_lang(previous)


def pin_rows(text):
    section = None
    rows = {}
    for line in text.splitlines():
        if line.startswith('['):
            section = line[1:-1]
        if re.match(r'^(step_pin|dir_pin|enable_pin|endstop_pin):', line):
            key, value = line.split(':', 1)
            value, comment = value.split('#', 1)
            rows[section, key] = (value.strip(), comment.strip())
            assert line.index('#') == max(48, len(line.split('#', 1)[0].rstrip()) + 1)
            assert line.count('#') == 1
    return rows


@pytest.mark.parametrize('language', ['English', 'Español', 'Português'])
@pytest.mark.parametrize('prefix', ['', '!', '^', '^!'])
def test_all_generated_motors_and_physical_endstops_keep_pins(tmp_path, language, prefix):
    set_lang(language)
    user = data(4)
    board = user['board_parsed']
    motors = ['stepper_x', 'stepper_y', 'stepper_z', 'stepper_z1', 'stepper_z2', 'stepper_z3', 'extruder']
    for index, name in enumerate(motors):
        board[name]['step_pin'] = '!' + board[name]['step_pin']
        if name != 'extruder':
            board[name]['endstop_pin'] = prefix + f'PI{index}'
    before = copy.deepcopy(user)
    output = generate_config(board, user, output_path=str(tmp_path/'printer.cfg'), verbose=False)['content']
    rows = pin_rows(output)
    assert len(rows) == 27
    for name in motors:
        for key in ('step_pin', 'dir_pin', 'enable_pin'):
            value, comment = rows[name, key]
            assert value == board[name][key]
            assert '!PA1' in comment
        if name != 'extruder':
            value, comment = rows[name, 'endstop_pin']
            assert value == board[name]['endstop_pin']
            assert all(example in comment for example in ('^PA1', '!PA1', '^!PA1'))
    if language != 'English':
        assert 'Step signal' not in output and 'Direction signal' not in output
        assert 'inverted logic' not in output
    assert '#                                               # ' not in output
    assert user == before


@pytest.mark.parametrize('language', ['English', 'Español', 'Português'])
@pytest.mark.parametrize('kind', ['probe', 'sensorless'])
def test_virtual_endstop_comments_do_not_suggest_gpio_prefixes(tmp_path, language, kind):
    set_lang(language)
    if kind == 'probe':
        user = data(4)
        board = user['board_parsed']
        user['probe'] = 'BLTouch'
        board['bltouch'] = dict(sensor_pin='^PB8', control_pin='PB9')
        for n in range(1,4):
            board[f'stepper_z{n}']['endstop_pin'] = 'probe:z_virtual_endstop'
        targets = ['stepper_z', 'stepper_z1', 'stepper_z2', 'stepper_z3']
        expected = 'Probe virtual endstop; no ^ or ! prefixes here'
    else:
        board, user = original_inputs(True)
        board['stepper_x']['homing_retract_dist'] = '0'
        targets = ['stepper_x']
        expected = 'Sensorless virtual endstop; no ^ or ! prefixes here'
    output = generate_config(board, user, output_path=str(tmp_path/'printer.cfg'), verbose=False)['content']
    rows = pin_rows(output)
    for target in targets:
        value, comment = rows[target, 'endstop_pin']
        assert value == ('probe:z_virtual_endstop' if kind == 'probe' else board[target]['endstop_pin'])
        assert comment == translate_comment(expected, language)
        assert '^PA1' not in comment


@pytest.mark.parametrize('language', ['English', 'Español', 'Português'])
def test_comments_preserve_long_names_option_examples_and_custom_bytes(language):
    set_lang(language)
    custom = '[probe]\r\npin: ^!tool:STOP # medición → posição\r\nz_offset: 1.25\r\n'
    pin = '!' + 'controller_'*6 + ':PA1'
    source = (f'dir_pin: {pin} # Direction signal; ! reverses motor rotation (e.g. !PA1)\n'
              '# homing_speed: 20 # Maximum velocity (in mm/s) of the stepper when homing\n'
              '__KACE_VERBATIM_CUSTOM_PROBE_BEGIN__\n' + custom +
              '\n__KACE_VERBATIM_CUSTOM_PROBE_END__\n')
    result = _postprocess_generated_output(source)
    assert custom in result
    first, second = result.splitlines()[:2]
    assert first.split('#')[0].rstrip() == f'dir_pin: {pin}'
    assert first.index('#') == len(f'dir_pin: {pin}') + 1
    assert second.startswith('# homing_speed: 20')
    assert second.index('#', 1) == 48


@pytest.mark.parametrize('language,macro_title,pid_description', [
    ('English', 'KACE Starter Macros', 'PID Calibration for the hotend'),
    ('Español', 'Macros iniciales de KACE', 'Calibracion PID para el hotend'),
    ('Português', 'Macros iniciais do KACE', 'Calibracao PID para o hotend'),
])
def test_generated_files_use_plain_localized_prose(tmp_path, language, macro_title, pid_description):
    set_lang(language)
    user = data(4)
    path = tmp_path / 'printer.cfg'
    generate_config(user['board_parsed'], user, output_path=str(path), include_macros=True, verbose=False)
    printer = path.read_text(encoding='utf-8')
    macros = path.with_name('macros.cfg').read_text(encoding='utf-8')
    for text in (printer, macros):
        for line in text.splitlines():
            if '#' in line:
                comment = line.partition('#')[2]
                assert comment.isascii(), line
                assert not re.fullmatch(r'\s*[-=]{5,}\s*', comment), line
    assert macros.startswith(f'# {macro_title}\n')
    assert f'# {pid_description}\n[gcode_macro PID_HOTEND]\ndescription: {pid_description}\n' in macros
    assert all(line.isascii() for line in macros.splitlines() if line.startswith('description:'))


def test_endstop_helper_emits_only_one_comment_line():
    """Comment helper cannot emit a section or a parameter into active config."""
    source = (Path(__file__).resolve().parents[2]/'templates/printer.cfg.j2').read_text(encoding='utf-8')
    macro = source.split('{%- endmacro -%}', 1)[0] + '{%- endmacro -%}'
    for pin in ('PA1', '!tool:PA1', '^!STOP', 'probe:z_virtual_endstop', 'tmc2209_stepper_y:virtual_endstop'):
        rendered = Template(macro + '{{ endstop_comment(pin) }}').render(pin=pin)
        assert '\n' not in rendered and '#' not in rendered
        assert rendered == rendered.strip()


def test_static_template_explanations_have_both_translations():
    source = (Path(__file__).resolve().parents[2]/'templates/printer.cfg.j2').read_text(encoding='utf-8')
    for line in source.splitlines():
        if '# ' not in line or '{#' in line:
            continue
        comment = line.rsplit('# ', 1)[1].strip()
        if not re.search('[A-Za-z]', comment) or '{{' in comment or '{%' in comment:
            continue
        # Config examples and identifiers must remain valid Klipper syntax.
        if re.match(r'(?:\[|aliases:|EXP\d_|homing_positive_dir:)', comment):
            continue
        for language in ('Español', 'Português'):
            assert translate_comment(comment, language) != comment, (language, comment)
