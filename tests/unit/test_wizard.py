import unittest
from unittest.mock import patch, MagicMock
from core.wizard import run_wizard
from core.exceptions import WizardExit

class TestWizard(unittest.TestCase):

    @patch("questionary.select")
    @patch("core.wizard.discover_mcu")
    @patch("core.wizard.fetch_config_list")
    def test_wizard_exit_on_quit(self, mock_fetch, mock_mcu, mock_select):
        """Verify that choosing Quit raises WizardExit exception."""
        mock_mcu.return_value = {"mcu_path": "/dev/serial/by-id/mock", "derived_mcu": "stm32f103"}
        mock_fetch.return_value = ["printer-mock.cfg"]
        
        # Mock questionary select to return __quit__
        mock_ask = MagicMock(return_value="__quit__")
        mock_select.return_value.ask = mock_ask
        
        user_data = {
            "printer_profile": "Custom / Scratch Build",
            "board": "generic-bigtreetech-skr-v1.4.cfg",
            "kinematics": "cartesian",
            "x_size": "235",
            "y_size": "235",
            "z_size": "250",
            "probe": "None",
            "hotend_thermistor": "Generic 3950",
            "bed_thermistor": "Generic 3950",
            "driver_type": "None (Standard)",
            "driver_mode": "Standalone",
            "web_interface": "Mainsail",
            "z_motors": "1",
            "mcu_path": "/dev/serial/by-id/mock"
        }
        
        with self.assertRaises(WizardExit):
            run_wizard(user_data)

    @patch("questionary.select")
    @patch("questionary.text")
    def test_interactive_profile_review_edit_kinematics(self, mock_text, mock_select):
        """Verify interactive_profile_review can edit kinematics and updates correctly."""
        from core.wizard import interactive_profile_review
        
        defaults = {"kinematics": "cartesian"}
        parsed = {"printer": {"kinematics": "cartesian"}}
        user_data = {"kinematics": "cartesian"}
        
        # 1st select: choose 'edit'
        # 2nd select: choose 'kinematics'
        # 3rd select: choose 'corexy'
        # 4th select: choose 'save'
        # 5th select: choose 'confirm'
        mock_select.return_value.ask.side_effect = ["edit", "kinematics", "corexy", "save", "confirm"]
        
        result = interactive_profile_review(defaults, parsed, user_data)
        
        self.assertEqual(result, "confirm")
        self.assertEqual(user_data["kinematics"], "corexy")
        self.assertEqual(defaults["kinematics"], "corexy")
        self.assertEqual(parsed["printer"]["kinematics"], "corexy")

    @patch("questionary.select")
    @patch("questionary.text")
    def test_interactive_profile_review_edit_volume(self, mock_text, mock_select):
        """Verify interactive_profile_review can edit build volume and validates inputs."""
        from core.wizard import interactive_profile_review
        
        defaults = {"x_size": "235", "y_size": "235", "z_size": "250"}
        parsed = {}
        user_data = {"x_size": "235", "y_size": "235", "z_size": "250"}
        
        # Select edit -> volume -> save -> confirm
        mock_select.return_value.ask.side_effect = ["edit", "volume", "save", "confirm"]
        
        # Enter valid dimensions: 300, 300, 350
        mock_text.return_value.ask.side_effect = ["300", "300", "350"]
        
        result = interactive_profile_review(defaults, parsed, user_data)
        
        self.assertEqual(result, "confirm")
        self.assertEqual(user_data["x_size"], "300")
        self.assertEqual(user_data["y_size"], "300")
        self.assertEqual(user_data["z_size"], "350")
        self.assertEqual(parsed["stepper_x"]["position_max"], "300")
        self.assertEqual(parsed["stepper_y"]["position_max"], "300")
        self.assertEqual(parsed["stepper_z"]["position_max"], "350")

    @patch("questionary.select")
    @patch("questionary.text")
    def test_interactive_profile_review_edit_individual_limits(self, mock_text, mock_select):
        """Verify interactive_profile_review can edit individual limits and handles sync correctly."""
        from core.wizard import interactive_profile_review
        
        defaults = {
            "x_position_min": "0", "x_position_max": "235", "x_position_endstop": "0",
            "y_position_min": "0", "y_position_max": "235", "y_position_endstop": "0",
            "x_size": "235", "y_size": "235"
        }
        parsed = {}
        user_data = {
            "x_position_min": "0", "x_position_max": "235", "x_position_endstop": "0",
            "y_position_min": "0", "y_position_max": "235", "y_position_endstop": "0",
            "x_size": "235", "y_size": "235"
        }
        
        # We will do two separate edits inside the loop:
        # First iteration: choose 'edit' -> 'x_position_min' -> type '-10' -> loop back
        # Second iteration: choose 'y_position_max' -> type '320' -> loop back
        # Third iteration: choose 'save' -> 'confirm'
        mock_select.return_value.ask.side_effect = [
            "edit", "x_position_min",
            "y_position_max",
            "save", "confirm"
        ]
        
        mock_text.return_value.ask.side_effect = ["-10", "320"]
        
        result = interactive_profile_review(defaults, parsed, user_data)
        
        self.assertEqual(result, "confirm")
        # Check X min edit
        self.assertEqual(user_data["x_position_min"], "-10")
        self.assertEqual(defaults["x_position_min"], "-10")
        self.assertEqual(parsed["stepper_x"]["position_min"], "-10")
        
        # Check Y max edit and synchronization to y_size
        self.assertEqual(user_data["y_position_max"], "320")
        self.assertEqual(defaults["y_position_max"], "320")
        self.assertEqual(parsed["stepper_y"]["position_max"], "320")
        self.assertEqual(user_data["y_size"], "320")
        self.assertEqual(defaults["y_size"], "320")



class TestWizardRunner(unittest.TestCase):

    def test_runner_basic_flow_and_back_pruning(self):
        """Verify that WizardRunner handles forward steps and prunes state on back navigation."""
        from core.wizard import WizardRunner
        
        step_order = ["stepA", "stepB", "stepC"]
        steps_config = {
            "stepA": {
                "prompt": lambda ud: ud.update({"keyA": "valueA"}) or "valueA"
            },
            "stepB": {
                "prompt": lambda ud: ud.update({"keyB": "valueB"}) or "valueB",
                "next": lambda ans, ud: "stepC"
            },
            "stepC": {
                "prompt": lambda ud: "__back__" if ud.get("trigger_back") else "valueC"
            }
        }
        
        # Test 1: Straight forward execution
        user_data = {"trigger_back": False}
        runner = WizardRunner(steps_config, step_order, initial_data=user_data)
        res = runner.run("stepA")
        
        self.assertEqual(res["keyA"], "valueA")
        self.assertEqual(res["keyB"], "valueB")
        self.assertEqual(runner.history_stack, ["stepA", "stepB", "stepC"])
        
        # Test 2: Trigger back from stepC -> should prune stepB's keyB and stepC's inputs
        user_data = {"trigger_back": True}
        # Step C will return __back__, so runner will undo Step C, pop Step B from history stack, and undo Step B.
        # Then, since we went back to Step B, the runner will execute Step B again.
        # On this second execution of Step B, we will change trigger_back to False so it advances and stops.
        call_count = 0
        def step_b_prompt(ud):
            nonlocal call_count
            call_count += 1
            ud["keyB"] = f"valueB_run{call_count}"
            if call_count == 2:
                ud["trigger_back"] = False
            return "valueB"
            
        steps_config["stepB"]["prompt"] = step_b_prompt
        
        runner = WizardRunner(steps_config, step_order, initial_data=user_data)
        res = runner.run("stepA")
        
        # We expect stepB to be run twice, stepC run twice (first returned back, second succeeded)
        self.assertEqual(call_count, 2)
        self.assertEqual(res["keyA"], "valueA")
        self.assertEqual(res["keyB"], "valueB_run2")
        self.assertEqual(runner.history_stack, ["stepA", "stepB", "stepC"])

    def test_runner_snapshot_rollback(self):
        """Verify that rollback_to restores the user_data snapshot and trims history."""
        from core.wizard import WizardRunner
        
        step_order = ["stepA", "stepB", "stepC"]
        steps_config = {
            "stepA": {
                "prompt": lambda ud: ud.update({"keyA": "valueA"}) or "valueA"
            },
            "stepB": {
                "prompt": lambda ud: ud.update({"keyB": "valueB"}) or "valueB"
            },
            "stepC": {
                "prompt": lambda ud: ud.update({"keyC": "valueC"}) or "valueC"
            }
        }
        
        runner = WizardRunner(steps_config, step_order, initial_data={"initial": "state"})
        runner.run("stepA")
        
        # Verify initial execution state
        self.assertEqual(runner.user_data["keyA"], "valueA")
        self.assertEqual(runner.user_data["keyB"], "valueB")
        self.assertEqual(runner.user_data["keyC"], "valueC")
        self.assertEqual(runner.user_data["initial"], "state")
        
        # Rollback to stepB -> should revert changes made by stepB and stepC
        runner.rollback_to("stepB")
        
        self.assertEqual(runner.user_data["keyA"], "valueA")
        self.assertNotIn("keyB", runner.user_data)
        self.assertNotIn("keyC", runner.user_data)
        self.assertEqual(runner.user_data["initial"], "state")
        self.assertEqual(runner.history_stack, ["stepA"])
        self.assertNotIn("stepB", runner.snapshots)
        self.assertNotIn("stepC", runner.snapshots)

    def test_runner_retry_rollback(self):
        """Verify that returning __retry__ restores step snapshots without advancing."""
        from core.wizard import WizardRunner
        
        step_order = ["stepA"]
        
        call_count = 0
        def step_a_prompt(ud):
            nonlocal call_count
            call_count += 1
            ud["keyA"] = f"try_{call_count}"
            if call_count == 1:
                return "__retry__"
            return "valueA"
            
        steps_config = {
            "stepA": {
                "prompt": step_a_prompt
            }
        }
        
        runner = WizardRunner(steps_config, step_order, initial_data={"initial": "state"})
        res = runner.run("stepA")
        
        # In the first run, keyA was set to "try_1" and __retry__ was returned.
        # So rollback reverted keyA. Then the second run completed successfully.
        self.assertEqual(res["keyA"], "try_2")
        self.assertEqual(res["initial"], "state")
        self.assertEqual(runner.history_stack, ["stepA"])
        self.assertEqual(call_count, 2)

    def test_runner_no_orphaned_snapshots_consecutive_back(self):
        """Verify that multiple consecutive back operations do not leave orphaned snapshots."""
        from core.wizard import WizardRunner
        
        step_order = ["stepA", "stepB", "stepC", "stepD"]
        steps_config = {
            "stepA": {"prompt": lambda ud: "valA"},
            "stepB": {"prompt": lambda ud: "valB"},
            "stepC": {"prompt": lambda ud: "valC"},
            "stepD": {"prompt": lambda ud: "__back__"}
        }
        
        runner = WizardRunner(steps_config, step_order, initial_data={"initial": "state"})
        # Run manually/simulate steps to test snapshots and rollback
        runner.user_data = {"initial": "state", "step": "D"}
        runner.history_stack = ["stepA", "stepB", "stepC"]
        runner.snapshots = {
            "stepA": {"initial": "state"},
            "stepB": {"initial": "state", "keyA": "valA"},
            "stepC": {"initial": "state", "keyA": "valA", "keyB": "valB"},
            "stepD": {"initial": "state", "keyA": "valA", "keyB": "valB", "keyC": "valC"}
        }
        
        # Rollback to stepC
        runner.rollback_to("stepC")
        # stepC and stepD snapshots should be cleaned up. Only A and B remain.
        self.assertEqual(list(runner.snapshots.keys()), ["stepA", "stepB"])
        self.assertEqual(runner.history_stack, ["stepA", "stepB"])

    def test_runner_branch_switching_cleanup(self):
        """Verify that branch switching correctly resets values and cleans up abandoned step snapshots."""
        from core.wizard import WizardRunner
        
        # Branching layout:
        # A -> B -> C (if B returns C_val)
        #   -> D (if B returns D_val)
        step_order = ["stepA", "stepB", "stepC", "stepD"]
        steps_config = {
            "stepA": {"prompt": lambda ud: "valA"},
            "stepB": {
                "prompt": lambda ud: ud.update({"branch_key": "C"}) or "C",
                "next": lambda ans, ud: "stepC" if ans == "C" else "stepD"
            },
            "stepC": {
                "prompt": lambda ud: ud.update({"c_only_key": "valC"}) or "valC",
                "next": lambda ans, ud: None
            },
            "stepD": {
                "prompt": lambda ud: ud.update({"d_only_key": "valD"}) or "valD",
                "next": lambda ans, ud: None
            }
        }
        
        runner = WizardRunner(steps_config, step_order, initial_data={})
        
        # 1. Run branch A -> B -> C
        runner.run("stepA")
        self.assertEqual(runner.user_data.get("c_only_key"), "valC")
        self.assertEqual(runner.history_stack, ["stepA", "stepB", "stepC"])
        self.assertIn("stepC", runner.snapshots)
        
        # 2. Rollback to stepB and change the branch to D
        # Simulate user going back to stepB
        runner.rollback_to("stepB")
        # B and C snapshots should be popped, history stack becomes ["stepA"]
        self.assertEqual(list(runner.snapshots.keys()), ["stepA"])
        self.assertEqual(runner.history_stack, ["stepA"])
        self.assertNotIn("c_only_key", runner.user_data)
        
        # Now prompt for stepB returns D
        steps_config["stepB"]["prompt"] = lambda ud: ud.update({"branch_key": "D"}) or "D"
        # Resume run
        res = runner.run("stepB")
        self.assertEqual(res.get("d_only_key"), "valD")
        self.assertNotIn("c_only_key", res)  # Verify no stale value leaked from branch C
        self.assertEqual(runner.history_stack, ["stepA", "stepB", "stepD"])
        self.assertNotIn("stepC", runner.snapshots)  # Verify branch C snapshot is cleaned up


class TestZSocketAssignment(unittest.TestCase):

    @patch("questionary.select")
    @patch("core.wizard.fetch_raw_config")
    def test_z_socket_assignment_and_tmc_post_processing(self, mock_fetch, mock_select):
        from core.wizard import _step_z_socket_assignment, _apply_z_tmc_mappings
        mock_fetch.return_value = "[extruder1]\nstep_pin: PE1\ndir_pin: PE2\nenable_pin: PE3\n[tmc2209 extruder1]\nuart_pin: PD12\n"
        
        # User selects E1 (extruder1) for stepper_z1
        mock_select.return_value.ask.return_value = "extruder1"
        
        board_parsed = {
            "extruder1": {
                "step_pin": "PE1",
                "dir_pin": "PE2",
                "enable_pin": "PE3"
            },
            "tmc2209 extruder1": {
                "uart_pin": "PD12"
            }
        }
        
        user_data = {
            "z_motors": "2",
            "board": "generic-mock.cfg",
            "board_raw_config": mock_fetch.return_value,
            "board_parsed": board_parsed,
            "driver_type": None,  # driver_type is not selected yet!
            "driver_mode": None
        }
        
        # 1. Run step
        res = _step_z_socket_assignment(user_data)
        self.assertEqual(res, "done")
        self.assertEqual(user_data["z_socket_assignments"], {"stepper_z1": "extruder1"})
        self.assertIn("stepper_z1", board_parsed)
        self.assertEqual(board_parsed["stepper_z1"]["step_pin"], "PE1")
        # Ensure the TMC section was not copied yet because driver_type is None
        self.assertNotIn("tmc2209 stepper_z1", board_parsed)
        
        # 2. Later in wizard, user selects TMC2209 UART
        user_data["driver_type"] = "TMC2209"
        user_data["driver_mode"] = "UART"
        
        # 3. Post-processing maps Z stepper TMC configuration
        _apply_z_tmc_mappings(user_data)
        self.assertIn("tmc2209 stepper_z1", board_parsed)
        self.assertEqual(board_parsed["tmc2209 stepper_z1"]["uart_pin"], "PD12")
        # Ensure the original extruder1 TMC section is gone
        self.assertNotIn("tmc2209 extruder1", board_parsed)


class TestWizardTransitions(unittest.TestCase):

    def test_run_wizard_transition_lambdas(self):
        from core.wizard import run_wizard, WizardRunner
        
        captured_config = {}
        original_init = WizardRunner.__init__
        
        def mock_init(self_runner, steps_config, step_order, initial_data=None):
            captured_config.update(steps_config)
            original_init(self_runner, steps_config, step_order, initial_data)
            
        with patch("core.wizard.WizardRunner.__init__", mock_init), \
             patch("core.wizard.discover_mcu", return_value={}), \
             patch("core.wizard.fetch_config_list", return_value=[]), \
             patch("core.wizard.WizardRunner.run", return_value={}):
            run_wizard()
            
        # Assert transition lambdas are configured properly and don't return None
        self.assertIn("z_socket_assignment", captured_config)
        self.assertIn("driver_type", captured_config)
        self.assertIn("printer_profile", captured_config)
        
        # 1. z_socket_assignment transitions
        next_fn = captured_config["z_socket_assignment"]["next"]
        self.assertEqual(next_fn("__skip__", {}), "driver_type")
        self.assertEqual(next_fn("done", {}), "driver_type")
        
        # 2. driver_type transitions
        next_fn = captured_config["driver_type"]["next"]
        self.assertEqual(next_fn("TMC2209", {}), "driver_mode")
        self.assertEqual(next_fn("TMC2208", {}), "driver_mode")
        self.assertEqual(next_fn("None (Standard)", {}), "printer_profile")
        self.assertEqual(next_fn("A4988", {}), "printer_profile")
        self.assertEqual(next_fn("DRV8825", {}), "printer_profile")
        
        # 3. printer_profile transitions
        next_fn = captured_config["printer_profile"]["next"]
        self.assertEqual(next_fn("some-profile", {"profile_loaded": True}), "profile_review")
        self.assertEqual(next_fn("some-profile", {"profile_loaded": False}), "kinematics")

        # 4. board transitions (with fan_assignment)
        next_fn = captured_config["board"]["next"]
        # If board has fan options, next is fan_assignment
        self.assertEqual(next_fn("generic-skr.cfg", {"board_raw_config": "[fan]\npin: PA8"}), "fan_assignment")
        # Otherwise, next is z_motors
        self.assertEqual(next_fn("generic-skr.cfg", {"board_raw_config": ""}), "z_motors")


class TestWizardFanAssignment(unittest.TestCase):
    def test_has_fan_options(self):
        from core.wizard import _has_fan_options
        # No raw config -> False
        self.assertFalse(_has_fan_options({}))
        
        # Raw config without fan -> False
        self.assertFalse(_has_fan_options({"board_raw_config": "[stepper_x]\npin: P2.0"}))
        
        # Raw config with fan -> True
        self.assertTrue(_has_fan_options({"board_raw_config": "[fan]\npin: PA8"}))

    @patch("questionary.select")
    def test_step_fan_assignment_default_and_none(self, mock_select):
        from core.wizard import _step_fan_assignment
        
        # Board with only default [fan]
        raw_cfg = "[fan]\npin: PA8\n"
        user_data = {"board_raw_config": raw_cfg}
        
        # Select "default" for part cooling, and "none" for hotend
        mock_select.return_value.ask.side_effect = ["default", "none"]
        
        res = _step_fan_assignment(user_data)
        self.assertEqual(res, "success")
        self.assertEqual(user_data["fan_part_cooling_pin"], "default")
        self.assertEqual(user_data["fan_hotend_pin"], "none")

    @patch("questionary.text")
    @patch("questionary.select")
    def test_step_fan_assignment_custom(self, mock_select, mock_text):
        from core.wizard import _step_fan_assignment
        
        # Board with fan and heater fan
        raw_cfg = "[fan]\npin: PA8\n#[heater_fan fan1]\n#pin: PE5\n"
        user_data = {"board_raw_config": raw_cfg}
        
        # Select "custom" for part cooling, then enter "PB6". Then select "PE5" for hotend.
        mock_select.return_value.ask.side_effect = ["custom", "PE5"]
        mock_text.return_value.ask.side_effect = ["PB6"]
        
        res = _step_fan_assignment(user_data)
        self.assertEqual(res, "success")
        self.assertEqual(user_data["fan_part_cooling_pin"], "PB6")
        self.assertEqual(user_data["fan_hotend_pin"], "PE5")


class TestWizardProfileMerging(unittest.TestCase):
    def test_run_wizard_merges_profile_pins(self):
        from core.wizard import run_wizard
        # We mock WizardRunner.run to return our mocked user_data
        mock_user_data = {
            "board_parsed": {
                "heater_bed": {
                    "heater_pin": "PD2",
                    "sensor_pin": "PA6"
                },
                "stepper_x": {
                    "step_pin": "PD7",
                    "dir_pin": "PC5"
                }
            },
            "_profile_parsed": {
                "heater_bed": {
                    "heater_pin": "PD4",
                    "sensor_type": "Generic 3950"
                },
                "stepper_x": {
                    "dir_pin": "!PC5"
                }
            }
        }
        with patch("core.wizard.WizardRunner.run", return_value=mock_user_data), \
             patch("core.wizard.discover_mcu", return_value={}), \
             patch("core.wizard._apply_z_tmc_mappings"):
            res = run_wizard()
            
        board_parsed = res.get("board_parsed", {})
        self.assertEqual(board_parsed["heater_bed"]["heater_pin"], "PD4")
        self.assertEqual(board_parsed["heater_bed"]["sensor_pin"], "PA6")
        self.assertEqual(board_parsed["heater_bed"]["sensor_type"], "Generic 3950")
        self.assertEqual(board_parsed["stepper_x"]["dir_pin"], "!PC5")
        self.assertEqual(board_parsed["stepper_x"]["step_pin"], "PD7")


class TestWizardUIOrientation(unittest.TestCase):
    @patch("sys.stdout", new_callable=lambda: __import__("io").StringIO())
    def test_print_step_header_auto_silence(self, mock_stdout):
        import os
        from core.wizard import _print_step_header
        with patch.dict(os.environ, {"KACE_AUTO": "1"}):
            _print_step_header("board", {})
            self.assertEqual(mock_stdout.getvalue(), "")

    @patch("sys.stdout", new_callable=lambda: __import__("io").StringIO())
    def test_print_step_header_quiet_silence(self, mock_stdout):
        import os
        from core.wizard import _print_step_header
        with patch.dict(os.environ, {"KACE_QUIET": "1"}):
            _print_step_header("board", {})
            self.assertEqual(mock_stdout.getvalue(), "")

    @patch("sys.stdout", new_callable=lambda: __import__("io").StringIO())
    def test_phase_transition_banner_fires_exactly_once(self, mock_stdout):
        import os
        from core.wizard import WizardRunner
        
        # We set up a simple wizard with 3 steps spanning 2 phases
        # Phase order: Hardware -> Motion -> Sensors -> Software
        steps_config = {
            "stepA": {
                "prompt": lambda ud: "ansA",
                "next": lambda ans, ud: "stepB"
            },
            "stepB": {
                "prompt": lambda ud: "ansB",
                "next": lambda ans, ud: "stepC"
            },
            "stepC": {
                "prompt": lambda ud: "__back__" if ud.get("go_back") else "ansC"
            }
        }
        step_order = ["stepA", "stepB", "stepC"]
        
        # Override PHASE_MAP inside the test module context
        from core.wizard import PHASE_MAP
        original_phase_map = PHASE_MAP.copy()
        PHASE_MAP["stepA"] = "Hardware"
        PHASE_MAP["stepB"] = "Motion"
        PHASE_MAP["stepC"] = "Motion"
        
        try:
            # First, test forward transition A -> B. Transition banner should print.
            # Then B -> C, within same phase, transition banner should NOT print.
            runner = WizardRunner(steps_config, step_order, initial_data={})
            
            # Step A prompt returns ansA -> moves to step B
            # Step B prompt returns ansB -> moves to step C
            # Step C prompt returns ansC -> finishes
            runner.run("stepA")
            
            output = mock_stdout.getvalue()
            # Phase transitions from Hardware to Motion. It should print phase complete banner once for Hardware.
            self.assertIn("✔ Phase complete: Hardware", output)
            self.assertNotIn("✔ Phase complete: Motion", output) # Since Motion is not completed (Software is not entered)
            
            # Clear output buffer
            mock_stdout.seek(0)
            mock_stdout.truncate(0)
            
            # Now test back navigation.
            # A -> B -> C -> Back to B -> C again.
            # We want to ensure no banner is printed when navigating backward (C -> B).
            # And when moving forward from B -> C again, it does not reprint the transition banner since they are within same phase.
            user_data = {"go_back": True}
            
            # We mock steps_config to first trigger a back navigation on step C,
            # then on the second visit to step C, return ansC to finish.
            call_count = 0
            def prompt_step_c(ud):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return "__back__"
                return "ansC"
                
            steps_config["stepC"]["prompt"] = prompt_step_c
            
            runner = WizardRunner(steps_config, step_order, initial_data=user_data)
            runner.run("stepA")
            
            output2 = mock_stdout.getvalue()
            # It should print transition banner for Hardware complete exactly once when moving from stepA to stepB.
            self.assertEqual(output2.count("Phase complete: Hardware"), 1)
            
        finally:
            # Restore original phase map
            PHASE_MAP.clear()
            PHASE_MAP.update(original_phase_map)


class TestBLTouchWizardPrompt(unittest.TestCase):

    def test_needs_bltouch_pins(self):
        from core.wizard import _needs_bltouch_pins
        
        # Scenario 1: missing completely
        user_data = {"board": "generic-melzi.cfg"}
        # get_current_board_parsed returns empty dict or parses it
        # Melzi has unknown bltouch pins in boards.yaml
        self.assertTrue(_needs_bltouch_pins(user_data))
        
        # Scenario 2: pins present in board config
        with patch("core.wizard.get_current_board_parsed") as mock_parsed:
            mock_parsed.return_value = {"bltouch": {"sensor_pin": "^PB7", "control_pin": "PB6"}}
            self.assertFalse(_needs_bltouch_pins(user_data))

            # Scenario 3: pins are TODO placeholders
            mock_parsed.return_value = {"bltouch": {"sensor_pin": "^TODO", "control_pin": "TODO"}}
            self.assertTrue(_needs_bltouch_pins(user_data))

    @patch("questionary.select")
    def test_probe_transitions(self, mock_select):
        from core.wizard import run_wizard, WizardRunner
        
        captured_config = {}
        original_init = WizardRunner.__init__
        
        def mock_init(self_runner, steps_config, step_order, initial_data=None):
            captured_config.update(steps_config)
            original_init(self_runner, steps_config, step_order, initial_data)
            
        with patch("core.wizard.WizardRunner.__init__", mock_init), \
             patch("core.wizard.discover_mcu", return_value={}), \
             patch("core.wizard.fetch_config_list", return_value=[]), \
             patch("core.wizard.WizardRunner.run", return_value={}):
            run_wizard()
            
        self.assertIn("probe", captured_config)
        self.assertIn("bltouch_pins", captured_config)
        
        probe_next = captured_config["probe"]["next"]
        
        # 1. Probe None -> hotend_therm
        self.assertEqual(probe_next("None", {}), "hotend_therm")
        
        # 2. Probe Inductive -> probe_offsets
        self.assertEqual(probe_next("Inductive", {}), "probe_offsets")
        
        # 3. Probe BLTouch with missing pins -> bltouch_pins
        with patch("core.wizard._needs_bltouch_pins", return_value=True):
            self.assertEqual(probe_next("BLTouch", {}), "bltouch_pins")
            
        # 4. Probe BLTouch with mapped pins -> probe_offsets
        with patch("core.wizard._needs_bltouch_pins", return_value=False):
            self.assertEqual(probe_next("BLTouch", {}), "probe_offsets")

    @patch("questionary.text")
    def test_step_bltouch_pins_prompt_success(self, mock_text):
        from core.wizard import _step_bltouch_pins
        
        # Mocking prompt for sensor and control pin
        mock_text.return_value.ask.side_effect = ["^PB7", "PB6"]
        
        user_data = {"board": "generic-melzi.cfg"}
        with patch("core.wizard.get_current_board_parsed", return_value={}):
            res = _step_bltouch_pins(user_data)
            
        self.assertEqual(res, "done")
        self.assertEqual(user_data["bltouch_sensor_pin"], "^PB7")
        self.assertEqual(user_data["bltouch_control_pin"], "PB6")

    @patch("questionary.text")
    def test_step_bltouch_pins_prompt_back(self, mock_text):
        from core.wizard import _step_bltouch_pins, _BACK
        
        # User presses Esc on first prompt -> returns None
        mock_text.return_value.ask.return_value = None
        
        user_data = {"board": "generic-melzi.cfg"}
        with patch("core.wizard.get_current_board_parsed", return_value={}):
            res = _step_bltouch_pins(user_data)
            
        self.assertEqual(res, _BACK)


class TestAxisLimitsWizard(unittest.TestCase):

    @patch("questionary.text")
    def test_step_x_limits_success(self, mock_text):
        from core.wizard import _step_x_limits
        
        # min, max, endstop
        mock_text.return_value.ask.side_effect = ["-5.5", "240.2", "0"]
        user_data = {}
        
        res = _step_x_limits(user_data)
        self.assertEqual(res, "done")
        self.assertEqual(user_data["x_position_min"], "-5.5")
        self.assertEqual(user_data["x_position_max"], "240.2")
        self.assertEqual(user_data["x_size"], "240.2")
        self.assertEqual(user_data["x_position_endstop"], "0")

    @patch("questionary.text")
    def test_step_y_limits_back_navigation(self, mock_text):
        from core.wizard import _step_y_limits, _BACK
        
        # User enters min, then at max types '<' to go back, enters min again, enters max, enters endstop
        mock_text.return_value.ask.side_effect = ["-10", "<", "-5", "250", "0"]
        user_data = {}
        
        res = _step_y_limits(user_data)
        self.assertEqual(res, "done")
        self.assertEqual(user_data["y_position_min"], "-5")
        self.assertEqual(user_data["y_position_max"], "250")
        self.assertEqual(user_data["y_position_endstop"], "0")

    @patch("questionary.text")
    def test_step_z_limits_back_out(self, mock_text):
        from core.wizard import _step_z_limits, _BACK
        
        # User enters '<' at the very first prompt to back out to previous step
        mock_text.return_value.ask.return_value = "<"
        user_data = {}
        
        res = _step_z_limits(user_data)
        self.assertEqual(res, _BACK)


if __name__ == '__main__':
    unittest.main()
