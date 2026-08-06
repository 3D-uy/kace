"""
tests/unit/test_reconciler.py
==============================
Unit tests for core/reconciler.py — Single Source of Truth for KACE Native Reconciliation.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.reconciler import (
    ensure_ini_section_and_option,
    reconcile_printer_cfg_content,
    reconcile_moonraker_conf_content,
    reconcile_file_atomically,
    reconcile_config_directory,
    write_text_atomically,
)


class TestReconcilerUnit(unittest.TestCase):

    def test_ensure_ini_section_and_option_adds_missing_section_and_option(self):
        content = "[printer]\nkinematics: cartesian\n"
        res, mod = ensure_ini_section_and_option(content, "exclude_object")
        self.assertTrue(mod)
        self.assertIn("[exclude_object]", res)

        res2, mod2 = ensure_ini_section_and_option(res, "force_move", "enable_force_move", "True")
        self.assertTrue(mod2)
        self.assertIn("[force_move]", res2)
        self.assertIn("enable_force_move: True", res2)

    def test_ensure_ini_section_and_option_preserves_existing_values(self):
        content = "[force_move]\nenable_force_move: False\n"
        res, mod = ensure_ini_section_and_option(content, "force_move", "enable_force_move", "True")
        self.assertFalse(mod)
        self.assertIn("enable_force_move: False", res)
        self.assertNotIn("enable_force_move: True", res)

    def test_reconcile_printer_cfg_content_defaults(self):
        content = "[printer]\nkinematics: cartesian\n"
        res, mod = reconcile_printer_cfg_content(content)
        self.assertTrue(mod)
        self.assertIn("[exclude_object]", res)
        self.assertIn("[force_move]", res)
        self.assertIn("enable_force_move: True", res)

    def test_reconcile_printer_cfg_content_preserves_existing_target_false(self):
        generated = "[printer]\nkinematics: cartesian\n"
        existing_target = "[force_move]\nenable_force_move: False\n"
        res, mod = reconcile_printer_cfg_content(generated, existing_target_content=existing_target)
        self.assertTrue(mod)
        self.assertIn("[exclude_object]", res)
        self.assertIn("[force_move]", res)
        self.assertIn("enable_force_move: False", res)
        self.assertNotIn("enable_force_move: True", res)

    def test_reconcile_moonraker_conf_content_adds_file_manager_and_option(self):
        content = "[server]\nport: 7125\n"
        res, mod = reconcile_moonraker_conf_content(content)
        self.assertTrue(mod)
        self.assertIn("[file_manager]", res)
        self.assertIn("enable_object_processing: True", res)
        self.assertIn("[server]", res)
        self.assertIn("port: 7125", res)

    def test_reconcile_file_atomically_updates_file_on_disk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "printer.cfg"
            file_path.write_text("[printer]\nkinematics: cartesian\n", encoding="utf-8")

            mod = reconcile_file_atomically(file_path, reconcile_printer_cfg_content)
            self.assertTrue(mod)

            final_text = file_path.read_text(encoding="utf-8")
            self.assertIn("[exclude_object]", final_text)
            self.assertIn("[force_move]", final_text)
            self.assertIn("enable_force_move: True", final_text)

    def test_atomic_write_keeps_previous_file_when_publish_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "printer.cfg"
            file_path.write_text("previous configuration\n", encoding="utf-8")

            with patch("core.reconciler.os.replace", side_effect=OSError("publish failed")):
                with self.assertRaises(OSError):
                    write_text_atomically(file_path, "new configuration\n")

            self.assertEqual(
                file_path.read_text(encoding="utf-8"),
                "previous configuration\n",
            )
            self.assertFalse(list(Path(tmpdir).glob(".printer.cfg.*.part")))

    def test_reconcile_file_aborts_without_writing_when_existing_file_cannot_be_read(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "moonraker.conf"
            original_content = "[power printer]\npin: !gpiochip0/gpio20\n"
            file_path.write_text(original_content, encoding="utf-8")

            original_read_text = Path.read_text

            def fail_target_read(path, *args, **kwargs):
                if path == file_path:
                    raise PermissionError("read denied")
                return original_read_text(path, *args, **kwargs)

            with patch.object(Path, "read_text", fail_target_read):
                with patch("core.reconciler.write_text_atomically") as writer:
                    with self.assertRaisesRegex(
                        OSError,
                        "Could not read existing configuration",
                    ):
                        reconcile_file_atomically(
                            file_path,
                            reconcile_moonraker_conf_content,
                        )

                    writer.assert_not_called()

            self.assertEqual(
                file_path.read_text(encoding="utf-8"),
                original_content,
            )

    def test_reconcile_config_directory_reconciles_both_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            (config_dir / "printer.cfg").write_text("[printer]\nkinematics: cartesian\n", encoding="utf-8")
            (config_dir / "moonraker.conf").write_text("[server]\nport: 7125\n", encoding="utf-8")

            reconcile_config_directory(config_dir)

            p_text = (config_dir / "printer.cfg").read_text(encoding="utf-8")
            m_text = (config_dir / "moonraker.conf").read_text(encoding="utf-8")

            self.assertIn("[exclude_object]", p_text)
            self.assertIn("enable_force_move: True", p_text)
            self.assertIn("[file_manager]", m_text)
            self.assertIn("enable_object_processing: True", m_text)


if __name__ == "__main__":
    unittest.main()
