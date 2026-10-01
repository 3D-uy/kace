"""A generated heated bed must have a real circuit, not just thermal defaults."""
import re
from unittest.mock import Mock
import pytest

from core.configuration_review import validate_configuration_plan
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_generator import _parsed, _user


def render(tmp_path):
    return generate_config(_parsed(), _user(), output_path=str(tmp_path/'base.cfg'), verbose=False)['content']


@pytest.mark.parametrize('missing', ['section', 'heater_pin', 'sensor_pin'])
@pytest.mark.parametrize('existing', [False, True])
def test_missing_board_bed_circuit_rejects_without_writing(tmp_path, missing, existing):
    board = _parsed()
    if missing == 'section':
        board.pop('heater_bed')
    else:
        board['heater_bed'].pop(missing)
    path = tmp_path/'printer.cfg'
    if existing:
        path.write_bytes(b'previous config')
    with pytest.raises(GenerationError, match='heater_bed.*required'):
        generate_config(board, _user(), output_path=str(path), verbose=False)
    assert path.read_bytes() == b'previous config' if existing else not path.exists()
    assert not (tmp_path/'printer.cfg.provenance.json').exists()


@pytest.mark.parametrize('field', ['heater_pin', 'sensor_pin'])
@pytest.mark.parametrize('value', ['', '  ', 'TODO', 'None', None])
def test_unresolved_bed_pin_rejects_before_writing(tmp_path, field, value):
    board = _parsed()
    board['heater_bed'][field] = value
    with pytest.raises(GenerationError, match='heater_bed.*required'):
        generate_config(board, _user(), output_path=str(tmp_path/'printer.cfg'), verbose=False)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('field', ['heater_pin', 'sensor_pin', 'sensor_type'])
def test_effective_bed_requires_its_circuit_fields(tmp_path, field):
    text = render(tmp_path)
    text = re.sub(r'(?ms)(^\[heater_bed\].*?)(?=^\[|\Z)',
                  lambda m: re.sub(r'(?m)^'+field+r':.*\n', '', m.group()), text)
    plan = build_managed_config_plan(text.encode(), None, {})
    errors = validate_configuration_plan(plan).errors
    assert any(e.code == 'bed-circuit' and field in e.message for e in errors)


@pytest.mark.parametrize('field', ['heater_pin', 'sensor_pin'])
@pytest.mark.parametrize('noop', [False, True])
def test_nested_included_empty_bed_pin_blocks_publish_and_resume(tmp_path, field, noop):
    text = render(tmp_path)
    remote = {'printer.cfg': (text+'\n[include user.cfg]\n').encode(),
              'user.cfg': b'[include thermal.cfg]\n',
              'thermal.cfg': f'[heater_bed]\n{field}:\n'.encode()}
    plan = lambda: build_managed_config_plan(text.encode(), None, remote)
    if noop:
        remote.update({a.remote_name:a.content for a in plan().artifacts})
        assert not plan().changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, text.encode(), None,
        activation='none', confirm=confirm, verify_existing_ready=noop,
        snapshot_root=str(tmp_path/'snapshots'), poll_interval=0).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED, result
    assert 'heater_bed' in result.detail and field in result.detail
    confirm.assert_not_called()
    assert transport.files == remote
    assert not any(c[0] in ('upload','delete','restart','restart_moonraker') for c in transport.calls)


def test_valid_bed_generation_and_effective_review_remain_valid(tmp_path):
    text = render(tmp_path)
    result = validate_configuration_plan(build_managed_config_plan(text.encode(), None, {}))
    assert result.valid, result.errors


@pytest.mark.parametrize('definition,sensor', [
    ('', 'PT1000'), ('thermistor custom', 'custom'), ('adc_temperature custom', 'custom')])
def test_adc_factories_require_sensor_pin_including_custom_curves(definition, sensor):
    from core.thermistor import validate_bed_circuit
    sections = {definition: {}, 'heater_bed': {'sensor_type':sensor, 'heater_pin':'PA6'}}
    with pytest.raises(GenerationError, match='sensor_pin is required'):
        validate_bed_circuit(sections)
    sections['heater_bed']['sensor_pin'] = 'PA7'
    validate_bed_circuit(sections)


def test_non_adc_factory_does_not_invent_adc_pin_requirement():
    from core.thermistor import validate_bed_circuit
    # This presence check does not qualify combined sensors or add generation
    # support for them. Their independent factory/configuration checks remain.
    validate_bed_circuit({'heater_bed': {'sensor_type':'temperature_combined', 'heater_pin':'PA6'}})
    validate_bed_circuit({})
    with pytest.raises(GenerationError, match='heater_pin is required'):
        validate_bed_circuit({}, required=True)


@pytest.mark.parametrize('missing', ['section', 'heater_pin', 'sensor_pin'])
def test_rendered_bed_cannot_bypass_source_check(tmp_path, monkeypatch, missing):
    from jinja2 import Template
    original = Template.render
    def broken(template, *args, **kwargs):
        text = original(template, *args, **kwargs)
        def alter(match):
            if missing == 'section':
                return ''
            return re.sub(r'(?m)^'+missing+r':.*\n', '', match.group())
        return re.sub(r'(?ms)^\[heater_bed\].*?(?=^\[|\Z)', alter, text)
    monkeypatch.setattr(Template, 'render', broken)
    with pytest.raises(GenerationError, match='heater_bed.*required'):
        generate_config(_parsed(), _user(), output_path=str(tmp_path/'printer.cfg'), verbose=False)
    assert list(tmp_path.iterdir()) == []
