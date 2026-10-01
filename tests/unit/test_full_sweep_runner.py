"""The full sweep must not equate parsing/generation with valid Klipper config."""

import contextlib
import io
import hashlib
import json
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.exceptions import GenerationError
from tests.sweep import full_sweep_runner as sweep
from tests.sweep.result_codes import SweepResult
from tests import run_tests


class FullSweepTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)

    def classify(self, **kwargs):
        return sweep._classify_config(
            "generic-test.cfg", "[printer]\nkinematics: cartesian\n", str(self.output), **kwargs
        )

    def test_generation_exception_is_failure_not_pass(self):
        for error in (GenerationError("unresolved output"), RuntimeError("broken generator")):
            with self.subTest(error=type(error).__name__), patch.object(
                sweep, "generate_config", side_effect=error
            ):
                result, generated, warnings = self.classify()
                self.assertEqual(result.code, SweepResult.FAILURE)
                self.assertFalse(generated)
                self.assertIn(str(error), result.detail)

    def test_no_display_is_explicit_and_changes_only_the_wizard_choice(self):
        selections = []
        for without_display in (False, True):
            with patch.object(sweep, "generate_config", side_effect=self.write_output) as generate:
                result, generated, _ = self.classify(without_display=without_display)
            self.assertEqual(result.code, SweepResult.GENERATED)
            self.assertTrue(generated)
            selections.append(generate.call_args.args[1])
        self.assertNotIn("display_choice", selections[0])
        self.assertEqual(selections[1].pop("display_choice"), "none")
        self.assertEqual(selections[0], selections[1])

    def test_no_display_still_requires_loader_success_and_records_selection(self):
        for valid in (True, False):
            with self.subTest(valid=valid):
                ok, report, validate = self.execute(
                    {"generic-test.cfg": {"valid": valid}}, without_display=True)
                self.assertEqual(ok, valid)
                self.assertEqual(report["results"][0]["code"],
                                 SweepResult.PASS if valid else SweepResult.FAILURE)
                self.assertEqual(report["fixture"]["display_choice"], "none")
                self.assertEqual(report["fixture"]["qualified_boards"], [])
                manifest = json.loads(validate.call_args.args[1].read_text(encoding="utf-8"))
                self.assertEqual(manifest["fixture"], report["fixture"])

    def test_no_display_does_not_credit_other_generation_failures(self):
        ok, report, validate = self.execute(
            generation_error=GenerationError("required hardware absent"), without_display=True)
        self.assertFalse(ok)
        self.assertEqual(report["results"][0]["code"], SweepResult.FAILURE)
        validate.assert_not_called()

    def test_real_generation_omits_panel_but_preserves_cooling(self):
        from tests.unit.test_generator import _parsed
        from core.configuration_review import _sections

        # The default selection recognizes this canonical hotend fan; arbitrary
        # unselected synthetic fan names do not carry reviewed-board authority.
        parsed = _parsed(
            mcu={"serial": "/tmp/klipper"},
            display={"lcd_type": "st7920", "cs_pin": "PF1",
                     "sclk_pin": "PF2", "sid_pin": "PF3"},
            **{"heater_fan hotend_fan": {"pin": "PF4", "heater": "extruder",
                                     "heater_temp": "50"}})
        raw = "\n".join("[" + name + "]\n" + "\n".join(
            key + ": " + value for key, value in fields.items())
            for name, fields in parsed.items())
        result, generated, _ = sweep._classify_config("generic-test.cfg", raw, str(self.output))
        self.assertEqual(result.code, SweepResult.FAILURE)
        self.assertIn("display", result.detail.lower())
        self.assertFalse(generated)
        self.assertEqual(list(self.output.iterdir()), [])
        result, generated, _ = sweep._classify_config(
            "generic-test.cfg", raw, str(self.output), without_display=True)
        self.assertEqual(result.code, SweepResult.GENERATED)
        self.assertTrue(generated)
        sections = _sections((self.output / "generic-test.out.cfg").read_text(encoding="utf-8"))
        self.assertNotIn("display", sections)
        self.assertEqual(sections["heater_fan hotend_fan"], parsed["heater_fan hotend_fan"])

    def test_real_headless_generation_retains_other_hardware_guards(self):
        from tests.unit.test_generator import _parsed

        for kind in ("probe", "replicape"):
            with self.subTest(kind=kind):
                parsed = _parsed(mcu={"serial": "/tmp/klipper"})
                if kind == "probe":
                    parsed["stepper_z"]["endstop_pin"] = "probe:z_virtual_endstop"
                else:
                    parsed["replicape"] = {"revision": "B3"}
                raw = "\n".join("[" + name + "]\n" + "\n".join(
                    key + ": " + value for key, value in fields.items())
                    for name, fields in parsed.items())
                result, generated, _ = sweep._classify_config(
                    "generic-test.cfg", raw, str(self.output), without_display=True)
                self.assertEqual(result.code, SweepResult.FAILURE)
                self.assertIn(kind, result.detail.lower())
                self.assertFalse(generated)
                self.assertEqual(list(self.output.iterdir()), [])

    def test_generator_returning_without_file_is_failure(self):
        with patch.object(sweep, "generate_config"):
            result, generated, _ = self.classify()
        self.assertEqual(result.code, SweepResult.FAILURE)
        self.assertFalse(generated)

    def test_unsupported_kinematics_is_classified_before_generation(self):
        with patch.object(sweep, "generate_config") as generate:
            result, generated, _ = sweep._classify_config(
                "printer-delta.cfg", "[printer]\nkinematics: delta\n", str(self.output)
            )
        self.assertEqual(result.code, SweepResult.UNSUPPORTED)
        self.assertFalse(generated)
        generate.assert_not_called()

    @staticmethod
    def write_output(*args, **kwargs):
        Path(kwargs["output_path"]).write_text("[fan]\n", encoding="utf-8")

    def test_generated_file_is_pending_until_official_validation(self):
        with patch.object(sweep, "generate_config", side_effect=self.write_output):
            result, generated, _ = self.classify()
        self.assertEqual(result.code, SweepResult.GENERATED)
        self.assertTrue(generated)

    def execute(self, validation=None, infra=None, generation_error=None, *, without_display=False,
                changed_inventory=False, changed_after_review=False, blocked_inventory=False):
        previous_reports = set((self.output / "artifacts").glob("run-*/report.json"))
        raw = "[printer]\nkinematics: cartesian\n"
        inventory = self.output / 'inventory.json'
        inventory.write_text(json.dumps({
            'schema_version': 1, 'klipper_ref': sweep.KLIPPER_REF,
            'scope': 'Synthetic runner test; not a reviewed physical board.',
            'profiles': [{'filename': 'generic-test.cfg',
                          'source_sha256_lf': '0' * 64 if changed_inventory else hashlib.sha256(raw.encode()).hexdigest(),
                          'classification': 'SOURCE_DEPENDENCY_BLOCKED' if blocked_inventory else 'LOAD_EVIDENCE',
                          'scenario': 'baseline_without_display',
                          'headless_class': 'electrical_dependency_blocked' if blocked_inventory else 'loaded_generated_configuration'}],
        }), encoding='utf-8')
        verify_inventory = sweep.verify_source_inventory

        def verify(config_dir):
            receipt = verify_inventory(config_dir, inventory)
            if changed_after_review:
                (config_dir / 'generic-test.cfg').write_text(raw + '# changed\n', encoding='utf-8')
            return receipt

        def clone(target):
            config = Path(target) / "config"
            config.mkdir()
            (config / "generic-test.cfg").write_text(
                raw, encoding="utf-8"
            )
            return True

        @contextlib.contextmanager
        def workspace(*args):
            with tempfile.TemporaryDirectory(dir=self.output) as name:
                yield Path(name)

        with patch.object(sweep, "GIT", "git"), \
             patch.object(sweep, "heavy_workspace", workspace), \
             patch.object(sweep, "ensure_free_space"), \
             patch.object(sweep, "_clone_klipper", side_effect=clone), \
             patch.object(sweep, "verify_source_inventory", side_effect=verify), \
             patch.object(sweep, "generate_config", side_effect=generation_error or self.write_output), \
             patch.object(sweep, "run_docker_validation", return_value=(validation or {}, infra)) as validate, \
             patch.object(sweep, "REPORT_PATH", str(self.output / "last.txt")), \
             contextlib.redirect_stdout(io.StringIO()):
            ok = sweep.run_full_sweep(artifact_dir=self.output / "artifacts", without_display=without_display)
        new_reports = set((self.output / "artifacts").glob("run-*/report.json")) - previous_reports
        self.assertEqual(len(new_reports), 1)
        report_path = new_reports.pop()
        return ok, json.loads(report_path.read_text(encoding="utf-8")), validate

    def test_changed_inventory_blocks_generation_and_loader(self):
        ok, report, validate = self.execute(changed_inventory=True)
        self.assertFalse(ok)
        self.assertEqual(report['results'], [])
        self.assertIsNone(report['scope_inventory'])
        self.assertIn('Reviewed source bytes changed', report['infrastructure_error'])
        validate.assert_not_called()
        self.assertEqual(list((self.output / 'artifacts').glob('run-*/*.cfg')), [])

    def test_source_changed_after_review_cannot_use_the_receipt(self):
        ok, report, validate = self.execute(changed_after_review=True)
        self.assertFalse(ok)
        self.assertEqual(report['results'], [])
        self.assertIn('Source changed after inventory verification', report['infrastructure_error'])
        validate.assert_not_called()
        self.assertEqual(list((self.output / 'artifacts').glob('run-*/*.cfg')), [])

    def test_blocked_disposition_never_waives_generation_errors(self):
        for error in (GenerationError('required hardware absent'), RuntimeError('unrelated bug')):
            with self.subTest(error=type(error).__name__):
                ok, report, validate = self.execute(generation_error=error, blocked_inventory=True)
                self.assertFalse(ok)
                self.assertEqual(report['results'][0]['code'], SweepResult.FAILURE)
                self.assertEqual(report['scope_inventory']['disposition_counts'], {'SOURCE_DEPENDENCY_BLOCKED': 1})
                validate.assert_not_called()

    def test_actual_loader_rejection_fails_sweep(self):
        ok, report, validate = self.execute({"generic-test.cfg": {"valid": False, "reason": "pin missing"}})
        self.assertFalse(ok)
        self.assertEqual(report["results"][0]["code"], SweepResult.FAILURE)
        self.assertIn("pin missing", report["results"][0]["detail"])
        manifest_path = validate.call_args.args[1]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["klipper_ref"], sweep.KLIPPER_REF)
        self.assertEqual(manifest["cases"][0]["generation"]["status"], "generated")
        self.assertTrue((manifest_path.parent / manifest["cases"][0]["config_path"]).is_file())

    def test_validated_output_is_the_only_pass(self):
        ok, report, _ = self.execute({"generic-test.cfg": {"valid": True, "reason": "loaded"}})
        self.assertTrue(ok)
        self.assertEqual(report["results"][0]["code"], SweepResult.PASS)
        self.assertEqual(report['scope_inventory']['qualification'], 'source-inventory-only')
        self.assertEqual(report['scope_inventory']['qualified_boards'], [])
        self.assertEqual(report['results'][0]['source_sha256_lf'],
                         report['scope_inventory']['source_sha256_lf']['generic-test.cfg'])

    def test_unavailable_loader_is_infrastructure_error(self):
        ok, report, _ = self.execute(infra="Docker unavailable")
        self.assertFalse(ok)
        self.assertEqual(report["results"][0]["code"], SweepResult.INFRA_ERROR)

    def test_missing_or_malformed_result_cannot_pass(self):
        for response in ({}, {"valid": "yes"}, {"valid": 1}, None):
            with self.subTest(response=response):
                ok, report, _ = self.execute({"generic-test.cfg": response})
                self.assertFalse(ok)
                self.assertEqual(report["results"][0]["code"], SweepResult.INFRA_ERROR)

    def test_generation_failure_propagates_without_running_loader(self):
        ok, report, validate = self.execute(generation_error=GenerationError("invalid output"))
        self.assertFalse(ok)
        self.assertEqual(report["results"][0]["code"], SweepResult.FAILURE)
        self.assertFalse(report["results"][0]["generated"])
        validate.assert_not_called()

    def test_cli_uses_full_validation_and_propagates_exit_status(self):
        for successful, exit_code in ((True, 0), (False, 1)):
            with self.subTest(successful=successful), \
                 patch.object(sys, "argv", ["run_tests.py", "--full-klipper-sweep"]), \
                 patch.object(sweep, "run_full_sweep", return_value=successful) as full, \
                 patch("tests.sweep.klipper_sweep.run_full_sweep") as parser_only:
                with self.assertRaises(SystemExit) as result:
                    run_tests.main()
                self.assertEqual(result.exception.code, exit_code)
                full.assert_called_once_with(verbose=False)
                parser_only.assert_not_called()

    def test_pending_and_empty_summaries_cannot_succeed(self):
        for code in (None, SweepResult.GENERATED, SweepResult.INFRA_ERROR):
            with self.subTest(code=code):
                summary = sweep.SweepSummary()
                if code:
                    summary.add(SweepResult(code, "generic-test.cfg"))
                self.assertFalse(summary.was_successful())


if __name__ == "__main__":
    unittest.main()
