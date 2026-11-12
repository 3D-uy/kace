"""Deferred fan checks cover objects loaded with Klipper's whitespace rules."""
import ast
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parents[2]
KLIPPER = ROOT / '.klipper-contract-source' / 'klippy'


def pinned_method(path, class_name, name):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    module = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
    namespace = {}
    exec(compile(module, str(path), 'exec'), namespace)
    return namespace[name]


@pytest.fixture
def validator(monkeypatch):
    monkeypatch.setitem(sys.modules, 'klippy', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'reactor', SimpleNamespace())
    monkeypatch.setattr(sys, 'path', list(sys.path))
    spec = importlib.util.spec_from_file_location('matrix_fan_whitespace', ROOT / 'tests/matrix/klipper_validator.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('family', ['heater_fan', 'controller_fan'])
@pytest.mark.parametrize('separator', [' ', '\t', '  '])
@pytest.mark.parametrize('heater,valid', [('extruder', True), ('Missing', False)])
def test_deferred_fan_references_include_every_loaded_header(validator, family, separator, heater, valid):
    lookup_objects = pinned_method(KLIPPER / 'klippy.py', 'Printer', 'lookup_objects')
    handle_connect = pinned_method(KLIPPER / 'extras/controller_fan.py', 'ControllerFan', 'handle_connect')
    calls = []

    def lookup_heater(name):
        calls.append(name)
        if name != 'extruder':
            raise ValueError('Unknown heater ' + name)
        return object()

    heaters = SimpleNamespace(lookup_heater=lookup_heater)
    printer = SimpleNamespace(objects={}, lookup_object=lambda name: heaters if name == 'heaters' else None)
    printer.lookup_objects = lambda module=None: lookup_objects(printer, module)
    fan = SimpleNamespace(heater_names=[heater])
    if family == 'controller_fan':
        fan.printer = printer
        fan.stepper_names = None
        fan.stepper_enable = SimpleNamespace(get_steppers=lambda: [])
        fan.handle_connect = lambda: handle_connect(fan)
    printer.objects[family + separator + 'Audit'] = fan
    if valid:
        validator.validate_fan_references(printer)
    else:
        with pytest.raises(ValueError, match='Unknown heater'):
            validator.validate_fan_references(printer)
    assert calls == [heater]


def test_unrelated_loaded_objects_are_not_treated_as_fans(validator):
    lookup_objects = pinned_method(KLIPPER / 'klippy.py', 'Printer', 'lookup_objects')
    printer = SimpleNamespace(objects={'other\tAudit': object()}, lookup_object=Mock())
    printer.lookup_objects = lambda module=None: lookup_objects(printer, module)
    validator.validate_fan_references(printer)
    printer.lookup_object.assert_not_called()
