"""
tests/regression/test_main_integration.py
==========================================
Priority-3 — Full CLI integration test for kace.main().

Validates the complete pipeline instead of isolated subsystems:

    main()
    ├─ Phase 0: run_wizard()
    ├─ Phase 1: board config fetch + BLTouch gate + display check
    ├─ Phase 2: firmware wizard gate (has_todo_pins)
    ├─ Phase 3: generate_config()
    └─ Phase 4: deployment selection

Windows headless note
---------------------
All test classes that exercise code paths touching prompt_toolkit output
(even indirectly via the banner or run_dashboard import) must patch
`prompt_toolkit.output.create_output` in setUp() to suppress the
NoConsoleScreenBufferError that prompt_toolkit raises when there is no
Windows console attached (e.g. during pytest / run_tests.py invocations).

Tests verify:
  - Phase transitions (phases sequence correctly, earlier phases gate later ones)
  - Error handling (WizardExit, KeyboardInterrupt, missing deps, GenerationError)
  - User-data propagation (wizard output reaches generate_config correctly)
  - board_parsed short-circuit (pre-fetched board skips fetch_raw_config)
  - TODO-pin gate prevents firmware wizard from running
  - Correct sys.exit codes per scenario

Strategy
--------
* run_wizard is patched to return a controlled user_data — this decouples
  the integration test from the interactive wizard tests.
* All questionary prompts in main() (macros confirm, deploy select) are
  patched directly on the kace module object.
* generate_config is patched to avoid Jinja2 dependency in most tests;
  a generate_config smoke variant runs only when jinja2 is available.
* sys.exit is NOT patched — we use self.assertRaises(SystemExit) and
  inspect the exit code from the exception.
"""

import io
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

# ── Dependency guards ─────────────────────────────────────────────────────────
# kace.py imports core.generator at module level which requires jinja2.
# Pre-stub it when jinja2 is absent so the integration test can still import
# and run the non-generation scenarios.

try:
    import jinja2  # noqa: F401
    _JINJA2_AVAILABLE = True
except ImportError:
    _JINJA2_AVAILABLE = False
    if 'core.generator' not in sys.modules:
        _gen_stub = MagicMock()
        _gen_stub.generate_config.return_value = {"content": "[printer]\n"}
        _gen_stub.has_todo_pins.return_value = []
        sys.modules['core.generator'] = _gen_stub

try:
    import questionary  # noqa: F401
    _QUESTIONARY_AVAILABLE = True
except ImportError:
    _QUESTIONARY_AVAILABLE = False

_skip_no_questionary = unittest.skipUnless(
    _QUESTIONARY_AVAILABLE,
    "questionary not installed — integration tests run in Docker only",
)

_skip_no_jinja2 = unittest.skipUnless(
    _JINJA2_AVAILABLE,
    "jinja2 not installed — generation integration tests run in Docker only",
)

# ── Minimal fixtures ──────────────────────────────────────────────────────────

_RAW_BOARD_CFG = """\
[stepper_x]
step_pin: P2.2
dir_pin: !P2.6
enable_pin: !P2.1
microsteps: 16
rotation_distance: 40
endstop_pin: P1.29
position_endstop: 0
position_max: 235

[stepper_y]
step_pin: P0.19
dir_pin: P0.20
enable_pin: !P2.8
microsteps: 16
rotation_distance: 40
endstop_pin: P1.28
position_endstop: 0
position_max: 235

[stepper_z]
step_pin: P0.22
dir_pin: !P2.11
enable_pin: !P0.21
microsteps: 16
rotation_distance: 8
endstop_pin: P1.25
position_endstop: 0
position_max: 250

[extruder]
step_pin: P2.13
dir_pin: !P0.11
enable_pin: !P2.12
microsteps: 16
rotation_distance: 33.500
nozzle_diameter: 0.400
filament_diameter: 1.750
heater_pin: P2.7
sensor_type: Generic 3950
sensor_pin: P0.24
control: pid
pid_Kp: 22.2
pid_Ki: 1.08
pid_Kd: 114
min_temp: 0
max_temp: 260

[heater_bed]
heater_pin: P2.5
sensor_type: Generic 3950
sensor_pin: P0.25
control: pid
pid_Kp: 54.027
pid_Ki: 0.770
pid_Kd: 948.182
min_temp: 0
max_temp: 130

[bltouch]
sensor_pin: ^P0.10
control_pin: P2.0
"""

_WIZARD_USER_DATA_WITH_PARSED = {
    "board":             "generic-bigtreetech-skr-v1.4.cfg",
    "kinematics":        "cartesian",
    "x_size":            "235",
    "y_size":            "235",
    "z_size":            "250",
    "probe":             "BLTouch",
    "probe_x_offset":    "0",
    "probe_y_offset":    "0",
    "hotend_thermistor": "Generic 3950",
    "bed_thermistor":    "Generic 3950",
    "driver_type":       "TMC2209",
    "driver_mode":       "UART",
    "web_interface":     "Mainsail",
    "z_motors":          "1",
    "mcu_path":          "/dev/serial/by-id/mock",
    # board_parsed pre-populated so fetch_raw_config is NOT called
    "board_parsed": {
        "stepper_x":  {"step_pin": "P2.2",  "dir_pin": "!P2.6",
                       "position_max": "235", "position_endstop": "0"},
        "stepper_y":  {"step_pin": "P0.19", "dir_pin": "P0.20",
                       "position_max": "235", "position_endstop": "0"},
        "stepper_z":  {"step_pin": "P0.22", "dir_pin": "!P2.11",
                       "position_max": "250", "position_endstop": "0"},
        "extruder":   {"sensor_type": "Generic 3950", "heater_pin": "P2.7",
                       "sensor_pin": "P0.24"},
        "heater_bed": {"heater_pin": "P2.5", "sensor_type": "Generic 3950",
                       "sensor_pin": "P0.25"},
        "bltouch":    {"sensor_pin": "^P0.10", "control_pin": "P2.0"},
    },
}

# Same user_data WITHOUT board_parsed to trigger the fetch branch
_WIZARD_USER_DATA_NO_PARSED = {
    k: v for k, v in _WIZARD_USER_DATA_WITH_PARSED.items() if k != "board_parsed"
}


# ── Context manager helpers ───────────────────────────────────────────────────

def _mock_questionary_for_main(macros_answer=True, deploy_answer="none"):
    """Return a dict of patches to suppress Phase 3/4 prompts
    inside main() (macros confirm + deployment select)."""
    return {
        "kace.yes_no": MagicMock(return_value=macros_answer),
        "kace.numbered_select":  MagicMock(return_value=deploy_answer),
    }


# ── Shared setUp helper ───────────────────────────────────────────────────────

class _HeadlessMixin:
    """Suppress prompt_toolkit Windows console errors and bypass the dashboard.

    Two problems exist in headless (no-terminal) environments on Windows:

    1.  prompt_toolkit raises NoConsoleScreenBufferError when there is no
        Windows console.  Patching create_output prevents that.
    2.  kace.main() does `from core.dashboard import ...` when KACE_AUTO is
        not set, which triggers a prompt_toolkit initialisation that also
        raises the error.

    Setting KACE_AUTO=1 in setUp() causes main() to set _bypassed=True and
    skip the dashboard import entirely.

    3.  kace.py runs `_ap.parse_known_args()` at module-import time.  When
        pytest is invoked with ``-v`` (verbose), that flag is seen as the
        ``--version``/``-v`` CLI option and `sys.exit(0)` fires during the
        lazy `import kace` triggered by @patch decorators.  Neutralising
        sys.argv in setUp() prevents this; tearDown() restores it so other
        test modules are unaffected.
    """

    def setUp(self):
        # Neutralise sys.argv so kace.py's module-level argparse does not
        # misinterpret pytest's -v/--verbose flag as --version.
        self._orig_argv = sys.argv[:]
        sys.argv = ["kace"]
        # Bypass dashboard / prompt_toolkit import inside kace.main()
        os.environ["KACE_AUTO"] = "1"
        self._pt_patch = patch(
            'prompt_toolkit.output.create_output',
            return_value=MagicMock(),
        )
        self._pt_patch.start()

    def tearDown(self):
        self._pt_patch.stop()
        os.environ.pop("KACE_AUTO", None)
        sys.argv = self._orig_argv


# ── Phase-transition & error-handling tests ────────────────────────────────────

class TestMainCLIPipelinePhases(_HeadlessMixin, unittest.TestCase):
    """
    Each test validates one distinct execution path through main().
    All tests patch run_wizard to supply controlled user_data; only the
    variable under test changes between scenarios.
    """

    # ── WizardExit ────────────────────────────────────────────────────────────

    @patch('kace.print_kace_banner')
    @patch('kace.run_wizard', side_effect=__import__('core.exceptions', fromlist=['WizardExit']).WizardExit)
    @patch('builtins.print')
    def test_wizard_exit_is_caught_and_exits_cancelled(self, mock_print, mock_wizard, mock_banner):
        """WizardExit is a terminal cancellation, never workflow success."""
        import kace
        with self.assertRaises(SystemExit) as ctx:
            kace.main()
        self.assertEqual(ctx.exception.code, 2)

    # ── KeyboardInterrupt ─────────────────────────────────────────────────────

    @patch('kace.print_kace_banner')
    @patch('kace.run_wizard', side_effect=KeyboardInterrupt)
    @patch('builtins.print')
    def test_keyboard_interrupt_is_caught_and_exits_cancelled(self, mock_print, mock_wizard, mock_banner):
        """Ctrl-C from the wizard is a terminal cancellation."""
        import kace
        with self.assertRaises(SystemExit) as ctx:
            kace.main()
        self.assertEqual(ctx.exception.code, 2)

    # ── Missing dependency ────────────────────────────────────────────────────

    @patch('kace.print_kace_banner')
    @patch('kace.run_wizard', side_effect=ImportError("No module named 'paramiko'"))
    @patch('builtins.print')
    def test_missing_dependency_is_caught_and_exits_1(self, mock_print, mock_wizard, mock_banner):
        """An ImportError from the wizard (missing dep) must exit with code 1."""
        import kace
        with self.assertRaises(SystemExit) as ctx:
            kace.main()
        self.assertEqual(ctx.exception.code, 10)

    # ── Board fetch failure ───────────────────────────────────────────────────

    @patch('kace.print_kace_banner')
    @patch('kace.run_wizard', return_value=dict(_WIZARD_USER_DATA_NO_PARSED))
    @patch('kace.fetch_raw_config', return_value="")  # empty = fetch failed
    @patch('builtins.print')
    def test_board_fetch_failure_exits_1(self, mock_print, mock_fetch, mock_wizard, mock_banner):
        """If fetch_raw_config returns '' (network/404 failure), main() must
        print an error message and exit with code 1."""
        import kace
        with self.assertRaises(SystemExit) as ctx:
            kace.main()
        self.assertEqual(ctx.exception.code, 10)
        printed = ' '.join(str(c) for c in mock_print.call_args_list)
        self.assertIn("Board configuration could not be fetched", printed)

    # ── fetch_raw_config bypassed when board_parsed in user_data ──────────────

    @patch('kace.print_kace_banner')
    @patch('kace.run_wizard', return_value=dict(_WIZARD_USER_DATA_WITH_PARSED))
    @patch('kace.fetch_raw_config')
    @patch('kace.check_display_compatibility', return_value=[])
    @patch('kace.generate_config', return_value={"content": "[printer]\n"})
    @patch('kace.has_todo_pins', return_value=[])
    @patch('kace.print_summary')
    @patch('kace.time.sleep')
    @patch('builtins.print')
    def test_board_parsed_in_user_data_bypasses_fetch(
        self, mock_print, mock_sleep, mock_summary, mock_todos,
        mock_gen, mock_display, mock_fetch, mock_wizard, mock_banner,
    ):
        """If run_wizard already set board_parsed, fetch_raw_config must NOT
        be called — the cached parse is reused directly."""
        q_patches = _mock_questionary_for_main()
        with patch('kace.yes_no', q_patches['kace.yes_no']), \
             patch('kace.numbered_select',  q_patches['kace.numbered_select']):
            import kace
            with self.assertRaises(SystemExit):
                kace.main()

        mock_fetch.assert_not_called()

    # ── TODO-pin gate blocks firmware wizard ──────────────────────────────────

    @patch('kace.print_kace_banner')
    @patch('kace.run_wizard', return_value={
        **_WIZARD_USER_DATA_WITH_PARSED,
        "mcu_type": "stm32f103",          # MCU present → firmware path attempted
        "mcu_hint": "usb",
    })
    @patch('kace.fetch_raw_config', return_value=_RAW_BOARD_CFG)
    @patch('kace.check_display_compatibility', return_value=[])
    @patch('kace.has_todo_pins', return_value=[("bltouch", "sensor_pin")])  # TODO present
    @patch('kace.generate_config', return_value={"content": "[printer]\n"})
    @patch('kace.print_summary')
    @patch('kace.time.sleep')
    @patch('builtins.print')
    def test_todo_pins_gate_skips_firmware_wizard(
        self, mock_print, mock_sleep, mock_summary, mock_gen, mock_todos,
        mock_display, mock_fetch, mock_wizard, mock_banner,
    ):
        """When has_todo_pins() returns unresolved pins, the firmware wizard
        must be skipped and a clear explanation printed to the user."""
        q_patches = _mock_questionary_for_main()
        firmware_wizard_calls = []

        with patch('kace.yes_no', q_patches['kace.yes_no']), \
             patch('kace.numbered_select',  q_patches['kace.numbered_select']), \
             patch('core.firmware_wizard.run_firmware_wizard',
                   side_effect=lambda ud: firmware_wizard_calls.append(ud)):
            import kace
            with self.assertRaises(SystemExit):
                kace.main()

        self.assertEqual(firmware_wizard_calls, [],
                         "run_firmware_wizard must NOT be called when TODO pins exist")
        printed = ' '.join(str(c) for c in mock_print.call_args_list)
        self.assertIn("Firmware compilation skipped", printed)

    # ── GenerationError aborts with exit 1 ───────────────────────────────────

    @patch('kace.print_kace_banner')
    @patch('kace.run_wizard', return_value=dict(_WIZARD_USER_DATA_WITH_PARSED))
    @patch('kace.check_display_compatibility', return_value=[])
    @patch('kace.has_todo_pins', return_value=[])
    @patch('kace.print_summary')
    @patch('kace.time.sleep')
    @patch('builtins.print')
    def test_generation_error_exits_1(
        self, mock_print, mock_sleep, mock_summary, mock_todos,
        mock_display, mock_wizard, mock_banner,
    ):
        """A GenerationError from generate_config() must be caught and produce
        sys.exit(1) with an informative error message."""
        from core.exceptions import GenerationError
        gen_err = GenerationError(
            "Unresolved TODO pin in [bltouch]",
            todos=[("bltouch", "sensor_pin")],
        )

        q_patches = _mock_questionary_for_main()
        with patch('kace.yes_no', q_patches['kace.yes_no']), \
             patch('kace.numbered_select',  q_patches['kace.numbered_select']), \
             patch('kace.generate_config', side_effect=gen_err):
            import kace
            with self.assertRaises(SystemExit) as ctx:
                kace.main()

        self.assertEqual(ctx.exception.code, 20)
        printed = ' '.join(str(c) for c in mock_print.call_args_list)
        self.assertIn("ERROR", printed)

    # ── Deploy = none → clean exit 0 ─────────────────────────────────────────

    @patch('kace.print_kace_banner')
    @patch('kace.run_wizard', return_value=dict(_WIZARD_USER_DATA_WITH_PARSED))
    @patch('kace.check_display_compatibility', return_value=[])
    @patch('kace.generate_config', return_value={"content": "[printer]\n"})
    @patch('kace.has_todo_pins', return_value=[])
    @patch('kace.print_summary')
    @patch('kace.time.sleep')
    @patch('builtins.print')
    def test_deploy_none_exits_successfully(
        self, mock_print, mock_sleep, mock_summary, mock_todos,
        mock_gen, mock_display, mock_wizard, mock_banner,
    ):
        """Choosing 'none' for deployment must complete the pipeline and
        exit with code 0."""
        q_patches = _mock_questionary_for_main(macros_answer=True, deploy_answer="none")
        with patch('kace.yes_no', q_patches['kace.yes_no']), \
             patch('kace.numbered_select',  q_patches['kace.numbered_select']):
            import kace
            with self.assertRaises(SystemExit) as ctx:
                kace.main()

        self.assertEqual(ctx.exception.code, 0)


# ── User-data propagation tests ───────────────────────────────────────────────

class TestMainCLIDataPropagation(_HeadlessMixin, unittest.TestCase):
    """Verifies that data flows correctly between pipeline phases."""

    @patch('kace.print_kace_banner')
    @patch('kace.run_wizard', return_value=dict(_WIZARD_USER_DATA_WITH_PARSED))
    @patch('kace.check_display_compatibility', return_value=[])
    @patch('kace.has_todo_pins', return_value=[])
    @patch('kace.print_summary')
    @patch('kace.time.sleep')
    @patch('builtins.print')
    def test_generate_config_receives_correct_board_parsed(
        self, mock_print, mock_sleep, mock_summary, mock_todos,
        mock_display, mock_wizard, mock_banner,
    ):
        """generate_config must be called with the board_parsed dict that was
        returned (or pre-set) by the wizard — not with an empty dict."""
        captured_args = {}

        def capture_generate(parsed_data, user_data, **kwargs):
            captured_args["parsed_data"] = parsed_data
            captured_args["user_data"]   = user_data
            return {"content": "[printer]\n"}

        q_patches = _mock_questionary_for_main()
        with patch('kace.yes_no', q_patches['kace.yes_no']), \
             patch('kace.numbered_select',  q_patches['kace.numbered_select']), \
             patch('kace.generate_config', side_effect=capture_generate):
            import kace
            with self.assertRaises(SystemExit):
                kace.main()

        self.assertIn("parsed_data", captured_args, "generate_config was never called")
        self.assertIn("stepper_x", captured_args["parsed_data"],
                      "board_parsed must contain stepper_x section")
        self.assertEqual(
            captured_args["user_data"]["board"],
            "generic-bigtreetech-skr-v1.4.cfg",
            "user_data must propagate the board name to generate_config",
        )

    @patch('kace.print_kace_banner')
    @patch('kace.run_wizard', return_value=dict(_WIZARD_USER_DATA_NO_PARSED))
    @patch('kace.fetch_raw_config', return_value=_RAW_BOARD_CFG)
    @patch('kace.check_display_compatibility', return_value=[])
    @patch('kace.has_todo_pins', return_value=[])
    @patch('kace.print_summary')
    @patch('kace.time.sleep')
    @patch('builtins.print')
    def test_fetch_raw_config_called_when_board_parsed_absent(
        self, mock_print, mock_sleep, mock_summary, mock_todos,
        mock_display, mock_fetch, mock_wizard, mock_banner,
    ):
        """When the wizard does not pre-populate board_parsed, main() must call
        fetch_raw_config with the board name from user_data."""
        q_patches = _mock_questionary_for_main()
        with patch('kace.yes_no', q_patches['kace.yes_no']), \
             patch('kace.numbered_select',  q_patches['kace.numbered_select']), \
             patch('kace.generate_config', return_value={"content": "[printer]\n"}):
            import kace
            with self.assertRaises(SystemExit):
                kace.main()

        mock_fetch.assert_called_once_with("generic-bigtreetech-skr-v1.4.cfg")

    @patch('kace.print_kace_banner')
    @patch('kace.run_wizard', return_value=dict(_WIZARD_USER_DATA_WITH_PARSED))
    @patch('kace.check_display_compatibility', return_value=[])
    @patch('kace.generate_config', return_value={"content": "[printer]\n"})
    @patch('kace.has_todo_pins', return_value=[])
    @patch('kace.print_summary')
    @patch('kace.time.sleep')
    @patch('builtins.print')
    def test_macros_flag_propagated_to_generate_config(
        self, mock_print, mock_sleep, mock_summary, mock_todos,
        mock_gen, mock_display, mock_wizard, mock_banner,
    ):
        """The macros_generated flag (from user's confirm answer) must reach
        generate_config as the include_macros keyword argument."""
        captured_kwargs = {}

        def capture(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return {"content": "[printer]\n"}

        with patch('kace.yes_no', return_value=False), \
             patch('kace.numbered_select', return_value='none'), \
             patch('kace.generate_config', side_effect=capture):
            import kace
            with self.assertRaises(SystemExit):
                kace.main()

        self.assertIn("include_macros", captured_kwargs,
                      "include_macros kwarg must be passed to generate_config")
        self.assertFalse(captured_kwargs["include_macros"],
                         "include_macros must be False when user declined macros generation")


# ── Deployment path selection tests ──────────────────────────────────────────

class TestMainCLIDeploymentSelection(_HeadlessMixin, unittest.TestCase):
    """Verifies the correct deployment function is called for each deploy choice."""

    def _run_with_deploy(self, deploy_choice: str, deploy_fn_path: str):
        """Run main() with the given deploy choice and assert the correct
        deployment function is called (or not called for 'none')."""
        deploy_mock = MagicMock()

        with patch('kace.print_kace_banner'), \
             patch('kace.run_wizard', return_value=dict(_WIZARD_USER_DATA_WITH_PARSED)), \
             patch('kace.check_display_compatibility', return_value=[]), \
             patch('kace.generate_config', return_value={"content": "[printer]\n"}), \
             patch('kace.has_todo_pins', return_value=[]), \
             patch('kace.print_summary'), \
             patch('kace.time.sleep'), \
             patch('builtins.print'), \
             patch('kace.yes_no', return_value=True), \
             patch('kace.numbered_select', return_value=deploy_choice), \
             patch(deploy_fn_path, deploy_mock):
            import kace
            with self.assertRaises(SystemExit):
                kace.main()

        return deploy_mock

    def test_deploy_usb_calls_deploy_usb(self):
        """Selecting 'usb' must invoke deploy_usb with artifact_type='config'."""
        deploy_mock = self._run_with_deploy("usb", "kace.deploy_usb")
        deploy_mock.assert_called_once()
        _, kwargs = deploy_mock.call_args
        self.assertEqual(kwargs.get("artifact_type", None) or
                         deploy_mock.call_args[0][1] if len(deploy_mock.call_args[0]) > 1 else kwargs.get("artifact_type"),
                         "config")

    def test_deploy_local_calls_deploy_local(self):
        """Selecting 'local' must invoke deploy_local."""
        deploy_mock = self._run_with_deploy("local", "kace.deploy_local")
        deploy_mock.assert_called_once()

    def test_deploy_moonraker_calls_deploy_moonraker(self):
        """Selecting 'moonraker' must invoke deploy_moonraker."""
        deploy_mock = self._run_with_deploy("moonraker", "kace.deploy_moonraker")
        deploy_mock.assert_called_once()

    def test_deploy_none_calls_no_deploy_function(self):
        """Selecting 'none' must not invoke any deployment function."""
        usb_mock   = MagicMock()
        ssh_mock   = MagicMock()
        moon_mock  = MagicMock()
        local_mock = MagicMock()

        with patch('kace.print_kace_banner'), \
             patch('kace.run_wizard', return_value=dict(_WIZARD_USER_DATA_WITH_PARSED)), \
             patch('kace.check_display_compatibility', return_value=[]), \
             patch('kace.generate_config', return_value={"content": "[printer]\n"}), \
             patch('kace.has_todo_pins', return_value=[]), \
             patch('kace.print_summary'), \
             patch('kace.time.sleep'), \
             patch('builtins.print'), \
             patch('kace.yes_no', return_value=True), \
             patch('kace.numbered_select', return_value='none'), \
             patch('kace.deploy_usb',       usb_mock), \
             patch('kace.deploy_local',     local_mock), \
             patch('kace.deploy_config',    ssh_mock), \
             patch('kace.deploy_moonraker', moon_mock):
            import kace
            with self.assertRaises(SystemExit):
                kace.main()

        usb_mock.assert_not_called()
        ssh_mock.assert_not_called()
        moon_mock.assert_not_called()
        local_mock.assert_not_called()


class TestMainCLIFirmwareTransactionResult(_HeadlessMixin, unittest.TestCase):
    """The structured terminal result must control the process exit code."""

    def _run(self, terminal_state):
        from core.moonraker_deployer import DeployResult
        # kace.py owns ``-v`` as --version; unittest also uses it for verbose
        # output, so import with a neutral argv in isolated module runs.
        with patch.object(sys, "argv", ["test_main_integration"]):
            import kace
        user_data = dict(_WIZARD_USER_DATA_WITH_PARSED)
        user_data["pending_firmware_deployment"] = True
        user_data["klipper_version"] = "kace-test"
        user_data["firmware_artifact"] = SimpleNamespace(firmware_identity=object())
        result = DeployResult(terminal_state, "test result")

        with patch('kace.print_kace_banner'), \
             patch('kace.run_wizard', return_value=user_data), \
             patch('kace.check_display_compatibility', return_value=[]), \
             patch('kace.generate_config', return_value={"content": "[printer]\n"}), \
             patch('kace.has_todo_pins', return_value=[]), \
             patch('kace.print_summary'), \
             patch('kace.time.sleep'), \
             patch('builtins.print'), \
             patch('kace.yes_no', return_value=True), \
             patch('kace.numbered_select') as deploy_menu, \
             patch('kace.deploy_firmware_installation', return_value=result) as install:
            with self.assertRaises(SystemExit) as ctx:
                kace.main()

        install.assert_called_once_with(user_data)
        deploy_menu.assert_not_called()
        return ctx.exception.code

    def test_done_exits_zero(self):
        from core.moonraker_deployer import DeployState
        self.assertEqual(self._run(DeployState.DONE), 0)

    def test_non_done_exits_nonzero(self):
        from core.moonraker_deployer import DeployState
        self.assertEqual(self._run(DeployState.FAILED_FLASH), 30)


# ── Full smoke pipeline test (requires jinja2) ─────────────────────────────────

@_skip_no_jinja2
class TestMainCLIFullPipelineSmoke(_HeadlessMixin, unittest.TestCase):
    """Smoke test: runs the COMPLETE pipeline with real generate_config()
    so that the Jinja2 template is exercised end-to-end through main()."""

    @patch('kace.print_kace_banner')
    @patch('kace.run_wizard')   # return_value set dynamically in test body
    @patch('kace.check_display_compatibility', return_value=[])
    @patch('kace.has_todo_pins', return_value=[])
    @patch('kace.print_summary')
    @patch('kace.time.sleep')
    @patch('builtins.print')
    def test_real_generate_config_called_and_exits_0(
        self, mock_print, mock_sleep, mock_summary, mock_todos,
        mock_display, mock_wizard, mock_banner,
    ):
        """With real generate_config(), the pipeline must complete without
        raising an unhandled exception and exit with code 0.

        Uses the fully-parsed _RAW_BOARD_CFG fixture so the Jinja2 template
        has all required stepper/driver fields and does not emit TODO pins.
        """
        import tempfile
        import kace
        from core.scraper import parse_config

        # Build a complete board_parsed from the raw fixture string
        full_parsed = parse_config(_RAW_BOARD_CFG, 'generic-bigtreetech-skr-v1.4.cfg')

        user_data = {
            **_WIZARD_USER_DATA_WITH_PARSED,
            "board_parsed": full_parsed,
        }
        mock_wizard.return_value = user_data

        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, 'kace'), exist_ok=True)

            # Redirect expanduser so printer.cfg lands in tmpdir, not ~/kace/
            real_expanduser = os.path.expanduser
            def _redirect(p):
                expanded = real_expanduser(p)
                home = real_expanduser('~')
                if expanded.startswith(home):
                    return expanded.replace(home, tmpdir, 1)
                return expanded

            with patch('kace.yes_no', return_value=True), \
                 patch('kace.numbered_select', return_value='none'), \
                 patch('core.generator.os.path.expanduser', side_effect=_redirect), \
                 patch('kace.os.path.expanduser', side_effect=_redirect):
                with self.assertRaises(SystemExit) as ctx:
                    kace.main()

        self.assertEqual(ctx.exception.code, 0,
                         "Full pipeline with real generate_config must exit cleanly")



if __name__ == '__main__':
    unittest.main()
