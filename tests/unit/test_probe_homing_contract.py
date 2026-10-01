"""Probe availability is independent of the physical Z homing switch."""
import pytest
import re

from core.configuration_review import build_configuration_review, validate_configuration_plan
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_config_transaction import FakeTransport
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState


PROBES = {
    "probe": "[probe]\npin: ^PC0\nz_offset: 1\n",
    "bltouch": "[bltouch]\nsensor_pin: ^PC0\ncontrol_pin: PC4\nz_offset: 1\n",
}
MESH = "[bed_mesh]\nmesh_min: 20,20\nmesh_max: 200,200\nprobe_count: 3,3\n"
SAFE = "[safe_z_home]\nhome_xy_position: 100,100\n"


@pytest.fixture
def base(tmp_path):
    return generate_config(_parsed(), _user(), output_path=str(tmp_path / "base.cfg"), verbose=False)["content"]


def plan(text, remote=None):
    return build_managed_config_plan(text.encode(), None, remote or {})


def virtual(text):
    def replace_z(match):
        body = match.group().replace("endstop_pin: PB2", "endstop_pin: probe:z_virtual_endstop")
        return re.sub(r"(?m)^position_endstop:.*\n", "", body)
    return re.sub(r"(?ms)^\[stepper_z\].*?(?=^\[|\Z)", replace_z, text)


@pytest.mark.parametrize("kind", PROBES)
@pytest.mark.parametrize("safe", [False, True])
def test_virtual_homing_with_probe_remains_valid(base, kind, safe):
    text = virtual(base) + "\n" + PROBES[kind] + MESH + (SAFE if safe else "") + "# PROBE_CALIBRATE\n"
    assert validate_configuration_plan(plan(text)).valid


def test_virtual_probe_still_requires_calibration_guidance(base):
    text = virtual(base) + "\n" + PROBES["probe"]
    assert "probe-calibration-missing" in {e.code for e in validate_configuration_plan(plan(text)).errors}


@pytest.mark.parametrize("kind", PROBES)
@pytest.mark.parametrize("safe", [False, True])
@pytest.mark.parametrize("guide", [False, True])
def test_physical_homing_and_mesh_probe_are_independent(base, kind, safe, guide):
    text = base + "\n" + PROBES[kind] + MESH + (SAFE if safe else "")
    if guide:
        text += "# PROBE_CALIBRATE\n"
    review = build_configuration_review(plan(text))
    assert review.validation.valid, review.validation.errors
    summary = " ".join(item.text for item in review.summary)
    assert "probe Z offset" in summary
    assert "physical Z endstop" in summary


@pytest.mark.parametrize("kind", PROBES)
def test_nested_preserved_probe_and_noop_plan(base, kind):
    remote = {"printer.cfg": (base + "\n[include user.cfg]\n").encode(),
              "user.cfg": b"[include sensor.cfg]\n", "sensor.cfg": PROBES[kind].encode()}
    first = plan(base, remote)
    assert validate_configuration_plan(first).valid
    for artifact in first.artifacts:
        remote[artifact.remote_name] = artifact.content
    again = plan(base, remote)
    assert not again.changed_artifacts
    review = build_configuration_review(again)
    assert review.validation.valid
    assert any("probe Z offset" in item.text for item in review.summary)


@pytest.mark.parametrize("kind", PROBES)
@pytest.mark.parametrize("noop", [False, True])
def test_publication_preserves_mesh_probe_with_physical_homing(base, kind, noop, tmp_path):
    remote = {"printer.cfg": (base + "\n[include user.cfg]\n").encode(),
              "user.cfg": b"[include sensor.cfg]\n", "sensor.cfg": (PROBES[kind] + MESH).encode()}
    if noop:
        remote.update({a.remote_name: a.content for a in plan(base, remote).artifacts})
    transport = FakeTransport(remote)
    result = ConfigDeploymentTransaction(transport, base.encode(), None,
        activation="none", confirm=lambda _: True, verify_existing_ready=noop,
        snapshot_root=str(tmp_path / "snapshots"), poll_interval=0).run()
    expected = (ConfigTransactionState.COMMITTED if noop
                else ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION)
    assert result.state == expected, result
    assert not any(call[0] == "restart" for call in transport.calls)
    assert any(call[0] == "upload" for call in transport.calls) is not noop
    assert transport.files["sensor.cfg"] == remote["sensor.cfg"]
    assert transport.files["user.cfg"] == remote["user.cfg"]


@pytest.mark.parametrize("extra", ["", "[probe other]\npin: PC0\nz_offset: 1\n"])
def test_virtual_endstop_without_supported_probe_remains_blocked(base, extra):
    text = base.replace("endstop_pin: PB2", "endstop_pin: probe:z_virtual_endstop") + "\n" + extra
    errors = validate_configuration_plan(plan(text)).errors
    assert "probe-z-endstop" in {e.code for e in errors}


def test_probe_calibration_without_probe_remains_blocked(base):
    errors = validate_configuration_plan(plan(base + "\n# PROBE_CALIBRATE\n")).errors
    assert "probe-calibration-extra" in {e.code for e in errors}


def test_physical_endstop_still_requires_own_guidance(base):
    text = base.replace("Z_ENDSTOP_CALIBRATE", "removed") + "\n" + PROBES["probe"] + "# PROBE_CALIBRATE\n"
    assert "endstop-calibration-missing" in {e.code for e in validate_configuration_plan(plan(text)).errors}


def test_probe_cannot_share_physical_endstop_gpio(base):
    text = base + "\n" + PROBES["probe"].replace("PC0", "PB2")
    assert "probe-pin-conflict" in {e.code for e in validate_configuration_plan(plan(text)).errors}


def test_safe_z_home_does_not_override_composition_guard(base):
    text = base + "\n" + PROBES["probe"] + SAFE + "[homing_override]\ngcode: G28\n"
    assert "homing-composition" in {e.code for e in validate_configuration_plan(plan(text)).errors}


def test_commented_virtual_endstop_does_not_change_summary(base):
    review = build_configuration_review(plan(base + "\n# endstop_pin: probe:z_virtual_endstop\n"))
    summary = " ".join(item.text for item in review.summary)
    assert "physical Z endstop" in summary
    assert "probe Z offset" not in summary


# Klipper pins.py strips whitespace on either side of the chip separator.
VIRTUAL_TOKENS = ("probe:z_virtual_endstop", "probe: z_virtual_endstop",
                  "probe :z_virtual_endstop", "probe\t:\tz_virtual_endstop")


@pytest.mark.parametrize("token", VIRTUAL_TOKENS)
def test_generation_missing_probe_blocks_before_artifacts(tmp_path, token):
    from core.exceptions import GenerationError
    parsed = _parsed()
    parsed["stepper_z"]["endstop_pin"] = token
    with pytest.raises(GenerationError, match="requires a generated probe"):
        generate_config(parsed, _user(), output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("token", VIRTUAL_TOKENS)
@pytest.mark.parametrize("kind", PROBES)
def test_spaced_virtual_pin_with_probe_is_valid_and_summary_is_virtual(base, token, kind):
    text = virtual(base).replace("probe:z_virtual_endstop", token)
    text += "\n" + PROBES[kind] + "# PROBE_CALIBRATE\n"
    review = build_configuration_review(plan(text))
    assert review.validation.valid, review.validation.errors
    summary = " ".join(item.text for item in review.summary)
    assert "probe Z offset" in summary
    assert "physical Z endstop" not in summary


@pytest.mark.parametrize("token", VIRTUAL_TOKENS)
@pytest.mark.parametrize("noop", [False, True])
def test_preserved_virtual_pin_without_probe_blocks_publication(base, token, noop, tmp_path):
    # Preserve an override through nested includes; no-op means a resume before
    # DONE, not supervision of subsequent user edits.
    override = f"[stepper_z]\nendstop_pin: {token}\n"
    remote = {"printer.cfg": (base + "\n[include user.cfg]\n").encode(),
              "user.cfg": b"[include homing.cfg]\n", "homing.cfg": override.encode()}
    if noop:
        remote.update({a.remote_name: a.content for a in plan(base, remote).artifacts})
        assert not plan(base, remote).changed_artifacts
    errors = validate_configuration_plan(plan(base, remote)).errors
    assert "probe-z-endstop" in {e.code for e in errors}
    transport = FakeTransport(remote)
    result = ConfigDeploymentTransaction(transport, base.encode(), None,
        activation="none", confirm=lambda _: True, verify_existing_ready=noop,
        snapshot_root=str(tmp_path / "snapshots"), poll_interval=0).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED, result
    assert not any(call[0] in ("upload", "delete", "restart", "restart_moonraker")
                   for call in transport.calls)
    assert transport.files == remote
