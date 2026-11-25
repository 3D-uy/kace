"""Display warnings and hardware notes in generated config files."""
import pytest

from core.generator import _render_display_blocks
from core.loader import load_displays_yaml
from core.translations import get_lang, set_lang
from core.translations._display_comments import display_comment


@pytest.fixture(params=["English", "Español", "Português"])
def language(request):
    previous = get_lang()
    set_lang(request.param)
    yield request.param
    set_lang(previous)


@pytest.mark.parametrize("choice", [None, "override:t5uid1"])
def test_unsafe_display_keeps_warning_and_inactive_fields_in_all_languages(language, choice):
    parsed = {"t5uid1": {"data_pin": "PC0", "label": "Prueba São José"}}
    text = _render_display_blocks({"display_choice": choice}, {}, parsed)
    assert "# [t5uid1]" in text and "\n[t5uid1]" not in text
    assert "# label: Prueba São José" in text
    assert text.replace("Prueba São José", "").isascii()
    assert "====" not in text
    danger, instruction = {
        "English": ("DANGER", "DISCONNECT the display"),
        "Español": ("PELIGRO", "DESCONECTA la pantalla"),
        "Português": ("PERIGO", "DESCONECTE a tela"),
    }[language]
    assert danger in text and instruction in text
    assert "# data_pin: TODO #" in text and "PC0" in text


def test_display_catalog_notes_have_plain_translations(language):
    catalog = load_displays_yaml()
    entries = list(catalog["display_configs"].values())
    for displays in catalog["board_display_matrix"].values():
        entries.extend(displays.values())
    for entry in entries:
        for field in ("damage_risks", "required_modifications", "notes"):
            for source in entry.get(field, []):
                text = display_comment(source)
                assert text.isascii()
                if language != "English":
                    assert text != source, source
                if "≥" in source:
                    assert ">=" in text
