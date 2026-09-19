"""Regressions for configuration preservation and durable deployment state."""
import unittest
from dataclasses import replace
from pathlib import Path
import tempfile
import json
import subprocess
import sys
from core.firmware_workflow import (
    create_checkpoint, transition_checkpoint, write_checkpoint, load_checkpoint,
    FirmwareWorkflowState as State, FirmwareWorkflowError,
    checkpoint_revision,
)
from tests.unit.test_firmware_workflow import base_user_data
from tests.unit import test_moonraker_deployer as physical_tests
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.snapshot import create_snapshot, verify_snapshot_restored
from unittest.mock import Mock

from core.managed_config import build_managed_config_plan, HARDWARE_REMOTE, ROOT_REMOTE, MACROS_REMOTE
from core.configuration_review import build_configuration_review, render_configuration_review


class ManagedSettingWarningsTests(unittest.TestCase):
    def test_replaced_settings_are_visible_and_calibrated_values_are_preserved(self):
        generated = b"[extruder]\nrotation_distance: 22\nmax_temp: 250\n[probe]\nz_offset: 0\n"
        root = b"[extruder]\nrotation_distance: 23.7\nmax_temp: 260\nmax_extrude_only_distance: 120\n[probe]\nz_offset: 1.8\n"
        plan = build_managed_config_plan(generated, None, {ROOT_REMOTE: root})
        rendered = render_configuration_review(build_configuration_review(plan), color=False)
        self.assertTrue(any("max_temp" in warning for warning in plan.warnings))
        self.assertIn("max_temp", rendered)
        self.assertIn("260", rendered)
        self.assertIn("250", rendered)
        for setting in ("rotation_distance", "max_extrude_only_distance", "z_offset"):
            self.assertFalse(any(setting in warning for warning in plan.warnings))
        combined = b"\n".join(a.content for a in plan.artifacts)
        self.assertIn(b"rotation_distance: 23.7", combined)
        self.assertIn(b"max_extrude_only_distance: 120", combined)
        self.assertIn(b"z_offset: 1.8", combined)

    def test_removed_managed_section_and_changed_macro_body_are_reported(self):
        plan = build_managed_config_plan(b"[mcu]\nserial: same\n", b"[gcode_macro START]\ngcode:\n  G28\n", {
            HARDWARE_REMOTE: b"[input_shaper]\nshaper_freq_x: 42\n",
            MACROS_REMOTE: b"[gcode_macro START]\ngcode:\n  M117 customized\n",
        })
        self.assertTrue(any("shaper_freq_x" in w and HARDWARE_REMOTE in w for w in plan.warnings))
        self.assertTrue(any("gcode" in w and "M117 customized" in w for w in plan.warnings))

    def test_retained_tuning_user_sections_and_idempotent_plan_do_not_warn_of_loss(self):
        generated = b"[printer]\nmax_velocity: 300\n"
        root = b"[printer]\nmax_velocity: 100\n[gcode_macro USER]\ngcode: M117 user\n"
        first = build_managed_config_plan(generated, None, {ROOT_REMOTE: root})
        self.assertFalse(first.warnings)
        files = {a.remote_name: a.content for a in first.artifacts}
        repeated = build_managed_config_plan(generated, None, files)
        self.assertFalse(repeated.warnings)
        self.assertFalse(repeated.changed_artifacts)


class PhysicalRollbackBytesTests(unittest.TestCase):
    def test_edit_during_recovery_restart_is_not_reported_as_success(self):
        fixture = physical_tests.InstallationWorkflowTests()
        fixture.setUp()
        try:
            client = physical_tests.Client({})
            client.firmware_restart = lambda: client.remote.update({'printer.cfg': b'external after restart'})
            deployer = fixture.make(client=client)
            deployer._attempted_config_writes = {'printer.cfg': b'new'}
            ok, detail = deployer._rollback()
            self.assertFalse(ok)
            self.assertIn('after restart', detail)
            self.assertEqual(client.remote['printer.cfg'], b'external after restart')
        finally:
            fixture.tearDown()

    def test_successful_upload_response_does_not_prove_restored_bytes(self):
        for mode in ('corrupt', 'missing', 'new_file_survives', 'unreadable'):
            with self.subTest(mode=mode):
                fixture = physical_tests.InstallationWorkflowTests()
                fixture.setUp()
                try:
                    client = physical_tests.Client({})
                    fixture.snapshot = replace(fixture.snapshot, missing_files=('macros.cfg',))

                    def fake_restore(snapshot, **_kwargs):
                        client.remote = dict(snapshot.config_files)
                        if mode == 'corrupt':
                            client.remote['printer.cfg'] = b'corrupt but parseable'
                        elif mode == 'missing':
                            client.remote.pop('printer.cfg')
                        elif mode == 'new_file_survives':
                            client.remote['macros.cfg'] = b'undeleted'
                        return []

                    client.restore_snapshot = fake_restore
                    client.read_config_files = Mock(side_effect=ConnectionError('read unavailable')) if mode == 'unreadable' else lambda ns: {n: client.remote.get(n) for n in ns}
                    deployer = fixture.make(client=client)
                    deployer._attempted_config_writes = {'printer.cfg': b'new', 'macros.cfg': b'new macro'}
                    ok, detail = deployer._rollback()
                    self.assertFalse(ok, mode)
                    self.assertIn('rollback', detail)
                    self.assertNotIn('restart', client.calls)
                finally:
                    fixture.tearDown()


class SharedRollbackGuaranteeTests(unittest.TestCase):
    def test_missing_read_evidence_is_not_confirmed_file_absence(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = create_snapshot({'new.cfg': None}, persist_root=directory)
            with self.assertRaisesRegex(RuntimeError, 'no current-state evidence'):
                verify_snapshot_restored(snapshot, {}, ('new.cfg',))
            verify_snapshot_restored(snapshot, {'new.cfg': None}, ('new.cfg',))

    def test_configuration_route_does_not_restart_when_manual_recovery_is_required(self):
        for changed_name in ('printer.cfg', 'kace/generated-hardware.cfg'):
            with self.subTest(name=changed_name), tempfile.TemporaryDirectory() as directory:
                transport = FakeTransport({'printer.cfg': b'# original\n'})

                def restart(mode):
                    transport.calls.append(('restart', mode))
                    if transport.calls.count(('restart', mode)) == 1:
                        raise RuntimeError('activation failed')
                    transport.files[changed_name] = b'external edit during recovery'

                transport.restart = restart
                result = ConfigDeploymentTransaction(
                    transport, GENERATED, None, activation='firmware',
                    snapshot_root=directory, poll_interval=0, output=lambda _: None,
                ).run()
                self.assertEqual(result.state, ConfigTransactionState.ROLLBACK_FAILED)
                self.assertFalse(result.rollback_succeeded)
                self.assertIn('manual recovery', result.detail)
                self.assertEqual(transport.calls.count(('restart', 'firmware')), 1)
                self.assertEqual(result.snapshot.config_files['printer.cfg'], b'# original\n')


class CheckpointWriterTests(unittest.TestCase):
    def test_two_processes_cannot_commit_from_the_same_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'checkpoint.json')
            write_checkpoint(create_checkpoint(base_user_data()), path)
            script = '''
import sys
from core.firmware_workflow import *
checkpoint = load_checkpoint(sys.argv[1])
print('ready', flush=True)
sys.stdin.readline()
checkpoint = transition_checkpoint(checkpoint, FirmwareWorkflowState.COMPILE_REQUIRED, last_error=sys.argv[2])
try:
    write_checkpoint(checkpoint, sys.argv[1])
    print('written')
except CheckpointConflict:
    print('conflict')
'''
            processes = [subprocess.Popen([sys.executable, '-B', '-c', script, path, str(i)],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                         for i in range(2)]
            try:
                for process in processes:
                    self.assertEqual(process.stdout.readline().strip(), 'ready')
                for process in processes:
                    process.stdin.write('go\n')
                    process.stdin.flush()
                results = [process.communicate(timeout=10) for process in processes]
                self.assertCountEqual([out.strip() for out, _ in results], ['written', 'conflict'])
                self.assertTrue(all(process.returncode == 0 for process in processes), results)
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                    process.communicate()

    def test_explicit_new_workflow_invalidates_old_writer_and_keeps_v1_format(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'checkpoint.json')
            old = create_checkpoint(base_user_data())
            write_checkpoint(old, path)
            fresh = create_checkpoint(base_user_data())
            write_checkpoint(fresh, path, expected_revision=checkpoint_revision(path))
            with self.assertRaises(FirmwareWorkflowError):
                write_checkpoint(transition_checkpoint(old, State.COMPILE_REQUIRED), path)
            self.assertEqual(load_checkpoint(path)['workflow_id'], fresh['workflow_id'])
            self.assertNotIn('_storage_revision', json.loads(Path(path).read_text()))
            fresh = transition_checkpoint(fresh, State.COMPILE_REQUIRED)
            fresh = transition_checkpoint(fresh, State.COMPILE_REQUIRED)
            write_checkpoint(fresh, path)
            write_checkpoint(fresh, path)  # Same object can be persisted again.

    def test_stale_writer_cannot_replace_even_with_a_higher_sequence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'checkpoint.json')
            first = create_checkpoint(base_user_data())
            write_checkpoint(first, path)
            stale = load_checkpoint(path)
            winner = transition_checkpoint(load_checkpoint(path), State.COMPILE_REQUIRED, last_error='winner')
            write_checkpoint(winner, path)
            stale = transition_checkpoint(stale, State.COMPILE_REQUIRED, last_error='stale')
            stale = transition_checkpoint(stale, State.COMPILE_REQUIRED, last_error='even later')
            before = Path(path).read_bytes()
            with self.assertRaises(FirmwareWorkflowError):
                write_checkpoint(stale, path)
            self.assertEqual(Path(path).read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
