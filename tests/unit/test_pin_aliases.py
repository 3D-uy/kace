"""Board aliases are MCU-local names, not a new physical pin namespace."""
from unittest.mock import Mock

import pytest

from core.deployer import _preflight_check
from core.pin_validator import validate_pins_for_mcu


def validate(tmp_path, text, mcu="stm32f103"):
    path = tmp_path / "printer.cfg"
    path.write_text(text, encoding="utf-8")
    before = path.read_bytes()
    result = validate_pins_for_mcu(str(path), mcu)
    assert path.read_bytes() == before
    return result


@pytest.mark.parametrize("definition", [
    "[board_pins]\naliases: EXP1_1=PA0",
    "[board_pins headers]\naliases: EXP1_1=PA0",
    "[board_pins]\naliases:\n    EXP1_1=PA0, # header\n    UNUSED=PA1",
    "[board_pins]\naliases: FIRST=PA0\naliases_exp: EXP1_1=FIRST",
    "[board_pins]\naliases: EXP1_1=SECOND, SECOND=PA0",
    "[board_pins]\naliases = EXP1_1=PA0",
])
def test_alias_resolves_without_rewriting_the_token(tmp_path, definition):
    assert validate(tmp_path, "[output_pin led]\npin: !EXP1_1\n" + definition + "\n") == []


def test_alias_target_is_checked_against_the_selected_architecture(tmp_path):
    result = validate(tmp_path, "[board_pins]\naliases: EXP1_1=PA0\n[output_pin led]\npin: EXP1_1\n", "lpc1769")
    assert any(item[1:] == ("pin", "EXP1_1", "lpc176x") for item in result)


@pytest.mark.parametrize("aliases", [
    "A=B, B=A", "A=A", "A=PA0, A=PA1", "A=NOT_DEFINED",
    "A=!PA0", "A=toolhead:PA0", "A=PA 0", "A", "A=",
])
def test_invalid_alias_definitions_are_rejected(tmp_path, aliases):
    with pytest.raises(ValueError):
        validate(tmp_path, f"[board_pins]\naliases: {aliases}\n[output_pin led]\npin: A\n")


def test_reserved_alias_is_valid_in_table_but_not_as_a_gpio(tmp_path):
    table = "[board_pins]\naliases: GND=<GND>, SIGNAL=PA0\n"
    assert validate(tmp_path, table + "[output_pin led]\npin: SIGNAL\n") == []
    with pytest.raises(ValueError, match="reserved"):
        validate(tmp_path, table + "[output_pin led]\npin: GND\n")


def test_same_alias_name_on_two_mcus_does_not_conflict(tmp_path):
    text = """[board_pins main]
aliases: LED=PA0
[board_pins head]
mcu: toolhead
aliases: LED=gpio5
[output_pin main_led]
pin: LED
[output_pin head_led]
pin: toolhead:LED
"""
    assert validate(tmp_path, text, {"mcu": "stm32f103", "toolhead": "rp2040"}) == []


def test_mcu_qualifier_does_not_escape_primary_validation(tmp_path):
    issues = validate(tmp_path, "[output_pin led]\npin: mcu:PA0\n", "lpc1769")
    assert len(issues) == 1


def test_multiple_mcu_alias_list_and_unknown_secondary_arch(tmp_path):
    text = "[board_pins shared]\nmcu: mcu, toolhead\naliases: LED=PA0\n[output_pin led]\npin: toolhead:LED\n"
    assert validate(tmp_path, text) == []


def test_two_spellings_of_one_physical_pin_are_not_independent_outputs(tmp_path):
    text = "[board_pins]\naliases: A=PA0, B=PA0\n[output_pin a]\npin: A\n[output_pin b]\npin: B\n"
    with pytest.raises(ValueError, match="alias"):
        validate(tmp_path, text)


def test_shared_enable_pin_keeps_existing_sharing_contract(tmp_path):
    text = "[board_pins]\naliases: ENABLE=PA0\n[stepper_x]\nenable_pin: !ENABLE\n[stepper_y]\nenable_pin: !ENABLE\n"
    assert validate(tmp_path, text) == []


def test_invalid_alias_cannot_be_overridden_in_preflight(tmp_path):
    from tests.unit.test_pin_validator import VALID_CFG
    path = tmp_path / "printer.cfg"
    path.write_text(VALID_CFG + "\n[board_pins]\naliases: A=B, B=A\n", encoding="utf-8")
    prompt = Mock(return_value=True)
    assert _preflight_check(str(path), {"mcu_type": "lpc1769"}, prompt) is False
    prompt.assert_not_called()


def test_scrape_and_generate_preserve_named_aliases_and_tokens(tmp_path):
    from core.generator import generate_config
    from core.scraper import parse_config
    from tests.unit.test_generator import _parsed, _user

    text = """[board_pins headers]
mcu: mcu
aliases: STEP=PA1
aliases_extra:
    DIRECTION=PA2,
    ENABLE=PA3
    # UNUSED=PA4
"""
    sections = parse_config(text)
    assert "board_pins" not in sections
    assert "UNUSED" not in sections["board_pins headers"]["aliases_extra"]
    parsed = _parsed(**sections)
    parsed["stepper_x"].update(step_pin="STEP", dir_pin="DIRECTION", enable_pin="!ENABLE")
    target = tmp_path / "printer.cfg"
    result = generate_config(parsed, _user(), output_path=str(target), verbose=False)
    rendered = parse_config(result["content"])
    assert rendered["stepper_x"]["step_pin"] == "STEP"
    assert rendered["stepper_x"]["enable_pin"] == "!ENABLE"
    assert rendered["board_pins headers"]["mcu"] == "mcu"
    assert "ENABLE=PA3" in rendered["board_pins headers"]["aliases_extra"]
    assert validate_pins_for_mcu(str(target), "stm32f103") == []


def test_valid_alias_requires_no_preflight_override(tmp_path):
    from tests.unit.test_pin_validator import VALID_CFG
    path = tmp_path / "printer.cfg"
    path.write_text(VALID_CFG.replace("step_pin: P1.4", "step_pin: EXP1_1")
                    + "\n[board_pins]\naliases: EXP1_1=P1.4\n", encoding="utf-8")
    prompt = Mock(return_value=False)
    assert _preflight_check(str(path), {"mcu_type": "lpc1769"}, prompt) is True
    prompt.assert_not_called()


@pytest.mark.parametrize("first,second", [("PA0", "!A"), ("A", "mcu:PA0")])
def test_raw_pin_and_alias_are_one_physical_identity(tmp_path, first, second):
    with pytest.raises(ValueError, match="alias"):
        validate(tmp_path, f"[board_pins]\naliases: A=PA0\n[output_pin a]\npin: {first}\n[output_pin b]\npin: {second}\n")


def test_equal_physical_name_on_distinct_mcus_stays_distinct(tmp_path):
    text = "[board_pins main]\naliases: A=PA0\n[board_pins head]\nmcu: toolhead\naliases: B=PA0\n[output_pin a]\npin: A\n[output_pin b]\npin: toolhead:B\n"
    assert validate(tmp_path, text, {"mcu": "stm32f103", "toolhead": "stm32f103"}) == []


def test_duplicate_override_declaration_is_not_a_pin_consumer(tmp_path):
    text = "[duplicate_pin_override]\npins: PA0\n[board_pins]\naliases: A=PA0\n[output_pin a]\npin: A\n"
    assert validate(tmp_path, text) == []
