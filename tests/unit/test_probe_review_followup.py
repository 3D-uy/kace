"""Deferred calibration remains a compact travel review, never an implicit edit."""
import copy
import os

import pytest

from core.menu import _plain_label
from core.translations import get_lang, set_lang, t
from core.wizard.steps.probe_homing import review_probe_homing_geometry
from tests.unit.test_probe_deferred_z_review import deferred_user


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
def test_incompatible_deferred_review_stays_short_and_cancel_preserves_values(monkeypatch, capsys, language):
    previous = get_lang()
    set_lang(language)
    monkeypatch.setenv("KACE_AUTO", "0")
    monkeypatch.setattr("core.wizard.steps.probe_homing.shutil.get_terminal_size",
                        lambda **kw: os.terminal_size((100, 40)))
    try:
        user = deferred_user()
        original = copy.deepcopy(user)
        answers = iter(["n", "cancel"])
        monkeypatch.setattr("builtins.input", lambda *a: next(answers))
        assert review_probe_homing_geometry(user) is False
        assert user == original
        text = _plain_label(capsys.readouterr().out)
        assert "0.5" in text and "0 mm" in text
        assert "PROBE_CALIBRATE" in text and "SAVE_CONFIG" in text
        assert len([line for line in text.splitlines() if line.strip()]) <= 15
        assert len(t("wizard.probe_z.deferred_context").split()) <= 25
        assert len(t("wizard.probe_z.deferred_minimum", minimum="0.5").split()) <= 45
    finally:
        set_lang(previous)
