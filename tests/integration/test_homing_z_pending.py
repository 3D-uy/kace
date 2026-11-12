"""Effective homing review rejects invalid plans before writes; pinned constructors."""
import ast
import importlib.util
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.homing_source import validate_safe_z_hop
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.pin_validator import _read_pin_config
from core.probe_configuration import validate_probe_homing_geometry
from tests.klipper_contract import KLIPPER_REF
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_effective_xy_geometry import _generate, _context, _assert_no_destination_mutations


INVALID = [
    ("[safe_z_home]\nspeed: 0\n", "speed"),
    ("[safe_z_home]\nz_hop: 0\nz_hop_speed: 0\n", "z_hop_speed"),
    ("[safe_z_home]\nspeed: nan\n", "speed"),
    ("[safe_z_home]\nz_hop_speed: inf\n", "z_hop_speed"),
    ("[stepper_z]\nhoming_positive_dir: nope\n", "homing_positive_dir"),
    ("[stepper_z]\nposition_min: 0\nhoming_positive_dir: True\n", "homing_positive_dir"),
    ("[stepper_z]\nhoming_positive_dir: False\n[bltouch]\nz_offset: 250\n"
     "[bed_mesh]\nhorizontal_move_z: 250\n", "homing_positive_dir"),
]


@pytest.mark.parametrize("override,reason", INVALID)
@pytest.mark.parametrize("noop", [False, True])
def test_effective_homing_rejects_before_confirmation_and_writes(tmp_path, override, reason, noop):
    content = _generate(tmp_path)
    context = _context(tmp_path, content)
    remote = {"printer.cfg": content + b"\n[include user.cfg]\n",
              "user.cfg": b"[include nested.cfg]\n", "nested.cfg": override.encode()}
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    if noop:
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        plan = build_managed_config_plan(content, None, remote, geometry_context=context)
        assert not plan.changed_artifacts
    validation = validate_configuration_plan(plan)
    assert not validation.valid
    assert all(reason in e.message for e in validation.errors)
    transport = FakeTransport(remote)
    before = dict(transport.files)
    confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, content, None, geometry_context=context,
        activation="none", confirm=confirm, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path / "snapshots")).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    _assert_no_destination_mutations(transport, before)


@pytest.mark.parametrize("override", [
    "[safe_z_home]\nz_hop: 0\nspeed: 0.001\nz_hop_speed: 50.125\n",
    "[stepper_z]\nhoming_positive_dir: True\n",
])
def test_compatible_homing_can_still_be_published(tmp_path, override):
    content = _generate(tmp_path)
    context = _context(tmp_path, content)
    remote = {"printer.cfg": content + b"\n[include user.cfg]\n", "user.cfg": override.encode()}
    assert validate_configuration_plan(build_managed_config_plan(content, None, remote, geometry_context=context)).valid
    transport = FakeTransport(remote)
    result = ConfigDeploymentTransaction(transport, content, None, geometry_context=context,
        activation="none", confirm=lambda _: True, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path / "snapshots")).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION


@pytest.mark.parametrize("override,reason", INVALID)
def test_postrender_invalid_homing_preserves_cfg_and_sidecar(tmp_path, monkeypatch, override, reason):
    import core.generator as generator
    original = generator._postprocess_generated_output
    monkeypatch.setattr(generator, "_postprocess_generated_output",
                        lambda text: original(text) + "\n" + override)
    target = tmp_path / "printer.cfg"
    sidecar = tmp_path / "printer.cfg.provenance.json"
    target.write_bytes(b"existing CFG")
    sidecar.write_bytes(b"existing provenance")
    with pytest.raises(GenerationError, match=reason):
        _generate(tmp_path)
    assert target.read_bytes() == b"existing CFG"
    assert sidecar.read_bytes() == b"existing provenance"


@pytest.fixture(scope="module")
def official():
    root = Path(os.environ.get("KACE_KLIPPER_SOURCE",
        Path(__file__).resolve().parents[2] / ".klipper-contract-source"))
    if not root.is_dir():
        pytest.skip("Pinned Klipper source required")
    assert subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip() == KLIPPER_REF
    assert not subprocess.check_output(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"], text=True).strip()
    spec = importlib.util.spec_from_file_location("homing_contract_configfile", root / "klippy/configfile.py")
    configfile = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(configfile)
    namespace = {}
    for path, name in [("klippy/stepper.py", "GenericPrinterRail"), ("klippy/extras/safe_z_home.py", "SafeZHoming")]:
        source = root / path
        tree = ast.parse(source.read_text(encoding="utf-8"))
        nodes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name]
        assert len(nodes) == 1
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
    namespace["manual_probe"] = SimpleNamespace(lookup_z_endstop_config=lambda cfg: cfg.getsection("stepper_z"))
    class Printer:
        config_error = ValueError
        def __init__(self, offset): self.offset = offset
        def lookup_object(self, name):
            if name == "pins":
                return SimpleNamespace(parse_pin=lambda *a: {"chip_name":"probe", "pin":"z_virtual_endstop", "invert":False, "pullup":False},
                    setup_pin=lambda *a: SimpleNamespace(get_position_endstop=lambda: self.offset))
            if name == "gcode":
                return SimpleNamespace(register_command=lambda *a: None)
        def load_object(self, *args):
            return SimpleNamespace(register_endstop=lambda *a: None)
    def load(text, kind, offset=0.):
        fc = configfile.ConfigFileReader().build_fileconfig_with_includes(text, str(root / "audit-not-written.cfg"))
        section = "safe_z_home" if kind == "safe" else "stepper_z"
        cfg = configfile.ConfigWrapper(Printer(offset), fc, {}, section)
        return namespace["SafeZHoming" if kind == "safe" else "GenericPrinterRail"](cfg)
    return load


@pytest.mark.parametrize("option,value", [("speed", "0"), ("z_hop_speed", "0"), ("speed", "-1")])
def test_safe_home_positive_speed_bounds_match_pinned_constructor(official, option, value):
    text = f"[stepper_z]\nposition_max: 250\n[safe_z_home]\nhome_xy_position: 100,100\nz_hop: 0\n{option}: {value}\n"
    with pytest.raises(Exception, match=option + ".*above"):
        official(text, "safe")
    with pytest.raises(GenerationError, match=option):
        validate_safe_z_hop(_read_pin_config(text)[0])


@pytest.mark.parametrize("offset,direction,accepted", [
    (0., "True", False), (250., "False", False), (0., "nope", False),
    (0., "False", True), (250., "True", True), (125., None, False),
    (125., "True", True), (125., "False", True), (62.5, None, True), (187.5, None, True),
])
def test_virtual_z_direction_matches_pinned_rail(official, offset, direction, accepted):
    text = "[stepper_z]\nendstop_pin: probe:z_virtual_endstop\nposition_min: 0\nposition_max: 250\n"
    if direction is not None:
        text += f"homing_positive_dir: {direction}\n"
    sections = _read_pin_config(text)[0]
    sections["bltouch"] = {"z_offset": str(offset)}
    if accepted:
        official(text, "rail", offset)
        validate_probe_homing_geometry(sections)
    else:
        with pytest.raises(Exception, match="homing_positive_dir"):
            official(text, "rail", offset)
        with pytest.raises(GenerationError, match="homing_positive_dir"):
            validate_probe_homing_geometry(sections)

