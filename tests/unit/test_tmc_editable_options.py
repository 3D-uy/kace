"""Editable TMC examples must not change effective electrical settings."""
import re

import pytest

from core.generator import generate_config
from core.pin_validator import _read_pin_config
from tests.unit.test_full_steps_preservation import multi_board
from tests.unit.test_tmc_electrical_authority import inputs
from tests.unit.test_tmc_socket import confirm_currents, inputs as socket_inputs


@pytest.fixture(autouse=True)
def english_comments(monkeypatch):
    monkeypatch.setattr("core.translations._state._current_lang", "English")


def section_text(content, section):
    return re.split(r"\n(?:# )?\[", content.split(f"[{section}]", 1)[1], maxsplit=1)[0]


@pytest.mark.parametrize("model", ["tmc2208", "tmc2209", "tmc2130", "tmc5160"])
@pytest.mark.parametrize("target", ["x", "y", "z", "z1", "z2", "z3", "e"])
def test_default_options_are_editable_comments_without_changing_settings(tmp_path, model, target):
    board, _, user, section = inputs(model, target)
    board.update(multi_board())
    for option in ("hold_current", "stealthchop_threshold", "sense_resistor"):
        board[section].pop(option)
    result = generate_config(board, user, output_path=str(tmp_path / "printer.cfg"), verbose=False)
    text = section_text(result["content"], section)
    rendered, _ = _read_pin_config(result["content"])
    for option, value in (("interpolate", "True"), ("hold_current", "0.580"), ("stealthchop_threshold", "0")):
        assert re.search(rf"^# ?{option}: {re.escape(value)}\s+#", text, re.MULTILINE)
        assert option not in rendered[section]
    assert "spreadCycle" in text and "stealthChop" in text and "999999" in text
    assert "uart_address:" not in text and "sense_resistor:" not in text
    assert result["value_provenance"][f"hold_current_{target}"] == "KLIPPER_DEFAULT"
    assert result["value_provenance"][f"stealthchop_threshold_{target}"] == "KLIPPER_DEFAULT"


@pytest.mark.parametrize("interpolate", ["True", "False"])
def test_explicit_settings_are_not_duplicated_or_replaced(tmp_path, interpolate):
    board, _, user, section = inputs()
    user["z_motors"] = "1"
    board[section]["interpolate"] = interpolate
    result = generate_config(board, user, output_path=str(tmp_path / "printer.cfg"), verbose=False)
    text = section_text(result["content"], section)
    rendered, _ = _read_pin_config(result["content"])
    for option, value in (("interpolate", interpolate), ("hold_current", "0.250"), ("stealthchop_threshold", "0")):
        assert rendered[section][option] == value
        assert len(re.findall(rf"^(?:# ?)?{option}:", text, re.MULTILINE)) == 1


@pytest.mark.parametrize("language,expected", [
    ("English", ("interpolate to 256", "Standstill current", "torque/accuracy", "quieter")),
    ("Español", ("interpolación", "Corriente en reposo", "par/precisión", "silencioso")),
    ("Português", ("interpolação", "Corrente em repouso", "torque/precisão", "silencioso")),
])
@pytest.mark.parametrize("model", ["TMC2209", "TMC2225"])
def test_socket_options_and_explanations_are_available_in_each_language(tmp_path, monkeypatch, language, expected, model):
    monkeypatch.setattr("core.translations._state._current_lang", language)
    board, user = socket_inputs(model=model)
    confirm_currents(board, user)
    content = generate_config(board, user, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    canonical = "tmc2208" if model == "TMC2225" else "tmc2209"
    for target in ("stepper_x", "stepper_y", "stepper_z", "stepper_z1", "extruder"):
        text = section_text(content, f"{canonical} {target}")
        for translated in expected:
            assert translated in text
        assert "# interpolate: True" in text
        assert "# hold_current: 0.580" in text
        if model == "TMC2225":
            # This socket profile already selects stealthChop for the TMC2208 alias.
            assert re.search(r"^stealthchop_threshold: 999999\s+#", text, re.MULTILINE)
            assert "# stealthchop_threshold:" not in text
        else:
            assert "# stealthchop_threshold: 0" in text
        assert "uart_address:" not in text and "sense_resistor:" not in text
