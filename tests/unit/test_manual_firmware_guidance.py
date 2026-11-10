"""Prepared firmware guidance preserves artifact authority and readable prose."""
from copy import deepcopy
import hashlib
import os
import re
from unittest.mock import patch

import pytest

import kace
from core.firmware_workflow import FirmwareWorkflowError
from core.terminal import SECTION, WARNING, RESET
from core.translations import get_lang, get_mode, set_lang, set_mode, t


@pytest.fixture
def presentation_settings():
    language, mode = get_lang(), get_mode()
    yield
    set_lang(language)
    set_mode(mode)


def prepared_checkpoint(tmp_path):
    source = tmp_path / "immutable" / "klipper.bin"
    source.parent.mkdir()
    source.write_bytes(b"verified firmware bytes")
    return {"state": "AWAITING_FLASH", "artifact": {
        "path": str(source), "final_filename": "firmware.bin",
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "instructions": [{"text": (
            "Use the board's documented update method for firmware.bin and "
            "retain this exact filename throughout the procedure."
        )}],
    }}


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
@pytest.mark.parametrize("mode", ["Beginner", "Advanced"])
@pytest.mark.parametrize("columns", [60, 80, 120])
def test_pending_guidance_shows_board_instructions_and_copyable_path(
    tmp_path, capsys, presentation_settings, language, mode, columns,
):
    set_lang(language)
    set_mode(mode)
    checkpoint = prepared_checkpoint(tmp_path)
    before = deepcopy(checkpoint)
    download = tmp_path / "recovery" / "firmware-downloads" / "firmware.bin"
    with patch("shutil.get_terminal_size", return_value=os.terminal_size((columns, 24))), \
         patch("core.firmware_workflow.checkpoint_path", return_value=str(tmp_path / "recovery" / "checkpoint.json")):
        kace._show_prepared_firmware(checkpoint)
    raw = capsys.readouterr().out
    output = re.sub(r"\x1b\[[0-9;]*m", "", raw)
    lines = output.splitlines()
    assert "    " + str(download) in lines
    filename_line = next(line for line in lines if t("firmware.manual.filename_label").rstrip(":") in line)
    assert filename_line.rstrip().endswith(": firmware.bin")
    assert download.read_bytes() == b"verified firmware bytes"
    assert all(len(line) <= columns for line in lines if line != "    " + str(download))
    normalized = " ".join(output.split())
    assert checkpoint["artifact"]["instructions"][0]["text"] in normalized
    assert t("firmware.manual.required") in normalized
    assert f"2. {t('firmware.manual.power_step')}" in normalized
    assert t("firmware.manual.copy_step") not in normalized
    assert t("firmware.manual.keep_open") in normalized
    assert t("firmware.manual.next_steps") not in normalized
    path_index = lines.index("    " + str(download))
    assert lines[path_index - 1] == "    " + t("firmware.manual.artifact_label")
    assert not lines[path_index - 2].strip()
    assert not lines[path_index + 1].strip()
    assert f"{SECTION}{t('firmware.manual.artifact_label')}{RESET}" in raw
    assert f"{WARNING}{download}{RESET}" in raw
    assert t("firmware.manual.prepared_title") in output
    assert checkpoint == before


def test_view_only_does_not_reissue_flash_requirement(tmp_path, capsys, presentation_settings):
    set_lang("English")
    set_mode("Beginner")
    checkpoint = prepared_checkpoint(tmp_path)
    checkpoint["state"] = "MCU_VERIFIED"
    before = deepcopy(checkpoint)
    with patch("core.firmware_workflow.checkpoint_path", return_value=str(tmp_path / "recovery" / "checkpoint.json")):
        kace._show_prepared_firmware(checkpoint, view_only=True)
    output = capsys.readouterr().out
    assert t("firmware.manual.prepared_title") in output
    assert t("firmware.manual.required") not in output
    assert t("firmware.manual.next_steps") not in output
    for key in ("firmware.manual.copy_step", "firmware.manual.power_step", "firmware.manual.keep_open"):
        assert t(key) not in output
    assert "Use the board's documented update method" not in output
    assert checkpoint == before


def test_invalid_artifact_is_not_presented_or_copied(tmp_path, capsys):
    checkpoint = prepared_checkpoint(tmp_path)
    checkpoint["artifact"]["sha256"] = "0" * 64
    with patch("core.firmware_workflow.checkpoint_path", return_value=str(tmp_path / "recovery" / "checkpoint.json")):
        with pytest.raises(FirmwareWorkflowError, match="checksum mismatch"):
            kace._show_prepared_firmware(checkpoint)
    assert not (tmp_path / "recovery").exists()
    assert not capsys.readouterr().out


def test_missing_board_instructions_still_explains_both_actions(tmp_path, capsys, presentation_settings):
    set_lang('Español')
    checkpoint = prepared_checkpoint(tmp_path)
    checkpoint['artifact']['instructions'] = []
    with patch('core.firmware_workflow.checkpoint_path', return_value=str(tmp_path/'checkpoint.json')):
        kace._show_prepared_firmware(checkpoint)
    output = ' '.join(capsys.readouterr().out.split())
    assert f"1. {t('firmware.manual.copy_step')}" in output
    assert f"2. {t('firmware.manual.power_step')}" in output
