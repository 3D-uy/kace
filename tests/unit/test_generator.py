# tests/unit/test_generator.py
#
# Unit tests for core/generator.py — generate_config() and has_todo_pins().
#
# Design decisions:
#   - All tests use output_path=<tempfile> to avoid touching ~/kace/printer.cfg.
#   - MINIMAL_PARSED / MINIMAL_USER_DATA are defined once so individual tests
#     only override the key they care about.
#   - generate_config() mutates user_data in-place (known side-effect). Each test
#     receives a fresh copy so they are independent.
#   - No network, no questionary, no git — fully offline.
#   - Requires jinja2. Tests are skipped on the Windows host where only the
#     Docker environment has the full dependency stack.

import copy
import os
import tempfile
import unittest
from unittest.mock import patch

try:
    import jinja2  # noqa: F401
    _JINJA2_AVAILABLE = True
except ImportError:
    _JINJA2_AVAILABLE = False

_skip_no_jinja2 = unittest.skipUnless(
    _JINJA2_AVAILABLE,
    "jinja2 not installed — generator tests run in Docker only",
)

if _JINJA2_AVAILABLE:
    from core.generator import generate_config, has_todo_pins
    from core.exceptions import GenerationError
else:
    generate_config = None
    has_todo_pins = None
    class GenerationError(Exception):
        pass


# ── Shared test fixtures ──────────────────────────────────────────────────────

# Minimal parsed board config with all required pins present.
# Using recognizable but fake pin names so we can assert they appear in output.
_PARSED_COMPLETE = {
    "stepper_x": {
        "step_pin": "PA1",
        "dir_pin": "PA2",
        "enable_pin": "!PA3",
        "endstop_pin": "PB0",
    },
    "stepper_y": {
        "step_pin": "PC1",
        "dir_pin": "PC2",
        "enable_pin": "!PC3",
        "endstop_pin": "PB1",
    },
    "stepper_z": {
        "step_pin": "PD1",
        "dir_pin": "PD2",
        "enable_pin": "!PD3",
        "endstop_pin": "PB2",
    },
    "extruder": {
        "step_pin": "PE1",
        "dir_pin": "PE2",
        "enable_pin": "!PE3",
        "heater_pin": "PA4",
        "sensor_pin": "PA5",
    },
    "heater_bed": {
        "heater_pin": "PA6",
        "sensor_pin": "PA7",
    },
    "fan": {"pin": "PC5"},
}

# Minimal user data dict that produces a clean, valid config.
_USER_DATA_BASE = {
    "mcu_path": "/dev/serial/by-id/usb-test-if00",
    "board": "test-board.cfg",
    "printer_profile": "test-board.cfg",
    "kinematics": "cartesian",
    "x_size": "235",
    "y_size": "235",
    "z_size": "250",
    "probe": "None",
    "driver_type": "None (Standard)",
    "driver_mode": "Standalone",
    "hotend_thermistor": "EPCOS 100K B57560G104F",
    "bed_thermistor": "EPCOS 100K B57560G104F",
    "web_interface": "None",
    "z_motors": "1",
    "motors": "4",
    "extruder": "1",
    "runout": "No",
    "language": "en",
    "gear_ratio_x": None,
    "gear_ratio_y": None,
    "gear_ratio_z": None,
    "gear_ratio_e": None,
    "rotation_distance_x": None,
    "rotation_distance_y": None,
    "rotation_distance_z": None,
    "rotation_distance_e": None,
}


def _user(**overrides):
    """Return a fresh copy of the base user_data dict with overrides applied."""
    d = copy.deepcopy(_USER_DATA_BASE)
    d.update(overrides)
    return d


def _parsed(**extra_sections):
    """Return a fresh copy of the complete parsed dict with optional extra sections."""
    d = copy.deepcopy(_PARSED_COMPLETE)
    d.update(extra_sections)
    return d


def _generate(parsed, user, **kwargs):
    """Call generate_config() with a named temp file and return the output string."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".cfg", delete=False, encoding="utf-8"
    ) as f:
        tmp_path = f.name
    try:
        res = generate_config(parsed, user, output_path=tmp_path, **kwargs)
        # Mutate user dictionary locally in test helper to satisfy existing mutation tests
        user.update(res)
        return res["content"]
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# ── has_todo_pins ─────────────────────────────────────────────────────────────

@_skip_no_jinja2
class TestHasTodoPins(unittest.TestCase):
    """Tests for the has_todo_pins() helper."""

    def test_clean_config_returns_empty_list(self):
        """A complete config with no TODO values must return []."""
        result = has_todo_pins(_parsed())
        self.assertEqual(result, [])

    def test_detects_single_todo_pin(self):
        """A single TODO value must be returned as a (section, key) tuple."""
        parsed = _parsed()
        parsed["stepper_x"]["step_pin"] = "TODO"
        result = has_todo_pins(parsed)
        self.assertEqual(len(result), 1)
        self.assertIn(("stepper_x", "step_pin"), result)

    def test_detects_multiple_todo_pins_across_sections(self):
        """Multiple TODO values across sections must all be reported."""
        parsed = _parsed()
        parsed["stepper_x"]["step_pin"] = "TODO"
        parsed["heater_bed"]["heater_pin"] = "TODO"
        result = has_todo_pins(parsed)
        self.assertEqual(len(result), 2)
        self.assertIn(("stepper_x", "step_pin"), result)
        self.assertIn(("heater_bed", "heater_pin"), result)

    def test_empty_parsed_returns_empty_list(self):
        self.assertEqual(has_todo_pins({}), [])

    def test_non_dict_section_values_are_skipped(self):
        """Top-level keys with non-dict values (e.g. _advanced_sections) must not crash."""
        parsed = {"_advanced_sections": ["block1", "block2"]}
        result = has_todo_pins(parsed)
        self.assertEqual(result, [])

    def test_todo_substring_in_value_is_detected(self):
        """TODO embedded inside a value string (e.g. 'probe:TODO') must be detected."""
        parsed = _parsed()
        parsed["stepper_x"]["endstop_pin"] = "probe:TODO"
        result = has_todo_pins(parsed)
        self.assertIn(("stepper_x", "endstop_pin"), result)


# ── generate_config() — structural output ────────────────────────────────────

@_skip_no_jinja2
class TestGenerateConfigStructure(unittest.TestCase):
    """Verify the static structural elements always present in generated output."""

    @classmethod
    def setUpClass(cls):
        # Generate once with a clean base config; reuse across structural checks.
        cls.output = _generate(_parsed(), _user())

    def test_output_is_non_empty_string(self):
        self.assertIsInstance(self.output, str)
        self.assertGreater(len(self.output), 100)

    def test_printer_section_present(self):
        self.assertIn("[printer]", self.output)

    def test_kinematics_line_present(self):
        self.assertIn("kinematics: cartesian", self.output)

    def test_mcu_section_present(self):
        self.assertIn("[mcu]", self.output)

    def test_mcu_serial_path_present(self):
        self.assertIn("/dev/serial/by-id/usb-test-if00", self.output)

    def test_heater_bed_section_present(self):
        self.assertIn("[heater_bed]", self.output)

    def test_extruder_section_present(self):
        self.assertIn("[extruder]", self.output)

    def test_no_jinja2_placeholders_remain(self):
        """Unresolved Jinja2 {{ }} expressions must never appear in output."""
        self.assertNotIn("{{", self.output)
        self.assertNotIn("}}", self.output)

    def test_output_is_written_to_disk(self):
        """generate_config() must write the same content to the output_path file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".cfg", delete=False, encoding="utf-8"
        ) as f:
            tmp = f.name
        try:
            result = generate_config(_parsed(), _user(), output_path=tmp)
            with open(tmp, "r", encoding="utf-8") as f:
                on_disk = f.read()
            self.assertEqual(result["content"], on_disk)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


# ── generate_config() — probe branch ─────────────────────────────────────────

@_skip_no_jinja2
class TestGenerateConfigProbeBranch(unittest.TestCase):
    """Verify probe=None vs BLTouch/Inductive conditional rendering."""

    def test_probe_none_omits_bed_mesh(self):
        """probe='None' must NOT emit a [bed_mesh] section."""
        output = _generate(_parsed(), _user(probe="None"))
        self.assertNotIn("[bed_mesh]", output)

    def test_probe_none_omits_safe_z_home(self):
        """probe='None' must NOT emit a [safe_z_home] section."""
        output = _generate(_parsed(), _user(probe="None"))
        self.assertNotIn("[safe_z_home]", output)

    def test_probe_none_z_endstop_is_physical_pin(self):
        """With no probe, [stepper_z] must have a physical endstop_pin, not virtual."""
        output = _generate(_parsed(), _user(probe="None"))
        self.assertNotIn("probe:z_virtual_endstop", output)

    def test_bltouch_includes_bed_mesh(self):
        """probe='BLTouch' must emit a [bed_mesh] section."""
        parsed = _parsed(bltouch={"sensor_pin": "^PB1", "control_pin": "PB0"})
        output = _generate(
            parsed,
            _user(
                probe="BLTouch",
                probe_x_offset="-38",
                probe_y_offset="0",
            ),
        )
        self.assertIn("[bed_mesh]", output)
        self.assertIn("[bltouch]", output)

    def test_bltouch_uses_virtual_z_endstop(self):
        """With BLTouch, [stepper_z] endstop must be probe:z_virtual_endstop."""
        parsed = _parsed(bltouch={"sensor_pin": "^PB1", "control_pin": "PB0"})
        output = _generate(
            parsed,
            _user(probe="BLTouch", probe_x_offset="-38", probe_y_offset="0"),
        )
        self.assertIn("probe:z_virtual_endstop", output)

    def test_inductive_includes_bed_mesh(self):
        """probe='Inductive' must also emit a [bed_mesh] section."""
        parsed = _parsed(**{"probe": {"sensor_pin": "^PC0"}})
        output = _generate(
            parsed,
            _user(probe="Inductive", probe_x_offset="0", probe_y_offset="25"),
        )
        self.assertIn("[bed_mesh]", output)

    def test_bltouch_includes_safe_z_home(self):
        """BLTouch must emit a [safe_z_home] section."""
        parsed = _parsed(bltouch={"sensor_pin": "^PB1", "control_pin": "PB0"})
        output = _generate(
            parsed,
            _user(probe="BLTouch", probe_x_offset="-38", probe_y_offset="0"),
        )
        self.assertIn("[safe_z_home]", output)

    def test_probe_x_offset_appears_in_output(self):
        """The probe x_offset value must be correctly written into the probe section."""
        parsed = _parsed(bltouch={"sensor_pin": "^PB1", "control_pin": "PB0"})
        output = _generate(
            parsed,
            _user(probe="BLTouch", probe_x_offset="-38", probe_y_offset="2"),
        )
        self.assertIn("x_offset: -38", output)
        self.assertIn("y_offset: 2", output)


# ── generate_config() — web interface branch ──────────────────────────────────

@_skip_no_jinja2
class TestGenerateConfigWebInterface(unittest.TestCase):

    def test_mainsail_include_present(self):
        output = _generate(_parsed(), _user(web_interface="Mainsail"))
        self.assertIn("[include mainsail.cfg]", output)

    def test_fluidd_include_present(self):
        output = _generate(_parsed(), _user(web_interface="Fluidd"))
        self.assertIn("[include fluidd.cfg]", output)

    def test_none_web_interface_no_include(self):
        output = _generate(_parsed(), _user(web_interface="None"))
        self.assertNotIn("[include mainsail.cfg]", output)
        self.assertNotIn("[include fluidd.cfg]", output)


# ── generate_config() — z_motors branch ──────────────────────────────────────

@_skip_no_jinja2
class TestGenerateConfigZMotors(unittest.TestCase):

    def test_one_z_motor_no_z1_section(self):
        """z_motors='1' must NOT emit a [stepper_z1] section."""
        output = _generate(_parsed(), _user(z_motors="1"))
        self.assertNotIn("[stepper_z1]", output)

    def test_two_z_motors_emits_z1(self):
        """z_motors='2' must emit [stepper_z1] in the output."""
        parsed = _parsed(
            stepper_z1={"step_pin": "PF1", "dir_pin": "PF2", "enable_pin": "!PF3"}
        )
        output = _generate(parsed, _user(z_motors="2"))
        self.assertIn("[stepper_z1]", output)
        self.assertNotIn("[stepper_z2]", output)

    def test_three_z_motors_emits_z1_and_z2(self):
        """z_motors='3' must emit [stepper_z1] and [stepper_z2]."""
        parsed = _parsed(
            stepper_z1={"step_pin": "PF1", "dir_pin": "PF2", "enable_pin": "!PF3"},
            stepper_z2={"step_pin": "PG1", "dir_pin": "PG2", "enable_pin": "!PG3"},
        )
        output = _generate(parsed, _user(z_motors="3"))
        self.assertIn("[stepper_z1]", output)
        self.assertIn("[stepper_z2]", output)

    def test_four_z_motors_emits_z1_z2_z3(self):
        """z_motors='4' must emit [stepper_z1], [stepper_z2], and [stepper_z3]."""
        parsed = _parsed(
            stepper_z1={"step_pin": "PF1", "dir_pin": "PF2", "enable_pin": "!PF3"},
            stepper_z2={"step_pin": "PG1", "dir_pin": "PG2", "enable_pin": "!PG3"},
            stepper_z3={"step_pin": "PH1", "dir_pin": "PH2", "enable_pin": "!PH3"},
        )
        output = _generate(parsed, _user(z_motors="4"))
        self.assertIn("[stepper_z1]", output)
        self.assertIn("[stepper_z2]", output)
        self.assertIn("[stepper_z3]", output)

    def test_two_motors_z_tilt_template_comment_present(self):
        """With z_motors='2', the z_tilt commented template block must be present."""
        parsed = _parsed(
            stepper_z1={"step_pin": "PF1", "dir_pin": "PF2", "enable_pin": "!PF3"}
        )
        output = _generate(parsed, _user(z_motors="2"))
        self.assertIn("z_tilt", output)

    def test_corexy_four_motors_quad_gantry_comment_present(self):
        """CoreXY + z_motors >= 3 must emit the quad_gantry_level comment block."""
        parsed = _parsed(
            stepper_z1={"step_pin": "PF1", "dir_pin": "PF2", "enable_pin": "!PF3"},
            stepper_z2={"step_pin": "PG1", "dir_pin": "PG2", "enable_pin": "!PG3"},
            stepper_z3={"step_pin": "PH1", "dir_pin": "PH2", "enable_pin": "!PH3"},
        )
        output = _generate(
            parsed,
            _user(kinematics="corexy", z_motors="4"),
        )
        self.assertIn("quad_gantry_level", output)


# ── generate_config() — TMC driver branch ────────────────────────────────────

@_skip_no_jinja2
class TestGenerateConfigTMCBranch(unittest.TestCase):

    def _uart_parsed(self):
        d = _parsed()
        d["tmc2209 stepper_x"] = {"uart_pin": "PC11", "tx_pin": "PC10"}
        d["tmc2209 stepper_y"] = {"uart_pin": "PC11", "tx_pin": "PC10"}
        d["tmc2209 stepper_z"] = {"uart_pin": "PC11", "tx_pin": "PC10"}
        d["tmc2209 extruder"]  = {"uart_pin": "PC11", "tx_pin": "PC10"}
        return d

    def test_standard_driver_no_tmc_section(self):
        """driver_type='None (Standard)' must NOT emit any [tmc*] sections."""
        output = _generate(_parsed(), _user(driver_type="None (Standard)"))
        self.assertNotIn("[tmc", output.lower())

    def test_tmc2209_uart_emits_driver_sections(self):
        """TMC2209 UART must emit [tmc2209 stepper_x/y/z/extruder] sections."""
        output = _generate(
            self._uart_parsed(),
            _user(driver_type="TMC2209", driver_mode="UART"),
        )
        self.assertIn("[tmc2209 stepper_x]", output)
        self.assertIn("[tmc2209 stepper_y]", output)
        self.assertIn("[tmc2209 stepper_z]", output)
        self.assertIn("[tmc2209 extruder]", output)

    def test_tmc2209_uart_includes_uart_pin(self):
        """UART mode TMC sections must include uart_pin."""
        output = _generate(
            self._uart_parsed(),
            _user(driver_type="TMC2209", driver_mode="UART"),
        )
        self.assertIn("uart_pin: PC11", output)

    def test_tmc2209_standalone_mode_no_uart_section(self):
        """Standalone driver mode must NOT emit active [tmc*] sections."""
        output = _generate(
            _parsed(),
            _user(driver_type="TMC2209", driver_mode="Standalone"),
        )
        # In standalone mode there are no pin keys, so sections should be commented
        active_tmc = [l for l in output.splitlines()
                      if l.startswith("[tmc")]
        self.assertEqual(active_tmc, [],
                         "Standalone mode must not produce active tmc sections")

    def test_a4988_driver_no_tmc_section(self):
        """A4988 driver must NOT emit any [tmc*] sections."""
        output = _generate(_parsed(), _user(driver_type="A4988", driver_mode="Standalone"))
        self.assertNotIn("[tmc", output.lower())


# ── generate_config() — TODO safety gate ─────────────────────────────────────

@_skip_no_jinja2
class TestGenerateConfigTODOGate(unittest.TestCase):
    """
    Tests for the active-TODO validation gate (lines 264-284 of generator.py).

    This is the primary safety mechanism preventing KACE from deploying a
    config with unresolved pins to a real printer.
    """

    def test_complete_config_does_not_raise(self):
        """A config with all pins present must complete without raising."""
        try:
            _generate(_parsed(), _user())
        except GenerationError:
            self.fail("generate_config() raised GenerationError on a complete config")

    def test_active_todo_pin_raises_generation_error(self):
        """A config with an active TODO step_pin must raise GenerationError."""
        parsed = _parsed()
        parsed["stepper_x"]["step_pin"] = "TODO"
        with self.assertRaises(GenerationError) as ctx:
            _generate(parsed, _user())
        self.assertIsNotNone(ctx.exception.todos)
        self.assertGreater(len(ctx.exception.todos), 0)

    def test_generation_error_reports_correct_section_and_key(self):
        """GenerationError.todos must identify the exact offending section and key."""
        parsed = _parsed()
        parsed["heater_bed"]["heater_pin"] = "TODO"
        with self.assertRaises(GenerationError) as ctx:
            _generate(parsed, _user())
        offending = ctx.exception.todos
        self.assertTrue(
            any("heater_bed" in str(item) for item in offending),
            f"Expected heater_bed in {offending}",
        )

    def test_commented_todo_does_not_raise(self):
        """A TODO value that appears only inside a comment must NOT raise."""
        # The template places pin TODOs for missing pins like fan
        # (commented out as "# pin: TODO"). These should be allowed.
        parsed = _parsed()
        # Remove the fan section so its TODO fallback goes into a comment
        del parsed["fan"]
        try:
            _generate(parsed, _user())
        except GenerationError:
            self.fail("generate_config() raised GenerationError for a commented TODO")

    def test_generation_error_is_catchable(self):
        """GenerationError must be an Exception subclass, not a SystemExit."""
        parsed = _parsed()
        parsed["stepper_x"]["step_pin"] = "TODO"
        with self.assertRaises(GenerationError):
            _generate(parsed, _user())
        # If we get here, the process was NOT killed — the error was catchable.


# ── generate_config() — include_macros branch ────────────────────────────────

@_skip_no_jinja2
class TestGenerateConfigMacros(unittest.TestCase):

    def test_include_macros_false_no_include_line(self):
        """include_macros=False (default) must NOT add [include macros.cfg]."""
        output = _generate(_parsed(), _user(), include_macros=False)
        self.assertNotIn("[include macros.cfg]", output)

    def test_include_macros_true_adds_include_line(self):
        """include_macros=True must prepend [include macros.cfg] to the output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "printer.cfg")
            result = generate_config(
                _parsed(), _user(), output_path=out, include_macros=True
            )
        self.assertTrue(result["content"].lstrip().startswith("[include macros.cfg]"))

    def test_include_macros_true_creates_macros_cfg(self):
        """include_macros=True must also write a macros.cfg file alongside the output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "printer.cfg")
            generate_config(_parsed(), _user(), output_path=out, include_macros=True)
            self.assertTrue(
                os.path.exists(os.path.join(tmpdir, "macros.cfg")),
                "macros.cfg must be created when include_macros=True",
            )

    def test_include_macros_fallback_to_user_data(self):
        """When include_macros=False but user_data['macros_generated']=True, must still add include and create macros.cfg."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "printer.cfg")
            user = _user(macros_generated=True)
            result = generate_config(
                _parsed(), user, output_path=out, include_macros=False
            )
            self.assertTrue(result["content"].lstrip().startswith("[include macros.cfg]"))
            self.assertTrue(
                os.path.exists(os.path.join(tmpdir, "macros.cfg")),
                "macros.cfg must be created when user_data['macros_generated']=True"
            )


# ── generate_config() — user_data mutation side-effect ───────────────────────

@_skip_no_jinja2
class TestGenerateConfigSideEffects(unittest.TestCase):
    """
    Document (and guard against regression of) the known user_data mutation.

    generate_config() currently mutates user_data in-place by adding
    'motion_space' and 'bed_mesh' keys. This is an architectural limitation.
    These tests pin the current behaviour so any change is flagged explicitly.
    """

    def test_user_data_receives_motion_space_key(self):
        """After generate_config(), user_data must contain 'motion_space'."""
        user = _user()
        self.assertNotIn("motion_space", user)
        _generate(_parsed(), user)
        self.assertIn("motion_space", user,
                      "generate_config() is expected to add 'motion_space' to user_data")

    def test_user_data_receives_bed_mesh_key_with_probe(self):
        """After generate_config() with a probe, user_data must contain 'bed_mesh'."""
        parsed = _parsed(bltouch={"sensor_pin": "^PB1", "control_pin": "PB0"})
        user = _user(probe="BLTouch", probe_x_offset="-38", probe_y_offset="0")
        self.assertNotIn("bed_mesh", user)
        _generate(parsed, user)
        self.assertIn("bed_mesh", user,
                      "generate_config() is expected to add 'bed_mesh' to user_data")

    def test_motion_space_is_dict(self):
        """The injected motion_space must be a serialized dict (not an object)."""
        user = _user()
        _generate(_parsed(), user)
        self.assertIsInstance(user["motion_space"], dict)

    def test_second_call_with_different_size_updates_motion_space(self):
        """
        A second call with a different bed size must overwrite the stale motion_space,
        NOT reuse the first call's cached value. Documents the mutation risk.
        """
        user = _user(x_size="235", y_size="235")
        _generate(_parsed(), user)
        first_x_size = user["motion_space"]["printable_bed_area"]["x"][1]

        user["x_size"] = "350"
        user["y_size"] = "350"
        _generate(_parsed(), user)
        second_x_size = user["motion_space"]["printable_bed_area"]["x"][1]

        self.assertNotEqual(
            first_x_size, second_x_size,
            "Second call must update motion_space; stale data would indicate a caching bug",
        )


# ── generate_config() — thermistor passthrough ───────────────────────────────

@_skip_no_jinja2
class TestGenerateConfigThermistors(unittest.TestCase):

    def test_hotend_thermistor_in_output(self):
        output = _generate(_parsed(), _user(hotend_thermistor="Generic 3950"))
        self.assertIn("sensor_type: Generic 3950", output)

    def test_bed_thermistor_in_output(self):
        output = _generate(
            _parsed(), _user(bed_thermistor="NTC 100K beta 3950")
        )
        self.assertIn("sensor_type: NTC 100K beta 3950", output)


# ── generate_config() — advanced section passthrough ─────────────────────────

@_skip_no_jinja2
class TestGenerateConfigAdvancedSections(unittest.TestCase):

    def test_neopixel_section_rendered_as_comment(self):
        """A neopixel section must be rendered as commented passthrough, not active."""
        parsed = _parsed(**{
            "neopixel sb_leds": {
                "pin": "PB7",
                "chain_count": "3",
                "color_order": "GRBW",
            }
        })
        output = _generate(parsed, _user())
        self.assertIn("# [neopixel sb_leds]", output)
        # Must NOT appear as an active section header
        active = [l for l in output.splitlines() if l.startswith("[neopixel")]
        self.assertEqual(active, [])

    def test_adxl345_section_rendered_as_comment(self):
        """An adxl345 section must be rendered as a commented passthrough block."""
        parsed = _parsed(**{
            "adxl345": {"cs_pin": "PA4", "spi_software_sclk_pin": "PA5"}
        })
        output = _generate(parsed, _user())
        self.assertIn("# [adxl345]", output)

    def test_advanced_sections_banner_present_when_sections_exist(self):
        """The ADVANCED HARDWARE SECTIONS banner must appear if any section was detected."""
        parsed = _parsed(**{"neopixel my_led": {"pin": "PB7"}})
        output = _generate(parsed, _user())
        self.assertIn("ADVANCED HARDWARE SECTIONS", output)

    def test_no_advanced_sections_banner_absent(self):
        """No advanced sections means the banner must NOT appear."""
        output = _generate(_parsed(), _user())
        self.assertNotIn("ADVANCED HARDWARE SECTIONS", output)


class TestLevelingPoints(unittest.TestCase):

    def test_derive_leveling_points_2_motors(self):
        from core.motion_model import PrinterMotionSpace
        from core.leveling import derive_leveling_points
        user_data = {
            "x_size": "200", "y_size": "200", "z_size": "200",
            "x_position_min": "0", "x_position_max": "200",
            "y_position_min": "0", "y_position_max": "200",
            "z_position_min": "0", "z_position_max": "200",
            "probe_x_offset": "-10", "probe_y_offset": "-10",
            "probe": "BLTouch"
        }
        space = PrinterMotionSpace(user_data)
        res = derive_leveling_points(space, 2)
        self.assertEqual(res["z_tilt_points"], [(20.0, 105.0), (190.0, 105.0)])

    def test_derive_leveling_points_3_motors(self):
        from core.motion_model import PrinterMotionSpace
        from core.leveling import derive_leveling_points
        user_data = {
            "x_size": "200", "y_size": "200", "z_size": "200",
            "x_position_min": "0", "x_position_max": "200",
            "y_position_min": "0", "y_position_max": "200",
            "z_position_min": "0", "z_position_max": "200",
            "probe_x_offset": "0", "probe_y_offset": "0",
            "probe": "BLTouch"
        }
        space = PrinterMotionSpace(user_data)
        res = derive_leveling_points(space, 3)
        self.assertEqual(res["z_tilt_points"], [(10.0, 10.0), (190.0, 10.0), (100.0, 190.0)])


@_skip_no_jinja2
class TestGenerateConfigDisplayBranch(unittest.TestCase):
    def test_display_choice_none_strips_display_keys(self):
        # With display_choice="none", display sections are stripped from pins_ctx
        # and not rendered.
        parsed = _parsed(display={"lcd_type": "st7920"}, ssd1306={"pin": "PB1"})
        user = _user(display_choice="none")
        output = _generate(parsed, user)
        self.assertNotIn("[display]", output)
        self.assertNotIn("[ssd1306]", output)
        self.assertNotIn("DISPLAY HARDWARE SECTIONS", output)

    def test_display_choice_recommended_unsafe(self):
        # Choose unsafe display in wizard
        parsed = _parsed()
        user = _user(display_choice="recommended:t5uid1", board="generic-creality-v4.2.2.cfg")
        output = _generate(parsed, user)
        self.assertIn("# DISPLAY: T5UID1", output)
        self.assertIn("# Compatibility: UNSAFE", output)
        self.assertIn("DANGER: THIS COMBINATION IS UNSAFE / HIGH RISK", output)
        self.assertIn("# [t5uid1]", output)

    def test_display_choice_recommended_adapter(self):
        # Choose compatible_with_adapter display in wizard
        parsed = _parsed()
        user = _user(display_choice="manual:dwin_set", board="generic-creality-v4.2.2.cfg")
        output = _generate(parsed, user)
        self.assertIn("# DISPLAY: DWIN_SET", output)
        self.assertIn("# Compatibility: COMPATIBLE_WITH_ADAPTER", output)
        self.assertIn("WARNING: ADAPTER OR WIRING MODIFICATION REQUIRED", output)
        self.assertIn("# [dwin_set]", output)

    def test_display_choice_experimental(self):
        # Choose experimental display in wizard
        parsed = _parsed()
        user = _user(display_choice="override:some_unknown_display")
        output = _generate(parsed, user)
        self.assertIn("# DISPLAY: SOME_UNKNOWN_DISPLAY", output)
        self.assertIn("# Compatibility: EXPERIMENTAL", output)
        self.assertIn("# 🟠 EXPERIMENTAL: Community reports only", output)

    def test_display_choice_fully_compatible_with_existing_fields(self):
        # Choose fully compatible display in wizard with existing fields in parsed
        parsed = _parsed(display={"lcd_type": "st7920", "contrast": "40"})
        user = _user(display_choice="manual:display")
        output = _generate(parsed, user)
        self.assertIn("[display]", output)
        self.assertIn("lcd_type: st7920", output)
        self.assertIn("contrast: 40", output)

    def test_auto_mode_detected_displays(self):
        # Auto mode: no display_choice, detect from parsed config
        parsed = _parsed(t5uid1={"data_pin": "PC0"}, display={"lcd_type": "st7920"})
        user = _user() # display_choice is None (auto mode)
        output = _generate(parsed, user)
        # Should render t5uid1 as commented (since t5uid1 is unsafe/unsupported)
        self.assertIn("# [t5uid1]", output)
        self.assertIn("# data_pin: TODO # WAS: PC0", output)
        # Should render display as active (fully compatible)
        self.assertIn("[display]", output)
        self.assertIn("lcd_type: st7920", output)

    def test_comment_translation_replaced(self):
        # Test line 97: translation replacement
        from core.translations import set_lang, get_lang
        orig_lang = get_lang()
        parsed = _parsed()
        user = _user()
        try:
            set_lang("Português")
            # Let's verify that comments like "# Printer kinematics type (cartesian, corexy, delta)" are translated
            # and replaced correctly in the output.
            output = _generate(parsed, user)
            self.assertIn("# Tipo de cinemática da impressora (cartesiana, corexy, delta)", output)
        finally:
            set_lang(orig_lang)

    def test_z_tilt_and_qgl_comment_translation(self):
        from core.translations import set_lang, get_lang
        orig_lang = get_lang()
        parsed = _parsed(
            stepper_z1={"step_pin": "PF1", "dir_pin": "PF2", "enable_pin": "!PF3"}
        )
        user = _user(z_motors="2")
        try:
            set_lang("Español")
            output = _generate(parsed, user)
            self.assertIn("# Nivelación automática del gantry cuando hay 2 o más motores Z independientes.", output)
            self.assertIn("-30, 117", output)
            self.assertIn("Motor Z izquierdo (ajustar según tu impresora)", output)
            self.assertIn("Velocidad de desplazamiento entre puntos de medición (mm/s)", output)

            set_lang("Português")
            output = _generate(parsed, user)
            self.assertIn("# Nivelamento automático do gantry quando há 2 ou mais motores Z independentes.", output)
            self.assertIn("-30, 117", output)
            self.assertIn("Motor Z esquerdo (ajuste conforme sua impressora)", output)
            self.assertIn("Velocidade de deslocamento entre pontos de medição (mm/s)", output)
        finally:
            set_lang(orig_lang)


@_skip_no_jinja2
class TestGenerateConfigFanBranch(unittest.TestCase):
    def test_fan_default_behavior(self):
        # Default behavior: fan pin maps default from board parsed config, and no heater_fan
        parsed = _parsed(fan={"pin": "PA8"})
        user = _user() # fan_part_cooling_pin is None, fan_hotend_pin is None
        output = _generate(parsed, user)
        self.assertIn("[fan]", output)
        self.assertIn("pin: PA8", output)
        self.assertNotIn("[heater_fan hotend_fan]", output)

    def test_fan_custom_assignments(self):
        # Overriding fan pin with custom pin, and adding hotend fan pin
        parsed = _parsed(fan={"pin": "PA8"})
        user = _user(fan_part_cooling_pin="PC5", fan_hotend_pin="PE5")
        output = _generate(parsed, user)
        self.assertIn("[fan]", output)
        self.assertIn("pin: PC5", output)
        self.assertIn("[heater_fan hotend_fan]", output)
        self.assertIn("pin: PE5", output)

    def test_fan_disabled(self):
        # Setting part cooling fan to 'none' disables it / leaves it commented out
        parsed = _parsed(fan={"pin": "PA8"})
        user = _user(fan_part_cooling_pin="none")
        output = _generate(parsed, user)
        self.assertIn("[fan]", output)
        self.assertIn("# pin: TODO", output)
        self.assertNotIn("pin: PA8", output)


if __name__ == "__main__":
    unittest.main()
