"""Effective includes must retain the geometry guarantees of generation."""
from dataclasses import replace
import json
from unittest.mock import Mock

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.config_geometry import load_geometry_context
from core.configuration_review import (
    build_configuration_review, render_configuration_review, validate_configuration_plan,
)
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.pin_validator import _read_pin_config
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_generator import _parsed, _user


INVALID_OVERRIDES = [
    pytest.param(
        "[bed_mesh]\nmesh_min: 300,300\nmesh_max: 400,400\n",
        False, "mesh", id="mesh-outside-travel",
    ),
    pytest.param(
        "[safe_z_home]\nhome_xy_position: 999,999\n",
        False, "home", id="home-outside-travel",
    ),
    pytest.param(
        "[bltouch]\nx_offset: 500\n",
        False, "probe", id="probe-offset-drift",
    ),
    pytest.param(
        "[stepper_x]\nposition_max: 50\n",
        False, "x", id="travel-shrunk",
    ),
    pytest.param(
        "[z_tilt]\nz_positions: 0,0\n 235,235\npoints: 999,999\n 1000,1000\n",
        True, "z_tilt", id="leveling-outside-travel",
    ),
]

VALID_OVERRIDES = [
    pytest.param("", False, id="unchanged-geometry"),
    pytest.param(
        "[bltouch]\nx_offset: 20\n"
        "[bed_mesh]\nmesh_min: 30,10\nmesh_max: 215,225\n"
        "[safe_z_home]\nhome_xy_position: 100,100\n",
        False, id="positive-probe-offset",
    ),
    pytest.param(
        "[bltouch]\nx_offset: -20\n"
        "[bed_mesh]\nmesh_min: 10,10\nmesh_max: 205,225\n"
        "[safe_z_home]\nhome_xy_position: 120,120\n",
        False, id="negative-probe-offset",
    ),
    pytest.param(
        "[bltouch]\ny_offset: 20\n"
        "[bed_mesh]\nmesh_min: 10,30\nmesh_max: 225,215\n"
        "[safe_z_home]\nhome_xy_position: 100,100\n",
        False, id="positive-y-probe-offset",
    ),
    pytest.param(
        "[bltouch]\ny_offset: -20\n"
        "[bed_mesh]\nmesh_min: 10,10\nmesh_max: 225,205\n"
        "[safe_z_home]\nhome_xy_position: 120,120\n",
        False, id="negative-y-probe-offset",
    ),
    pytest.param(
        "[stepper_x]\nposition_max: 50\n"
        "[bed_mesh]\nmesh_min: 10,10\nmesh_max: 40,225\n"
        "[safe_z_home]\nhome_xy_position: 25,100\n",
        False, id="consistent-reduced-travel",
    ),
    pytest.param(
        "[z_tilt]\nz_positions: -30,100\n 265,100\npoints: 20,20\n 210,210\n",
        True, id="leveling-with-off-bed-pivots",
    ),
]


def _generate(tmp_path, *, two_z=False, z_count=None, **values):
    sections = {"bltouch": {"sensor_pin": "^PB8", "control_pin": "PB9"}}
    z_count = z_count or (2 if two_z else 1)
    for index in range(1, z_count):
        sections[f"stepper_z{index}"] = {
            "step_pin": f"PF{index * 3 - 2}", "dir_pin": f"PF{index * 3 - 1}",
            "enable_pin": f"PF{index * 3}",
        }
    user = _user(
        probe="BLTouch", z_motors=str(z_count),
        printable_x_min="0", printable_x_max="235",
        printable_y_min="0", printable_y_max="235",
    )
    user.update(values)
    return generate_config(
        _parsed(**sections), user, output_path=str(tmp_path / "printer.cfg"), verbose=False,
    )["content"].encode()


def _context(tmp_path, content):
    context = load_geometry_context(tmp_path / "printer.cfg", content)
    assert context is not None
    return context


def _destination(content, override, *, noop=False, geometry_context=None):
    remote = {
        "printer.cfg": content + b"\n[include user.cfg]\n",
        "user.cfg": b"[include nested.cfg]\n",
        "nested.cfg": override.encode(),
    }
    if noop:
        plan = build_managed_config_plan(content, None, remote, geometry_context=geometry_context)
        remote.update({artifact.remote_name: artifact.content for artifact in plan.artifacts})
        assert not build_managed_config_plan(
            content, None, remote, geometry_context=geometry_context,
        ).changed_artifacts
    return remote


@pytest.mark.parametrize("override,two_z,error_subject", INVALID_OVERRIDES)
def test_effective_xy_review_rejects_inconsistent_includes(tmp_path, override, two_z, error_subject):
    content = _generate(tmp_path, two_z=two_z)
    plan = build_managed_config_plan(
        content, None, _destination(content, override), geometry_context=_context(tmp_path, content),
    )

    validation = validate_configuration_plan(plan)

    assert not validation.valid
    assert any(error_subject in error.message.casefold() for error in validation.errors)


@pytest.mark.parametrize("override,two_z,error_subject", INVALID_OVERRIDES)
@pytest.mark.parametrize("noop", [False, True], ids=["publish", "noop"])
@pytest.mark.parametrize("activation", ["none", "firmware"])
def test_inconsistent_xy_blocks_before_writes_or_activation(
    tmp_path, override, two_z, error_subject, noop, activation,
):
    content = _generate(tmp_path, two_z=two_z)
    context = _context(tmp_path, content)
    transport = FakeTransport(_destination(content, override, noop=noop, geometry_context=context))
    before = dict(transport.files)
    confirm = Mock(return_value=True)
    events = []

    result = ConfigDeploymentTransaction(
        transport, content, None, activation=activation, confirm=confirm,
        output=lambda _: None, snapshot_root=str(tmp_path / "snapshots"),
        poll_interval=0, state_sink=lambda state, detail: events.append(state),
        geometry_context=context,
    ).run()

    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "semantic configuration validation failed" in result.detail
    assert error_subject in result.detail.casefold()
    confirm.assert_not_called()
    assert result.snapshot is None
    assert transport.files == before
    assert not any(
        call[0] in ("upload", "delete", "restart", "restart_moonraker")
        for call in transport.calls
    )
    assert "DONE" not in events


@pytest.mark.parametrize("override,two_z", VALID_OVERRIDES)
def test_consistent_effective_geometry_is_preserved_and_published(tmp_path, override, two_z):
    content = _generate(tmp_path, two_z=two_z)
    context = _context(tmp_path, content)
    remote = _destination(content, override)
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    expected = _read_pin_config(effective_hardware_text(plan))[0]
    assert validate_configuration_plan(plan).valid
    transport = FakeTransport(remote)

    result = ConfigDeploymentTransaction(
        transport, content, None, activation="none", confirm=lambda _: True,
        output=lambda _: None, snapshot_root=str(tmp_path / "snapshots"), poll_interval=0,
        geometry_context=context,
    ).run()

    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    assert transport.files["nested.cfg"] == override.encode()
    after = build_managed_config_plan(content, None, transport.files, geometry_context=context)
    assert _read_pin_config(effective_hardware_text(after))[0] == expected
    assert not after.changed_artifacts
    assert any(call[0] == "upload" for call in transport.calls)
    assert not any(call[0] in ("restart", "restart_moonraker") for call in transport.calls)


def test_same_impossible_offset_is_rejected_at_generation(tmp_path):
    with pytest.raises(GenerationError, match="Probeable X area"):
        _generate(tmp_path, probe_x_offset="500")
    assert not (tmp_path / "printer.cfg").exists()
    assert not (tmp_path / "printer.cfg.provenance.json").exists()


def test_physical_homing_without_probe_remains_valid(tmp_path):
    content = generate_config(
        _parsed(), _user(), output_path=str(tmp_path / "printer.cfg"), verbose=False,
    )["content"].encode()
    plan = build_managed_config_plan(content, None, {"printer.cfg": None})
    assert validate_configuration_plan(plan).valid
    sections = _read_pin_config(effective_hardware_text(plan))[0]
    assert "bed_mesh" not in sections
    assert "safe_z_home" not in sections


def _assert_no_destination_mutations(transport, before):
    assert transport.files == before
    assert not any(
        call[0] in ("upload", "delete", "restart", "restart_moonraker")
        for call in transport.calls
    )


@pytest.mark.parametrize("provenance", ["missing", "legacy"])
def test_missing_bound_bed_provenance_blocks_without_writes(tmp_path, provenance):
    content = _generate(tmp_path)
    sidecar = tmp_path / "printer.cfg.provenance.json"
    if provenance == "missing":
        sidecar.unlink()
    else:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        payload.pop("geometry")
        sidecar.write_text(json.dumps(payload), encoding="utf-8")
    context = load_geometry_context(tmp_path / "printer.cfg", content)
    assert context is None
    transport = FakeTransport(_destination(content, ""))
    before = dict(transport.files)
    confirm = Mock(return_value=True)

    result = ConfigDeploymentTransaction(
        transport, content, None, geometry_context=context, activation="firmware",
        confirm=confirm, output=lambda _: None, snapshot_root=str(tmp_path / "snapshots"),
        poll_interval=0,
    ).run()

    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "provenance" in result.detail
    confirm.assert_not_called()
    assert result.snapshot is None
    _assert_no_destination_mutations(transport, before)


@pytest.mark.parametrize("provenance", ["malformed", "stale-hash"])
def test_sidecar_reader_rejects_invalid_provenance(tmp_path, provenance):
    content = _generate(tmp_path)
    sidecar = tmp_path / "printer.cfg.provenance.json"
    if provenance == "malformed":
        sidecar.write_text("{invalid-json", encoding="utf-8")
    else:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        payload["geometry"]["source_sha256"] = "0" * 64
        sidecar.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="XY geometry provenance"):
        load_geometry_context(tmp_path / "printer.cfg", content)
    assert (tmp_path / "printer.cfg").read_bytes() == content


@pytest.mark.parametrize("provenance", ["malformed", "stale-hash"])
def test_invalid_context_cannot_enter_publication(tmp_path, provenance):
    content = _generate(tmp_path)
    context = _context(tmp_path, content)
    context = (replace(context, printable_x_max=float("nan")) if provenance == "malformed"
               else replace(context, source_sha256="0" * 64))
    transport = FakeTransport(_destination(content, ""))
    before = dict(transport.files)
    confirm = Mock(return_value=True)

    result = ConfigDeploymentTransaction(
        transport, content, None, geometry_context=context, activation="firmware",
        confirm=confirm, output=lambda _: None, snapshot_root=str(tmp_path / "snapshots"),
        poll_interval=0,
    ).run()

    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "provenance" in result.detail
    confirm.assert_not_called()
    assert result.snapshot is None
    _assert_no_destination_mutations(transport, before)


def test_manual_mesh_without_probe_uses_nozzle_coordinates(tmp_path):
    content = _generate(tmp_path, probe="None")
    context = _context(tmp_path, content)
    override = (
        "[bed_mesh]\nmesh_min: 10,10\nmesh_max: 225,225\n"
        "probe_count: 5,5\nalgorithm: bicubic\n"
    )
    remote = _destination(content, override)
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    sections = _read_pin_config(effective_hardware_text(plan))[0]
    assert "probe" not in sections and "bltouch" not in sections
    assert sections["bed_mesh"]["mesh_max"] == "225,225"
    assert validate_configuration_plan(plan).valid
    transport = FakeTransport(remote)

    result = ConfigDeploymentTransaction(
        transport, content, None, geometry_context=context, activation="none",
        confirm=lambda _: True, output=lambda _: None,
        snapshot_root=str(tmp_path / "snapshots"), poll_interval=0,
    ).run()

    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    assert transport.files["nested.cfg"] == override.encode()


@pytest.mark.parametrize("radius,valid", [
    pytest.param("80", True, id="within-bed"),
    pytest.param("117.59", True, id="klipper-tenth-mm-radius-floor"),
    pytest.param("120", False, id="outside-bed"),
])
def test_preserved_manual_circular_mesh_uses_effective_radius_and_bed(tmp_path, radius, valid):
    content = _generate(tmp_path, probe="None")
    context = _context(tmp_path, content)
    override = (
        f"[bed_mesh]\nmesh_radius: {radius}\nmesh_origin: 117.5,117.5\n"
        "round_probe_count: 5\nalgorithm: bicubic\n"
    )
    remote = _destination(content, override)
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    validation = validate_configuration_plan(plan)
    transport = FakeTransport(remote)
    before = dict(transport.files)
    confirm = Mock(return_value=True)

    result = ConfigDeploymentTransaction(
        transport, content, None, geometry_context=context, activation="none",
        confirm=confirm, output=lambda _: None,
        snapshot_root=str(tmp_path / "snapshots"), poll_interval=0,
    ).run()

    if valid:
        assert validation.valid, validation.errors
        assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
        assert transport.files["nested.cfg"] == override.encode()
    else:
        assert not validation.valid
        assert any("bed_mesh" in error.message for error in validation.errors)
        assert result.state == ConfigTransactionState.PRECONDITION_FAILED
        assert result.snapshot is None
        confirm.assert_not_called()
        _assert_no_destination_mutations(transport, before)


@pytest.mark.parametrize("outside_bed", [False, True], ids=["on-bed", "off-bed"])
def test_manual_z_tilt_checks_bed_in_addition_to_nozzle_travel(tmp_path, outside_bed):
    content = _generate(tmp_path, two_z=True, probe="None", printable_x_max="200")
    context = _context(tmp_path, content)
    points = "220,100\n 230,100" if outside_bed else "10,100\n 190,100"
    override = f"[z_tilt]\nz_positions: -30,100\n 265,100\npoints: {points}\n"
    remote = _destination(content, override)
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    validation = validate_configuration_plan(plan)
    transport = FakeTransport(remote)
    before = dict(transport.files)

    result = ConfigDeploymentTransaction(
        transport, content, None, geometry_context=context, activation="none",
        confirm=lambda _: True, output=lambda _: None,
        snapshot_root=str(tmp_path / "snapshots"), poll_interval=0,
    ).run()

    if outside_bed:
        assert not validation.valid
        assert any("z_tilt" in error.message and "on bed" in error.message
                   for error in validation.errors)
        assert result.state == ConfigTransactionState.PRECONDITION_FAILED
        _assert_no_destination_mutations(transport, before)
    else:
        assert validation.valid
        assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
        assert transport.files["nested.cfg"] == override.encode()


@pytest.mark.parametrize("offset,points", [
    pytest.param("20", "10,20\n 210,210", id="positive-probe-offset"),
    pytest.param("-20", "30,20\n 230,210", id="negative-probe-offset"),
])
def test_z_tilt_points_remain_nozzle_coordinates_with_probe_offsets(tmp_path, offset, points):
    content = _generate(tmp_path, two_z=True, probe_x_offset=offset)
    context = _context(tmp_path, content)
    override = f"[z_tilt]\nz_positions: -30,100\n 265,100\npoints: {points}\n"
    remote = _destination(content, override)
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    validation = validate_configuration_plan(plan)
    assert validation.valid
    transport = FakeTransport(remote)

    result = ConfigDeploymentTransaction(
        transport, content, None, geometry_context=context, activation="none",
        confirm=lambda _: True, output=lambda _: None,
        snapshot_root=str(tmp_path / "snapshots"), poll_interval=0,
    ).run()

    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    assert transport.files["nested.cfg"] == override.encode()


@pytest.mark.parametrize("invalid_second_point", [False, True])
def test_qgl_reviews_every_nozzle_point_but_allows_external_corners(tmp_path, invalid_second_point):
    content = _generate(tmp_path, z_count=4, kinematics="corexy")
    context = _context(tmp_path, content)
    second = "999,210" if invalid_second_point else "20,210"
    override = (
        "[quad_gantry_level]\ngantry_corners: -60,-10\n 295,325\n"
        f"points: 20,20\n {second}\n 210,210\n 210,20\n"
    )
    remote = _destination(content, override)
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    validation = validate_configuration_plan(plan)
    transport = FakeTransport(remote)
    before = dict(transport.files)
    confirm = Mock(return_value=True)

    result = ConfigDeploymentTransaction(
        transport, content, None, geometry_context=context, activation="none",
        confirm=confirm, output=lambda _: None, snapshot_root=str(tmp_path / "snapshots"),
        poll_interval=0,
    ).run()

    if invalid_second_point:
        assert not validation.valid
        assert any("quad_gantry_level" in error.message and "#2" in error.message
                   for error in validation.errors)
        assert result.state == ConfigTransactionState.PRECONDITION_FAILED
        confirm.assert_not_called()
        _assert_no_destination_mutations(transport, before)
    else:
        assert validation.valid
        assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
        assert transport.files["nested.cfg"] == override.encode()


@pytest.mark.parametrize("points", [
    pytest.param("20,20\n 20,210\n 210,210", id="three-points"),
    pytest.param("20,20\n 20,210\n 210,210\n 210,20\n 100,100", id="five-points"),
    pytest.param("20,20\n 30,210\n 210,200\n 20,30", id="zero-x03"),
    pytest.param("20,20\n 210,210\n 210,200\n 200,30", id="zero-x12"),
    pytest.param("20,20\n 30,20\n 210,210\n 200,30", id="zero-y01"),
    pytest.param("20,20\n 210,20\n 210,210\n 20,210", id="old-generated-order"),
])
def test_singular_qgl_in_include_rejects_before_approval_or_writes(tmp_path, points):
    content = _generate(tmp_path, z_count=4, kinematics="corexy")
    context = _context(tmp_path, content)
    remote = _destination(content,
        "[quad_gantry_level]\ngantry_corners: -60,-10\n 295,325\n"
        f"points: {points}\n")
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    validation = validate_configuration_plan(plan)
    assert not validation.valid
    assert any("quad_gantry_level" in error.message for error in validation.errors)
    transport = FakeTransport(remote)
    before = dict(transport.files)
    confirm = Mock(return_value=True)

    result = ConfigDeploymentTransaction(
        transport, content, None, geometry_context=context, activation="none",
        confirm=confirm, output=lambda _: None, snapshot_root=str(tmp_path / "snapshots"),
        poll_interval=0,
    ).run()

    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    _assert_no_destination_mutations(transport, before)


@pytest.mark.parametrize("offset", ["-15", "15"])
def test_qgl_review_accepts_non_rectangular_non_singular_points(tmp_path, offset):
    content = _generate(tmp_path, z_count=4, kinematics="corexy", probe_x_offset=offset)
    context = _context(tmp_path, content)
    override = ("[quad_gantry_level]\ngantry_corners: -60,-10\n 295,325\n"
                "points: 20,20\n 30,210\n 210,200\n 200,30\n")
    plan = build_managed_config_plan(content, None, _destination(content, override),
                                    geometry_context=context)
    assert validate_configuration_plan(plan).valid


@pytest.mark.parametrize("saved_offset", ["0", "500"])
def test_saved_probe_offset_is_used_for_effective_xy_review(tmp_path, saved_offset):
    content = _generate(tmp_path)
    context = _context(tmp_path, content)
    saved = (
        "\n#*# <---------------------- SAVE_CONFIG ---------------------->\n"
        f"#*# [bltouch]\n#*# x_offset = {saved_offset}\n"
    ).encode()
    remote = {"printer.cfg": content.replace(b"x_offset: 0", b"#x_offset: 0") + saved}
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    sections = _read_pin_config(effective_hardware_text(plan))[0]
    assert sections["bltouch"]["x_offset"] == saved_offset
    validation = validate_configuration_plan(plan)
    transport = FakeTransport(remote)
    before = dict(transport.files)
    confirm = Mock(return_value=True)

    result = ConfigDeploymentTransaction(
        transport, content, None, geometry_context=context, activation="none",
        confirm=confirm, output=lambda _: None, snapshot_root=str(tmp_path / "snapshots"),
        poll_interval=0,
    ).run()

    if saved_offset == "500":
        assert not validation.valid
        assert result.state == ConfigTransactionState.PRECONDITION_FAILED
        confirm.assert_not_called()
        _assert_no_destination_mutations(transport, before)
    else:
        assert validation.valid
        assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
        assert transport.files["printer.cfg"].endswith(saved)


def test_valid_noop_still_verifies_firmware_and_loaded_configuration(tmp_path):
    content = _generate(tmp_path)
    context = _context(tmp_path, content)
    transport = FakeTransport(_destination(content, "", noop=True, geometry_context=context))
    before = dict(transport.files)
    verify_firmware = Mock()
    events = []

    result = ConfigDeploymentTransaction(
        transport, content, None, geometry_context=context, activation="firmware",
        confirm=lambda _: True, output=lambda _: None, snapshot_root=str(tmp_path / "snapshots"),
        poll_interval=0, verify_existing_ready=True, verify_firmware=verify_firmware,
        state_sink=lambda state, detail: events.append(state),
    ).run()

    assert result.state == ConfigTransactionState.COMMITTED
    verify_firmware.assert_called_once_with()
    assert ("verify_active_configuration",) in transport.calls
    assert "DONE" in events
    _assert_no_destination_mutations(transport, before)


def test_external_edit_during_confirmation_is_preserved_without_publication(tmp_path):
    content = _generate(tmp_path)
    context = _context(tmp_path, content)
    transport = FakeTransport(_destination(content, ""))
    external = b"[safe_z_home]\nhome_xy_position: 999,999\n"
    before = dict(transport.files)
    before["nested.cfg"] = external

    def confirm(_diff):
        transport.files["nested.cfg"] = external
        return True

    result = ConfigDeploymentTransaction(
        transport, content, None, geometry_context=context, activation="firmware",
        confirm=confirm, output=lambda _: None, snapshot_root=str(tmp_path / "snapshots"),
        poll_interval=0,
    ).run()

    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert result.snapshot is None
    _assert_no_destination_mutations(transport, before)


def test_invalid_postrender_home_preserves_previous_cfg_and_provenance(tmp_path, monkeypatch):
    import core.generator as generator

    _generate(tmp_path)
    cfg = tmp_path / "printer.cfg"
    sidecar = tmp_path / "printer.cfg.provenance.json"
    before = cfg.read_bytes(), sidecar.read_bytes()
    original = generator._postprocess_generated_output
    monkeypatch.setattr(
        generator, "_postprocess_generated_output",
        lambda text: original(text) + "\n[safe_z_home]\nhome_xy_position: 999,999\n",
    )

    with pytest.raises(GenerationError, match="home_xy_position"):
        _generate(tmp_path)

    assert (cfg.read_bytes(), sidecar.read_bytes()) == before


@pytest.mark.parametrize("field,value", [
    ("probe_x_offset", "nan"),
    ("probe_y_offset", "inf"),
    ("x_position_max", "nan"),
    ("printable_y_min", "-inf"),
])
def test_nonfinite_generation_geometry_is_rejected_without_defaulting_or_writes(tmp_path, field, value):
    _generate(tmp_path)
    cfg = tmp_path / "printer.cfg"
    sidecar = tmp_path / "printer.cfg.provenance.json"
    before = cfg.read_bytes(), sidecar.read_bytes()

    with pytest.raises(GenerationError, match=field):
        _generate(tmp_path, **{field: value})

    assert (cfg.read_bytes(), sidecar.read_bytes()) == before


def test_explicit_shifted_bed_retains_its_origin_through_publication(tmp_path):
    content = _generate(
        tmp_path, x_size="220", y_size="220",
        x_position_min="-30", x_position_max="270", x_position_endstop="-30",
        y_position_min="-20", y_position_max="280", y_position_endstop="-20",
        printable_x_min="-10", printable_x_max="210",
        printable_y_min="20", printable_y_max="240",
        probe_x_offset="-10", probe_y_offset="15",
    )
    context = _context(tmp_path, content)
    assert (context.printable_x_min, context.printable_x_max) == (-10, 210)
    assert (context.printable_y_min, context.printable_y_max) == (20, 240)
    remote = {"printer.cfg": None}
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    assert validate_configuration_plan(plan).valid
    sections = _read_pin_config(effective_hardware_text(plan))[0]
    assert sections["bed_mesh"]["mesh_min"] == "0.0, 30.0"
    assert sections["bed_mesh"]["mesh_max"] == "200.0, 230.0"
    assert sections["safe_z_home"]["home_xy_position"] == "110, 115"
    transport = FakeTransport(remote)

    result = ConfigDeploymentTransaction(
        transport, content, None, geometry_context=context, activation="none",
        confirm=lambda _: True, output=lambda _: None,
        snapshot_root=str(tmp_path / "snapshots"), poll_interval=0,
    ).run()

    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    after = build_managed_config_plan(content, None, transport.files, geometry_context=context)
    assert _read_pin_config(effective_hardware_text(after))[0] == sections


@pytest.mark.parametrize("language,localized_heading", [
    ("Español", "Revisá la geometría XY efectiva"),
    ("Português", "Revise a geometria XY efetiva"),
])
def test_localized_review_retains_offending_xy_section_value_and_range(tmp_path, language, localized_heading):
    content = _generate(tmp_path)
    override = "[safe_z_home]\nhome_xy_position: 999,999\n"
    plan = build_managed_config_plan(
        content, None, _destination(content, override), geometry_context=_context(tmp_path, content),
    )
    review = build_configuration_review(plan)

    text = render_configuration_review(review, language=language, color=False)

    assert not review.validation.valid
    assert localized_heading in text
    assert "[safe_z_home] home_xy_position" in text
    assert "X=999" in text
    assert "[0, 235]" in text
