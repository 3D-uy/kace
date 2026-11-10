"""The pinned Klipper parser reads initial root macros and inline probe values."""
import importlib.util
from pathlib import Path

import pytest

from core.custom_probe import GuidedCustomProbeSettings
from core.generator import generate_config
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.configuration_review import _sections
from core.translations import get_lang, set_lang
from tests.unit.test_generator import _parsed, _user


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
@pytest.mark.parametrize("offset", [None, 2.000000000000001])
def test_pinned_parser_matches_reviewed_initial_layout(tmp_path, language, offset):
    source = Path(__file__).resolve().parents[2] / ".klipper-contract-source/klippy/configfile.py"
    if not source.is_file():
        pytest.skip("Pinned Klipper parser unavailable")
    spec = importlib.util.spec_from_file_location("initial_layout_klipper", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    previous = get_lang()
    try:
        set_lang(language)
        custom = GuidedCustomProbeSettings("^PB8", -12, 6, offset).to_config(language=language)
        user = _user(probe_kind="custom", custom_probe=custom, z_position_min="0",
                     macros_generated=True, web_interface="Mainsail")
        target = tmp_path / "generated" / "printer.cfg"
        target.parent.mkdir()
        generate_config(_parsed(), user, output_path=str(target), verbose=False)
        macros = target.with_name("macros.cfg").read_bytes()
        plan = build_managed_config_plan(target.read_bytes(), macros,
                                         {"printer.cfg": None, "mainsail.cfg": b"[pause_resume]\n"})
        folder = tmp_path / "config"
        folder.mkdir()
        for name, content in {**dict(plan.source_files), **{a.remote_name: a.content for a in plan.artifacts}}.items():
            if content is not None:
                path = folder / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
        root = (folder / "printer.cfg").read_text(encoding="utf-8")
        actual = module.ConfigFileReader().build_fileconfig_with_includes(root, str(folder / "printer.cfg"))
        reviewed = _sections(effective_hardware_text(plan))
        for key, value in reviewed["probe"].items():
            assert actual.get("probe", key) == value
        assert actual.getfloat("probe", "z_offset") == (offset or 0)
        assert actual.has_section("gcode_macro HOME_AND_CENTER")
        assert not (folder / "kace").exists()
    finally:
        set_lang(previous)
