"""Visible wizard headings and TMC help fit localized terminal displays."""
import os
import re

import pytest

from core.translations import get_lang, get_mode, set_lang, set_mode, t
from core.wizard import ui
from core.wizard.runner import PHASE_MAP, _BACK
from core.wizard.steps import hardware, sensors
from core import menu
from tests.unit.test_tmc_required_current import missing_user


@pytest.fixture(autouse=True)
def restore_ui(monkeypatch):
    language, mode = get_lang(), get_mode()
    set_mode("Beginner")
    monkeypatch.setenv("KACE_AUTO", "0")
    monkeypatch.setenv("KACE_QUIET", "0")
    monkeypatch.setattr(ui, "_SUPPRESS_HEADERS", False)
    yield
    set_lang(language)
    set_mode(mode)


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
@pytest.mark.parametrize("width", [60, 80, 120])
def test_every_visible_catalog_header_has_localized_text(monkeypatch, capsys, language, width):
    set_lang(language)
    monkeypatch.setattr("shutil.get_terminal_size", lambda **kw: os.terminal_size((width, 24)))
    for step in PHASE_MAP:
        # This is the hidden in-memory builder, not an interactive screen.
        if step == "custom_probe":
            continue
        ui._print_step_header(step, {})
        rendered = capsys.readouterr().out
        assert not re.search(r"\bwizard\.[a-z_]", rendered), (language, step, rendered)
        plain = re.sub(r"\x1b\[[0-9;]*m", "", rendered)
        assert all(len(line) <= width for line in plain.splitlines()), (step, plain)
        assert "┌" in plain and "└" in plain
        hint_key = f"wizard.step.{step}.hint"
        if step.startswith("custom_probe"):
            hint_key = "wizard.step.probe_offsets.hint" if step.endswith(("preview", "offsets")) else "wizard.custom_probe_guided_hint"
        body = " ".join(plain.replace("│", " ").split())
        assert " ".join(t(hint_key).split()) in body


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
@pytest.mark.parametrize("width", [60, 80, 120])
def test_tmc_help_wraps_without_dropping_guidance(monkeypatch, capsys, language, width):
    set_lang(language)
    monkeypatch.setattr("shutil.get_terminal_size", lambda **kw: os.terminal_size((width, 24)))
    monkeypatch.setattr(hardware, "simple_input", lambda *a, **kw: _BACK)
    assert hardware._step_tmc_currents(missing_user()) == _BACK
    plain = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
    assert all(len(line) <= width for line in plain.splitlines())
    assert " ".join(t("wizard.tmc_current.help").split()) in " ".join(plain.split())


@pytest.mark.parametrize("width", [60, 80, 120])
@pytest.mark.parametrize("answer,expected", [("<", _BACK), ("", "5.0"), ("2", "2")])
def test_long_input_keeps_help_and_navigation(monkeypatch, capsys, width, answer, expected):
    set_lang("Español")
    monkeypatch.setattr(menu, "_MOCK_PROMPTS_ACTIVE", False)
    monkeypatch.setattr("shutil.get_terminal_size", lambda **kw: os.terminal_size((width, 24)))
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or answer)
    result = menu.simple_input("Retracción Z entre mediciones, en milímetros. Revisá el espacio disponible para levantar la boquilla",
                               default="5.0", back_value=_BACK)
    assert result == expected
    rendered = capsys.readouterr().out + prompts[0]
    assert all(len(line) <= width for line in rendered.splitlines())
    assert "[Volver: <]" in rendered
    assert "Enter acepta 5.0" in " ".join(rendered.split())


def test_long_confirmation_keeps_default(monkeypatch, capsys):
    monkeypatch.setattr(menu, "_MOCK_PROMPTS_ACTIVE", False)
    monkeypatch.setattr("shutil.get_terminal_size", lambda **kw: os.terminal_size((60, 24)))
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or "")
    assert menu.yes_no("Confirmar el cambio del recorrido permitido después de comprobar físicamente el espacio disponible", default=False) is False
    rendered = capsys.readouterr().out + prompts[0]
    assert all(len(line) <= 60 for line in rendered.splitlines())
    assert "Confirmar el cambio" in rendered


def test_probe_speed_input_reserves_trailing_separator_at_114_columns(monkeypatch, capsys):
    set_lang("Español")
    monkeypatch.setattr(menu, "_MOCK_PROMPTS_ACTIVE", False)
    monkeypatch.setattr("shutil.get_terminal_size", lambda **kw: os.terminal_size((114, 29)))
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or "<")
    assert menu.simple_input(t("wizard.custom_probe_speed"), default="7", back_value=_BACK) == _BACK
    rendered = capsys.readouterr().out + prompts[0]
    assert all(len(line) <= 114 for line in rendered.splitlines())
    assert "Enter acepta 7" in " ".join(rendered.split())
    assert " ".join(t("wizard.custom_probe_speed").rstrip(":").split()) in " ".join(rendered.split())


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
def test_bltouch_manual_guidance_wraps_and_preserves_identifiers(monkeypatch, capsys, language):
    set_lang(language)
    monkeypatch.setattr("shutil.get_terminal_size", lambda **kw: os.terminal_size((80, 24)))
    monkeypatch.setattr(sensors, "_get_parsed", lambda data: {})
    aliases = [(f"EXP1_{i}", f"P0.{i}") for i in range(1, 7)]
    monkeypatch.setattr(sensors, "_get_unused_pins", lambda data: aliases)
    monkeypatch.setattr(sensors, "simple_input", lambda *a, **kw: _BACK)
    data = {"board": "generic-bigtreetech-skr-v1.4.cfg"}
    assert sensors._step_bltouch_pins(data) == _BACK
    rendered = capsys.readouterr().out
    assert all(len(line) <= 80 for line in rendered.splitlines())
    assert data["board"] in rendered
    assert all(alias in rendered for alias, _ in aliases)
    assert data == {"board": "generic-bigtreetech-skr-v1.4.cfg"}
