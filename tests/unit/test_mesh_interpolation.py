"""Rectangular mesh selection and effective configuration compatibility."""
import copy
from unittest.mock import Mock

import pytest

from core.bed_mesh import generate_bed_mesh_config
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.configuration_review import validate_configuration_plan
from core.motion_model import PrinterMotionSpace
from core.pin_validator import _read_pin_config
from tests.unit.test_generator import _parsed, _user


def generated(tmp_path, mesh=None, **choices):
    board = _parsed(bltouch={"sensor_pin": "^PB8", "control_pin": "PB9"}, bed_mesh=mesh or {})
    return generate_config(board, _user(probe="BLTouch", **choices),
        output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]


@pytest.mark.parametrize("x,y,counts", [(80, 350, "4, 7"), (350, 80, "7, 4"),
    (80, 80, "3, 3"), (120, 350, "4, 7"), (235, 235, "5, 5"), (350, 350, "7, 7")])
@pytest.mark.parametrize("probe", ["BLTouch", "CR-Touch", "Inductive"])
def test_auto_counts_preserve_area_and_never_reduce_sampling(x, y, counts, probe):
    user = {"x_size": str(x), "y_size": str(y), "probe": probe}
    result = generate_bed_mesh_config(PrinterMotionSpace(user), user, {})
    assert result["probe_count"] == counts
    assert result["mesh_min"] == "10.0, 10.0"
    assert result["mesh_max"] == f"{x-10:.1f}, {y-10:.1f}"
    assert result["algorithm"] == ("lagrange" if counts == "3, 3" else "bicubic")


@pytest.mark.parametrize("counts,algorithm,pps,effective", [
    ("3, 6", "lagrange", "2", "lagrange"), ("6, 3", "bicubic", "2", "lagrange"),
    ("4, 7", "bicubic", "2, 0", "bicubic"), ("7, 4", "bicubic", "0, 2", "bicubic"),
    ("3, 7", "lagrange", "0", "direct"), ("7, 3", "bicubic", "0, 0", "direct"),
    ("6", " LAGRANGE ", "1, 3", "lagrange"), ("4", "bicubic", "2", "bicubic")])
def test_explicit_compatible_settings_are_preserved(tmp_path, counts, algorithm, pps, effective):
    from core.bed_mesh import validate_mesh_interpolation
    text = generated(tmp_path, {"probe_count": counts, "algorithm": algorithm, "mesh_pps": pps})
    section = _read_pin_config(text)[0]["bed_mesh"]
    pair = counts.split(",") if "," in counts else [counts, counts]
    assert section["probe_count"] == ", ".join(v.strip() for v in pair)
    assert section["algorithm"] == algorithm.strip().lower()
    assert validate_mesh_interpolation({"bed_mesh": section}) == effective
    assert section["mesh_pps"] == (pps if "," in pps else f"{pps}, {pps}")


INVALID = [
    {"probe_count": "3, 7", "algorithm": "lagrange"},
    {"probe_count": "7, 3", "algorithm": "bicubic"},
    {"probe_count": "7, 6", "algorithm": "lagrange"},
    {"probe_count": "3, 7", "mesh_pps": "0, 2"},
    {"algorithm": "direct", "mesh_pps": "0"},
    {"algorithm": "unknown"}, {"probe_count": "2, 5"}, {"probe_count": "3, 4, 5"},
    {"probe_count": "3.0, 4"}, {"probe_count": ""}, {"probe_count": None},
    {"mesh_pps": "-1, 2"}, {"mesh_pps": "0,"}, {"mesh_pps": "bad"},
    {"bicubic_tension": "2.1"}, {"bicubic_tension": "-0.1"}, {"bicubic_tension": "nan"},
]


@pytest.mark.parametrize("mesh", INVALID)
def test_invalid_explicit_settings_do_not_replace_output(tmp_path, mesh):
    target = tmp_path / "printer.cfg"
    target.write_bytes(b"existing user configuration")
    with pytest.raises(GenerationError, match="bed_mesh"):
        generated(tmp_path, mesh)
    assert target.read_bytes() == b"existing user configuration"
    assert not (tmp_path / "printer.cfg.provenance.json").exists()


def test_profile_checkpoint_and_switch_do_not_use_old_interpolation(tmp_path):
    import json
    from core.firmware_workflow import persistable_wizard_data
    profile = {"bed_mesh": {"probe_count": "6, 3", "algorithm": "lagrange", "mesh_pps": "1"}}
    before = copy.deepcopy(profile)
    user = json.loads(json.dumps(persistable_wizard_data(_user(probe="BLTouch", _profile_parsed=profile))))
    board = _parsed(bltouch={"sensor_pin": "^PB8", "control_pin": "PB9"}, bed_mesh={"probe_count": "9"})
    text = generate_config(board, user, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    assert _read_pin_config(text)[0]["bed_mesh"]["probe_count"] == "6, 3"
    user["_profile_parsed"] = {}
    text = generate_config(board, user, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    assert _read_pin_config(text)[0]["bed_mesh"]["probe_count"] == "5, 5"
    assert profile == before


@pytest.mark.parametrize("source", ["root", "managed", "include"])
def test_existing_interpolation_survives_and_second_plan_is_noop(tmp_path, source):
    text = generated(tmp_path).encode()
    old = text.replace(b"probe_count: 5, 5", b"probe_count: 6, 3").replace(b"algorithm: bicubic", b"algorithm: lagrange")
    if source == "root":
        remote = {"printer.cfg": old}
    elif source == "managed":
        remote = {"printer.cfg": b"[mcu]\nserial: /tmp/klipper\n[include kace/generated-hardware.cfg]\n",
                  "kace/generated-hardware.cfg": old}
    else:
        remote = {"printer.cfg": text + b"\n[include user.cfg]\n",
                  "user.cfg": b"[bed_mesh]\nprobe_count: 6, 3\nalgorithm: lagrange\n"}
    plan = build_managed_config_plan(text, None, remote)
    section = _read_pin_config(effective_hardware_text(plan))[0]["bed_mesh"]
    assert section["probe_count"] == "6, 3" and section["algorithm"] == "lagrange"
    assert validate_configuration_plan(plan).valid
    remote.update({a.remote_name: a.content for a in plan.artifacts})
    assert not build_managed_config_plan(text, None, remote).changed_artifacts


@pytest.mark.parametrize("noop", [False, True])
@pytest.mark.parametrize("options", INVALID[:5] + [{
    "probe_count": "3, 3", "mesh_min": "0, 0", "mesh_max": "1.99, 100", "mesh_pps": "0"}])
def test_invalid_nested_include_blocks_before_confirmation(tmp_path, noop, options):
    from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
    from tests.unit.test_config_transaction import FakeTransport
    text = generated(tmp_path).encode()
    remote = {"printer.cfg": text + b"\n[include user.cfg]\n", "user.cfg": b"[include nested.cfg]\n",
        "nested.cfg": ("[bed_mesh]\n" + "\n".join(f"{k}: {v}" for k, v in options.items())).encode()}
    if noop:
        plan = build_managed_config_plan(text, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(text, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    before = dict(transport.files)
    result = ConfigDeploymentTransaction(transport, text, None, activation="none", confirm=confirm,
        output=lambda _: None, snapshot_root=str(tmp_path / "snapshots"), poll_interval=0).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED and "bed_mesh" in result.detail
    confirm.assert_not_called()
    assert transport.files == before
    assert not any(c[0] in ("upload", "delete", "restart", "restart_moonraker") for c in transport.calls)


@pytest.mark.parametrize("x,y,offsets", [(80, 350, {"probe_x_offset": "79.96"}),
                                      (350, 80, {"probe_y_offset": "79.96"})])
def test_unrepresentable_narrow_area_is_rejected(tmp_path, x, y, offsets):
    with pytest.raises(GenerationError, match="mesh"):
        generated(tmp_path, x_size=str(x), y_size=str(y), **offsets)
    assert not (tmp_path / "printer.cfg").exists()


def test_post_render_algorithm_is_checked_before_write(tmp_path, monkeypatch):
    import core.generator as generator
    original = generator._postprocess_generated_output
    monkeypatch.setattr(generator, "_postprocess_generated_output", lambda text:
        original(text).replace("algorithm: bicubic", "algorithm: unknown"))
    with pytest.raises(GenerationError, match="bed_mesh"):
        generated(tmp_path)
    assert not (tmp_path / "printer.cfg").exists()


def test_explicit_large_count_with_unspecified_algorithm_selects_bicubic(tmp_path):
    section = _read_pin_config(generated(tmp_path, {"probe_count": "7"}))[0]["bed_mesh"]
    assert section["probe_count"] == "7, 7" and section["algorithm"] == "bicubic"


@pytest.mark.parametrize("count,effective", [("3", "lagrange"), ("7", "bicubic")])
def test_preserved_circular_counts_are_checked_without_enabling_generation(tmp_path, count, effective):
    from core.bed_mesh import validate_mesh_interpolation
    mesh = {"mesh_radius": "40", "round_probe_count": count, "algorithm": "bicubic"}
    assert validate_mesh_interpolation({"bed_mesh": mesh}) == effective
    with pytest.raises(GenerationError, match="circular mesh generation"):
        generated(tmp_path, mesh)


def test_invalid_existing_tuple_is_not_replaced_with_an_auto_choice(tmp_path):
    text = generated(tmp_path).encode()
    old = text.replace(b"probe_count: 5, 5", b"probe_count: 3, 7")
    plan = build_managed_config_plan(text, None, {"printer.cfg": old})
    assert _read_pin_config(effective_hardware_text(plan))[0]["bed_mesh"]["probe_count"] == "3, 7"
    assert any(e.code == "mesh-interpolation" for e in validate_configuration_plan(plan).errors)


@pytest.mark.parametrize("width,error", [("2.9", "minimum spacing"),
    ("2.99", "formatted mesh bounds"), ("3", None), ("3.01", None)])
@pytest.mark.parametrize("transpose", [False, True])
def test_minimum_spacing_on_narrow_long_beds(tmp_path, width, error, transpose):
    dimensions = {"x_size": "350" if transpose else width, "y_size": width if transpose else "350"}
    if error is None:
        generated(tmp_path, **dimensions)
    else:
        with pytest.raises(GenerationError, match=error):
            generated(tmp_path, **dimensions)


@pytest.mark.parametrize("pps", ["0", "2"])
def test_interpolation_disabled_does_not_disable_probe_spacing_check(pps):
    from core.bed_mesh import validate_mesh_interpolation
    with pytest.raises(GenerationError, match="minimum spacing"):
        validate_mesh_interpolation({"bed_mesh": {"probe_count": "3, 3", "mesh_pps": pps,
            "mesh_min": "0, 0", "mesh_max": "1.99, 100"}})
