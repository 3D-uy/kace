"""Completed installation remains distinct from generated or pending output."""

import io
import os
from unittest.mock import patch

import pytest
from wcwidth import wcswidth

from core.menu import _plain_label
from core.summary import print_installation_complete, print_summary
from core.terminal import SECTION, SUCCESS, WARNING
from core.translations import get_lang, set_lang, t


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
@pytest.mark.parametrize("columns", [32, 60, 80, 120])
@pytest.mark.parametrize("color", [False, True])
def test_completion_groups_verified_checks_and_commissioning_before_final_banner(language, columns, color):
    previous = get_lang()
    output = io.StringIO()
    try:
        set_lang(language)
        with patch("shutil.get_terminal_size", return_value=os.terminal_size((columns, 24))):
            print_installation_complete(stream=output, color=color)
        raw = output.getvalue()
        plain = _plain_label(raw)
        normalized = " ".join(plain.split())
        for key in ("title", "firmware", "configuration", "klipper", "next", "commissioning", "calibration"):
            assert " ".join(t("installation.complete." + key).split()) in normalized
        assert plain.count("HAPPY PRINTING!") == 1
        assert normalized.index(t("installation.complete.calibration")) < normalized.index("HAPPY PRINTING!")
        assert plain.rstrip().endswith("┘")
        assert all(wcswidth(line) <= columns for line in plain.splitlines())
        assert plain.count("✓") == 3
        if color:
            assert all(role in raw for role in (SECTION, SUCCESS, WARNING))
        else:
            assert "\033[" not in raw
    finally:
        set_lang(previous)


@pytest.mark.parametrize("environment", [{"NO_COLOR": "1"}, {"TERM": "dumb"}])
def test_completion_respects_plain_terminal(environment):
    output = io.StringIO()
    with patch.dict(os.environ, environment):
        print_installation_complete(stream=output)
    assert "\033[" not in output.getvalue()


def test_generation_digest_has_no_completion_banner(capsys):
    print_summary({"kinematics": "cartesian", "x_size": 300, "y_size": 300, "z_size": 350})
    output = _plain_label(capsys.readouterr().out)
    assert "HAPPY PRINTING!" not in output
    assert t("installation.complete.title") not in output
