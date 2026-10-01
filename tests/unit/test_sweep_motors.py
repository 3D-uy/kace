"""Motor classes, preservation and complete official-result requirements."""
import copy
from unittest.mock import patch

import pytest

from core.exceptions import GenerationError
from tests.sweep import motor_contract as contract


@pytest.fixture(scope='module')
def generated(tmp_path_factory):
    folder = tmp_path_factory.mktemp('guided-motors')
    receipt, records = contract.generate_motors(contract.SOURCE, folder)
    return folder, receipt, records


@pytest.mark.parametrize('mode,count', [('UART', 4), ('SPI', 1), (None, 1)])
def test_complete_functional_classes(generated, mode, count):
    folder, receipt, records = generated
    assert receipt['profile_count'] == 192 and receipt['qualified_boards'] == []
    rows = [r for r in records if r['driver_answers']['driver_mode'] == mode]
    assert len(rows) == count
    for row in rows:
        assert row['status'] == 'GENERATED'
        assert (folder / row['config_path']).is_file()
        assert (folder / (row['config_path'] + '.provenance.json')).is_file()


@pytest.mark.parametrize('field', contract.MOTOR_FIELDS)
@pytest.mark.parametrize('mutation', ['missing', 'changed'])
def test_motor_option_cannot_be_lost_or_changed(field, mutation):
    rendered = {'stepper_z1': {field: 'different'} if mutation == 'changed' else {}}
    with pytest.raises(AssertionError):
        contract.compare_fields({'stepper_z1': {field: 'PC6'}}, rendered)


@pytest.mark.parametrize('section,field', [('tmc2209 stepper_z', 'uart_pin'),
    ('tmc2130 stepper_x', 'cs_pin'), ('tmc2209 extruder', 'run_current'),
    ('controller_fan cooling', 'stepper'), ('controller_fan cooling', 'heater')])
def test_driver_bus_current_and_cooling_options_cannot_disappear(section, field):
    with pytest.raises(AssertionError):
        contract.compare_fields({section: {field: '1'}}, {section: {}})


def test_missing_motor_section_cannot_pass():
    with pytest.raises(AssertionError, match='Missing section'):
        contract.compare_fields({'stepper_z1': {'endstop_pin': 'PC6'}}, {})


@pytest.mark.parametrize('independent', [False, True])
def test_endstop_expectation_comes_from_source(independent):
    source = {'stepper_z': {'endstop_pin': 'PA1'}, 'stepper_z1': {}}
    if independent:
        source['stepper_z1']['endstop_pin'] = 'PA2'
    expected = {'stepper_z': ['stepper_z'], 'z1': ['stepper_z1']} if independent else {
        'stepper_z': ['stepper_z', 'stepper_z1']}
    assert contract.expected_objects(source)['z_endstops'] == expected


def test_virtual_endstop_helper_is_distinct_from_physical_ownership():
    source = {'stepper_z': {'endstop_pin': 'probe:z_virtual_endstop'}, 'stepper_z1': {}}
    result = contract.expected_objects(source)
    assert result['z_endstops'] == {'stepper_z': []}
    assert result['virtual_z'] is True
    assert result['z_steppers'] == ['stepper_z', 'stepper_z1']


def test_fan_defaults_and_explicit_consumers_are_distinct():
    source = {'stepper_x': {}, 'stepper_z': {}, 'extruder': {},
              'controller_fan default': {},
              'controller_fan explicit': {'stepper': 'stepper_z', 'heater': 'heater_bed'}}
    fans = contract.expected_objects(source)['controller_fans']
    assert fans['controller_fan default'] == dict(steppers=['extruder', 'stepper_x', 'stepper_z'], heaters=['extruder'])
    assert fans['controller_fan explicit'] == dict(steppers=['stepper_z'], heaters=['heater_bed'])


def official_results(rows):
    loaded = {r['filename']: {'valid': True} for r in rows}
    objects = {r['filename']: dict(valid=True, **copy.deepcopy(r['expected_objects'])) for r in rows}
    return loaded, objects


@pytest.mark.parametrize('mutation', ['missing_load', 'missing_objects', 'extra', 'load_false',
    'object_false', 'truthy', 'wrong_ownership', 'wrong_consumers', 'infra', 'empty', 'duplicate'])
def test_incomplete_or_wrong_official_evidence_cannot_pass(generated, mutation):
    rows = copy.deepcopy(generated[2])
    loaded, objects = official_results(rows)
    name = rows[0]['filename']
    error = None
    if mutation == 'missing_load':
        del loaded[name]
    elif mutation == 'missing_objects':
        del objects[name]
    elif mutation == 'extra':
        objects['unknown'] = {'valid': True}
    elif mutation == 'load_false':
        loaded[name]['valid'] = False
    elif mutation == 'object_false':
        objects[name]['valid'] = False
    elif mutation == 'truthy':
        objects[name]['valid'] = 'true'
    elif mutation == 'wrong_ownership':
        objects[name]['z_endstops'] = {}
    elif mutation == 'wrong_consumers':
        name = next(r['filename'] for r in rows if r['expected_objects']['controller_fans'])
        objects[name]['controller_fans'] = {}
    elif mutation == 'infra':
        error = 'Docker unavailable'
    elif mutation == 'duplicate':
        rows[-1] = copy.deepcopy(rows[0])
    else:
        rows, loaded, objects = [], {}, {}
    assert contract.apply_results(rows, loaded, objects, error)[0] is False


def test_both_complete_official_gates_are_required(generated):
    rows = copy.deepcopy(generated[2])
    loaded, objects = official_results(rows)
    assert contract.apply_results(rows, loaded, objects, None) == (True, None)
    assert all(r['status'] == 'PASS' for r in rows)


@pytest.mark.parametrize('error', [GenerationError('wrong TMC'), RuntimeError('broken driver')])
def test_generation_error_is_not_credited_as_expected(generated, tmp_path, error):
    with patch.object(contract, 'generate_config', side_effect=error):
        with pytest.raises(AssertionError):
            contract.replay_motor(generated[2][0], contract.SOURCE, tmp_path)


def test_source_drift_blocks_before_replay(generated, tmp_path):
    row = generated[2][0]
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config' / row['filename']).write_text('# changed', encoding='utf-8')
    with pytest.raises(AssertionError, match='Source drift'):
        contract.replay_motor(row, tmp_path, tmp_path)


def test_existing_directory_cannot_reuse_results(tmp_path):
    with pytest.raises(FileExistsError):
        contract.execute(contract.SOURCE, tmp_path)


@pytest.mark.parametrize('mutation', ['missing', 'accepted', 'unrelated', 'truthy', 'extra'])
def test_semantic_controls_require_specific_official_rejections(mutation):
    results = {k: dict(valid=False, reason=v) for k, v in contract.CONTROL_REASONS.items()}
    name = next(iter(results))
    if mutation == 'missing':
        del results[name]
    elif mutation == 'accepted':
        results[name]['valid'] = True
    elif mutation == 'unrelated':
        results[name]['reason'] = 'unexpected parser error'
    elif mutation == 'truthy':
        results[name]['valid'] = 0
    else:
        results['other'] = dict(valid=False, reason='other')
    assert not contract.valid_controls(results)


def test_control_mutations_leave_generated_files_intact(generated, tmp_path):
    folder, _, records = generated
    for row in records:
        (tmp_path / row['config_path']).write_bytes((folder / row['config_path']).read_bytes())
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    controls = contract.object_controls(records, tmp_path)
    assert len(controls) == 2
    assert all((tmp_path / k).read_bytes() == v for k, v in before.items())
