"""Fan selection must preserve chip identity and PWM inversion end to end."""
from unittest.mock import patch
from pathlib import Path

import pytest

from core.exceptions import GenerationError
from core.generator import generate_config
from core.scraper import detect_fan_pins, parse_config
from core.wizard.steps.hardware import _step_fan_assignment
from tests.unit.test_generator import _parsed, _user


TOKENS = ("replicape:power_fan0", "multi_pin:extruder_fans", "!toolhead:gpio5", "!PA8", "EXP1_1")


@pytest.mark.parametrize("token", TOKENS)
@pytest.mark.parametrize("prefix", ["", "#", "  # "])
def test_discovery_keeps_full_token_and_label(token, prefix):
    found = detect_fan_pins(f"{prefix}[heater_fan aux]\n{prefix}pin: {token} # socket\n")
    assert len(found) == 1
    assert found[0]["pin"] == token
    assert token in found[0]["label"]


@pytest.mark.parametrize("token", TOKENS)
@pytest.mark.parametrize("role", ["part", "hotend", "default"])
def test_selection_and_generation_keep_identity(tmp_path, token, role):
    raw = f"[fan]\npin: {token}\n"
    user = _user(board_raw_config=raw)
    decisions = {"part": [token, "none"], "hotend": ["none", token], "default": ["default", "none"]}
    # Explicit part selection uses a non-default fan entry, as in the real UI.
    if role == "part":
        raw = f"[fan_generic aux]\npin: {token}\n"
        user["board_raw_config"] = raw
    offered = []

    def choose(*args, **kwargs):
        values = [item.get("value") for item in kwargs["choices"] if isinstance(item, dict)]
        offered.append(values)
        choice = decisions[role][len(offered) - 1]
        assert choice in values
        return choice

    with patch("core.wizard.steps.hardware.numbered_select", side_effect=choose):
        assert _step_fan_assignment(user) == "success"
    parsed = _parsed(fan={"pin": token})
    # Exercise the actual menu source, not a substituted pin-only [fan] fixture.
    parsed.update(parse_config(raw, keep_comments=True))
    target = tmp_path / "printer.cfg"
    if token == "replicape:power_fan0":
        # Discovery/selection must retain the full token even when generation
        # rejects the unsupported provider. Never turn it into an MCU GPIO.
        assert parsed["fan"]["pin"] == token
        if role != "default":
            assert user["fan_part_cooling_pin" if role == "part" else "fan_hotend_pin"] == token
        with pytest.raises(GenerationError, match="Replicape pin provider"):
            generate_config(parsed, user, output_path=str(target), verbose=False)
        assert not target.exists()
        assert not Path(str(target) + ".provenance.json").exists()
        return
    result = generate_config(parsed, user, output_path=str(target), verbose=False)
    section = "heater_fan hotend_fan" if role == "hotend" else "fan"
    assert parse_config(result["content"])[section]["pin"] == token


@pytest.mark.parametrize("token", ["^PA8", "~PA8", "!!PA8", "!^PA8", "toolhead:!gpio5", "PA8 garbage", "toolhead:"])
def test_discovery_never_offers_a_partial_or_invalid_pwm_pin(token):
    assert detect_fan_pins(f"[fan]\npin: {token}\n") == []


@pytest.mark.parametrize("token", ["^PA8", "~PA8", "!!PA8", "!^PA8", "toolhead:!gpio5"])
@pytest.mark.parametrize("role", ["default", "part", "hotend"])
def test_illegal_pwm_modifiers_fail_before_publication(tmp_path, token, role):
    parsed = _parsed(fan={"pin": token if role == "default" else "PA8"})
    user = _user()
    if role != "default":
        user["fan_part_cooling_pin" if role == "part" else "fan_hotend_pin"] = token
    target = tmp_path / "printer.cfg"
    with pytest.raises(GenerationError, match="fan.*pin"):
        generate_config(parsed, user, output_path=str(target), verbose=False)
    assert not target.exists()


def test_polarity_and_mcu_are_not_lost_during_deduplication():
    text = "[fan]\npin: !PA8\n[fan_generic a]\npin: PA8\n[fan_generic b]\npin: toolhead:PA8\n[fan_generic c]\npin: !PA8\n"
    assert [item["pin"] for item in detect_fan_pins(text)] == ["!PA8", "PA8", "toolhead:PA8"]


def test_active_pin_takes_precedence_over_commented_example():
    text = "[fan]\n# pin: PA8\npin: !toolhead:gpio5\n"
    assert detect_fan_pins(text)[0]["pin"] == "!toolhead:gpio5"


def test_hotend_choices_exclude_opposite_polarity_of_selected_gpio():
    raw = "[fan]\npin: !PA8\n[fan_generic opposite]\npin: mcu:PA8\n[heater_fan head]\npin: toolhead:PA8\n"
    with patch("core.wizard.steps.hardware.numbered_select", side_effect=["default", "none"]) as choose:
        _step_fan_assignment({"board_raw_config": raw})
    choices = choose.call_args_list[1].kwargs["choices"]
    values = [item.get("value") for item in choices if isinstance(item, dict)]
    assert "!PA8" not in values
    assert "mcu:PA8" not in values
    assert "toolhead:PA8" in values


@pytest.mark.parametrize("role", ["part", "hotend"])
def test_custom_prompt_uses_pwm_validation_and_keeps_token(role):
    def enter_pin(*args, **kwargs):
        validator = kwargs["validate"]
        assert validator("^PA8") is not True
        assert validator("toolhead:!gpio5") is not True
        assert validator("!toolhead:gpio5") is True
        return "!toolhead:gpio5"

    decisions = ["custom", "none"] if role == "part" else ["none", "custom"]
    user = {"board_raw_config": "[fan]\npin: PA8\n"}
    with patch("core.wizard.steps.hardware.numbered_select", side_effect=decisions), \
         patch("core.wizard.steps.hardware.simple_input", side_effect=enter_pin):
        assert _step_fan_assignment(user) == "success"
    key = "fan_part_cooling_pin" if role == "part" else "fan_hotend_pin"
    assert user[key] == "!toolhead:gpio5"


@pytest.mark.parametrize("name,token", [
    ("generic-replicape.cfg", "replicape:power_fan0"),
    ("printer-geeetech-301-2019.cfg", "multi_pin:extruder_fans"),
])
def test_official_configs_keep_virtual_chip_names(name, token):
    path = Path(__file__).resolve().parents[1] / "fixtures/fan-pin-identity" / name
    assert token in [item["pin"] for item in detect_fan_pins(path.read_text(encoding="utf-8"))]
