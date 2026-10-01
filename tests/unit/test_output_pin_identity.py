"""Output instance names must survive extraction and publication unchanged."""
from unittest.mock import Mock

import pytest

from core.board_auxiliary import SOURCE_ACTIVITY, SOURCE_OPTIONS, selected_board_electrical_source, unresolved_pwm_outputs
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import _sections
from core.managed_config import (ROOT_REMOTE, MANAGED_BEGIN, MANAGED_END,
    build_managed_config_plan, effective_hardware_text, _section_options, _setting_loss_warnings)
from core.pin_validator import _read_pin_config
from core.scraper import parse_config
from tests.unit.test_config_transaction import FakeTransport, GENERATED


UPPER = "[output_pin BEEPER]\npin: PG1\npwm: True\ncycle_time: .001\n"
LOWER = "[output_pin beeper]\npin: PG2\nvalue: 0\n"


@pytest.mark.parametrize("comments", [False, True])
def test_source_activity_options_and_repeated_sections_are_case_sensitive(comments):
    raw = UPPER + LOWER + "[output_pin BEEPER]\nscale: 1000\n" + "#[output_pin Beeper]\n#pwm: True\n"
    parsed = parse_config(raw, keep_comments=comments)
    assert parsed["output_pin BEEPER"]["pin"] == "PG1"
    assert parsed["output_pin BEEPER"]["scale"] == "1000"
    assert parsed["output_pin beeper"] == {"pin": "PG2", "value": "0"}
    assert parsed[SOURCE_ACTIVITY]["output_pin BEEPER"] is True
    assert "pwm" in parsed[SOURCE_OPTIONS]["output_pin BEEPER"]
    assert "pwm" not in parsed[SOURCE_OPTIONS]["output_pin beeper"]
    assert unresolved_pwm_outputs(parsed) == ["output_pin BEEPER"]
    if comments:
        assert parsed[SOURCE_ACTIVITY]["output_pin Beeper"] is False


@pytest.mark.parametrize("reader", [_sections, _section_options, lambda text: _read_pin_config(text)[0]])
def test_review_and_planner_keep_distinct_instances(reader):
    parsed = reader(UPPER + LOWER + "[output_pin BEEPER]\nscale: 1000\n")
    assert set(parsed) == {"output_pin BEEPER", "output_pin beeper"}
    assert parsed["output_pin BEEPER"]["pin"] == "PG1"
    assert parsed["output_pin BEEPER"]["scale"] == "1000"
    assert parsed["output_pin beeper"] == {"pin": "PG2", "value": "0"}


@pytest.mark.parametrize("inline,inside", [(False, False), (True, False), (True, True)])
def test_reconcile_preserves_user_case_variant_without_carrying_its_options(inline, inside):
    # The API may preserve user PWM. It does not enable generation from a PWM board.
    root = ("# KACE layout: root-v1\n" if inline else "")
    root += f"{MANAGED_BEGIN}\n{LOWER if inside else ''}{MANAGED_END}\n"
    if not inside:
        root += LOWER
    plan = build_managed_config_plan(UPPER.encode(), None, {ROOT_REMOTE: root.encode()})
    effective = _read_pin_config(effective_hardware_text(plan))[0]
    assert effective["output_pin beeper"] == {"pin": "PG2", "value": "0"}
    assert "value" not in effective["output_pin BEEPER"]
    assert effective["output_pin BEEPER"]["pin"] == "PG1"
    assert not plan.warnings
    files = {item.remote_name: item.content for item in plan.artifacts}
    assert build_managed_config_plan(UPPER.encode(), None, files).changed_artifacts == ()


def test_actual_instance_removal_is_not_hidden_by_case_variant():
    warnings = _setting_loss_warnings("printer.cfg", UPPER, UPPER.replace("BEEPER", "beeper"))
    assert warnings and all("[output_pin BEEPER]" in w and "removed" in w for w in warnings)


@pytest.mark.parametrize("inline", [False, True])
def test_save_config_does_not_move_or_shadow_another_instances_options(inline):
    root = ("# KACE layout: root-v1\n" if inline else "") + LOWER
    root += ("#*# <---------------------- SAVE_CONFIG ---------------------->\n"
             "#*# [output_pin BEEPER]\n#*# scale = 1000\n")
    plan = build_managed_config_plan(UPPER.encode(), None, {ROOT_REMOTE: root.encode()})
    sections = _read_pin_config(effective_hardware_text(plan))[0]
    assert sections["output_pin BEEPER"]["scale"] == "1000"
    assert "scale" not in sections["output_pin beeper"]


@pytest.mark.parametrize("raw_authority", [False, True])
def test_recovered_pwm_still_blocks_before_transport_with_exact_name(tmp_path, raw_authority):
    wizard = {"board": "selected.cfg", "board_parsed": parse_config(UPPER)}
    if raw_authority:
        wizard["board_raw_config"] = UPPER
    source = selected_board_electrical_source({"workflow_checkpoint": {"wizard_data": wizard}})
    dest, confirm = FakeTransport(), Mock(return_value=True)
    result = ConfigDeploymentTransaction(dest, GENERATED, None, selected_board=source,
        confirm=confirm, activation="firmware", snapshot_root=str(tmp_path)).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "output_pin BEEPER" in result.detail
    assert not dest.calls
    confirm.assert_not_called()


def test_transaction_preserves_uppercase_user_include_and_lowercase_sibling(tmp_path):
    root = GENERATED + LOWER.encode() + b"[include user.cfg]\n"
    dest = FakeTransport({ROOT_REMOTE: root, "user.cfg": UPPER.encode()})
    result = ConfigDeploymentTransaction(dest, GENERATED, None, selected_board=parse_config(GENERATED.decode()),
        activation="none", snapshot_root=str(tmp_path), poll_interval=0).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    assert dest.files["user.cfg"] == UPPER.encode()
    assert LOWER.encode() in dest.files[ROOT_REMOTE]
