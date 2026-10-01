"""Line endings do not change source authority; content edits still do."""
import hashlib

import pytest

from core.board_bx_panel import PROFILE, SOURCE_PANEL, reviewed_panel
from core.board_pwm import SOURCE_FIXED_PWM, reviewed_beepers
from core.generator import generate_config
from core.reviewed_source import matches_reviewed_source
from core.scraper import parse_config
from tests.unit.test_fixed_pwm_beepers import board_case


@pytest.mark.parametrize("manifest_ending", ["\n", "\r\n"])
@pytest.mark.parametrize("actual_ending", ["\n", "\r\n"])
def test_only_line_endings_can_differ(manifest_ending, actual_ending):
    text = "[fan]\npin: PA6\n# reviewed consumer\n"
    digest = hashlib.sha256(text.replace("\n", manifest_ending).encode()).hexdigest()
    actual = text.replace("\n", actual_ending)
    assert matches_reviewed_source(actual, digest)
    for mutated in (actual + actual_ending, actual.replace("PA6", "PA7"), actual.replace("consumer", "other"),
                    actual.replace("pin:", "pin: "), actual.rstrip(), actual.replace(actual_ending, "\r")):
        assert not matches_reviewed_source(mutated, digest)


@pytest.mark.parametrize("profile", list(reviewed_beepers()))
@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_reviewed_board_generation_equivalent_across_line_endings(tmp_path, profile, ending):
    raw, board, choices = board_case(profile)
    text = raw.replace("\r\n", "\n").replace("\n", ending)
    normalized = parse_config(text, profile, keep_comments=True)
    assert normalized[SOURCE_FIXED_PWM] == board[SOURCE_FIXED_PWM]
    if profile == PROFILE:
        assert normalized[SOURCE_PANEL] == board[SOURCE_PANEL] == reviewed_panel()
    expected = generate_config(board, choices, output_path=str(tmp_path / "original.cfg"), verbose=False)["content"]
    actual = generate_config(normalized, choices, output_path=str(tmp_path / "normalized.cfg"), verbose=False)["content"]
    assert actual == expected
    changed = parse_config(text.replace("pwm: True", "pwm: False"), profile, keep_comments=True)
    assert SOURCE_FIXED_PWM not in changed or changed[SOURCE_FIXED_PWM] is None
    if profile == PROFILE:
        assert SOURCE_PANEL not in changed or changed[SOURCE_PANEL] is None
