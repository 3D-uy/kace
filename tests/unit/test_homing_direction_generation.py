"""Homing intent survives generation while automatic settings stay inactive."""
import re
from unittest.mock import patch

import pytest

from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.profile_values import mark_user_override, resolve_generation_values
from tests.unit.test_generator import _parsed, _user


def section(text, axis):
    return re.search(rf"(?ms)^\[stepper_{axis}\]\n(.*?)(?=^\[|\Z)", text).group(1)


@pytest.mark.parametrize('axis', 'xyz')
@pytest.mark.parametrize('endstop,expected', [('0', 'false'), ('320', 'true')])
@pytest.mark.parametrize('language,guidance', [
    ('English', 'Automatic homing:'),
    ('Español', 'Homing automático:'),
    ('Português', 'Homing automático:'),
])
def test_automatic_direction_is_localized_and_commented(tmp_path, axis, endstop, expected, language, guidance):
    user = _user(**{f'{axis}_position_min': '0', f'{axis}_position_max': '320',
                   f'{axis}_position_endstop': endstop})
    with patch('core.generator.get_lang', return_value=language):
        result = generate_config(_parsed(), user, output_path=str(tmp_path/'printer.cfg'), verbose=False)
    body = section(result['content'], axis)
    assert f'# homing_positive_dir: {expected}' in body
    assert guidance in body
    assert not re.search(r'(?m)^homing_positive_dir:', body)
    assert result['value_provenance'][f'homing_positive_dir_{axis}'] == 'INFERRED'
    plan = build_managed_config_plan(result['content'].encode(), None, {})
    assert validate_configuration_plan(plan).valid


@pytest.mark.parametrize('axis', 'xyz')
@pytest.mark.parametrize('direction,endstop', [('False', '0'), ('True', '320')])
@pytest.mark.parametrize('origin', ['PROFILE', 'USER_OVERRIDE'])
def test_explicit_import_or_choice_remains_active(tmp_path, axis, direction, endstop, origin):
    key = f'homing_positive_dir_{axis}'
    board = _parsed()
    if origin == 'PROFILE':
        board[f'stepper_{axis}'].update(position_min='0', position_max='320',
                                      position_endstop=endstop, homing_positive_dir=direction)
    user = _user(**{f'{axis}_position_min': '0', f'{axis}_position_max': '320',
                   f'{axis}_position_endstop': endstop, key: direction,
                   '_value_provenance': {key: origin}})
    mark_user_override(user, *(f'{axis}_position_{option}' for option in ('min', 'max', 'endstop')))
    result = generate_config(board, user, output_path=str(tmp_path/'printer.cfg'), verbose=False)
    body = section(result['content'], axis)
    assert re.search(rf'(?m)^homing_positive_dir: {direction}\s+#', body)
    assert not re.search(r'(?m)^# homing_positive_dir:', body)
    assert result['value_provenance'][key] == origin


@pytest.mark.parametrize('axis', 'xyz')
@pytest.mark.parametrize('cached,endstop,expected', [('False', '320', 'True'), ('True', '0', 'False')])
def test_automatic_recomputes_after_geometry_edit_and_overrides_import(tmp_path, axis, cached, endstop, expected):
    key = f'homing_positive_dir_{axis}'
    board = _parsed()
    board[f'stepper_{axis}']['homing_positive_dir'] = cached
    user = _user(**{f'{axis}_position_min': '0', f'{axis}_position_max': '320',
                   f'{axis}_position_endstop': endstop, key: cached,
                   '_value_provenance': {key: 'INFERRED'}})
    mark_user_override(user, *(f'{axis}_position_{option}' for option in ('min', 'max', 'endstop')))
    values, provenance = resolve_generation_values(board, user)
    assert values[key] == expected
    assert provenance[key] == 'INFERRED'
    result = generate_config(board, user, output_path=str(tmp_path/'printer.cfg'), verbose=False)
    body = section(result['content'], axis)
    assert f'# homing_positive_dir: {expected.lower()}' in body
    assert not re.search(r'(?m)^homing_positive_dir:', body)
    assert validate_configuration_plan(build_managed_config_plan(result['content'].encode(), None, {})).valid


@pytest.mark.parametrize('axis', 'xyz')
@pytest.mark.parametrize('cached', ['False', 'True', None])
def test_automatic_cannot_reuse_a_cached_direction_for_ambiguous_geometry(tmp_path, axis, cached):
    key = f'homing_positive_dir_{axis}'
    board = _parsed()
    board[f'stepper_{axis}']['homing_positive_dir'] = 'True'
    user = _user(**{f'{axis}_position_min': '0', f'{axis}_position_max': '320',
                   f'{axis}_position_endstop': '160', key: cached,
                   '_value_provenance': {key: 'INFERRED'}})
    mark_user_override(user, *(f'{axis}_position_{option}' for option in ('min', 'max', 'endstop')))
    with pytest.raises(GenerationError, match=key):
        generate_config(board, user, output_path=str(tmp_path/'printer.cfg'), verbose=False)
    assert not (tmp_path/'printer.cfg').exists()


@pytest.mark.parametrize('physical_endstop', ['0', '250'])
def test_automatic_probe_z_does_not_recommend_a_physical_endstop_direction(tmp_path, physical_endstop):
    result = generate_config(_parsed(bltouch={'sensor_pin': '^PB5', 'control_pin': 'PB6'}),
                             _user(probe='BLTouch', z_position_endstop=physical_endstop),
                             output_path=str(tmp_path/'printer.cfg'), verbose=False)
    body = section(result['content'], 'z')
    assert 'endstop_pin: probe:z_virtual_endstop' in body
    assert re.search(r'(?m)^# homing_positive_dir:\s+# Optional override:', body)
    assert not re.search(r'(?m)^# homing_positive_dir: (true|false)', body)
    assert not re.search(r'(?m)^homing_positive_dir:', body)
    assert validate_configuration_plan(build_managed_config_plan(result['content'].encode(), None, {})).valid


@pytest.mark.parametrize('axis', 'xyz')
@pytest.mark.parametrize('source', ['root', 'user_include'])
@pytest.mark.parametrize('override,valid', [('True', True), ('False', False)])
def test_automatic_does_not_hide_retained_destination_homing_override(tmp_path, axis, source, override, valid):
    user = _user(**{f'{axis}_position_min': '0', f'{axis}_position_max': '320',
                   f'{axis}_position_endstop': '320'})
    mark_user_override(user, *(f'{axis}_position_{option}' for option in ('min', 'max', 'endstop')))
    generated = generate_config(_parsed(), user, output_path=str(tmp_path/'printer.cfg'), verbose=False)['content']
    retained = f'[stepper_{axis}]\nhoming_positive_dir: {override}\n'.encode()
    remote = ({'printer.cfg': retained} if source == 'root' else
              {'printer.cfg': b'[include user-motion.cfg]\n', 'user-motion.cfg': retained})
    plan = build_managed_config_plan(generated.encode(), None, remote)
    effective = effective_hardware_text(plan)
    assert re.search(rf'(?m)^homing_positive_dir: {override}\s*$', effective)
    review = validate_configuration_plan(plan)
    assert review.valid is valid
    assert not any(item.code == f'homing-{axis}-inferred' for item in review.warnings)
    if not valid:
        assert any(item.code == f'homing-{axis}-contradiction' for item in review.errors)
    if source == 'user_include':
        assert all(item.remote_name != 'user-motion.cfg' for item in plan.artifacts)
    remote.update({item.remote_name: item.content for item in plan.artifacts})
    retry = build_managed_config_plan(generated.encode(), None, remote)
    assert not retry.changed_artifacts
    assert validate_configuration_plan(retry).valid is valid
