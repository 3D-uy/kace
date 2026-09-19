"""
Unit tests for scripts/pre-commit

Validates that the pre-commit hook correctly:
  - allows clean files with production repo URLs (exit 0)
  - blocks github.com/kace-dev URLs in any file type (exit 1)
  - blocks raw.githubusercontent.com/kace-dev URLs (exit 1)
  - allows 'kace-dev' as a bare word / docker service name with no URL prefix (exit 0)
  - blocks Windows C:\\Users path leaks (exit 1)
  - blocks secondary-drive workspace path leaks (exit 1)

The hook is exercised in-process by patching subprocess.check_output so that
the fake git-diff result points at temporary files we control. This avoids
any dependency on the real git index or a working git installation.

Background: the double-escaping bug (C:\\\\Users vs C:\\Users) found during
manual validation is exactly the class of silent failure these tests guard
against. A hook that looks like it catches path leaks but fails on real file
content is worse than no hook at all.
"""
import os
import sys
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from unittest.mock import patch


# Locate the hook relative to this file: tests/unit/ -> tests/ -> root -> scripts/pre-commit
_TESTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOT_DIR  = os.path.dirname(_TESTS_DIR)
_HOOK_PATH = os.path.join(_ROOT_DIR, "scripts", "pre-commit")


def _run_hook(staged_file_contents: dict) -> int:
    """
    Execute the pre-commit hook logic in-process against a controlled set of
    staged files.

    Args:
        staged_file_contents: dict mapping relative filename to file content string.
            Files are written to a temp directory; their absolute paths are fed to
            the hook as the output of 'git diff --cached --name-only'.

    Returns:
        The integer exit code (0 = clean, 1 = blocked).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        written_paths = []
        for fname, content in staged_file_contents.items():
            fpath = os.path.join(tmpdir, fname)
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(content)
            written_paths.append(fpath)

        fake_git_output = "\n".join(written_paths)

        with patch("subprocess.check_output", return_value=fake_git_output):
            with open(_HOOK_PATH, "r", encoding="utf-8") as f:
                source = f.read()
            ns = {"__name__": "__main__", "__file__": _HOOK_PATH}
            try:
                exec(compile(source, _HOOK_PATH, "exec"), ns)  # noqa: S102
                return 0   # hook completed without calling sys.exit → clean
            except SystemExit as e:
                return e.code if isinstance(e.code, int) else 0


class TestPreCommitHook(unittest.TestCase):

    def test_copied_hook_uses_repository_portability_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(["git", "init", directory], check=True, capture_output=True)
            scripts = os.path.join(directory, "scripts")
            os.makedirs(scripts)
            shutil.copyfile(os.path.join(_ROOT_DIR, "scripts", "check_portability.py"),
                            os.path.join(scripts, "check_portability.py"))
            hook = os.path.join(directory, ".git", "hooks", "pre-commit")
            shutil.copyfile(_HOOK_PATH, hook)
            with open(os.path.join(directory, "example.txt"), "w", encoding="utf-8") as stream:
                stream.write("D:" + "/fixture-workspace/cache")
            subprocess.run(["git", "add", "example.txt"], cwd=directory,
                           check=True, capture_output=True)
            result = subprocess.run([sys.executable, hook], cwd=directory,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("Local path leak detected", result.stdout)

    # ── Should pass (exit 0) ──────────────────────────────────────────────────

    def test_clean_file_exits_zero(self):
        """Clean file with production URL — hook exits 0."""
        code = _run_hook({
            "core/example.py": textwrap.dedent("""\
                # Normal file
                REPO_URL = "https://github.com/3D-uy/kace.git"
                print("hello")
            """)
        })
        self.assertEqual(code, 0)

    def test_docker_service_name_not_blocked(self):
        """'kace-dev' as a bare docker-compose service name (no URL) — hook exits 0."""
        code = _run_hook({
            "docs/en/docker_guide.md": "docker-compose run --rm kace-dev\n"
        })
        self.assertEqual(code, 0)

    def test_contributing_two_repo_description_not_blocked(self):
        """Prose mention of kace-dev without a GitHub URL — hook exits 0."""
        code = _run_hook({
            "docs/en/CONTRIBUTING.md": (
                "PRs should target `kace-dev` for verification before promotion.\n"
            )
        })
        self.assertEqual(code, 0)

    # ── Should block (exit 1) ─────────────────────────────────────────────────

    def test_github_kace_dev_url_in_py_blocked(self):
        """github.com/kace-dev repo URL in a .py file — hook exits 1."""
        code = _run_hook({
            "core/bad.py": 'REPO_URL = "https://github.com/3D-uy/kace-dev.git"\n'
        })
        self.assertEqual(code, 1)

    def test_raw_githubusercontent_kace_dev_url_in_md_blocked(self):
        """raw.githubusercontent.com/kace-dev URL in a .md file — hook exits 1."""
        code = _run_hook({
            "README.md": (
                "curl -sSL https://raw.githubusercontent.com/3D-uy/kace-dev/main/install.sh\n"
            )
        })
        self.assertEqual(code, 1)

    def test_github_kace_dev_url_in_sh_blocked(self):
        """github.com/kace-dev URL in a .sh file — hook exits 1."""
        code = _run_hook({
            "install.sh": 'REPO_URL="https://github.com/3D-uy/kace-dev.git"\n'
        })
        self.assertEqual(code, 1)

    def test_windows_c_users_path_leak_blocked(self):
        """C:\\Users path leak in a .py file — hook exits 1.

        The fixture writes one backslash per separator. Escaped and alternate
        separators are also covered by the shared portability guard tests.
        """
        code = _run_hook({
            "core/deployer.py": 'path = "' + 'C:' + chr(92) + 'Users' + chr(92) + 'fixture-user' + chr(92) + 'project"\n'
        })
        self.assertEqual(code, 1)

    def test_windows_secondary_drive_path_leak_blocked(self):
        """secondary-drive workspace path leak in a .py file — hook exits 1."""
        code = _run_hook({
            "core/scraper.py": 'cache = "' + 'D:' + chr(92) + 'fixture-workspace' + chr(92) + 'cache"\n'
        })
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
