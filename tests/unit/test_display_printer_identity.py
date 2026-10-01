"""OEM filenames identify advice, never hardware qualification (K17/K13)."""
from unittest.mock import patch

import pytest

from core.display_checker import (
    _get_printer_profiles,
    _match_printer_profile,
    check_display_compatibility,
    get_display_compat,
)


@pytest.mark.parametrize("filename, expected", [
    ("printer-creality-ender3-2018.cfg", "ender-3"),
    ("printer-creality-ender3pro-2020.cfg", "ender-3"),
    ("printer-creality-ender3-v2-2020.cfg", "ender-3-v2"),
    ("printer-creality-ender3-v2-neo-2022.cfg", None),
    ("printer-creality-ender3-s1-2021.cfg", None),
    ("printer-creality-ender3-s1plus-2022.cfg", None),
    ("printer-creality-ender3max-2021.cfg", None),
    ("printer-creality-ender6-2020.cfg", None),
    ("printer-creality-ender-3.cfg", "ender-3"),
    ("printer-creality-ender-3-v2.cfg", "ender-3-v2"),
    ("printer-cr6-se.cfg", "cr6-se"),
    ("printer-creality-cr6-se.cfg", "cr6-se"),
    ("printer-artillery-sidewinder-x1.cfg", "artillery-sidewinder"),
])
def test_real_variants_and_explicit_legacy_aliases(filename, expected):
    assert _match_printer_profile(filename)[0] == expected


@pytest.mark.parametrize("filename", [
    "printer-creality-ender3-v2-2020.cfg",
    "printer-creality-ender-3-v2.cfg",
    " PRINTER-CREALITY-ENDER3-V2-2020.CFG ",
])
@pytest.mark.parametrize("reverse", [False, True])
def test_v2_diagnostic_has_specific_identity_without_positive_hardware_advice(filename, reverse):
    items = list(_get_printer_profiles().items())
    with patch("core.display_checker._get_printer_profiles", return_value=dict(items[::-1] if reverse else items)):
        finding, = check_display_compatibility({}, filename)
        assert finding["printer_profile"] == "ender-3-v2"
        assert finding["section"] == "dwin_set"
        assert finding["source"] == "printer_profile"
        assert finding["hardware_evidence"] == "unknown"
        assert finding["status"] == "untested"
        assert not finding["required_modifications"]
        static = get_display_compat("display", filename)
        assert static["source"] == "printer_profile"
        assert static["hardware_evidence"] == "unknown"
        assert not static["required_modifications"]


@pytest.mark.parametrize("filename", [
    "printer-creality-ender-3-v2-custom.cfg",
    "printer-creality-ender3-v2-2020.cfg.bak",
    "copy-printer-creality-ender3-v2-2020.cfg",
    "config/printer-creality-ender3-v2-2020.cfg",
    "config\\printer-creality-ender3-v2-2020.cfg",
    "printer-voron-custom.cfg",
    "generic-mks-robin-new.cfg",
    "generic-bigtreetech-octopus-new.cfg",
    "printer-cr6-se-custom.cfg",
    "ender-3-v2",
    "",
])
def test_substrings_suffixes_and_paths_do_not_inherit_an_oem_display(filename):
    assert _match_printer_profile(filename) == (None, None)
    assert check_display_compatibility({}, filename) == []
    # An unbound name must not suppress an actual unsupported config section.
    finding, = check_display_compatibility({"t5uid1": {}}, filename)
    assert finding["source"] == "display_config"
    assert finding["compatibility_class"] == "unsafe"


@pytest.mark.parametrize("field", ["config_filenames", "filename_aliases"])
def test_ambiguous_binding_is_an_error_even_when_other_profile_would_match(field):
    profiles = {
        "generic": {"config_filenames": ["printer-example.cfg"]},
        "specific": {field: ["printer-example.cfg"]},
    }
    with patch("core.display_checker._get_printer_profiles", return_value=profiles):
        with pytest.raises(RuntimeError, match="ambiguous OEM filename"):
            _match_printer_profile("printer-example.cfg")


@pytest.mark.parametrize("binding", ["printer-example.cfg", None, [None], [""],
                                      ["Example.cfg"], ["printer-example"],
                                      ["dir/example.cfg"], ["dir\\example.cfg"]])
def test_malformed_binding_cannot_become_a_substring_match(binding):
    with patch("core.display_checker._get_printer_profiles", return_value={
        "example": {"config_filenames": binding},
    }):
        with pytest.raises(RuntimeError, match="invalid OEM"):
            _match_printer_profile("printer-example.cfg")


def test_all_declared_identities_resolve_without_bypassing_k13():
    profiles = _get_printer_profiles()
    for key, profile in profiles.items():
        for name in profile["config_filenames"] + profile["filename_aliases"]:
            assert _match_printer_profile(name)[0] == key
            result = get_display_compat("display", name)
            assert result["source"] == "printer_profile"
            if profile["compatibility_class"] == "unsafe":
                assert result["compatibility_class"] == "unsafe"
            else:
                assert result["hardware_evidence"] == "unknown"
                assert not result["required_modifications"]
