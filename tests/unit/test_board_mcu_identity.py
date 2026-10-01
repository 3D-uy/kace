"""K14: names select reviewed MCU candidates, never substring guesses."""
from unittest.mock import patch

import pytest

from core.wizard.steps.sensors import _get_mcu_for_board


@pytest.mark.parametrize("filename, expected", [
    ("generic-bigtreetech-skr-mini-e3-v3.0.cfg", "stm32g0b1"),
    ("generic-bigtreetech-octopus-max-ez.cfg", "stm32h723"),
    ("generic-bigtreetech-octopus-pro-v1.1.cfg", "stm32h723"),
    ("generic-duet3-mini.cfg", "same54p20"),
    ("generic-fysetc-cheetah-v2.0.cfg", "stm32f401"),
    ("generic-bigtreetech-skr-v1.3.cfg", "lpc1768"),
])
def test_exact_single_model(filename, expected):
    assert _get_mcu_for_board(filename) == expected


@pytest.mark.parametrize("filename", [
    "generic-cramps.cfg", "generic-ruramps-v1.3.cfg",
    "generic-printrboard-g2.cfg", "generic-duet2-maestro.cfg",
    "custom-cheetah-v2.0.cfg", "generic-bigtreetech-skr-mini-e3-v30.cfg",
    "generic-mks-tinybee.cfg", "mks-gen-l", "mks-sgen-l",
])
def test_unreviewed_name_does_not_inherit_model(filename):
    assert _get_mcu_for_board(filename) == ""


@pytest.mark.parametrize("filename", [
    "generic-bigtreetech-skr-v1.4.cfg", "generic-bigtreetech-skr-2.cfg",
    "generic-bigtreetech-octopus-pro-v1.0.cfg",
    "generic-bigtreetech-octopus-v1.1.cfg", "generic-ramps.cfg",
])
def test_multivariant_profile_does_not_choose_first_model(filename):
    assert _get_mcu_for_board(filename) == ""


@pytest.mark.parametrize("filename, observed, expected", [
    ("generic-bigtreetech-skr-v1.4.cfg", "lpc1768", "lpc1768"),
    ("generic-bigtreetech-skr-v1.4.cfg", "lpc1769", "lpc1769"),
    ("generic-bigtreetech-skr-2.cfg", "stm32f407xx", "stm32f407"),
    ("generic-bigtreetech-skr-2.cfg", "stm32f429xx", "stm32f429"),
    ("generic-bigtreetech-octopus-pro-v1.0.cfg", "stm32h723xx", "stm32h723"),
    ("generic-ramps.cfg", "atmega1280", "atmega1280"),
    ("generic-duet3-mini.cfg", "same54p20a", "same54p20"),
    ("generic-bigtreetech-skr-2.cfg", "stm32f4", ""),
    ("generic-bigtreetech-skr-2.cfg", "stm32f407-fake", ""),
    ("generic-bigtreetech-skr-2.cfg", "stm32h723", ""),
    ("custom-skr-2.cfg", "stm32f407", ""),
])
def test_only_reviewed_models_or_explicit_aliases_narrow_variants(filename, observed, expected):
    assert _get_mcu_for_board(filename, observed) == expected


@pytest.mark.parametrize("model, expected", [
    ("stm32g0b1xx", ["generic-bigtreetech-skr-mini-e3-v3.0.cfg"]),
    ("stm32f103xe", ["generic-bigtreetech-skr-mini-e3-v2.0.cfg"]),
    ("atmega2560", ["generic-ramps.cfg"]),
    ("stm32f4", []),
])
def test_real_wizard_uses_exact_identity_but_keeps_manual_catalog(model, expected):
    from core.wizard import run_wizard
    names = ["generic-bigtreetech-skr-mini-e3-v3.0.cfg",
             "generic-bigtreetech-skr-mini-e3-v2.0.cfg",
             "generic-ramps.cfg", "generic-cramps.cfg"]

    def run_board_step(runner, start_step):
        runner.steps_config["board"]["prompt"](runner.user_data)
        return runner.user_data

    with patch("core.wizard.discover_mcu", return_value={"derived_mcu": model}), \
         patch("core.wizard.fetch_config_list", return_value=names), \
         patch("core.wizard.WizardRunner.run", run_board_step), \
         patch("core.wizard._step_board") as board_step:
        run_wizard()
    assert board_step.call_args.args[1:] == (expected, names)


@pytest.mark.parametrize("filename, observed, allowed, invalid", [
    ("generic-bigtreetech-skr-v1.4.cfg", "", "P0.5", "PA5"),
    ("generic-bigtreetech-skr-2.cfg", "", "PA5", "P0.5"),
    ("generic-ramps.cfg", "", "PL7", "PL8"),
    ("generic-ramps.cfg", "atmega1280", "PL7", "PL8"),
    ("generic-bigtreetech-skr-mini-e3-v3.0.cfg", "stm32g0b1xx", "PA5", "gpio5"),
])
def test_pin_validator_keeps_all_candidate_constraints(filename, observed, allowed, invalid):
    from core.wizard.steps.sensors import make_pin_validator_with_collision_check
    with patch("core.wizard.steps.sensors._get_parsed", return_value={}), \
         patch("core.firmware_workflow.generation_pin_reservations", return_value={}):
        validator = make_pin_validator_with_collision_check({"board": filename, "mcu_type": observed})
    assert validator(allowed) is True
    assert validator(invalid) is not True


def test_pin_validator_rejects_conflicting_model_without_applying_it_to_secondary_mcu():
    from core.wizard.steps.sensors import make_pin_validator_with_collision_check
    with patch("core.wizard.steps.sensors._get_parsed", return_value={}), \
         patch("core.firmware_workflow.generation_pin_reservations", return_value={}):
        validator = make_pin_validator_with_collision_check({
            "board": "generic-bigtreetech-skr-2.cfg", "mcu_type": "rp2040"})
    assert "conflicts" in validator("gpio5")
    assert validator("toolhead:gpio5") is True


def test_authoritative_identity_data_error_is_not_a_shadow_fallback():
    with patch("core.board_identity.load_boards_yaml", side_effect=RuntimeError("broken data")):
        with pytest.raises(RuntimeError, match="broken data"):
            _get_mcu_for_board("generic-bigtreetech-skr-2.cfg")
