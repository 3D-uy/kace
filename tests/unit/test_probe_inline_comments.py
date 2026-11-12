"""Guided probe layout changes comments only, retaining exact explicit Z values."""
import pytest

from core.custom_probe import GuidedCustomProbeSettings, parse_custom_probe_config
from core.translations import UI_STRINGS


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
@pytest.mark.parametrize("z", [None, 0, 2.000000000000001])
@pytest.mark.parametrize("pending", [False, True])
def test_guided_comments_share_aligned_parameter_lines(language, z, pending):
    model = GuidedCustomProbeSettings("^!P1.27", -9, 30, z).to_config(
        language=language, polarity_unverified=pending)
    rows = [line for line in model.config_text.splitlines() if ":" in line and not line.startswith("#")]
    assert len(rows) == 10
    assert len({line.index("#") for line in rows}) == 1
    for line in rows:
        option = line.split(":", 1)[0]
        key = "uncalibrated" if option == "z_offset" and z is None else option
        assert line.split("# ", 1)[1] == UI_STRINGS[f"wizard.probe_comment.{key}"][language]
    assert model.x_offset == -9 and model.y_offset == 30
    assert model.z_offset == (0 if z is None else z)
    assert f"pin: ^!P1.27" in model.config_text
    assert (UI_STRINGS["wizard.probe_signal.pending"][language] in model.config_text) is pending


def test_imported_block_keeps_its_comment_positions_and_bytes():
    text = "[probe]\r\n# keep above\r\npin: ^PA1 # keep inline\r\nx_offset: -9\r\ny_offset: 30\r\nz_offset: 2.000000000000001\r\n"
    model = parse_custom_probe_config(text)
    assert model.config_text == text
    assert model.z_offset == 2.000000000000001
