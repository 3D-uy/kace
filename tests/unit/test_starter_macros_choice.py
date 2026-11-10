"""Starter macro consent is collected before firmware and survives recovery."""
import copy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core import menu, wizard
from core.deployer import _generated_config_bytes, _run_config_transaction
from core.exceptions import WizardExit
from core.firmware_workflow import create_checkpoint, restore_wizard_data
from core.generator import generate_config
from core.managed_config import build_managed_config_plan, MACROS_REMOTE
from core.translations import get_lang, get_mode, set_lang, set_mode, t
from core.wizard.runner import WizardRunner, _BACK
from core.wizard.steps.software import _step_starter_macros
from core.workflow_outcome import WorkflowOutcome
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_probe_review_navigation import actual_catalog


@pytest.fixture(autouse=True)
def interactive(monkeypatch):
    language, mode = get_lang(), get_mode()
    set_lang("English")
    monkeypatch.setenv("KACE_AUTO", "0")
    monkeypatch.setattr(menu, "_MOCK_PROMPTS_ACTIVE", False)
    yield
    set_lang(language)
    set_mode(mode)


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
@pytest.mark.parametrize("mode", ["Beginner", "Advanced"])
@pytest.mark.parametrize("answer,expected", [("1", True), ("2", False)])
def test_macro_question_is_visible_in_both_modes_and_records_only_choice(
        monkeypatch, capsys, language, mode, answer, expected):
    set_lang(language)
    set_mode(mode)
    user = {"web_interface": "None", "geometry": {"x": -30}}
    original = copy.deepcopy(user)
    monkeypatch.setattr("builtins.input", lambda *a: answer)
    assert _step_starter_macros(user) == "done"
    assert user == {**original, "macros_generated": expected}
    normalized = " ".join(menu._plain_label(capsys.readouterr().out).split())
    assert " ".join(t("kace.generate_macros_prompt").split()) in normalized
    assert "macros.cfg" in normalized
    assert "software." not in normalized


@pytest.mark.parametrize("prior", [None, False, True])
def test_enter_preserves_saved_answer_or_original_yes_default(monkeypatch, prior):
    user = {} if prior is None else {"macros_generated": prior}
    monkeypatch.setattr("builtins.input", lambda *a: "")
    assert _step_starter_macros(user) == "done"
    assert user["macros_generated"] is (True if prior is None else prior)


@pytest.mark.parametrize("answer", ["3", "<", "4", "q"])
def test_back_and_quit_do_not_mutate_existing_choice(monkeypatch, answer):
    user = {"macros_generated": False, "web_interface": "Mainsail"}
    original = copy.deepcopy(user)
    monkeypatch.setattr("builtins.input", lambda *a: answer)
    if answer in ("3", "<"):
        assert _step_starter_macros(user) == _BACK
    else:
        with pytest.raises(WizardExit):
            _step_starter_macros(user)
    assert user == original


@pytest.mark.parametrize("answer,expected", [("1", True), ("2", False)])
def test_actual_wizard_asks_after_web_interface_without_firmware_work(
        monkeypatch, tmp_path, answer, expected):
    responses = iter(["3", answer])
    monkeypatch.setattr("builtins.input", lambda *a: next(responses))
    monkeypatch.setattr(wizard, "discover_mcu", lambda: {})
    monkeypatch.setattr(wizard, "fetch_config_list", lambda *a, **k: [])
    monkeypatch.setattr("core.dashboard.get_printer_cfg_path", lambda: str(tmp_path / "missing.cfg"))
    monkeypatch.setattr("core.dashboard._detect_webui", lambda *a: False)
    with patch("core.macro_generator.generate_starter_macros") as generate:
        result = wizard.run_wizard({"start_step": "web_ui"})
    assert result["web_interface"] == "None"
    assert result["macros_generated"] is expected
    generate.assert_not_called()
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(StopIteration):
        next(responses)


def test_back_from_macros_reopens_web_interface_and_can_finish(monkeypatch, tmp_path):
    catalog = actual_catalog()
    responses = iter(["3", "3", "1", "1"])
    monkeypatch.setattr("builtins.input", lambda *a: next(responses))
    monkeypatch.setattr("core.dashboard.get_printer_cfg_path", lambda: str(tmp_path / "missing.cfg"))
    monkeypatch.setattr("core.dashboard._detect_webui", lambda *a: False)
    runner = WizardRunner(catalog, ["web_ui", "starter_macros"], {"macros_generated": False})
    result = runner.run("web_ui")
    assert result["web_interface"] == "Mainsail"
    assert result["macros_generated"] is True
    assert runner.history_stack == ["web_ui", "starter_macros"]
    with pytest.raises(StopIteration):
        next(responses)


@pytest.mark.parametrize("answer,expected", [("1", True), ("2", False)])
def test_macro_decision_is_in_first_firmware_checkpoint(monkeypatch, answer, expected):
    user = {"board": "generic-bigtreetech-skr-v1.4.cfg", "mcu_type": "lpc1769"}
    monkeypatch.setattr("builtins.input", lambda *a: answer)
    _step_starter_macros(user)
    saved = create_checkpoint(user, identity_reader=SimpleNamespace(read=lambda path: None))
    assert saved["state"] == "HARDWARE_SELECTED"
    assert saved["wizard_data"]["macros_generated"] is expected
    assert restore_wizard_data(saved["wizard_data"])["macros_generated"] is expected


@pytest.mark.parametrize("selected", [False, True])
def test_generation_reader_and_managed_plan_respect_saved_choice(monkeypatch, tmp_path, selected):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    folder = tmp_path / "kace"
    folder.mkdir()
    macros_path = folder / "macros.cfg"
    macros_path.write_bytes(b"# leftover from a previous run\n")
    user = _user(macros_generated=selected, web_interface="None")
    generate_config(_parsed(), user, output_path=str(folder / "printer.cfg"), verbose=False)
    path, hardware, macros = _generated_config_bytes(user)
    assert Path(path) == folder / "printer.cfg"
    assert hardware == (folder / "printer.cfg").read_bytes()
    assert b"[include macros.cfg]" not in hardware
    if selected:
        assert macros == macros_path.read_bytes()
        assert b"[gcode_macro TEST_MOVEMENT]" in macros
    else:
        assert macros is None
        assert macros_path.read_bytes() == b"# leftover from a previous run\n"
    plan = build_managed_config_plan(hardware, macros, {"printer.cfg": None})
    files = {item.remote_name: item.content for item in plan.artifacts}
    assert ("macros.cfg" in files) is selected
    assert (b"[include macros.cfg]" in files["printer.cfg"]) is selected


def test_requested_missing_bundle_fails_instead_of_silently_omitting_it(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    folder = tmp_path / "kace"
    folder.mkdir()
    (folder / "printer.cfg").write_text("[mcu]\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="macros.cfg"):
        _generated_config_bytes({"macros_generated": True})
    transport = FakeTransport()
    result = _run_config_transaction(transport, {"macros_generated": True}, "none")
    assert result.outcome is WorkflowOutcome.PRECONDITION_FAILED
    assert "macros.cfg" in result.detail
    assert not transport.calls


def test_saved_no_does_not_remove_existing_user_macros(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    folder = tmp_path / "kace"
    folder.mkdir()
    user = _user(macros_generated=False, web_interface="None")
    generate_config(_parsed(), user, output_path=str(folder / "printer.cfg"), verbose=False)
    _, hardware, macros = _generated_config_bytes(user)
    existing = {"printer.cfg": b"[include macros.cfg]\n", "macros.cfg": b"# user-owned macros\n"}
    original = copy.deepcopy(existing)
    plan = build_managed_config_plan(hardware, macros, existing)
    assert all(item.remote_name not in ("macros.cfg", MACROS_REMOTE) for item in plan.artifacts)
    assert b"[include macros.cfg]" in next(a.content for a in plan.artifacts if a.remote_name == "printer.cfg")
    assert existing == original


@pytest.mark.parametrize("legacy_include", [False, True])
def test_legacy_reader_without_decision_retains_include_contract(monkeypatch, tmp_path, legacy_include):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    folder = tmp_path / "kace"
    folder.mkdir()
    (folder / "printer.cfg").write_bytes(b"[mcu]\n" + (b"[include macros.cfg]\n" if legacy_include else b""))
    (folder / "macros.cfg").write_bytes(b"# legacy\n")
    assert _generated_config_bytes()[2] == (b"# legacy\n" if legacy_include else None)
