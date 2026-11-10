"""The documented entrypoint must execute pytest functions and fixtures."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]


def run_fixture_suite(tmp_path, source, conftest=""):
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "test_sample.py").write_text(source, encoding="utf-8")
    (suite / "conftest.py").write_text(conftest, encoding="utf-8")
    # Exercise the real entrypoint against a tiny independent suite. Only its
    # discovery location changes; collection, fixtures and exit handling do not.
    script = (
        "import sys; from tests import run_tests; "
        "run_tests.__file__ = sys.argv[1]; "
        "sys.argv = ['run_tests.py']; run_tests.main()"
    )
    env = dict(os.environ, PYTEST_ADDOPTS="", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    return subprocess.run(
        [sys.executable, "-c", script, str(suite / "run_tests.py")],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=60,
    )


def test_entrypoint_executes_functions_and_unittest_fixtures(tmp_path):
    marker = tmp_path / "function-called"
    result = run_fixture_suite(tmp_path, f'''
from pathlib import Path
import unittest
import pytest

def test_function(fixture_value):
    assert fixture_value == "prepared"
    Path({str(marker)!r}).write_text("executed", encoding="utf-8")

@pytest.mark.usefixtures("prepare_case")
class TestWithFixture(unittest.TestCase):
    def test_fixture(self):
        self.assertEqual(self.prepared, "prepared")
''', '''
import pytest

@pytest.fixture
def fixture_value():
    return "prepared"

@pytest.fixture
def prepare_case(request, fixture_value):
    request.cls.prepared = fixture_value
''')
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.read_text(encoding="utf-8") == "executed"
    assert "2 passed" in result.stdout


def test_entrypoint_propagates_function_failure(tmp_path):
    result = run_fixture_suite(tmp_path, '''
def test_expected_failure():
    assert False, "deliberate entrypoint regression fixture"
''')
    assert result.returncode == 1, result.stdout + result.stderr
    assert "deliberate entrypoint regression fixture" in result.stdout


@pytest.mark.parametrize("success", [False, True])
@pytest.mark.parametrize("mode", ["--yaml-check", "--full-klipper-sweep"])
def test_special_modes_keep_separate_dispatch(monkeypatch, mode, success):
    from tests import run_tests

    calls = []
    def separate(verbose=False):
        calls.append(verbose)
        return success

    def unexpected_pytest(_args):
        pytest.fail("special mode must not execute the standard suite")

    monkeypatch.setattr(pytest, "main", unexpected_pytest)
    monkeypatch.setattr(sys, "argv", ["run_tests.py", mode, "--verbose"])
    if mode == "--yaml-check":
        monkeypatch.setattr(run_tests, "run_yaml_check", separate)
    else:
        from tests.sweep import full_sweep_runner
        monkeypatch.setattr(full_sweep_runner, "run_full_sweep", separate)
    with pytest.raises(SystemExit) as stopped:
        run_tests.main()
    assert stopped.value.code == (0 if success else 1)
    assert calls == [True]


def test_standard_mode_preserves_explicit_environment_flags(monkeypatch):
    from tests import run_tests

    for name in ("KACE_UPDATE_SNAPSHOTS", "KACE_TEST_BOARD", "KACE_TEST_ALL_BOARDS"):
        # Track restoration even when the key was originally absent: main()
        # writes os.environ directly and must not affect subsequent tests.
        monkeypatch.setenv(name, "")
    monkeypatch.setattr(sys, "argv", ["run_tests.py", "--update-snapshots", "--board", "fixture-board",
                                     "--all-boards", "--verbose"])
    def collect(_args):
        assert os.environ["KACE_UPDATE_SNAPSHOTS"] == "1"
        assert os.environ["KACE_TEST_BOARD"] == "fixture-board"
        assert os.environ["KACE_TEST_ALL_BOARDS"] == "1"
        return 2

    # No snapshot is updated: this exercises only option forwarding and exit
    # propagation, with collection replaced explicitly for this boundary test.
    monkeypatch.setattr(pytest, "main", collect)
    with pytest.raises(SystemExit) as stopped:
        run_tests.main()
    assert stopped.value.code == 2
