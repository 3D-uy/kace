"""Exact processor evidence suggests boards; an operator selects the model."""
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from core.board_identity import board_model_label, resolve_board_mcu, suggested_board_configs
from core.exceptions import WizardExit
from core.translations import get_lang, set_lang, t
from core.wizard.runner import _BACK
from core.wizard.steps import hardware
from firmware.detector import mcu_context_from_path


SKR14 = "generic-bigtreetech-skr-v1.4.cfg"
E3 = "generic-bigtreetech-skr-e3-turbo.cfg"
SGEN = "generic-mks-sgenl.cfg"
SKR13 = "generic-bigtreetech-skr-v1.3.cfg"
CATALOG = [SKR14, E3, SGEN, SKR13, "generic-mks-sgenl-v2.cfg", "custom-skr-turbo.cfg"]


@pytest.mark.parametrize("model, expected", [
    ("lpc1769", [SKR14, E3]),
    ("LPC1768", [SKR14, SGEN, SKR13]),
    ("lpc176", []), ("lpc176x", []), ("lpc1769fake", []),
    ("lpc1769-fake", []), ("", []),
])
def test_exact_reviewed_candidates_never_infer_sgen_v2_or_neighbour_mcu(model, expected):
    assert suggested_board_configs(CATALOG, model) == expected


def test_suggestions_only_reference_available_profiles_and_are_not_duplicated():
    assert suggested_board_configs([E3, E3, SKR13], "lpc1769") == [E3]


@pytest.mark.parametrize("path, model", [
    ("/dev/serial/by-id/usb-Klipper_lpc1769_ABC-if00", "lpc1769"),
    ("/dev/serial/by-id/usb-Klipper_lpc1768_ABC-if00", "lpc1768"),
    ("/dev/serial/by-id/USB-KLIPPER_LPC1769_ABC-if00", "lpc1769"),
    ("/dev/serial/by-id/usb-Klipper_lpc1769-fake_ABC-if00", None),
    ("/dev/serial/by-id/usb-Klipper_lpc1769.1_ABC-if00", None),
    ("/tmp/usb-Klipper_lpc1769_ABC/ttyACM0", None),
    ("/dev/serial/by-id/notusb-Klipper_lpc1769_ABC-if00", None),
    ("/dev/serial/by-id/usb-CH340_lpc1769_ABC-if00", None),
    ("/dev/ttyACM0", None),
])
def test_usb_identity_is_a_whole_klipper_token_in_device_basename(path, model):
    assert mcu_context_from_path(path)["derived_mcu"] == model


def test_lookalike_whole_token_cannot_become_reviewed_processor():
    model = mcu_context_from_path("/dev/serial/by-id/usb-Klipper_lpc1769fake_ABC-if00")["derived_mcu"]
    assert model == "lpc1769fake"
    assert suggested_board_configs(CATALOG, model) == []


def test_shared_skr_profile_uses_exact_turbo_name_without_guessing_variant():
    assert board_model_label(SKR14, "lpc1769") == "BIGTREETECH SKR 1.4 Turbo"
    assert board_model_label(SKR14, "lpc1768") == "BIGTREETECH SKR 1.4"
    assert board_model_label(SKR14) == SKR14
    assert board_model_label(E3, "lpc1768") == E3
    assert resolve_board_mcu(E3, "lpc1768") == ""
    assert resolve_board_mcu(SGEN, "lpc1769") == ""


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
def test_candidates_distinguish_processor_and_unconfirmed_board_without_loading(language, capsys):
    previous = get_lang()
    set_lang(language)
    state = {"mcu_type": "lpc1769"}
    def inspect_selection(_prompt, **kwargs):
        assert kwargs["require_explicit"] is True
        assert [c["value"] for c in kwargs["choices"][:2]] == [SKR14, E3]
        assert [c["name"] for c in kwargs["choices"][:2]] == [
            "BIGTREETECH SKR 1.4 Turbo", "BIGTREETECH SKR E3 Turbo"]
        assert "board" not in state
        assert "firmware_authority" not in state
        return _BACK
    try:
        with patch.object(hardware, "autocomplete_select", side_effect=inspect_selection), patch.object(
            hardware, "fetch_raw_config") as fetch, patch(
            "firmware.boards.runtime.resolve_firmware_authority") as authority:
            assert hardware._step_board(state, [SKR14, E3], CATALOG) == _BACK
        fetch.assert_not_called()
        authority.assert_not_called()
        output = capsys.readouterr().out
        assert t("catalog.detected_processor", mcu="LPC1769") in output
        assert " ".join(t("catalog.board_unconfirmed").split()) in " ".join(output.split())
    finally:
        set_lang(previous)


def test_empty_input_cannot_choose_single_candidate_or_load_a_profile(monkeypatch):
    monkeypatch.delenv("KACE_AUTO", raising=False)
    state = {"mcu_type": "lpc1769"}
    with patch("builtins.input", side_effect=["", "<"]) as read, patch.object(
        hardware, "fetch_raw_config") as fetch:
        assert hardware._step_board(state, [SKR14], [SKR14]) == _BACK
    assert read.call_count == 2
    assert state == {"mcu_type": "lpc1769"}
    fetch.assert_not_called()


@pytest.mark.parametrize("selected, expected_authority, expected_variant", [
    (SKR14, "board_contract", "lpc1769-turbo"),
    (E3, "legacy", ""),
])
def test_selection_loads_only_selected_profile_and_existing_authority(selected, expected_authority, expected_variant):
    state = {"mcu_type": "lpc1769"}
    with patch.object(hardware, "autocomplete_select", return_value=selected), patch.object(
        hardware, "fetch_raw_config", return_value="[mcu]\nserial: /dev/ttyACM0\n") as fetch:
        assert hardware._step_board(state, [SKR14, E3], CATALOG) == selected
    fetch.assert_called_once_with(selected)
    assert state["board"] == selected
    assert state["firmware_authority"] == expected_authority
    assert state["firmware_authority_decision"]["hardware_variant_id"] == expected_variant
    if selected == E3:
        assert state["firmware_authority_decision"]["board_id"] == ""


def test_manual_catalog_mismatched_lpc_model_does_not_load_or_record_authority(capsys):
    state = {"mcu_type": "lpc1769"}
    with patch.object(hardware, "autocomplete_select", side_effect=["__search_boards__", SGEN, _BACK]), patch.object(
        hardware, "fetch_raw_config") as fetch, patch(
        "firmware.boards.runtime.resolve_firmware_authority") as authority:
        assert hardware._step_board(state, [SKR14, E3], CATALOG) == _BACK
    fetch.assert_not_called()
    authority.assert_not_called()
    assert state == {"mcu_type": "lpc1769"}
    output = capsys.readouterr().out
    assert "LPC1768" in output and "LPC1769" in output


def test_e3_identity_comes_from_existing_pinned_source_fixture():
    raw = (Path(__file__).parents[1] / "fixtures/required-board-cooling" / E3).read_text(encoding="utf-8")
    header = raw.split("[stepper_x]", 1)[0]
    assert "BIGTREETECH SKR E3" in header
    assert "LPC1769." in header and "LPC1768" not in header
    assert resolve_board_mcu(E3) == "lpc1769"


def test_auto_mode_with_only_mcu_never_assigns_first_board(monkeypatch, capsys):
    monkeypatch.setenv("KACE_AUTO", "1")
    state = {"mcu_type": "lpc1769"}
    with patch.object(hardware, "fetch_raw_config") as fetch, patch(
        "firmware.boards.runtime.resolve_firmware_authority") as authority:
        with pytest.raises(WizardExit):
            hardware._step_board(state, [SKR14, E3], CATALOG)
    assert t("catalog.auto_board_required") in capsys.readouterr().out
    assert state == {"mcu_type": "lpc1769"}
    fetch.assert_not_called()
    authority.assert_not_called()


def test_auto_mode_preserves_explicit_board_instead_of_first_candidate(monkeypatch):
    monkeypatch.setenv("KACE_AUTO", "1")
    state = {"mcu_type": "lpc1769", "board": E3}
    with patch.object(hardware, "autocomplete_select") as select, patch.object(
        hardware, "fetch_raw_config", return_value="[mcu]\nserial: /dev/ttyACM0\n") as fetch:
        assert hardware._step_board(state, [SKR14, E3], CATALOG) == E3
    select.assert_not_called()
    fetch.assert_called_once_with(E3)
    assert state["firmware_authority"] == "legacy"


@pytest.mark.parametrize("selected", [SGEN, "absent.cfg"])
def test_auto_mode_rejects_stale_or_mismatched_explicit_board(monkeypatch, selected):
    monkeypatch.setenv("KACE_AUTO", "1")
    state = {"mcu_type": "lpc1769", "board": selected}
    with patch.object(hardware, "fetch_raw_config") as fetch, patch(
        "firmware.boards.runtime.resolve_firmware_authority") as authority:
        with pytest.raises(WizardExit):
            hardware._step_board(state, [SKR14, E3], CATALOG)
    fetch.assert_not_called()
    authority.assert_not_called()
    assert state == {"mcu_type": "lpc1769", "board": selected}


def test_auto_mode_explicit_prompt_fixture_still_selects_requested_board(monkeypatch):
    import sys
    from types import SimpleNamespace
    from core import menu
    monkeypatch.setenv("KACE_AUTO", "1")
    monkeypatch.setattr(menu, "_MOCK_PROMPTS_ACTIVE", True)
    ask = Mock(return_value=E3)
    monkeypatch.setitem(sys.modules, "questionary", SimpleNamespace(
        autocomplete=Mock(return_value=SimpleNamespace(ask=ask))))
    state = {"mcu_type": "lpc1769"}
    with patch.object(hardware, "fetch_raw_config", return_value="[mcu]\nserial: /dev/ttyACM0\n") as fetch:
        assert hardware._step_board(state, [SKR14, E3], CATALOG) == E3
    ask.assert_called_once()
    fetch.assert_called_once_with(E3)
