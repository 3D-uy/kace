"""Regression contracts limiting bootstrap changes to KACE-owned resources."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "scripts" / "bootstrap.sh"


def _find_bash() -> str | None:
    if os.name == "nt":
        program_files = os.environ.get("ProgramFiles")
        if program_files:
            git_bash = Path(program_files) / "Git" / "bin" / "bash.exe"
            if git_bash.is_file():
                return str(git_bash)
    return shutil.which("bash")


class TestBootstrapMinimalMutation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = BOOTSTRAP.read_text(encoding="utf-8")

    def test_bootstrap_never_disables_cloud_init_globally(self):
        self.assertNotIn("/etc/cloud/cloud-init.disabled", self.script)
        self.assertIn("cleanup_kace_cloud_init_seed", self.script)

    def test_service_compatibility_uses_only_kace_owned_dropins(self):
        helper_block = self.script.split("install_service_identity_dropin()", 1)[1].split(
            "if [ \"${KACE_BOOTSTRAP_LIB_ONLY:-0}\"", 1
        )[0]
        patch_block = self.script.split("patch_systemd_services()", 1)[1].split(
            "patch_systemd_services", 1
        )[0]
        self.assertNotIn("/lib/systemd/system", helper_block)
        self.assertNotIn("/usr/lib/systemd/system", helper_block)
        self.assertNotIn("sed -i", helper_block)
        self.assertIn("/etc/systemd/system", helper_block)
        self.assertIn("kace-identity.conf", helper_block)
        self.assertIn('systemctl show "${service_name}.service" --property=User', helper_block)
        self.assertIn('cmp -s "$temporary" "$destination"', helper_block)
        self.assertIn("install_service_identity_dropin klipper", patch_block)
        self.assertIn("install_service_identity_dropin moonraker", patch_block)

    def test_bootstrap_does_not_apply_opinionated_global_optimizations(self):
        self.assertNotIn("ExecStartPre=/bin/sleep", self.script)
        self.assertNotIn("systemctl stop apache2", self.script)
        self.assertNotIn("systemctl disable apache2", self.script)
        self.assertNotIn("systemctl stop lighttpd", self.script)
        self.assertNotIn("systemctl disable lighttpd", self.script)
        self.assertNotIn("tee -a /etc/hosts", self.script)
        self.assertNotIn('chown -R "${PRINTER_USER}:${PRINTER_GROUP}" "$PRINTER_HOME/printer_data"', self.script)

    def test_bootstrap_preserves_existing_printer_configuration(self):
        config_block = self.script.split('# ── 5. Printer Data Directories & Config Files', 1)[1].split(
            '# ── 6. Dashboard UI', 1
        )[0]
        self.assertNotIn("ensure_config_entry", config_block)
        self.assertNotIn("cat $PRINTER_HOME/printer_data/config/printer.cfg", config_block)
        self.assertIn('if [ ! -f "$PRINTER_HOME/printer_data/config/printer.cfg" ]', config_block)

    def test_unselected_crowsnest_is_preserved(self):
        crowsnest_block = self.script.split('# ── 10. Crowsnest (Optional)', 1)[1].split(
            '# ── 11. KACE Agent', 1
        )[0]
        unselected = crowsnest_block.split('else\n    log_stage "CROWSNEST"', 1)[1]
        self.assertNotIn("systemctl stop crowsnest", unselected)
        self.assertNotIn("systemctl disable crowsnest", unselected)

    @unittest.skipIf(_find_bash() is None, "bash is not available")
    def test_cloud_init_cleanup_removes_only_kace_owned_seed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kace_seed = root / "kace-seed"
            foreign_seed = root / "foreign-seed"
            for seed in (kace_seed, foreign_seed):
                seed.mkdir()
                (seed / "user-data").write_text("#cloud-config\n", encoding="utf-8")
                (seed / "network-config").write_text("network: {}\n", encoding="utf-8")
            (kace_seed / "meta-data").write_text("instance-id: kace-1234\n", encoding="utf-8")
            (foreign_seed / "meta-data").write_text("instance-id: user-managed\n", encoding="utf-8")

            command = """
set -euo pipefail
export KACE_BOOTSTRAP_LIB_ONLY=1
source "$1"
SUDO=""
cleanup_kace_cloud_init_seed "$2" "$3"
"""
            result = subprocess.run(
                [
                    _find_bash(),
                    "-c",
                    command,
                    "bootstrap-test",
                    BOOTSTRAP.as_posix(),
                    kace_seed.as_posix(),
                    foreign_seed.as_posix(),
                ],
                capture_output=True,
                text=True,
                env=self._bash_environment(),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((kace_seed / "meta-data").exists())
            self.assertFalse((kace_seed / "user-data").exists())
            self.assertFalse((kace_seed / "network-config").exists())
            self.assertTrue((foreign_seed / "meta-data").exists())
            self.assertTrue((foreign_seed / "user-data").exists())
            self.assertTrue((foreign_seed / "network-config").exists())

    @staticmethod
    def _bash_environment():
        environment = os.environ.copy()
        bash = _find_bash()
        if os.name == "nt" and bash:
            git_usr_bin = Path(bash).resolve().parents[1] / "usr" / "bin"
            environment["PATH"] = str(git_usr_bin) + os.pathsep + environment.get("PATH", "")
        return environment


if __name__ == "__main__":
    unittest.main()
