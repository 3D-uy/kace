"""Additional Z motors retain independent homing inputs before initial DONE."""
from unittest.mock import Mock, patch

import pytest
from jinja2 import Template

from core.board_auxiliary import validate_board_electrical_artifact
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from core.pin_validator import _read_pin_config
from core.scraper import parse_config
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_generator import _parsed, _user


def board(count=2, pin="^!PG0"):
    result = _parsed()
    for index in range(1, count):
        result[f"stepper_z{index}"] = {
            "step_pin": f"PF{index * 3}", "dir_pin": f"PF{index * 3 + 1}",
            "enable_pin": f"!PF{index * 3 + 2}",
        }
    if pin is not None:
        result[f"stepper_z{count - 1}"]["endstop_pin"] = pin
    return result


def generate(tmp_path, source, count=2, **user):
    return generate_config(source, _user(z_motors=str(count), **user),
                           output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]


@pytest.mark.parametrize("count", [2, 3, 4])
@pytest.mark.parametrize("pin", ["PG0", "^!PG0", None])
def test_independent_or_omitted_endstop_is_preserved(tmp_path, count, pin):
    sections = _read_pin_config(generate(tmp_path, board(count, pin), count))[0]
    assert sections[f"stepper_z{count - 1}"].get("endstop_pin") == pin
    for index in range(1, count - 1):
        assert "endstop_pin" not in sections[f"stepper_z{index}"]


@pytest.mark.parametrize("comment", [True, False])
def test_discovery_does_not_activate_commented_endstop(tmp_path, comment):
    source = board(pin=None)
    source.update(parse_config("[stepper_z1]\nstep_pin: PF3\ndir_pin: PF4\nenable_pin: !PF5\n"
                               + ("# " if comment else "") + "endstop_pin: ^PG0\n", keep_comments=True))
    rendered = _read_pin_config(generate(tmp_path, source))[0]["stepper_z1"]
    assert rendered.get("endstop_pin") == (None if comment else "^PG0")


def test_unselected_extra_motor_is_not_required(tmp_path):
    source = board()
    content = generate(tmp_path, source, count=1)
    assert "[stepper_z1]" not in content
    validate_board_electrical_artifact(source, content)


@pytest.mark.parametrize("replacement", ["", "endstop_pin: PG0", "endstop_pin: ^!PG1"])
def test_render_cannot_drop_or_change_independent_input(tmp_path, replacement):
    render = Template.render
    def alter(template, *args, **kwargs):
        return render(template, *args, **kwargs).replace("endstop_pin: ^!PG0", replacement)
    with patch.object(Template, "render", alter), pytest.raises(GenerationError, match="endstop_pin"):
        generate(tmp_path, board())
    assert not (tmp_path / "printer.cfg").exists()
    assert not (tmp_path / "printer.cfg.provenance.json").exists()


@pytest.mark.parametrize("pin", [None, "^!PG1", "PG0"])
def test_old_artifact_cannot_lose_source_endstop(tmp_path, pin):
    content = generate(tmp_path, board(pin=pin))
    with pytest.raises(GenerationError, match="endstop_pin"):
        validate_board_electrical_artifact(board(), content)


def test_alias_equivalence_retains_polarity(tmp_path):
    content = generate(tmp_path, board())
    source = board(pin="^!Z_STOP")
    source["board_pins names"] = {"aliases": "Z_STOP=PG0"}
    validate_board_electrical_artifact(source, content)


@pytest.mark.parametrize("noop", [False, True])
def test_preserved_nested_override_blocks_before_writes(tmp_path, noop):
    source = board()
    generated = generate(tmp_path, source).encode()
    remote = {"printer.cfg": generated + b"\n[include user.cfg]\n",
              "user.cfg": b"[include nested.cfg]\n",
              "nested.cfg": b"[stepper_z1]\nendstop_pin: PG0\n"}
    if noop:
        remote.update({a.remote_name: a.content for a in build_managed_config_plan(generated, None, remote).artifacts})
        assert not build_managed_config_plan(generated, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, generated, None, selected_board=source,
        activation="none", confirm=confirm, output=lambda _: None,
        snapshot_root=str(tmp_path / "snapshots"), poll_interval=0).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "endstop_pin" in result.detail
    confirm.assert_not_called()
    assert not any(c[0] in ("upload", "delete", "restart", "restart_moonraker") for c in transport.calls)


def test_secondary_probe_endstop_requires_provider(tmp_path):
    with pytest.raises(GenerationError, match="probe"):
        generate(tmp_path, board(pin="probe:z_virtual_endstop"))
    assert not (tmp_path / "printer.cfg").exists()
