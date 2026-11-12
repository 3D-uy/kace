"""Accepted profile edits retain the geometry and ownership used by generation."""

import copy
from pathlib import Path

import pytest

from core.generator import generate_config
from core.profile_values import mark_profile_values, resolve_generation_values, safe_defaults
from core.scraper import extract_profile_defaults, parse_config
from core.translations import get_lang, set_lang
from core.wizard.steps import motion
from tests.unit.test_generator import _user


@pytest.fixture
def profile_editor(monkeypatch):
    previous_language = get_lang()
    set_lang("English")
    monkeypatch.setenv("KACE_AUTO", "0")
    monkeypatch.setattr(motion, "_INTERACTIVE_MODE", False)
    name = "printer-creality-ender3-v2-2020.cfg"
    raw = (Path(__file__).resolve().parents[1] / "fixtures" /
           "board-profile-authority" / name).read_text(encoding="utf-8")
    parsed = parse_config(raw, name)
    defaults = extract_profile_defaults(parsed)
    data = {**safe_defaults(), **_user(), **defaults, "profile_loaded": True,
            "board": name, "printer_profile": name, "board_parsed": copy.deepcopy(parsed),
            "_profile_parsed": parsed, "_profile_defaults": defaults, "raw_config": raw}
    mark_profile_values(data, parsed)

    def run(answers):
        inputs = iter(answers)
        monkeypatch.setattr("builtins.input", lambda *args: next(inputs))
        result = motion._step_profile_editor_inner(defaults, parsed, data)
        assert next(inputs, None) is None
        return result

    yield data, defaults, parsed, run
    set_lang(previous_language)


@pytest.mark.parametrize("axis", "xyz")
def test_volume_expansion_persists_reviewed_limits_through_generation(profile_editor, tmp_path, axis):
    data, defaults, parsed, run = profile_editor
    source = copy.deepcopy(data["_profile_parsed"])
    sizes = ["300" if item == axis else data[f"{item}_size"] for item in "xyz"]
    assert run(["volume", *sizes, "save"]) == "save"

    resolved, provenance = resolve_generation_values(data["board_parsed"], data)
    for current in "xyz":
        key = f"{current}_position_max"
        expected = "300" if current == axis else source[f"stepper_{current}"]["position_max"]
        assert data[key] == defaults[key] == parsed[f"stepper_{current}"]["position_max"] == expected
        assert resolved[key] == expected
        assert provenance[key] == ("USER_OVERRIDE" if current == axis else "PROFILE")
    motion.normalize_and_validate_configuration({**data, **resolved})

    # The imported profile remains source evidence; user edits have their own ownership.
    assert data["_profile_parsed"] == source
    generated = generate_config(data["board_parsed"], data,
                                output_path=str(tmp_path / "printer.cfg"), verbose=False)
    output = parse_config(generated["content"], "printer.cfg")
    assert output[f"stepper_{axis}"]["position_max"] == "300"
    assert generated["value_provenance"][f"{axis}_position_max"] == "USER_OVERRIDE"


@pytest.mark.parametrize("axis", "xyz")
def test_smaller_volume_keeps_profile_physical_limits(profile_editor, axis):
    data, defaults, parsed, run = profile_editor
    maximum = data[f"{axis}_position_max"]
    sizes = ["200" if item == axis else data[f"{item}_size"] for item in "xyz"]
    assert run(["volume", *sizes, "save"]) == "save"
    resolved, provenance = resolve_generation_values(data["board_parsed"], data)
    assert resolved[f"{axis}_position_max"] == maximum
    assert provenance[f"{axis}_position_max"] == "PROFILE"
    assert data[f"printable_{axis}_max"] == "200"


@pytest.mark.parametrize("cancel_at", [0, 1, 2])
def test_cancelled_volume_entry_preserves_profile_and_provenance(profile_editor, cancel_at):
    data, defaults, parsed, run = profile_editor
    before = copy.deepcopy((data, defaults, parsed))
    assert run(["volume", *["300"] * cancel_at, "<", "back"]) == "back"
    assert (data, defaults, parsed) == before


def test_discard_after_complete_volume_entry_preserves_all_sources(profile_editor):
    data, defaults, parsed, run = profile_editor
    before = copy.deepcopy((data, defaults, parsed))
    assert run(["volume", "300", "300", "300", "back"]) == "back"
    assert (data, defaults, parsed) == before


def test_save_rejects_geometry_rejected_by_generation(profile_editor, capsys):
    data, defaults, parsed, run = profile_editor
    # A stale draft must not hide an incompatible authoritative profile minimum.
    parsed["stepper_x"]["position_min"] = "10"
    data["_value_provenance"]["x_position_min"] = "PROFILE"
    before = copy.deepcopy((data, defaults, parsed))
    assert run(["volume", "235", "235", "250", "save", "back"]) == "back"
    assert "Configuration Validation Failed" in capsys.readouterr().out
    assert (data, defaults, parsed) == before
