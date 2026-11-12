"""Static review/write gates and pinned scan Z approach; no hardware or E2E."""
import ast
import math
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.bed_mesh import validate_mesh_clearance
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.pin_validator import _read_pin_config
from tests.klipper_contract import KLIPPER_REF
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_effective_xy_geometry import _generate, _context, _assert_no_destination_mutations


def eddy_mesh(height=None):
    text = ("[probe_eddy_current sensor]\nx_offset: 0\ny_offset: 0\n"
            "[bed_mesh]\nmesh_min: 30,30\nmesh_max: 200,200\n")
    if height is not None:
        text += f"horizontal_move_z: {height}\n"
    return text.encode()


def destination(content, source, height):
    if source == "include":
        return {"printer.cfg": content + b"\n[include user.cfg]\n",
                "user.cfg": b"[include nested.cfg]\n", "nested.cfg": eddy_mesh(height)}
    if source == "save":
        return {"printer.cfg": content + b"\n" + eddy_mesh() + (
            "\n#*# <---------------------- SAVE_CONFIG ---------------------->\n"
            "#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.\n#*#\n"
            f"#*# [bed_mesh]\n#*# horizontal_move_z = {height}\n").encode()}
    return {"printer.cfg": content + b"\n" + eddy_mesh(height)}


@pytest.mark.parametrize("source", ["root", "include", "save"])
@pytest.mark.parametrize("noop", [False, True])
def test_effective_eddy_height_rejects_before_confirmation_and_writes(tmp_path, source, noop):
    content = _generate(tmp_path, probe="None")
    context = _context(tmp_path, content)
    remote = destination(content, source, "250")
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    effective = _read_pin_config(effective_hardware_text(plan))[0]
    assert "probe_eddy_current sensor" in effective
    assert effective["bed_mesh"]["horizontal_move_z"] == "250"
    if noop:
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        plan = build_managed_config_plan(content, None, remote, geometry_context=context)
        assert not plan.changed_artifacts
    validation = validate_configuration_plan(plan)
    assert not validation.valid
    assert all(e.code == "mesh-clearance" and "rapid_scan" in e.message for e in validation.errors)
    transport = FakeTransport(remote)
    before = dict(transport.files)
    confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(
        transport, content, None, activation="none", geometry_context=context,
        confirm=confirm, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path / "snapshots"),
    ).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "rapid_scan" in result.detail
    confirm.assert_not_called()
    _assert_no_destination_mutations(transport, before)


@pytest.mark.parametrize("source", ["root", "include", "save"])
def test_effective_eddy_approach_boundary_can_be_published(tmp_path, source):
    content = _generate(tmp_path, probe="None")
    context = _context(tmp_path, content)
    remote = destination(content, source, "249.5")
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    assert "probe_eddy_current sensor" in _read_pin_config(effective_hardware_text(plan))[0]
    assert validate_configuration_plan(plan).valid
    transport = FakeTransport(remote)
    confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(
        transport, content, None, activation="none", geometry_context=context,
        confirm=confirm, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path / "snapshots"),
    ).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    assert confirm.called
    effective = effective_hardware_text(build_managed_config_plan(
        content, None, transport.files, geometry_context=context))
    assert _read_pin_config(effective)[0]["bed_mesh"]["horizontal_move_z"] == "249.5"


def test_review_callback_cannot_approve_invalid_eddy_clearance(tmp_path):
    content = _generate(tmp_path, probe="None")
    context = _context(tmp_path, content)
    transport = FakeTransport(destination(content, "include", "250"))
    before = dict(transport.files)
    review = Mock(return_value=True)
    result = ConfigDeploymentTransaction(
        transport, content, None, activation="none", geometry_context=context,
        review=review, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path / "snapshots"),
    ).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "rapid_scan" in result.detail
    assert review.called
    assert not review.call_args.args[0].validation.valid
    _assert_no_destination_mutations(transport, before)


def test_postrender_eddy_height_rejects_before_overwriting_cfg_and_sidecar(tmp_path, monkeypatch):
    import core.generator as generator
    original = generator._postprocess_generated_output
    monkeypatch.setattr(generator, "_postprocess_generated_output",
                        lambda text: original(text) + "\n" + eddy_mesh("250").decode())
    target = tmp_path / "printer.cfg"
    sidecar = tmp_path / "printer.cfg.provenance.json"
    target.write_bytes(b"existing cfg")
    sidecar.write_bytes(b"existing sidecar")
    with pytest.raises(GenerationError, match="rapid_scan"):
        _generate(tmp_path, probe="None")
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
        ns = namespace or {}
        path = root / relative
        tree = ast.parse(path.read_text(encoding="utf-8"))
        nodes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name in names]
        assert {n.name for n in nodes} == set(names)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), ns)
        return ns
    scanner = extract("klippy/extras/bed_mesh.py", ["RapidScanHelper"])["RapidScanHelper"]
    command = extract("klippy/gcode.py", ["CommandError", "GCodeCommand"])["GCodeCommand"]
    kinematics = extract("klippy/kinematics/corexy.py", ["CoreXYKinematics"])["CoreXYKinematics"]
    return scanner, command, kinematics


@pytest.mark.parametrize("height,allowed", [(299.499999, True), (299.5, True), (299.500001, False), (300., False)])
def test_kace_decision_matches_pinned_default_scan_approach(official, height, allowed):
    scanner, command_cls, kin_cls = official
    kin = kin_cls.__new__(kin_cls)
    kin.limits = [(0., 235.), (0., 235.), (0., 300.)]
    kin.max_z_velocity, kin.max_z_accel = 15., 100.
    position, captured = [30., 30., 0., 0.], []
    def move(coord, speed):
        target = position[:]
        for index, value in enumerate(coord):
            if value is not None:
                target[index] = value
        captured.append(target[:])
        delta = [b-a for a,b in zip(position, target)]
        movement = SimpleNamespace(end_pos=target, axes_d=delta,
            move_d=math.sqrt(sum(d*d for d in delta[:3])),
            move_error=lambda message="Move out of range": ValueError(message),
            limit_speed=lambda *args: None)
        kin.check_move(movement)
        position[:] = target
    tool = SimpleNamespace(get_position=lambda:position[:], manual_move=move, dwell=lambda _:None)
    probe = SimpleNamespace(get_probe_params=lambda cmd:{"lift_speed":5., "probe_speed":5.})
    helper = scanner.__new__(scanner)
    helper.scan_height = height
    helper.printer = SimpleNamespace(lookup_object=lambda name: {"toolhead":tool, "probe":probe}[name])
    gcmd = command_cls(SimpleNamespace(respond_info=lambda *args:None, respond_raw=lambda *args:None),
                       "BED_MESH_CALIBRATE", "BED_MESH_CALIBRATE", {"SAMPLE_TIME":".02"}, False)
    cfg = {"bed_mesh":{"horizontal_move_z":str(height)}, "probe_eddy_current sensor":{},
           "stepper_z":{"position_min":"0", "position_max":"300"}}
    if allowed:
        validate_mesh_clearance(cfg)
        helper._raise_tool(gcmd, height)
        helper._move_to_scan_height(gcmd, height)
        assert max(p[2] for p in captured) == pytest.approx(height + .5)
        assert position[2] == height
    else:
        with pytest.raises(ValueError, match="Move out of range"):
            helper._raise_tool(gcmd, height)
        assert captured[0][2] == pytest.approx(height + .5)
        with pytest.raises(GenerationError, match="rapid_scan"):
            validate_mesh_clearance(cfg)

