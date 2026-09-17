"""Cross-stage regressions from the second audit. No hardware is used."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from core.managed_config import build_managed_config_plan, HARDWARE_REMOTE, ROOT_REMOTE
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from tests.unit.test_config_transaction import FakeTransport, GENERATED


class CalibrationTests(unittest.TestCase):
    def test_user_macro_text_is_not_mistaken_for_generated_calibration_guidance(self):
        from core.configuration_review import validate_configuration_plan
        plan = build_managed_config_plan(GENERATED, None, {
            ROOT_REMOTE: b"[gcode_macro OPTIONAL_PROBE]\ngcode: PROBE_CALIBRATE\n",
        })
        self.assertTrue(validate_configuration_plan(plan).valid)

    def test_saved_calibration_is_not_shadowed_and_plan_is_idempotent(self):
        generated = b"[probe]\npin: PA1\nz_offset: 0\n[extruder]\ncontrol: pid\npid_kp: 22.2\npid_ki: 1\npid_kd: 100\n"
        saved = (b"#*# <---------------------- SAVE_CONFIG ---------------------->\n"
                 b"#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.\n#*#\n"
                 b"#*# [probe]\n#*# z_offset = 2.375\n#*# [extruder]\n#*# control = pid\n#*# pid_kp = 31.5\n")
        plan = build_managed_config_plan(generated, None, {ROOT_REMOTE: saved})
        files = {a.remote_name: a.content for a in plan.artifacts}
        self.assertNotIn(b"z_offset:", files[HARDWARE_REMOTE])
        self.assertNotIn(b"pid_kp:", files[HARDWARE_REMOTE])
        self.assertNotIn(b"pid_kp:", files[ROOT_REMOTE])
        self.assertIn(b"pid_ki: 1", files[ROOT_REMOTE])
        self.assertTrue(files[ROOT_REMOTE].endswith(saved))
        self.assertEqual(build_managed_config_plan(generated, None, files).changed_artifacts, ())

    def test_real_klipper_reads_saved_calibration_and_can_save_again(self):
        source = Path(__file__).resolve().parents[2] / ".klipper-contract-source/klippy/configfile.py"
        if not source.is_file():
            self.skipTest("Pinned Klipper contract checkout is unavailable")
        spec = importlib.util.spec_from_file_location("klipper_config_audit", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        saved = (module.AUTOSAVE_HEADER + "#*# [probe]\n#*# z_offset = 2.375\n"
                 "#*# [extruder]\n#*# control = pid\n#*# pid_kp = 31.5\n").encode()
        generated = b"[probe]\npin: PA1\nz_offset: 0\n[extruder]\ncontrol: pid\npid_kp: 22.2\npid_ki: 1\npid_kd: 100\n"
        for prior in (saved, b""):
            with self.subTest(saved=bool(prior)), tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / ROOT_REMOTE
                plan = build_managed_config_plan(generated, None, {ROOT_REMOTE: prior})
                for artifact in plan.artifacts:
                    path = Path(temp) / artifact.remote_name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(artifact.content)
                printer = Mock()
                printer.get_start_args.return_value = {"config_file": str(root)}
                printer.command_error = RuntimeError
                autosave = module.ConfigAutoSave(printer)
                effective, _ = autosave.load_main_config()
                self.assertEqual(effective.getfloat("probe", "z_offset"), 2.375 if prior else 0)
                self.assertEqual(effective.getfloat("extruder", "pid_kp"), 31.5 if prior else 22.2)
                autosave.set("probe", "z_offset", "2.4")
                autosave.set("extruder", "pid_kp", "32")
                command = Mock()
                command.error = RuntimeError
                autosave.cmd_SAVE_CONFIG(command)
                effective, _ = autosave.load_main_config()
                self.assertEqual(effective.getfloat("probe", "z_offset"), 2.4)
                self.assertEqual(effective.getfloat("extruder", "pid_kp"), 32)
                files = {a.remote_name: (Path(temp) / a.remote_name).read_bytes() for a in plan.artifacts}
                replanned = build_managed_config_plan(generated, None, files)
                self.assertNotIn(b"z_offset:", next(a.content for a in replanned.artifacts if a.remote_name == HARDWARE_REMOTE))


class PublicationTests(unittest.TestCase):
    def run_deploy(self, transport):
        with tempfile.TemporaryDirectory() as temp:
            return ConfigDeploymentTransaction(transport, GENERATED, None, activation="firmware", snapshot_root=temp, poll_interval=0).run()

    def test_edit_between_uploads_is_preserved(self):
        transport = FakeTransport({ROOT_REMOTE: b"# original\n"})
        upload = transport.upload_bytes
        def edit_after_first(name, data):
            upload(name, data)
            transport.files[ROOT_REMOTE] = b"# external\n"
        transport.upload_bytes = edit_after_first
        result = self.run_deploy(transport)
        self.assertNotEqual(result.state, ConfigTransactionState.COMMITTED)
        self.assertEqual(transport.files[ROOT_REMOTE], b"# external\n")
        self.assertFalse(any(c == ("upload", ROOT_REMOTE) for c in transport.calls))

    def test_edit_during_activation_is_preserved_and_never_done(self):
        transport = FakeTransport({ROOT_REMOTE: b"# original\n"})
        transport.restart = lambda _mode: transport.files.update({HARDWARE_REMOTE: b"external"})
        result = self.run_deploy(transport)
        self.assertEqual(result.state, ConfigTransactionState.ROLLBACK_FAILED)
        self.assertEqual(transport.files[HARDWARE_REMOTE], b"external")
        self.assertIn("conflict", result.detail.lower())


class GeneratedMacroTests(unittest.TestCase):
    def test_stale_macros_are_not_loaded_without_current_include(self):
        from core.deployer import _generated_config_bytes
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "printer.cfg").write_bytes(GENERATED)
            (root / "macros.cfg").write_bytes(b"[gcode_macro OLD]\ngcode: G28\n")
            with patch("core.deployer.os.path.expanduser", side_effect=lambda p: str(root / Path(p).name)):
                self.assertIsNone(_generated_config_bytes()[2])
                (root / "printer.cfg").write_bytes(GENERATED + b"[include macros.cfg]\n")
                self.assertEqual(_generated_config_bytes()[2], (root / "macros.cfg").read_bytes())
                (root / "macros.cfg").unlink()
                with self.assertRaises(FileNotFoundError):
                    _generated_config_bytes()


class BridgeIdentityTests(unittest.TestCase):
    def test_bridge_name_needs_original_physical_identity_not_klipper_model_name(self):
        from core.mcu_monitor import McuIdentity
        from core.firmware_workflow import create_checkpoint, transition_checkpoint, verify_reappeared_mcu, CheckpointIncompatible, FirmwareWorkflowState as State
        from tests.unit.test_firmware_workflow import artifact
        from types import SimpleNamespace
        path = "/dev/serial/by-id/usb-Arduino_Mega_2560_ORIGINAL-if00"
        original = McuIdentity(path, "/dev/ttyACM0", physical_port="usb-1", vendor_id="2341", model_id="0042", serial="ORIGINAL")
        with tempfile.TemporaryDirectory() as temp:
            data = {"board": "generic-ramps.cfg", "mcu_type": "atmega2560", "mcu_path": path}
            checkpoint = create_checkpoint(data, identity_reader=SimpleNamespace(read=lambda _: original))
            checkpoint = transition_checkpoint(checkpoint, State.ARTIFACT_READY, artifact=artifact(Path(temp), model=data["mcu_type"]))
            checkpoint = transition_checkpoint(checkpoint, State.AWAITING_FLASH)
            with patch("core.firmware_workflow.os.path.exists", return_value=True):
                checked, observed = verify_reappeared_mcu(checkpoint, detector=lambda: {"mcu_path": path, "derived_mcu": None}, flash_evidence=True, identity_reader=SimpleNamespace(read=lambda _: original))
                self.assertEqual(checked["state"], State.MCU_VERIFIED.value)
                self.assertEqual(observed["derived_mcu"], "atmega2560")
                other = McuIdentity(path, "/dev/ttyACM0", physical_port="usb-2", vendor_id="2341", model_id="0042", serial="OTHER")
                with self.assertRaises(CheckpointIncompatible):
                    verify_reappeared_mcu(checkpoint, detector=lambda: {"mcu_path": path}, flash_evidence=True, identity_reader=SimpleNamespace(read=lambda _: other), ambiguity_resolver=lambda _: True)


class BuildConcurrencyTests(unittest.TestCase):
    def test_lto_retry_cannot_adopt_a_concurrent_configuration(self):
        import subprocess
        from firmware.builder import build_firmware_orchestrator, BuildContext
        from firmware.identity import FirmwareBuildInputs, ToolchainIdentity
        identity = lambda offset: FirmwareBuildInputs.create(
            klipper_commit="1" * 40, canonical_config=f'CONFIG_MCU="stm32"\nCONFIG_FLASH_START={offset}\n',
            toolchain=ToolchainIdentity("make", "make", "gcc", "gcc"), build_id="2" * 32,
        )
        with tempfile.TemporaryDirectory() as temp, \
             patch("firmware.builder.generate_firmware_config", return_value=(True, "")), \
             patch("firmware.builder.validate_config", return_value=(True, "")), \
             patch("firmware.builder.create_build_inputs", side_effect=[identity("0x8000"), identity("0x7000")]), \
             patch("firmware.builder._tmp_is_noexec", return_value=False), \
             patch("firmware.builder.subprocess.run", side_effect=[Mock(), Mock(), subprocess.CalledProcessError(1, "make", stderr="ltrans failed")]):
            (Path(temp) / "Makefile").write_text("$(PYTHON) ./scripts/buildcommands.py -d $(OUT)klipper.dict")
            result = build_firmware_orchestrator(klipper_path=temp, output_dir=str(Path(temp) / "out-copy"), config_dict={}, build_context=BuildContext(concurrency=1))
        self.assertEqual(result["status"], "error")
        self.assertIn("inputs changed before LTO retry", result["message"])

    def test_shared_workspace_is_locked_through_publication(self):
        from firmware.builder import build_firmware_orchestrator
        import threading
        first_entered, release_first, second_entered = (threading.Event() for _ in range(3))
        calls = []
        def build(*args):
            calls.append(args[0])
            if args[0] == "first":
                first_entered.set()
                self.assertTrue(release_first.wait(5))
            else:
                second_entered.set()
            return {"status": "success"}
        with tempfile.TemporaryDirectory() as temp, patch("firmware.builder._build_firmware_locked", side_effect=build):
            first = threading.Thread(target=build_firmware_orchestrator, kwargs={"mcu_path": "first", "klipper_path": temp})
            second = threading.Thread(target=build_firmware_orchestrator, kwargs={"mcu_path": "second", "klipper_path": temp})
            first.start()
            self.assertTrue(first_entered.wait(5))
            second.start()
            try:
                self.assertFalse(second_entered.wait(.15))
            finally:
                release_first.set()
                first.join(5)
                second.join(5)
            self.assertEqual(calls, ["first", "second"])

    def test_external_config_mutation_during_make_rejects_artifact(self):
        from firmware.builder import build_firmware_orchestrator, BuildContext
        from firmware.identity import FirmwareBuildInputs, ToolchainIdentity
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "Makefile").write_text("$(PYTHON) ./scripts/buildcommands.py -d $(OUT)klipper.dict")
            config = root / ".config"
            config.write_text('CONFIG_MCU="stm32"\nCONFIG_FLASH_START=0x8000\n')
            def inputs(**kwargs):
                return FirmwareBuildInputs.create(klipper_commit="1" * 40, canonical_config=config.read_text(), toolchain=ToolchainIdentity("make", "make", "gcc", "gcc"), build_id=kwargs.get("build_id") or "2" * 32)
            def make(command, **kwargs):
                if "clean" in command:
                    config.write_text('CONFIG_MCU="stm32"\nCONFIG_FLASH_START=0x7000\n')
                return Mock(stdout="", stderr="", returncode=0)
            with patch("firmware.builder.generate_firmware_config", return_value=(True, "")), patch("firmware.builder.validate_config", return_value=(True, "")), patch("firmware.builder.create_build_inputs", side_effect=inputs), patch("firmware.builder.subprocess.run", side_effect=make):
                result = build_firmware_orchestrator(klipper_path=temp, output_dir=str(root / "published"), config_dict={}, build_context=BuildContext(concurrency=1))
            self.assertEqual(result["status"], "error")
            self.assertIn("inputs changed", result["message"])
            self.assertFalse((root / "published").exists())


class PhysicalPublicationTests(unittest.TestCase):
    def test_concurrent_root_edit_between_physical_uploads_is_never_overwritten(self):
        from tests.unit.test_moonraker_deployer import InstallationWorkflowTests, Client
        from core.moonraker_deployer import DeployState
        fixture = InstallationWorkflowTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        client = Client({})
        upload = client.upload_config_if_unchanged
        def edit(content, name, previous):
            upload(content, name, previous)
            client.remote["printer.cfg"] = b"external"
        client.upload_config_if_unchanged = edit
        # Delegate ownership checks to the real rollback predicate.
        def restore(snapshot, *, expected_files):
            from core.snapshot import rollback_file_owned
            for name, written in expected_files.items():
                if rollback_file_owned(name, client.remote.get(name), snapshot.config_files.get(name), written):
                    if name in snapshot.config_files:
                        client.remote[name] = snapshot.config_files[name]
                    else:
                        client.remote.pop(name, None)
            return []
        client.restore_snapshot = restore
        result = fixture.make(client=client).run()
        self.assertNotEqual(result.state, DeployState.DONE)
        self.assertEqual(client.remote["printer.cfg"], b"external")
        self.assertNotIn(("upload", "printer.cfg"), client.calls)

    def test_post_activation_verification_also_covers_unchanged_plan_files(self):
        from tests.unit.test_moonraker_deployer import InstallationWorkflowTests, Client
        from core.moonraker_deployer import DeployState
        fixture = InstallationWorkflowTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        client = Client({})
        client.remote["untouched.cfg"] = b"reviewed"
        deployer = fixture.make(client=client)
        def verify():
            if client.remote["untouched.cfg"] != b"reviewed":
                raise RuntimeError("concurrent modification of untouched.cfg")
        deployer.verify_config_state = verify
        client.firmware_restart = lambda: client.remote.update({"untouched.cfg": b"external"})
        result = deployer.run()
        self.assertNotEqual(result.state, DeployState.DONE)
        self.assertIn("untouched.cfg", result.detail)
