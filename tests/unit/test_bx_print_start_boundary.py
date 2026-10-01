"""Print strategy is user-owned; hardware dependencies remain mandatory."""
from unittest.mock import patch

import pytest

from core.board_bx_panel import PROFILE
from core.configuration_review import build_configuration_review, render_configuration_review
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from core.pin_validator import _read_pin_config
from tests.unit.test_fixed_pwm_beepers import board_case


@pytest.mark.parametrize("starter", [False, True])
@pytest.mark.parametrize("mode", ["fresh", "missing", "commented", "nested", "root", "mixed_case"])
@pytest.mark.parametrize("noop", [False, True])
def test_print_strategy_is_not_required_or_replaced_on_effective_plan(tmp_path, starter, mode, noop):
    _, board, choices = board_case(PROFILE)
    text = generate_config(board, choices, include_macros=starter,
        output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"].encode()
    assert b"BX PRINT_START is not generated" not in text
    assert not any(n.casefold() == "gcode_macro print_start" for n in _read_pin_config(text.decode())[0])
    macros = (tmp_path / "macros.cfg").read_bytes() if starter else None
    if macros:
        assert "gcode_macro PRINT_START" not in macros.decode()
    custom = b"[gcode_macro PRINT_START]\ngcode:\n  M117 User start\n"
    remote = {}
    if mode != "fresh":
        remote["printer.cfg"] = text
    if mode in ("nested", "mixed_case", "commented", "missing"):
        remote["printer.cfg"] += b"\n[include user.cfg]\n"
        remote["user.cfg"] = b"[include inner.cfg]\n"
        remote["inner.cfg"] = (custom if mode == "nested" else custom.replace(b"PRINT_START", b"Print_Start")
            if mode == "mixed_case" else b"#[gcode_macro PRINT_START]\n#gcode: M117 comment\n"
            if mode == "commented" else b"[gcode_macro START_PRINT]\ngcode: M117 other name\n")
    elif mode == "root":
        remote["printer.cfg"] += b"\n"+custom
    originals = dict(remote)
    if noop:
        remote.update({a.remote_name: a.content for a in build_managed_config_plan(text, macros, remote).artifacts})
    plan = build_managed_config_plan(text, macros, remote)
    if noop:
        assert not plan.changed_artifacts
    review = build_configuration_review(plan, selected_board=board)
    assert review.validation.valid
    notices = [m for m in review.validation.warnings if m.code.startswith("bx-print-start-")]
    assert notices == []
    from core.managed_config import effective_hardware_text
    effective = effective_hardware_text(plan)
    if mode in ("root", "nested"):
        assert custom.decode() in effective
    elif mode == "mixed_case":
        assert custom.replace(b"PRINT_START", b"Print_Start").decode() in effective
    assert not any(a.remote_name in ("user.cfg", "inner.cfg") for a in plan.changed_artifacts)
    for name in ("user.cfg", "inner.cfg"):
        if name in originals:
            assert remote[name] == originals[name]
    for language in ("English", "Español", "Português"):
        with patch("core.translations.get_mode", return_value="Beginner"):
            rendered = render_configuration_review(review, language=language)
        assert "PRINT_START" not in rendered


def test_unselected_or_mechanical_bx_cannot_add_notice(tmp_path):
    from tests.unit.test_generator import _parsed, _user
    _, foreign, _ = board_case(PROFILE)
    text = generate_config(_parsed(), _user(_profile_parsed=foreign),
        output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    assert "BX PRINT_START is not generated" not in text


def test_invalid_selected_source_stays_blocking_not_just_a_warning(tmp_path):
    _, board, choices = board_case(PROFILE)
    text = generate_config(board, choices, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"].encode()
    board.pop("_board_bx_panel_source")
    review = build_configuration_review(build_managed_config_plan(text, None, {}), selected_board=board)
    assert not review.validation.valid
    assert any(m.code == "board-electrical-dependency" for m in review.validation.errors)
    assert not any(m.code.startswith("bx-print-start-") for m in review.validation.warnings)
