"""Primary XYZ rail defaults and bounds, independent of explicit direction."""
import re
from unittest.mock import Mock, patch

import pytest

from core.configuration_review import validate_configuration_plan
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.generator import generate_config
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.profile_values import infer_homing_positive_dir
from core.exceptions import GenerationError
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_generator import _parsed, _user


def axis_options(text, axis, **options):
    def update(match):
        body = match.group()
        for key, value in options.items():
            body = re.sub(rf"(?m)^{key}\s*:.*\n", "", body)
            if value is not None:
                body += f"{key}: {value}\n"
        return body
    return re.sub(rf"(?ms)^\[stepper_{axis}\].*?(?=^\[|\Z)", update, text)


@pytest.fixture
def base(tmp_path):
    return generate_config(_parsed(), _user(), output_path=str(tmp_path/'base.cfg'), verbose=False)['content']


def review(text):
    return validate_configuration_plan(build_managed_config_plan(text.encode(), None, {}))


@pytest.mark.parametrize('axis', 'xyz')
@pytest.mark.parametrize('endstop,direction', [('0', None), ('200', None), ('100', 'True')])
def test_omitted_minimum_equals_explicit_zero_without_injecting_it(base, axis, endstop, direction):
    text = axis_options(base, axis, position_min=None, position_max='200',
                        position_endstop=endstop, homing_positive_dir=direction)
    before = text.encode()
    plan = build_managed_config_plan(before, None, {})
    implicit = validate_configuration_plan(plan)
    explicit = review(axis_options(text, axis, position_min='0'))
    assert implicit.valid and explicit.valid, (implicit, explicit)
    assert implicit.errors == explicit.errors
    assert implicit.warnings == explicit.warnings
    assert axis_options(effective_hardware_text(plan), axis, position_min=None) == effective_hardware_text(plan)


@pytest.mark.parametrize('axis', 'xyz')
@pytest.mark.parametrize('minimum', ['-20', '0', '10'])
def test_explicit_limits_and_source_provenance_are_preserved(tmp_path, axis, minimum):
    board = _parsed()
    board['stepper_'+axis].update(position_min=minimum, position_endstop=minimum, position_max='300')
    result = generate_config(board, _user(), output_path=str(tmp_path/'printer.cfg'), verbose=False)
    assert result['value_provenance'][axis+'_position_min'] == 'PROFILE'
    assert f'position_min: {minimum}' in result['content']
    assert review(result['content']).valid


def test_generated_defaults_retain_existing_provenance(tmp_path):
    result = generate_config(_parsed(), _user(), output_path=str(tmp_path/'printer.cfg'), verbose=False)
    for axis in 'xyz':
        assert result['value_provenance'][axis+'_position_min'] == 'SAFE_DEFAULT'


def test_ambiguous_generation_requires_explicit_direction(tmp_path):
    with pytest.raises(GenerationError, match='homing_positive_dir_x'):
        generate_config(_parsed(), _user(x_position_endstop='90'),
                        output_path=str(tmp_path/'printer.cfg'), verbose=False)
    assert not (tmp_path/'printer.cfg').exists()


def test_wizard_prompts_for_middle_half_and_retains_user_choice():
    from core.wizard.steps.motion import _step_homing_directions
    user = dict(x_position_min='0', x_position_max='200', x_position_endstop='80',
                homing_positive_dir_y='False', homing_positive_dir_z='False')
    with patch.dict('os.environ', {'KACE_AUTO': '0'}), patch(
        'core.wizard.steps.motion.numbered_select', return_value='True') as select:
        assert _step_homing_directions(user) == 'done'
    select.assert_called_once()
    assert user['homing_positive_dir_x'] == 'True'
    assert user['_value_provenance']['homing_positive_dir_x'] == 'USER_OVERRIDE'


@pytest.mark.parametrize('noop', [False, True])
def test_nested_include_cannot_bypass_effective_default_range(base, tmp_path, noop):
    base = axis_options(base, 'x', position_min=None)
    remote = {'printer.cfg': (base+'\n[include user.cfg]\n').encode(),
              'user.cfg': b'[include limits.cfg]\n',
              'limits.cfg': b'[stepper_x]\nposition_endstop: -1\nhoming_positive_dir: False\n'}
    if noop:
        remote.update({a.remote_name: a.content for a in build_managed_config_plan(base.encode(), None, remote).artifacts})
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, base.encode(), None,
        activation='none', confirm=confirm, verify_existing_ready=noop,
        snapshot_root=str(tmp_path/'snapshots')).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    assert transport.files == remote
    assert all(call[0] == 'read' for call in transport.calls)


@pytest.mark.parametrize('axis', 'xyz')
@pytest.mark.parametrize('minimum,maximum,endstop', [
    (None, '0', '0'), (None, '-1', '0'), (None, '200', '-1'),
    (None, '200', '201'), ('10', '10', '10'), ('20', '10', '10'),
    ('-10', '200', '-11'), ('bad', '200', '0'), ('nan', '200', '0'),
    ('0', 'inf', '0'), ('0', '200', 'nan'), ('', '200', '0'),
])
def test_invalid_geometry_rejected_with_explicit_direction(base, axis, minimum, maximum, endstop):
    text = axis_options(base, axis, position_min=minimum, position_max=maximum,
                        position_endstop=endstop, homing_positive_dir='False')
    assert f'homing-{axis}-geometry' in {e.code for e in review(text).errors}


@pytest.mark.parametrize('axis', 'xyz')
@pytest.mark.parametrize('field', ['position_max', 'position_endstop'])
def test_required_geometry_not_defaulted(base, axis, field):
    assert not review(axis_options(base, axis, position_min=None, **{field: None})).valid


@pytest.mark.parametrize('endstop,expected', [('0', 'False'), ('50', 'False'),
    ('50.001', None), ('80', None), ('100', None), ('149.999', None), ('150', 'True'), ('200', 'True'),
    ('-1', None), ('201', None), ('nan', None)])
def test_official_inference_quarters(endstop, expected):
    assert infer_homing_positive_dir(endstop, '0', '200') == expected


@pytest.mark.parametrize('endstop,direction,valid', [
    ('80', None, False), ('80', 'True', True), ('25', 'True', True),
    ('175', 'False', True), ('0', 'True', False), ('200', 'False', False),
    ('0', 'no', True), ('200', 'yes', True), ('80', 'bad', False),
])
def test_direction_uses_upstream_rules(base, endstop, direction, valid):
    text = axis_options(base, 'x', position_min=None, position_max='200',
                        position_endstop=endstop, homing_positive_dir=direction)
    assert review(text).valid is valid


@pytest.mark.parametrize('noop', [False, True])
def test_preserved_omission_publication_and_noop(base, tmp_path, noop):
    for axis in 'xyz':
        base = axis_options(base, axis, position_min=None)
    remote = {'printer.cfg': base.encode()}
    if noop:
        remote.update({a.remote_name: a.content for a in build_managed_config_plan(base.encode(), None, remote).artifacts})
    transport = FakeTransport(remote)
    result = ConfigDeploymentTransaction(transport, base.encode(), None,
        activation='none', confirm=lambda _: True, verify_existing_ready=noop,
        snapshot_root=str(tmp_path/'snapshots'), poll_interval=0).run()
    expected = ConfigTransactionState.COMMITTED if noop else ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    assert result.state == expected, result
    assert not any(call[0] == 'restart' for call in transport.calls)
    text = effective_hardware_text(build_managed_config_plan(base.encode(), None, transport.files))
    assert not re.search(r'(?m)^position_min:', text)
