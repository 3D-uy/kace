"""Known offset edits retain source ownership and never relax Z geometry."""
import copy
import os

import pytest

from core.custom_probe import parse_custom_probe_config, CustomProbeValidationError
from core.firmware_workflow import persistable_wizard_data, restore_wizard_data
from core.menu import _plain_label
from core.translations import get_lang, set_lang
from core.wizard.steps import probe_homing, sensors
from tests.unit.test_probe_homing_contract import wizard_probe_data
from tests.unit.test_probe_review_navigation import guided_user, actual_catalog
from core.wizard.runner import WizardRunner


@pytest.fixture(autouse=True)
def interactive(monkeypatch):
    language = get_lang()
    set_lang("English")
    monkeypatch.setenv("KACE_AUTO", "0")
    yield
    set_lang(language)


def source_user(source):
    # These tests exercise editing a supplied zero. An explicitly deferred
    # offset now returns to probe review if the user wants to change that choice.
    user = known_guided_user() if source == "guided" else wizard_probe_data()
    if source == "resumed":
        user = restore_wizard_data(persistable_wizard_data(known_guided_user()))
    return user


def known_guided_user():
    user = guided_user()
    user["custom_probe_z_offset"] = "0"
    assert sensors._step_custom_probe(user) == "done"
    assert user["custom_probe_settings"].z_offset == 0
    return user


@pytest.mark.parametrize("source", ["guided", "imported", "resumed"])
@pytest.mark.parametrize("value", ["0.5", "1"])
def test_direct_known_offset_advances_only_after_confirmation(monkeypatch, source, value):
    user = source_user(source)
    original = copy.deepcopy(user)
    answers = iter(["offset", value, "y"])
    monkeypatch.setattr("builtins.input", lambda *args: next(answers))
    assert probe_homing.review_probe_homing_geometry(user)
    assert user["custom_probe"].z_offset == float(value)
    assert user["z_position_min"] == original["z_position_min"] == "0.5"
    assert user["_profile_parsed"] == original["_profile_parsed"]
    assert user["custom_probe"].x_offset == original["custom_probe"].x_offset
    probe_homing.validate_wizard_probe_homing_geometry(user)
    restored = restore_wizard_data(persistable_wizard_data(user))
    assert restored["custom_probe"].config_text == user["custom_probe"].config_text
    if "custom_probe_settings" in restored:
        assert restored["custom_probe_settings"]["z_offset"] == float(value)


@pytest.mark.parametrize("value", ["0.5000001", "0.500000123456789"])
def test_guided_known_offset_preserves_precision_at_z_minimum(monkeypatch, value):
    from core.profile_values import mark_user_override
    from core.translations import t

    user = known_guided_user()
    user["z_position_min"] = "0.5000001"
    mark_user_override(user, "z_position_min")
    original = copy.deepcopy(user)
    answers = iter(["offset", value])
    monkeypatch.setattr("builtins.input", lambda *args: next(answers))
    confirmations = []

    def confirm(prompt, default=False):
        # Staging must not alter the accepted state before confirmation.
        assert user == original
        confirmations.append(prompt)
        return True

    monkeypatch.setattr(probe_homing, "yes_no", confirm)
    assert probe_homing.review_probe_homing_geometry(user)
    assert confirmations == [t("wizard.probe_z.confirm_offset", old=0.0, new=value)]
    assert user["z_position_min"] == original["z_position_min"]
    assert user["custom_probe_settings"].z_offset == float(value)
    assert user["custom_probe"].z_offset == float(value)
    line = next(line for line in user["custom_probe"].config_text.splitlines()
                if line.startswith("z_offset:"))
    assert line.split("#", 1)[0].rstrip() == f"z_offset: {value}"
    probe_homing.validate_wizard_probe_homing_geometry(user)
    restored = restore_wizard_data(persistable_wizard_data(user))
    assert restored["custom_probe"].z_offset == float(value)


@pytest.mark.parametrize("source", ["guided", "imported", "resumed"])
@pytest.mark.parametrize("answers", [["offset", "<", "cancel"], ["offset", "1", "n", "cancel"],
                                     ["offset", "0", "cancel"], ["offset", "351", "cancel"]])
def test_cancelled_or_incompatible_offset_never_changes_draft(monkeypatch, source, answers):
    user = source_user(source)
    original = copy.deepcopy(user)
    responses = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *args: next(responses))
    assert not probe_homing.review_probe_homing_geometry(user)
    assert user == original


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("section", ["probe", "dockable_probe"])
def test_explicit_raw_offset_edit_preserves_every_other_byte(newline, section):
    raw = newline.join(["# own calibrated notes", f"[{section}]", "pin: ^PB8", "x_offset: -9",
                        "y_offset: 1", "  Z_offset : 0.0  # own comment", "speed: 7",
                        "[gcode_macro DOCK]", "gcode:", "    RESPOND MSG='z_offset: 123'", ""])
    original = parse_custom_probe_config(raw)
    changed = original.with_z_offset("0.75")
    assert changed.config_text == raw.replace("Z_offset : 0.0", "Z_offset : 0.75")
    assert changed.z_offset == 0.75
    assert original.config_text == raw


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "", "1\nz_offset: 2"])
def test_raw_editor_rejects_invalid_offset_without_mutation(value):
    original = parse_custom_probe_config("[probe]\npin: PB8\nz_offset: 0# keep\n")
    with pytest.raises(CustomProbeValidationError):
        original.with_z_offset(value)
    assert original.z_offset == 0


def test_raw_editor_preserves_attached_comment():
    original = parse_custom_probe_config("[probe]\npin: PB8\nz_offset: 0# keep\n")
    assert original.with_z_offset("1").config_text.endswith("z_offset: 1# keep\n")


def test_structured_probe_does_not_offer_an_offset_it_cannot_persist(monkeypatch):
    user = wizard_probe_data()
    user.update(probe="BLTouch", probe_kind="bltouch")
    user.pop("custom_probe")
    def cancel(prompt, choices, **kwargs):
        assert [item["value"] for item in choices] == ["prepare_zero", "edit", "cancel"]
        return "cancel"
    monkeypatch.setattr(probe_homing, "numbered_select", cancel)
    original = copy.deepcopy(user)
    assert not probe_homing.review_probe_homing_geometry(user)
    assert user == original


def test_imported_review_can_edit_known_offset_without_rebuilding_options(monkeypatch):
    user = wizard_probe_data()
    raw = user["custom_probe"].config_text + "\n# keep my tuning\nspeed: 3.25\n"
    user["custom_probe"] = parse_custom_probe_config(raw)
    answers = iter(["3", "1", "1"])
    monkeypatch.setattr("builtins.input", lambda *args: next(answers))
    assert sensors._step_custom_probe_review(user) == "done"
    assert user["custom_probe"].config_text == raw.replace("z_offset: 0", "z_offset: 1")


def test_real_runner_direct_offset_continues_to_next_question(monkeypatch):
    user = known_guided_user()
    answers = iter(["continue", "offset", "1", "y"])
    monkeypatch.setattr("builtins.input", lambda *args: next(answers))
    catalog = actual_catalog()
    catalog["hotend_therm"] = {"prompt": lambda state: "done", "next": lambda a, u: None}
    result = WizardRunner(catalog, ["custom_probe_review", "probe_homing", "hotend_therm"], user).run("custom_probe_review")
    assert result["custom_probe"].z_offset == 1
    assert result["z_position_min"] == "0.5"


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
@pytest.mark.parametrize("width", [60, 80, 120])
def test_review_explains_each_parameter_with_values_and_units(monkeypatch, capsys, language, width):
    set_lang(language)
    monkeypatch.setattr("shutil.get_terminal_size", lambda **kwargs: os.terminal_size((width, 24)))
    monkeypatch.setattr(sensors, "numbered_select", lambda *args, **kwargs: "continue")
    user = guided_user()
    original = copy.deepcopy(user)
    assert sensors._step_custom_probe_review(user) == "done"
    text = _plain_label(capsys.readouterr().out)
    for name in ("pin", "x_offset", "y_offset", "z_offset", "samples", "samples_result",
                 "samples_tolerance", "samples_tolerance_retries", "speed", "sample_retract_dist"):
        assert name + ":" in text
    assert "7 mm/s" in text and "-12 mm" in text and "PROBE_CALIBRATE" in text
    assert "wizard." not in text
    assert max(map(len, text.splitlines())) <= width
    assert user == original
