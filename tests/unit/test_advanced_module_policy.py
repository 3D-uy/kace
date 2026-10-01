"""Commented references are not proof that an upstream section can be enabled."""
import pytest

from core.advanced_module_handler import get_advanced_sections, is_unsupported_section
from core.loader import load_advanced_modules_yaml, load_displays_yaml


@pytest.mark.parametrize("module, emits, unsupported", [
    ("neopixel", True, False), ("dotstar", True, False),
    ("adxl345", True, False), ("sx1509", True, False),
    ("pca9685", True, True), ("resonance_tester", False, True),
    ("lis2dw", False, True), ("mpu9250", False, True), ("palette2", False, True),
])
def test_all_nine_module_policies(module, emits, unsupported):
    section = f"{module} audit" if module != "resonance_tester" else module
    blocks = get_advanced_sections({section: {"example_field": "source value"}})
    assert bool(blocks) is emits
    assert is_unsupported_section(section) is unsupported
    if blocks:
        assert all(not line.strip() or line.lstrip().startswith("#") for line in blocks[0].splitlines())


def test_pca9685_reference_explicitly_forbids_activation_and_replication_guess():
    block, = get_advanced_sections({"pca9685 audit": {"i2c_address": "0x70"}})
    assert "# [pca9685 audit]" in block
    assert "not a valid standalone Klipper section" in block
    assert "Do not uncomment" in block
    assert "Replicape" in block
    assert "# i2c_address: 0x70" in block
    assert "[replicape]" not in block
    entry = load_displays_yaml()["display_configs"]["pca9685"]
    assert entry["status"] == "unsupported"
    assert entry["compatibility_class"] != "fully_compatible"


@pytest.mark.parametrize("module", ["neopixel", "dotstar", "adxl345", "sx1509", "pca9685"])
def test_multiline_reference_cannot_leak_active_configuration(module):
    block, = get_advanced_sections({f"{module} audit": {"notes": "line one\nline two\n[output_pin example]\npin: PA1"}})
    assert all(not line.strip() or line.lstrip().startswith("#") for line in block.splitlines())
    assert "# [output_pin example]" in block


@pytest.mark.parametrize("name", ["gcode_macro pca9685_check", "gcode_macro neopixel_on", "custom_sx1509", ""])
def test_module_name_in_unrelated_section_does_not_select_module_policy(name):
    assert get_advanced_sections({name: {"gcode": "G4 P1"}}) == []
    assert not is_unsupported_section(name)


def test_real_module_references_do_not_claim_ready_to_enable():
    schemas = load_advanced_modules_yaml()["advanced_modules"]
    assert len(schemas) == 9
    for schema in schemas:
        if schema["passthrough"] and schema["section_prefix"] != "pca9685":
            assert "Reference only" in schema["note"]
            assert "uncomment" not in schema["note"].lower()
