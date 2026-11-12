"""Active leveling Z settings must be reviewed before publication, not only XY."""
import ast
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.pin_validator import _read_pin_config
from tests.klipper_contract import KLIPPER_REF
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_effective_xy_geometry import _generate, _context, _assert_no_destination_mutations


SECTIONS = ("z_tilt", "quad_gantry_level")


def leveling_text(section, height=None, speed=None):
    if section == "z_tilt":
        points = "z_positions: 0,0\n 235,235\npoints: 20,20\n 210,210\n"
    else:
        points = ("gantry_corners: 0,0\n 235,235\npoints: 20,20\n"
                  " 20,210\n 210,210\n 210,20\n")
    text = f"[{section}]\n{points}"
    if height is not None:
        text += f"horizontal_move_z: {height}\n"
    if speed is not None:
        text += f"speed: {speed}\n"
    return text.encode()


def destination(content, section, source, height):
    if source == "include":
        return {"printer.cfg": content + b"\n[include user.cfg]\n",
                "user.cfg": b"[include nested.cfg]\n",
                "nested.cfg": leveling_text(section, height)}
    if source == "save":
        return {"printer.cfg": content + b"\n" + leveling_text(section) + (
            "\n#*# <---------------------- SAVE_CONFIG ---------------------->\n"
            "#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.\n#*#\n"
            f"#*# [{section}]\n#*# horizontal_move_z = {height}\n").encode()}
    return {"printer.cfg": content + b"\n" + leveling_text(section, height)}


def generate(tmp_path, section):
    content = _generate(tmp_path, z_count=2 if section == "z_tilt" else 4)
    return content, _context(tmp_path, content)


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("source", ["root", "include", "save"])
@pytest.mark.parametrize("noop", [False, True])
def test_outside_leveling_height_rejects_before_confirmation_and_writes(tmp_path, section, source, noop):
    content, context = generate(tmp_path, section)
    remote = destination(content, section, source, "250.001")
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    assert _read_pin_config(effective_hardware_text(plan))[0][section]["horizontal_move_z"] == "250.001"
    if noop:
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        plan = build_managed_config_plan(content, None, remote, geometry_context=context)
        assert not plan.changed_artifacts
    validation = validate_configuration_plan(plan)
    assert not validation.valid
    assert all(e.code == "leveling-clearance" for e in validation.errors)
    transport = FakeTransport(remote)
    before = dict(transport.files)
    confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(
        transport, content, None, activation="none", geometry_context=context,
        confirm=confirm, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path / "snapshots"),
    ).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    _assert_no_destination_mutations(transport, before)


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("source", ["root", "include", "save"])
def test_leveling_height_at_maximum_can_be_published(tmp_path, section, source):
    content, context = generate(tmp_path, section)
    remote = destination(content, section, source, "250")
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    assert validate_configuration_plan(plan).valid
    transport = FakeTransport(remote)
    result = ConfigDeploymentTransaction(
        transport, content, None, activation="none", geometry_context=context,
        confirm=Mock(return_value=True), output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path / "snapshots"),
    ).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    actual = effective_hardware_text(build_managed_config_plan(
        content, None, transport.files, geometry_context=context))
    assert _read_pin_config(actual)[0][section]["horizontal_move_z"] == "250"


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("option,value", [
    ("horizontal_move_z", "nan"), ("horizontal_move_z", "1"),
    ("speed", "0"), ("speed", "nan"),
])
def test_active_scalar_and_probe_offset_constraints_are_reviewed(tmp_path, section, option, value):
    content, context = generate(tmp_path, section)
    extra = leveling_text(section) + f"{option}: {value}\n".encode()
    if value == "1":
        extra += b"[bltouch]\nz_offset: 2\n"
    remote = {"printer.cfg": content + b"\n[include user.cfg]\n", "user.cfg": extra}
    validation = validate_configuration_plan(build_managed_config_plan(
        content, None, remote, geometry_context=context))
    assert not validation.valid
    assert all(e.code == "leveling-clearance" for e in validation.errors)


@pytest.mark.parametrize("section", SECTIONS)
def test_invalid_review_acceptance_cannot_override_leveling_error(tmp_path, section):
    content, context = generate(tmp_path, section)
    remote = destination(content, section, "include", "250.001")
    transport = FakeTransport(remote)
    before = dict(transport.files)
    review = Mock(return_value=True)
    result = ConfigDeploymentTransaction(
        transport, content, None, activation="none", geometry_context=context,
        review=review, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path / "snapshots"),
    ).run()
    assert review.called
    assert not review.call_args.args[0].validation.valid
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    _assert_no_destination_mutations(transport, before)


@pytest.mark.parametrize("section", SECTIONS)
def test_postrender_rejects_leveling_before_cfg_and_sidecar_write(tmp_path, monkeypatch, section):
    import core.generator as generator
    original = generator._postprocess_generated_output
    monkeypatch.setattr(generator, "_postprocess_generated_output",
                        lambda text: original(text) + "\n" + leveling_text(section, "250.001").decode())
    target = tmp_path / "printer.cfg"
    sidecar = tmp_path / "printer.cfg.provenance.json"
    target.write_bytes(b"existing cfg")
    sidecar.write_bytes(b"existing sidecar")
    with pytest.raises(GenerationError, match="horizontal_move_z"):
        generate(tmp_path, section)
    assert target.read_bytes() == b"existing cfg"
    assert sidecar.read_bytes() == b"existing sidecar"


@pytest.fixture(scope="module")
def official():
    root = Path(os.environ.get("KACE_KLIPPER_SOURCE",
        Path(__file__).resolve().parents[2] / ".klipper-contract-source"))
    if not root.is_dir():
        pytest.skip("Pinned Klipper source required")
    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()
    assert git("rev-parse", "HEAD") == KLIPPER_REF
    assert not git("status", "--porcelain", "--untracked-files=no")
    def extract(relative, names, namespace=None):
        ns = {} if namespace is None else namespace
        path = root / relative
        tree = ast.parse(path.read_text(encoding="utf-8"))
        nodes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name in names]
        assert {n.name for n in nodes} == set(names)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), ns)
        return ns
    helper = extract("klippy/extras/probe.py", ["ProbePointsHelper"],
        {"manual_probe": SimpleNamespace(verify_no_manual_probe=lambda p: None)})["ProbePointsHelper"]
    command = extract("klippy/gcode.py", ["CommandError", "GCodeCommand"])["GCodeCommand"]
    return helper, command


@pytest.mark.parametrize("section", SECTIONS)
def test_leveling_uses_exact_height_without_rapid_scan_extra_lift(official, section):
    # Both upstream leveling modules instantiate ProbePointsHelper. Its first
    # lift targets the exact configured height, not the eddy-only +0.5 route.
    from core.leveling import validate_leveling_clearance
    helper_cls, _ = official
    moves = []
    helper = helper_cls.__new__(helper_cls)
    helper.horizontal_move_z, helper.lift_speed, helper.speed = 250., 5., 50.
    helper.printer = SimpleNamespace(lookup_object=lambda name:
        SimpleNamespace(manual_move=lambda pos, speed: moves.append((pos, speed))))
    validate_leveling_clearance({section: {"horizontal_move_z": "250"},
        "stepper_z": {"position_max": "250"}, "probe_eddy_current sensor": {}})
    helper._raise_tool(True)
    assert moves == [([None, None, 250.], 50.)]


@pytest.mark.parametrize("section", SECTIONS)
def test_default_automatic_probe_rejects_height_below_probe_offset(official, section):
    from core.leveling import validate_leveling_clearance
    helper_cls, command_cls = official
    helper = helper_cls.__new__(helper_cls)
    helper.default_horizontal_move_z = 1.
    probe = SimpleNamespace(get_probe_params=lambda g: {"lift_speed": 5.},
                            get_offsets=lambda g: (0., 0., 2.))
    helper.printer = SimpleNamespace(lookup_object=lambda *args: probe)
    gcmd = command_cls(SimpleNamespace(respond_info=lambda *a: None, respond_raw=lambda *a: None),
                      "LEVEL", "LEVEL", {}, False)
    with pytest.raises(gcmd.error, match="less than"):
        helper.start_probe(gcmd)
    with pytest.raises(GenerationError, match="z_offset"):
        validate_leveling_clearance({section: {"horizontal_move_z": "1"},
                                     "bltouch": {"z_offset": "2"}})

