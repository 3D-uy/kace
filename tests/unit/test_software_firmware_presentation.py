"""User choices and review output preserve existing configuration authority."""
from copy import deepcopy
import os
from unittest.mock import patch

import pytest

from core import menu
from core.exceptions import WizardExit
from core.firmware_wizard import _print_board_contract_firmware_review, run_firmware_wizard
from core.menu import _plain_label
from core.summary import print_summary
from core.translations import get_lang, set_lang, t
from core.wizard.runner import _BACK
from core.wizard.steps.software import _step_web_ui
from firmware.boards.runtime import resolve_firmware_authority


@pytest.fixture(autouse=True)
def restore_language():
    previous = get_lang()
    yield
    set_lang(previous)


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
def test_both_interfaces_preserve_existing_include_after_conflicting_choice(tmp_path, capsys, language):
    set_lang(language)
    cfg = tmp_path / "printer.cfg"
    original = "# user comment\n[include mainsail.cfg]\n[include custom.cfg]\n"
    cfg.write_text(original, encoding="utf-8")
    (tmp_path / "mainsail.cfg").write_text("# existing macros\n", encoding="utf-8")
    (tmp_path / "custom.cfg").write_text("# custom\n", encoding="utf-8")
    state = {"web_interface": "Mainsail"}
    with patch("core.dashboard.get_printer_cfg_path", return_value=str(cfg)), \
         patch("core.dashboard._detect_webui", return_value=True), \
         patch("core.menu._check_questionary_mock", return_value=menu._MOCK_DEFAULT), \
         patch.dict(os.environ, {"KACE_AUTO": "0"}), \
         patch("builtins.input", side_effect=["2", "1"]):
        assert _step_web_ui(state) == "None"
    output = " ".join(_plain_label(capsys.readouterr().out).split())
    assert " ".join(t("software.both_detected").split()) in output
    assert " ".join(t("software.include_conflict", selected="Fluidd", existing="Mainsail").split()) in output
    assert state == {"web_interface": "None", "web_interface_preserved": ["Mainsail"],
                     "web_interface_review_required": False}
    assert cfg.read_text(encoding="utf-8") == original
    from core.managed_config import _reconcile_root
    reconciled, _, _ = _reconcile_root(original, "[printer]\nkinematics: cartesian\n", False)
    assert reconciled.count("[include mainsail.cfg]") == 1
    assert "[include fluidd.cfg]" not in reconciled
    assert "[include custom.cfg]" in reconciled and "# user comment" in reconciled


@pytest.mark.parametrize("answer, expected", [("1", "Mainsail"), ("2", "Fluidd"), ("3", "None")])
def test_both_interfaces_without_existing_include_keeps_single_choice(tmp_path, answer, expected):
    state = {}
    with patch("core.dashboard.get_printer_cfg_path", return_value=str(tmp_path / "missing.cfg")), \
         patch("core.dashboard._detect_webui", return_value=True), \
         patch("core.menu._check_questionary_mock", return_value=menu._MOCK_DEFAULT), \
         patch.dict(os.environ, {"KACE_AUTO": "0"}), \
         patch("builtins.input", return_value=answer):
        assert _step_web_ui(state) == expected
    assert state == {"web_interface": expected, "web_interface_preserved": [],
                     "web_interface_review_required": False}


@pytest.mark.parametrize("answers", [["4"], ["2", "3"], ["2", "2", "4"]])
def test_back_from_software_and_conflict_leaves_state_unchanged(tmp_path, answers):
    cfg = tmp_path / "printer.cfg"
    cfg.write_text("[include mainsail.cfg]\n", encoding="utf-8")
    (tmp_path / "mainsail.cfg").write_text("# existing macros\n", encoding="utf-8")
    state = {"web_interface": "Mainsail", "web_interface_preserved": ["original"]}
    before = deepcopy(state)
    with patch("core.dashboard.get_printer_cfg_path", return_value=str(cfg)), \
         patch("core.dashboard._detect_webui", return_value=True), \
         patch("core.menu._check_questionary_mock", return_value=menu._MOCK_DEFAULT), \
         patch.dict(os.environ, {"KACE_AUTO": "0"}), \
         patch("builtins.input", side_effect=answers):
        assert _step_web_ui(state) == _BACK
    assert state == before


@pytest.mark.parametrize("answers", [["2", "1"], ["1"]])
def test_nested_interface_include_is_preserved_without_adding_root_include(tmp_path, answers):
    files = {"printer.cfg": "# root\n[include custom.cfg]\n",
             "custom.cfg": "# user macros\n[include mainsail.cfg]\n",
             "mainsail.cfg": "# Mainsail\n"}
    for name, content in files.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    state = {}
    with patch("core.dashboard.get_printer_cfg_path", return_value=str(tmp_path / "printer.cfg")), \
         patch("core.dashboard._detect_webui", return_value=True), \
         patch("core.menu._check_questionary_mock", return_value=menu._MOCK_DEFAULT), \
         patch.dict(os.environ, {"KACE_AUTO": "0"}), \
         patch("builtins.input", side_effect=answers):
        assert _step_web_ui(state) == "None"
    assert state["web_interface_preserved"] == ["Mainsail"]
    assert state["web_interface_review_required"] is False
    from core.managed_config import _reconcile_root
    root, _, _ = _reconcile_root(files["printer.cfg"], "[printer]\nkinematics: cartesian\n", False)
    assert "[include mainsail.cfg]" not in root and "[include fluidd.cfg]" not in root
    assert "[include custom.cfg]" in root
    for name, content in files.items():
        assert (tmp_path / name).read_text(encoding="utf-8") == content


@pytest.mark.parametrize("content", ["[include missing.cfg]\n", "[include extras/*.cfg]\n",
                                    "[include ../outside.cfg]\n"])
@pytest.mark.parametrize("answer", ["1", "2"])
def test_unreviewable_include_graph_only_allows_preserving_or_back(tmp_path, content, answer, capsys):
    cfg = tmp_path / "printer.cfg"
    cfg.write_text(content, encoding="utf-8")
    state = {"web_interface": "Fluidd"}
    before = deepcopy(state)
    with patch("core.dashboard.get_printer_cfg_path", return_value=str(cfg)), \
         patch("core.dashboard._detect_webui", return_value=True), \
         patch("core.menu._check_questionary_mock", return_value=menu._MOCK_DEFAULT), \
         patch.dict(os.environ, {"KACE_AUTO": "0"}), \
         patch("builtins.input", return_value=answer):
        result = _step_web_ui(state)
    if answer == "1":
        assert result == "None" and state["web_interface_review_required"] is True
    else:
        assert result == _BACK and state == before
    output = " ".join(_plain_label(capsys.readouterr().out).split())
    assert " ".join(t("software.includes_unverified").split()) in output
    assert cfg.read_text(encoding="utf-8") == content


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
@pytest.mark.parametrize("columns", [60, 80, 120])
def test_contract_summary_details_and_warning_are_contextual(language, columns, capsys):
    set_lang(language)
    decision = resolve_firmware_authority("generic-bigtreetech-skr-v1.4.cfg", detected_mcu="lpc1769")
    before = deepcopy(decision)
    with patch("shutil.get_terminal_size", return_value=os.terminal_size((columns, 24))):
        _print_board_contract_firmware_review(decision, detected_mcu="lpc1769")
        output = _plain_label(capsys.readouterr().out)
        assert "CONFIG_" not in output
        assert "LPC1769" in output
        assert " ".join(t("firmware.review.exact_mcu").split()) not in " ".join(output.split())
        assert " ".join(t("firmware.review.filename").split()) in " ".join(output.split())
        assert all(len(line) <= columns for line in output.splitlines())
        _print_board_contract_firmware_review(decision, detected_mcu="lpc1769", details=True)
        details = " ".join(_plain_label(capsys.readouterr().out).split())
        assert "CONFIG_MACH_LPC1769=y" in details
        assert " ".join(t("firmware.review.exact_mcu").split()) in details
        _print_board_contract_firmware_review(decision, detected_mcu="lpc1768")
        mismatch = " ".join(_plain_label(capsys.readouterr().out).split())
        assert " ".join(t("firmware.review.exact_mcu").split()) in mismatch
    assert decision == before


def test_details_then_skip_never_builds_or_mutates_geometry():
    state = {"board": "generic-bigtreetech-skr-v1.4.cfg", "mcu_type": "lpc1769",
             "x_position_min": -5, "z_position_min": 0.5, "probe_z_offset": 3}
    with patch("core.menu._check_questionary_mock", return_value=menu._MOCK_DEFAULT), \
         patch.dict(os.environ, {"KACE_AUTO": "0"}), \
         patch("builtins.input", side_effect=["2", "3"]), \
         patch("core.firmware_wizard.build_board_contract_runtime") as build:
        result = run_firmware_wizard(state)
    build.assert_not_called()
    assert state["firmware_compilation_skipped"] is True
    assert (state["x_position_min"], state["z_position_min"], state["probe_z_offset"]) == (-5, 0.5, 3)
    assert result.outcome.name == "DEPLOYED_PENDING_ACTIVATION"


def test_unknown_variant_still_blocks_before_build_or_selection():
    with patch("core.firmware_wizard.numbered_select") as select, \
         patch("core.firmware_wizard.build_board_contract_runtime") as build:
        result = run_firmware_wizard({"board": "generic-bigtreetech-skr-v1.4.cfg", "mcu_type": "lpc176x"})
    select.assert_not_called()
    build.assert_not_called()
    assert result.outcome.name == "FIRMWARE_FAILED"


def test_contract_menu_cancellation_remains_cancellation():
    with patch("core.firmware_wizard.numbered_select", side_effect=WizardExit), \
         patch("core.firmware_wizard.build_board_contract_runtime") as build, \
         pytest.raises(WizardExit):
        run_firmware_wizard({"board": "generic-bigtreetech-skr-v1.4.cfg", "mcu_type": "lpc1769"})
    build.assert_not_called()


def test_summary_reports_preserved_include_and_real_pending_firmware(capsys):
    state = {"probe": "None", "web_interface": "None", "web_interface_preserved": ["Mainsail"],
             "pending_firmware_deployment": True}
    before = deepcopy(state)
    print_summary(state)
    output = " ".join(_plain_label(capsys.readouterr().out).split())
    assert " ".join(t("software.preserved", includes="Mainsail").split()) in output
    assert " ".join(t("summary.firmware_pending_step").split()) in output
    assert state == before
