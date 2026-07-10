import os
import sys

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
