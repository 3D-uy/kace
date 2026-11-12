import os
import sys
from pathlib import Path

import pytest

# Keep environment flag active for tests that expect it
os.environ["KACE_TESTING"] = "1"

# Add project root to path
test_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(test_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Initialize generic mock, caching, and UI bypass settings
import core.loader as loader
import core.menu as menu
import core.wizard.ui as wizard_ui
import core.wizard.steps.motion as motion_step

loader.set_bypass_cache(True)
menu.set_mock_prompts_active(True)
wizard_ui.set_suppress_headers(True)
motion_step.set_interactive_mode(False)

# Register the testing compiler wrapper in PATH for subprocess invocation checks
from tests.fixtures.mocks import get_compiler_wrapper_path
os.environ["PATH"] = get_compiler_wrapper_path() + os.pathsep + os.environ.get("PATH", "")


# These pre-existing modules exercise publishing with simulated transports and
# partial synthetic CFGs. Their assertions concern those boundaries, not the
# isolated Klipper loader. New preflight tests run without this double.
_legacy_manifest = Path(test_dir) / "fixtures" / "legacy_preflight_modules.txt"
_legacy_publication_modules = frozenset(_legacy_manifest.read_text(encoding="utf-8").splitlines())
_preflight_test_exclusions = {
    "test_config_include_parser_identity.py",
    "test_firmware_staging_integrity.py",
}
if any("klipper_preflight" in Path(name).name or Path(name).name in _preflight_test_exclusions
       for name in _legacy_publication_modules):
    raise RuntimeError("Klipper preflight tests cannot use the legacy publication double")


@pytest.fixture(autouse=True)
def legacy_publication_preflight(request, monkeypatch):
    """Keep explicitly enumerated older publication tests independent of Docker."""
    try:
        name = Path(str(request.node.path)).resolve().relative_to(Path(project_root).resolve()).as_posix()
    except ValueError:
        return
    if name not in _legacy_publication_modules:
        return
    from core import klipper_preflight

    def simulated(plan):
        return klipper_preflight.PreflightResult(
            "valid", "legacy publication test double; Klipper not executed",
            klipper_preflight.plan_digest(plan),
        )

    monkeypatch.setattr(klipper_preflight, "validate_plan", simulated)
