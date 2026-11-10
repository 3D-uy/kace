"""Matrix validation checks deferred fan references without starting hardware."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import sys

import pytest


@pytest.fixture
def harness(monkeypatch):
    calls = []
    heaters = {'extruder': object(), 'Chamber': object(), 'Extension heater': object()}

    def lookup_heater(name):
        calls.append(('heater', name))
        if name not in heaters:
            raise ValueError(f"Unknown heater '{name}'")
        return heaters[name]

    objects = {'heater_fan': [], 'controller_fan': []}
    printer = SimpleNamespace(
        _read_config=Mock(side_effect=lambda: calls.append('load')),
        lookup_objects=Mock(side_effect=lambda name=None: objects[name] if name is not None
                            else objects['heater_fan'] + objects['controller_fan']),
        lookup_object=Mock(side_effect=lambda name: SimpleNamespace(lookup_heater=lookup_heater)
                           if name == 'heaters' else pytest.fail('unexpected object '+name)),
        send_event=Mock(side_effect=lambda event: calls.append(event)),
    )
    reactor = SimpleNamespace(run=Mock(), register_timer=Mock())
    printer.get_reactor = Mock(return_value=reactor)
    monkeypatch.setitem(sys.modules, 'klippy', SimpleNamespace(Printer=Mock(return_value=printer)))
    monkeypatch.setitem(sys.modules, 'reactor', SimpleNamespace(Reactor=Mock(return_value=reactor)))
    # The validator inserts the configured Klipper directory for container use.
    # Keep that import-path change local to this test module load.
    monkeypatch.setattr(sys, 'path', list(sys.path))
    source = Path(__file__).parents[1]/'matrix/klipper_validator.py'
    spec = importlib.util.spec_from_file_location('fan_registry_validator_test', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return SimpleNamespace(module=module, printer=printer, objects=objects,
                           reactor=reactor, calls=calls)


@pytest.mark.parametrize('names', [[], ['extruder'], ['Chamber', 'extruder'], ['Extension heater']])
def test_heater_references_use_actual_registry_without_ready_event(harness, names, tmp_path):
    fan = SimpleNamespace(heater_names=names, handle_ready=Mock())
    harness.objects['heater_fan'] = [('heater_fan Cooler', fan)]
    result = harness.module.validate_config(tmp_path/'printer.cfg')
    assert result['valid']
    assert result['checks'] == ['object_load', 'fan_references']
    assert harness.calls == ['load', *[('heater', n) for n in names], 'klippy:disconnect']
    fan.handle_ready.assert_not_called()
    harness.reactor.run.assert_not_called()
    harness.reactor.register_timer.assert_not_called()


@pytest.mark.parametrize('name', ['Missing', 'Extruder', ''])
def test_unknown_heater_fails_after_loading_not_after_hardware_start(harness, name, tmp_path):
    harness.objects['heater_fan'] = [('heater_fan Cooler', SimpleNamespace(heater_names=[name]))]
    result = harness.module.validate_config(tmp_path/'printer.cfg')
    assert not result['valid']
    assert result['stage'] == 'fan_references'
    assert result['checks'] == ['object_load']
    assert "Unknown heater" in result['reason']
    harness.printer.send_event.assert_called_once_with('klippy:disconnect')


@pytest.mark.parametrize('failure', [None, ValueError('Unknown heater'), ValueError('Unknown stepper')])
def test_controller_delegates_to_official_connect_method_only(harness, failure, tmp_path):
    def connect():
        assert harness.calls == ['load']
        harness.calls.append('controller_connect')
        if failure:
            raise failure
    fan = SimpleNamespace(handle_connect=Mock(side_effect=connect), handle_ready=Mock())
    harness.objects['controller_fan'] = [('controller_fan Cooler', fan)]
    result = harness.module.validate_config(tmp_path/'printer.cfg')
    assert result['valid'] is (failure is None)
    fan.handle_connect.assert_called_once_with()
    fan.handle_ready.assert_not_called()
    harness.printer.send_event.assert_called_once_with('klippy:disconnect')
    harness.reactor.run.assert_not_called()
    if failure:
        assert result['stage'] == 'fan_references'
        assert result['checks'] == ['object_load']


def test_load_failure_does_not_run_reference_checks(harness, tmp_path):
    harness.printer._read_config.side_effect = ValueError('unused option')
    result = harness.module.validate_config(tmp_path/'printer.cfg')
    assert not result['valid']
    assert result['stage'] == 'object_load'
    assert result['checks'] == []
    harness.printer.lookup_objects.assert_not_called()
    harness.printer.send_event.assert_called_once_with('klippy:disconnect')


def test_no_fans_requires_no_heater_registry(harness, tmp_path):
    result = harness.module.validate_config(tmp_path/'printer.cfg')
    assert result['valid']
    assert result['checks'] == ['object_load', 'fan_references']
    harness.printer.lookup_object.assert_not_called()
    assert harness.calls == ['load', 'klippy:disconnect']
