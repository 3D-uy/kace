"""Starter macro render-time guards and managed publication boundaries.

Modal execution is independently checked against official GCodeMove by the K05
evidence harness; these tests do not substitute a homemade movement interpreter.
"""
import configparser
from pathlib import Path

import jinja2
import pytest

from core.macro_generator import generate_starter_macros
from core.generator import generate_config
from core.managed_config import build_managed_config_plan, MACROS_REMOTE
from tests.unit.test_generator import _parsed, _user

NAMES = ("TEST_EXTRUDER", "LOAD_FILAMENT", "UNLOAD_FILAMENT")


def scripts(text):
    cfg = configparser.RawConfigParser()
    cfg.read_string(text)
    return {n: cfg.get("gcode_macro " + n, "gcode") for n in NAMES}


def render(script, *, hot=True, factor=1., limit=50., active="extruder", **ignored):
    def fail(msg):
        raise ValueError(msg)
    printer = {"toolhead": {"extruder": active}, "extruder": {"can_extrude": hot},
        "gcode_move": {"extrude_factor": factor},
        "configfile": {"settings": {"extruder": {"max_extrude_only_distance": limit}}}}
    return jinja2.Environment('{%', '%}', '{', '}').from_string(script).render(
        printer=printer, action_raise_error=fail)


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("settings,reason", [({"hot": False}, "temperature"),
    ({"limit": 49.99}, "max_extrude_only_distance"), ({"factor": 1.01}, "max_extrude_only_distance"),
    ({"active": ""}, "active extruder"), ({"factor": float("nan")}, "max_extrude_only_distance")])
def test_detectable_errors_abort_render_before_any_commands(tmp_path, name, settings, reason):
    text = Path(generate_starter_macros(str(tmp_path))).read_text(encoding="utf-8")
    with pytest.raises(ValueError, match=reason):
        render(scripts(text)[name], **settings)


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("factor,limit", [(1., 50.), (.5, 25.), (1.5, 75.)])
def test_valid_exact_limit_preserves_distance_feed_and_isolated_state(tmp_path, name, factor, limit):
    text = Path(generate_starter_macros(str(tmp_path))).read_text(encoding="utf-8")
    commands = [l.strip() for l in render(scripts(text)[name], factor=factor, limit=limit).splitlines() if l.strip()]
    state = "KACE_" + name
    distance, feed = (-50 if name == "UNLOAD_FILAMENT" else 50), (100 if name == "TEST_EXTRUDER" else 300)
    assert commands == [f"SAVE_GCODE_STATE NAME={state}", "M83", f"G1 E{distance} F{feed}",
                        f"RESTORE_GCODE_STATE NAME={state} MOVE=0"]


@pytest.mark.parametrize("choice", ["include_macros", "checkpoint"])
def test_generation_entry_points_publish_new_macros_and_resume_noop(tmp_path, choice):
    hardware = generate_config(_parsed(), _user(macros_generated=choice == "checkpoint"),
        include_macros=choice == "include_macros", output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"].encode()
    macros = (tmp_path / "macros.cfg").read_bytes()
    old = b"[gcode_macro LOAD_FILAMENT]\ngcode:\n G91\n G1 E50 F300\n G90\n"
    remote = {"printer.cfg": hardware, MACROS_REMOTE: old}
    plan = build_managed_config_plan(hardware, macros, remote)
    assert next(a.content for a in plan.changed_artifacts if a.remote_name == MACROS_REMOTE) == macros
    remote.update({a.remote_name: a.content for a in plan.artifacts})
    assert not build_managed_config_plan(hardware, macros, remote).changed_artifacts


def test_existing_user_macros_are_explicitly_outside_automatic_replacement(tmp_path):
    hardware = generate_config(_parsed(), _user(), output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"].encode()
    macros = Path(generate_starter_macros(str(tmp_path))).read_bytes()
    old = b"[gcode_macro LOAD_FILAMENT]\ngcode:\n G91\n G1 E50 F300\n G90\n"
    remote = {"printer.cfg": hardware + b"\n[include macros.cfg]\n", "macros.cfg": old}
    plan = build_managed_config_plan(hardware, macros, remote)
    assert not any(a.remote_name in ("macros.cfg", MACROS_REMOTE) for a in plan.artifacts)
    assert any("user-owned" in w for w in plan.warnings)
    assert remote["macros.cfg"] == old
