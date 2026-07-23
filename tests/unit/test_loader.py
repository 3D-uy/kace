# tests/unit/test_loader.py
import unittest
from unittest.mock import patch, mock_open
import yaml
from core.loader import (
    load_boards_yaml,
    load_displays_yaml,
    load_advanced_modules_yaml,
    read_version,
    set_bypass_cache
)

class TestLoaderErrorPaths(unittest.TestCase):

    def setUp(self):
        set_bypass_cache(True)

    def tearDown(self):
        set_bypass_cache(False)

    def test_load_boards_yaml_file_not_found(self):
        with patch("builtins.open", side_effect=FileNotFoundError):
            with self.assertRaises(RuntimeError) as ctx:
                load_boards_yaml()
            self.assertIn("boards database not found", str(ctx.exception))

    def test_load_boards_yaml_permission_error(self):
        with patch("builtins.open", side_effect=PermissionError):
            with self.assertRaises(RuntimeError) as ctx:
                load_boards_yaml()
            self.assertIn("Permission denied", str(ctx.exception))

    def test_load_boards_yaml_invalid_yaml(self):
        with patch("builtins.open", mock_open(read_data="invalid: [yaml: :")):
            with patch("yaml.safe_load", side_effect=yaml.YAMLError("parse error")):
                with self.assertRaises(RuntimeError) as ctx:
                    load_boards_yaml()
                self.assertIn("corrupt or invalid YAML", str(ctx.exception))

    def test_load_displays_yaml_file_not_found(self):
        with patch("builtins.open", side_effect=FileNotFoundError):
            with self.assertRaises(RuntimeError) as ctx:
                load_displays_yaml()
            self.assertIn("displays database not found", str(ctx.exception))

    def test_load_displays_yaml_permission_error(self):
        with patch("builtins.open", side_effect=PermissionError):
            with self.assertRaises(RuntimeError) as ctx:
                load_displays_yaml()
            self.assertIn("Permission denied", str(ctx.exception))

    def test_load_displays_yaml_invalid_yaml(self):
        with patch("builtins.open", mock_open(read_data="invalid: [yaml: :")):
            with patch("yaml.safe_load", side_effect=yaml.YAMLError("parse error")):
                with self.assertRaises(RuntimeError) as ctx:
                    load_displays_yaml()
                self.assertIn("corrupt or invalid YAML", str(ctx.exception))

    def test_load_advanced_modules_yaml_file_not_found(self):
        with patch("builtins.open", side_effect=FileNotFoundError):
            with self.assertRaises(RuntimeError) as ctx:
                load_advanced_modules_yaml()
            self.assertIn("advanced_modules database not found", str(ctx.exception))

    def test_load_advanced_modules_yaml_permission_error(self):
        with patch("builtins.open", side_effect=PermissionError):
            with self.assertRaises(RuntimeError) as ctx:
                load_advanced_modules_yaml()
            self.assertIn("Permission denied", str(ctx.exception))

    def test_load_advanced_modules_yaml_invalid_yaml(self):
        with patch("builtins.open", mock_open(read_data="invalid: [yaml: :")):
            with patch("yaml.safe_load", side_effect=yaml.YAMLError("parse error")):
                with self.assertRaises(RuntimeError) as ctx:
                    load_advanced_modules_yaml()
                self.assertIn("corrupt or invalid YAML", str(ctx.exception))

    def test_read_version_missing_file_fallback(self):
        with patch("builtins.open", side_effect=FileNotFoundError):
            ver = read_version()
            self.assertEqual(ver, "v?.?.?")

    def test_read_version_oserror_fallback(self):
        with patch("builtins.open", side_effect=OSError("Read error")):
            ver = read_version()
            self.assertEqual(ver, "v?.?.?")


if __name__ == '__main__':
    unittest.main()
