import contextlib
import io
import unittest

from core.configuration_review import (
    build_configuration_review,
    render_configuration_review,
    validate_configuration_plan,
)
from core.deployer import _interactive_configuration_review
from core.macro_generator import generate_starter_macros
from core.managed_config import build_managed_config_plan
from core.profile_values import (
    ValueProvenance,
    infer_homing_positive_dir,
    resolve_generation_values,
)


def _hardware(*, bed_control="pid", probe=False, inferred=False):
    provenance = "#   homing_positive_dir_x=INFERRED\n" if inferred else ""
    probe_section = "[probe]\npin: ^PB2\n" if probe else ""
    z_endstop = "endstop_pin: probe:z_virtual_endstop\n" if probe else "endstop_pin: PB2\nposition_endstop: 0\n"
    calibration = "# PROBE_CALIBRATE\n" if probe else "# Z_ENDSTOP_CALIBRATE\n"
    bed_pid = "pid_Kp: 50\npid_Ki: 1\npid_Kd: 500\n" if bed_control == "pid" else ""
    return f"""# Board: SKR 1.4 Turbo / LPC1769
# Stepper Drivers: TMC2209 (UART)
# Z Drivers: 2
{provenance}[mcu]
serial: /dev/serial/by-id/test
[printer]
kinematics: cartesian
[exclude_object]
[stepper_x]
position_min: 0
position_max: 235
position_endstop: 0
homing_positive_dir: False
[stepper_y]
position_min: 0
position_max: 235
position_endstop: 235
homing_positive_dir: True
[stepper_z]
{z_endstop}position_min: 0
position_max: 250
homing_positive_dir: False
[extruder]
control: pid
pid_Kp: 20
pid_Ki: 1
pid_Kd: 100
[heater_bed]
control: {bed_control}
{bed_pid}{probe_section}{calibration}""".encode()


def _plan(hardware, macros=None):
    return build_managed_config_plan(
        hardware,
        macros,
        {"printer.cfg": None, "moonraker.conf": None},
    )


class HomingInferenceTests(unittest.TestCase):
    def test_homing_infers_nearest_limit(self):
        self.assertEqual(infer_homing_positive_dir("0", "0", "235"), "False")
        self.assertEqual(infer_homing_positive_dir("235", "0", "235"), "True")
        resolved, provenance = resolve_generation_values({}, {})
        self.assertEqual(resolved["homing_positive_dir_x"], "False")
        self.assertEqual(provenance["homing_positive_dir_x"], ValueProvenance.INFERRED.value)

    def test_midpoint_homing_requires_explicit_answer(self):
        self.assertIsNone(infer_homing_positive_dir("100", "0", "200"))
        _, provenance = resolve_generation_values(
            {},
            {"x_position_min": "0", "x_position_max": "200", "x_position_endstop": "100"},
        )
        self.assertEqual(provenance["homing_positive_dir_x"], ValueProvenance.UNRESOLVED.value)


class HeaterAndCalibrationReviewTests(unittest.TestCase):
    def test_watermark_without_pid_or_pid_bed_is_valid(self):
        validation = validate_configuration_plan(_plan(_hardware(bed_control="watermark"), b"# macros\n"))
        self.assertTrue(validation.valid)

    def test_watermark_with_pid_bed_is_blocked(self):
        macros = b"[gcode_macro PID_BED]\ngcode: PID_CALIBRATE HEATER=heater_bed TARGET=60\n"
        validation = validate_configuration_plan(_plan(_hardware(bed_control="watermark"), macros))
        self.assertFalse(validation.valid)
        self.assertIn("PID_BED", " ".join(item.message for item in validation.errors))

    def test_pid_with_pid_values_and_macro_is_valid(self):
        macros = b"[gcode_macro PID_BED]\ngcode: PID_CALIBRATE HEATER=heater_bed TARGET=60\n"
        self.assertTrue(validate_configuration_plan(_plan(_hardware(), macros)).valid)

    def test_probe_none_uses_physical_endstop_calibration(self):
        validation = validate_configuration_plan(_plan(_hardware(probe=False)))
        self.assertTrue(validation.valid)

    def test_probe_uses_probe_calibrate(self):
        validation = validate_configuration_plan(_plan(_hardware(probe=True)))
        self.assertTrue(validation.valid)

    def test_macro_generator_omits_pid_bed_for_watermark(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            path = generate_starter_macros(root, bed_control="watermark")
            with open(path, encoding="utf-8") as source:
                content = source.read()
        self.assertNotIn("[gcode_macro PID_BED]", content)
        self.assertIn("[gcode_macro PID_HOTEND]", content)


class DryRunPresentationTests(unittest.TestCase):
    def setUp(self):
        self.review = build_configuration_review(_plan(_hardware(inferred=True)))

    def test_summary_hides_full_diff_by_default(self):
        rendered = render_configuration_review(self.review, language="Español", color=False)
        self.assertIn("Resumen de configuración", rendered)
        self.assertIn("kace/generated-hardware.cfg", rendered)
        self.assertNotIn("--- remote/printer.cfg", rendered)
        self.assertIn("advertencia", rendered)

    def test_advanced_mode_prints_full_diff(self):
        answers = iter((True, False))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            accepted = _interactive_configuration_review(
                self.review, lambda _prompt, default=False: next(answers)
            )
        self.assertFalse(accepted)
        self.assertIn("--- Technical diff ---", output.getvalue())
        self.assertIn("--- remote/printer.cfg", output.getvalue())

    def test_renderer_with_and_without_colors(self):
        colored = render_configuration_review(self.review, color=True)
        plain = render_configuration_review(self.review, color=False)
        self.assertIn("\033[", colored)
        self.assertNotIn("\033[", plain)
        self.assertIn("Configuration summary", plain)


if __name__ == "__main__":
    unittest.main()
