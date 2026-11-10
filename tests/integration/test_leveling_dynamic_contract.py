"""Pinned dynamic leveling semantics: observations, not physical guarantees.

Unmodified upstream classes run with external-device doubles. These tests do
not add KACE command restrictions or replace a full Klipper load.
"""
import ast
import importlib.util
import logging
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.klipper_contract import KLIPPER_REF


@pytest.fixture(scope="module")
def pinned():
    source = Path(os.environ.get("KACE_KLIPPER_SOURCE", Path(__file__).resolve().parents[2] / ".klipper-contract-source"))
    if not source.is_dir():
        pytest.skip("Pinned Klipper checkout required")
    assert subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip() == KLIPPER_REF
    assert not subprocess.check_output(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"], text=True).strip()
    scope = {"logging": logging}
    for relative, names in (
        ("klippy/extras/z_tilt.py", {"RetryHelper", "ZAdjustHelper"}),
        ("klippy/extras/quad_gantry_level.py", {"QuadGantryLevel"}),
        ("klippy/extras/probe.py", {"ProbeParameterHelper", "ProbePointsHelper"}),
    ):
        path = source / relative
        tree = ast.parse(path.read_text(encoding="utf-8"))
        nodes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name in names]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), scope)
    for name, relative in (("config", "klippy/configfile.py"), ("gcode", "klippy/gcode.py")):
        spec = importlib.util.spec_from_file_location("leveling_dynamic_" + name, source / relative)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        scope[name] = module
    return SimpleNamespace(**scope)


def command(pinned, params=None):
    return pinned.gcode.GCodeCommand(Mock(), "AUDIT", "AUDIT", params or {}, False)


def config(pinned, text, section="z_tilt"):
    gcode = Mock()
    gcode.create_gcode_command.return_value = command(pinned)
    printer = SimpleNamespace(lookup_object=lambda *args: gcode)
    parser = pinned.config.ConfigFileReader().build_fileconfig_with_includes(
        f"[{section}]\n{text}", "unused-audit.cfg",
    )
    return pinned.config.ConfigWrapper(printer, parser, {}, section)


def test_configured_retry_defaults_do_not_inherit_explicit_command_caps(pinned):
    helper = pinned.RetryHelper(config(pinned, "retries: 31\nretry_tolerance: 2"))
    helper.start(command(pinned))
    assert helper.max_retries == 31
    assert helper.retry_tolerance == 2
    for params in ({"RETRIES": "31"}, {"RETRY_TOLERANCE": "2"}):
        with pytest.raises(pinned.gcode.CommandError):
            helper.start(command(pinned, params))


def test_retry_zero_tolerance_has_distinct_config_default_and_command_contracts(pinned):
    helper = pinned.RetryHelper(config(pinned, ""))
    helper.start(command(pinned, {"RETRY_TOLERANCE": "0"}))
    assert helper.retry_tolerance == 0
    with pytest.raises(pinned.config.error, match="above"):
        pinned.RetryHelper(config(pinned, "retry_tolerance: 0"))


@pytest.mark.parametrize("spread,expected", [(0.0100004, "done"), (0.0100006, "retry")])
def test_retry_tolerance_compares_rounded_probed_spread(pinned, spread, expected):
    helper = pinned.RetryHelper(config(pinned, ""))
    helper.start(command(pinned, {"RETRIES": "2", "RETRY_TOLERANCE": "0.01"}))
    assert helper.check_retry([0, spread]) == expected


def test_retry_count_is_additional_rounds_after_initial_probing(pinned):
    helper = pinned.RetryHelper(config(pinned, "retries: 2\nretry_tolerance: 0.01"))
    helper.gcode.error = ValueError
    helper.start(command(pinned))
    assert helper.check_retry([0, 0.2]) == "retry"
    assert helper.check_retry([0, 0.2]) == "retry"
    with pytest.raises(ValueError, match="Too many retries"):
        helper.check_retry([0, 0.2])


def qgl(pinned, heights, height=5):
    obj = pinned.QuadGantryLevel.__new__(pinned.QuadGantryLevel)
    obj.horizontal_move_z = height
    obj.gantry_corners = [(0, 0), (100, 100)]
    obj.max_adjust = 4
    obj.gcode = Mock(error=ValueError)
    obj.probe_helper = Mock()
    obj.probe_helper.get_lift_speed.return_value = 7
    obj.z_helper = Mock()
    obj.retry_helper = Mock()
    obj.z_status = Mock()
    positions = [SimpleNamespace(bed_x=x, bed_y=y, bed_z=z) for (x, y), z in
                 zip([(0, 0), (0, 100), (100, 100), (100, 0)], heights)]
    return obj, positions


@pytest.mark.parametrize("heights", [[-6, 2, 2, 2], [-12, 4, 4, 4]])
def test_qgl_max_adjust_bounds_positive_not_absolute_correction(pinned, heights):
    obj, positions = qgl(pinned, heights)
    obj.probe_finalize(positions)
    assert obj.z_helper.adjust_steppers.call_args.args == (heights, 7)
    assert abs(min(heights)) > obj.max_adjust
    inverse, inverse_positions = qgl(pinned, [-z for z in heights])
    with pytest.raises(ValueError, match="max_adjust"):
        inverse.probe_finalize(inverse_positions)
    inverse.z_helper.adjust_steppers.assert_not_called()


def test_qgl_configured_height_constant_cancels_from_corrections(pinned):
    outputs = []
    for height in (5, 20):
        obj, positions = qgl(pinned, [-6, 2, 2, 2], height)
        obj.probe_finalize(positions)
        outputs.append(obj.z_helper.adjust_steppers.call_args.args)
    assert outputs[0] == outputs[1] == ([-6, 2, 2, 2], 7)


@pytest.mark.parametrize("initial,maximum,adjustments,expected_peak,reject", [
    (250, 250, [0, 0, 0, 0], 250, False),
    (250, 250, [-0.5, 0.5, 0.5, -0.5], 251, True),
    (5, 10, [-6, 2, 2, 2], 13, True),
    (5, 20, [-6, 2, 2, 2], 13, False),
])
def test_measured_adjustments_can_exceed_declared_z_and_restore_stepper_queues(
        pinned, initial, maximum, adjustments, expected_peak, reject):
    requested = []
    tool = Mock()
    tool.get_position.return_value = [0, 0, initial, 0]
    tool.get_trapq.return_value = "trapq"
    def move(position, speed):
        requested.append((position[2], speed))
        if position[2] > maximum:
            raise ValueError("simulated declared Z maximum exceeded")
    tool.move.side_effect = move
    obj = pinned.ZAdjustHelper.__new__(pinned.ZAdjustHelper)
    obj.z_steppers = [Mock() for _ in adjustments]
    obj.printer = SimpleNamespace(lookup_object=lambda name: tool if name == "toolhead" else Mock())
    if reject:
        with pytest.raises(ValueError, match="simulated"):
            obj.adjust_steppers(adjustments, 7)
    else:
        obj.adjust_steppers(adjustments, 7)
    assert max(z for z, speed in requested) == expected_peak
    assert all(speed == 7 for z, speed in requested)
    for stepper in obj.z_steppers:
        assert stepper.set_trapq.call_args.args == ("trapq",)


def test_provider_lift_speed_override_and_first_move_speed_are_distinct(pinned):
    params = pinned.ProbeParameterHelper(config(pinned, "speed: 4\nlift_speed: 7", "probe"))
    assert params.get_probe_params(command(pinned))["lift_speed"] == 7
    assert params.get_probe_params(command(pinned, {"LIFT_SPEED": "11"}))["lift_speed"] == 11
    helper = pinned.ProbePointsHelper.__new__(pinned.ProbePointsHelper)
    helper.horizontal_move_z = 5
    helper.speed = 50
    helper.lift_speed = 11
    helper._move = Mock()
    helper._raise_tool(True)
    helper._raise_tool(False)
    assert [call.args for call in helper._move.call_args_list] == [
        ([None, None, 5], 50), ([None, None, 5], 11),
    ]
