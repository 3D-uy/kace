"""POSIX integration coverage for the real install.sh wizard handoff."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "install.sh"


def _shell_path(path: Path) -> str:
    resolved = path.resolve()
    if os.name == "nt":
        drive = resolved.drive.rstrip(":").lower()
        relative = resolved.as_posix().split(":", 1)[1].lstrip("/")
        return f"/{drive}/{relative}"
    return resolved.as_posix()


def _find_bash() -> str | None:
    if os.name == "nt":
        program_files = os.environ.get("ProgramFiles")
        if program_files:
            git_bash = Path(program_files) / "Git" / "bin" / "bash.exe"
            if git_bash.is_file():
                return str(git_bash)
    return shutil.which("bash")


@unittest.skipUnless(_find_bash(), "requires bash")
class TestInstallWizardFlow(unittest.TestCase):
    def _write_executable(self, path: Path, content: str) -> None:
        with path.open("w", encoding="utf-8", newline="\n") as output:
            output.write(textwrap.dedent(content).lstrip())
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def _run_installer(
        self,
        wizard_exit_code: int,
        *,
        fetched_commit: str = "0123456789abcdef0123456789abcdef01234567",
        pip_exit_code: int = 0,
        wrapper_fail: bool = False,
    ) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        home = root / "home"
        install_dir = home / "kace"
        fake_bin = root / "bin"
        marker = root / "wizard-finished"
        install_dir.mkdir(parents=True)
        (home / ".local" / "bin").mkdir(parents=True)
        fake_bin.mkdir()
        (install_dir / ".git").mkdir()
        (install_dir / "VERSION").write_text("0.0-test\n", encoding="utf-8")
        (install_dir / "requirements.txt").write_text("", encoding="utf-8")
        (install_dir / "kace.py").write_text("print('old runtime')\n", encoding="utf-8")
        (install_dir / "venv").mkdir()
        (install_dir / "venv" / "stale-package").write_text("stale\n", encoding="utf-8")
        (install_dir / "printer.cfg").write_text("# generated config\n", encoding="utf-8")
        (install_dir / "snapshots").mkdir()
        (install_dir / "snapshots" / "state.json").write_text("{}\n", encoding="utf-8")

        self._write_executable(fake_bin / "clear", "#!/bin/sh\nexit 0\n")
        self._write_executable(fake_bin / "apt-get", "#!/bin/sh\nexit 0\n")
        self._write_executable(fake_bin / "getent", "#!/bin/sh\nexit 0\n")
        self._write_executable(
            fake_bin / "sudo",
            """
            #!/bin/sh
            if [ "$KACE_TEST_WRAPPER_FAIL" = "1" ] && [ "$1" = "mv" ]; then
                for argument in "$@"; do
                    if [ "$argument" = "$KACE_INSTALL_BIN" ]; then
                        exit 42
                    fi
                done
            fi
            exec "$@"
            """,
        )
        self._write_executable(fake_bin / "flock", "#!/bin/sh\nexit 0\n")
        self._write_executable(
            fake_bin / "git",
            """
            #!/bin/sh
            if [ "$1" = "--version" ]; then
                echo "git version 2.40.0"
                exit 0
            fi
            if [ "$1" != "-C" ]; then
                exit 2
            fi
            repo="$2"
            shift 2
            case "$1" in
                init)
                    mkdir -p "$repo/.git"
                    ;;
                remote|sparse-checkout|fetch)
                    ;;
                rev-parse)
                    printf '%s\n' "$KACE_TEST_FETCHED_COMMIT"
                    ;;
                -c)
                    mkdir -p "$repo/core" "$repo/firmware" "$repo/data" \
                        "$repo/templates" "$repo/scripts"
                    printf '0.0-new\n' > "$repo/VERSION"
                    printf '' > "$repo/requirements.txt"
                    printf '' > "$repo/requirements-ssh.txt"
                    printf 'print(\"new runtime\")\n' > "$repo/kace.py"
                    printf '# test wrapper\n' > "$repo/scripts/cc_wrapper.py"
                    ;;
                *)
                    exit 2
                    ;;
            esac
            exit 0
            """,
        )
        self._write_executable(
            fake_bin / "python3",
            """
            #!/bin/sh
            if [ "$1" = "-c" ]; then
                exec "$KACE_TEST_REAL_PYTHON" "$@"
            fi
            if [ "$1" = "-" ]; then
                exec "$KACE_TEST_REAL_PYTHON" "$@"
            fi
            if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
                venv_dir="$3"
                mkdir -p "$venv_dir/bin"
                printf 'command = %s/venv\\n' "$venv_dir" > "$venv_dir/pyvenv.cfg"
                cat >"$venv_dir/bin/python" <<'EOF'
            #!/bin/sh
            if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then
                exit "$KACE_TEST_PIP_EXIT"
            fi
            if [ "$1" = "-c" ]; then
                exit 0
            fi
            echo WIZARD_STARTED
            touch "$KACE_TEST_WIZARD_MARKER"
            echo WIZARD_FINISHED
            exit "$KACE_TEST_WIZARD_EXIT"
            EOF
                chmod +x "$venv_dir/bin/python"
                exit 0
            fi
            exit 2
            """,
        )

        environment = os.environ.copy()
        environment.update(
            {
                "HOME": str(home),
                "KACE_SOURCE_REF": "0123456789abcdef0123456789abcdef01234567",
                "KACE_INSTALL_BIN": _shell_path(home / ".local" / "bin" / "kace"),
                "KACE_TEST_REAL_PYTHON": _shell_path(Path(sys.executable)),
                "KACE_TEST_WIZARD_MARKER": _shell_path(marker),
                "KACE_TEST_WIZARD_EXIT": str(wizard_exit_code),
                "KACE_TEST_FETCHED_COMMIT": fetched_commit,
                "KACE_TEST_PIP_EXIT": str(pip_exit_code),
                "KACE_TEST_WRAPPER_FAIL": "1" if wrapper_fail else "0",
                "MSYS2_ENV_CONV_EXCL": "KACE_VENV_FROM;KACE_VENV_TO",
                "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            }
        )
        result = subprocess.run(
            [
                _find_bash(),
                "-c",
                'export PATH="$1:$PATH"; exec bash "$2"',
                "installer-test",
                _shell_path(fake_bin),
                _shell_path(INSTALLER),
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        return result, marker, install_dir

    def test_default_install_launches_and_waits_for_wizard(self):
        result, marker, install_dir = self._run_installer(0)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(marker.exists())
        launch_index = result.stdout.index("Launching KACE")
        started_index = result.stdout.index("WIZARD_STARTED")
        finished_index = result.stdout.index("WIZARD_FINISHED")
        self.assertLess(launch_index, started_index)
        self.assertLess(started_index, finished_index)
        self.assertEqual((install_dir / "printer.cfg").read_text(encoding="utf-8"), "# generated config\n")
        self.assertTrue((install_dir / "snapshots" / "state.json").is_file())
        self.assertFalse((install_dir / "venv" / "stale-package").exists())
        self.assertIn("new runtime", (install_dir / "kace.py").read_text(encoding="utf-8"))
        self.assertNotIn(
            ".kace-install.",
            (install_dir / "venv" / "pyvenv.cfg").read_text(encoding="utf-8"),
        )

    def test_wizard_failure_is_returned_by_installer(self):
        result, marker, _install_dir = self._run_installer(7)

        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
        self.assertTrue(marker.exists())
        self.assertIn("WIZARD_FINISHED", result.stdout)

    def test_wrong_fetched_commit_is_rejected_before_publication(self):
        result, marker, install_dir = self._run_installer(
            0,
            fetched_commit="f" * 40,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(marker.exists())
        self.assertIn("old runtime", (install_dir / "kace.py").read_text(encoding="utf-8"))
        self.assertTrue((install_dir / "venv" / "stale-package").is_file())
        self.assertTrue((install_dir / "printer.cfg").is_file())

    def test_dependency_failure_leaves_previous_runtime_untouched(self):
        result, marker, install_dir = self._run_installer(0, pip_exit_code=9)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(marker.exists())
        self.assertIn("old runtime", (install_dir / "kace.py").read_text(encoding="utf-8"))
        self.assertTrue((install_dir / "venv" / "stale-package").is_file())
        self.assertTrue((install_dir / "snapshots" / "state.json").is_file())

    def test_wrapper_publication_failure_rolls_back_replaced_runtime(self):
        result, marker, install_dir = self._run_installer(0, wrapper_fail=True)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(marker.exists())
        self.assertIn("old runtime", (install_dir / "kace.py").read_text(encoding="utf-8"))
        self.assertTrue((install_dir / "venv" / "stale-package").is_file())
        self.assertEqual((install_dir / "printer.cfg").read_text(encoding="utf-8"), "# generated config\n")
        self.assertTrue((install_dir / "snapshots" / "state.json").is_file())


if __name__ == "__main__":
    unittest.main()
