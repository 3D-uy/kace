import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from core.config_transaction import ConfigDeploymentTransaction, LocalMoonrakerConfigTransport
from core.managed_config import build_managed_config_plan, ROOT_REMOTE, HARDWARE_REMOTE
from core.translations import UI_STRINGS
from tests.unit.test_config_transaction import GENERATED


class LocalInstallationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = self.root / 'config'
        self.config.mkdir()
        self.live = self.config / 'printer.cfg'
        self.live.write_bytes(b'[mcu]\nserial: /dev/null\n[printer]\nkinematics: none\n')
        self.transport = LocalMoonrakerConfigTransport(str(self.config))
        self.transport.validate_activation_target = Mock()
        self.transport.restart = Mock()
        self.transport.klipper_state = Mock(return_value='ready')
        self.transport.moonraker_online = Mock(return_value=True)
        self.transport.verify_active_configuration = Mock()

    def transaction(self, **kwargs):
        return ConfigDeploymentTransaction(
            self.transport, GENERATED, None, activation='firmware',
            verify_existing_ready=True, poll_interval=0,
            snapshot_root=str(self.root / 'snapshots'), **kwargs,
        ).run()

    def test_clean_preexisting_placeholder_and_retry_without_restart(self):
        original = self.live.read_bytes()
        replace = os.replace
        publications = []

        def atomic(source, destination):
            if str(destination) == str(self.live):
                self.assertEqual(Path(source).parent, self.live.parent)
                self.assertEqual(self.live.read_bytes(), original)
                publications.append(Path(source).read_bytes())
            return replace(source, destination)

        with patch('core.config_transaction.os.replace', side_effect=atomic):
            result = self.transaction()
        self.assertTrue(result.ok, result.detail)
        self.assertEqual(result.snapshot.config_files[ROOT_REMOTE], original)
        self.assertEqual(publications, [self.live.read_bytes()])
        self.assertIn(b'[stepper_x]', self.live.read_bytes())
        self.assertNotIn(b'generated-hardware.cfg', self.live.read_bytes())
        self.transport.restart.assert_called_once()
        self.transport.restart.reset_mock()
        selector = Mock(side_effect=AssertionError('no restart prompt'))
        result = self.transaction(activation_selector=selector)
        self.assertTrue(result.ok, result.detail)
        self.transport.restart.assert_not_called()
        selector.assert_not_called()

    def test_edit_after_staging_is_preserved_with_recoverable_proposal(self):
        chmod = os.chmod

        def edit_after_stage(path, mode, **kwargs):
            chmod(path, mode, **kwargs)
            if Path(path).name.startswith('.kace-part-'):
                self.live.write_bytes(b'# edited externally\n')

        with patch('core.config_transaction.os.chmod', side_effect=edit_after_stage):
            result = self.transaction()
        self.assertFalse(result.ok)
        self.assertEqual(self.live.read_bytes(), b'# edited externally\n')
        self.transport.restart.assert_not_called()
        self.assertTrue(list((self.root / 'snapshots').glob('*-proposed')))

    def test_interrupted_publication_recovers_by_revalidating_active_files(self):
        self.transport.restart.side_effect = KeyboardInterrupt
        first = self.transaction()
        self.assertFalse(first.ok)
        self.assertIsNotNone(first.snapshot)
        self.transport.restart.reset_mock(side_effect=True)
        second = self.transaction()
        self.assertTrue(second.ok, second.detail)
        self.transport.restart.assert_not_called()

    def test_new_root_retains_save_config_and_calibration_on_retry(self):
        generated = GENERATED + b'[extruder]\ncontrol: pid\npid_kp: 22\n'
        first = build_managed_config_plan(generated, None, {ROOT_REMOTE: self.live.read_bytes()})
        files = {item.remote_name: item.content for item in first.artifacts}
        saved = b'#*# <---------------------- SAVE_CONFIG ---------------------->\n#*# [extruder]\n#*# pid_kp = 31\n'
        files[ROOT_REMOTE] = files[ROOT_REMOTE].replace(b'pid_kp: 22\n', b'') + saved
        second = build_managed_config_plan(generated, None, files)
        root = next(item.content for item in second.artifacts if item.remote_name == ROOT_REMOTE)
        self.assertTrue(root.endswith(saved))
        self.assertNotIn(b'pid_kp: 22', root)
        self.assertEqual(root.count(b'\n[extruder]'), 1)
        self.assertNotIn(HARDWARE_REMOTE, second.remote_names)

    def test_noop_requires_loaded_settings_and_handles_macro_case(self):
        from core.config_transaction import MoonrakerConfigTransport, ConfigConflictError
        plan = build_managed_config_plan(b'[mcu]\nserial: test\n[gcode_macro USER]\ngcode:\n    G28\n', None, {})
        transport = MoonrakerConfigTransport('localhost', 7125)
        body = {'result': {'status': {'configfile': {'config': {
            'mcu': {'serial': 'test'}, 'gcode_macro USER': {'gcode': '\nG28'},
        }}}}}
        with patch('core.moonraker._get', return_value=(True, '', body)):
            transport.verify_active_configuration(plan)
            body['result']['status']['configfile']['config']['mcu']['serial'] = 'old'
            with self.assertRaises(ConfigConflictError):
                transport.verify_active_configuration(plan)

    def test_root_layout_keeps_user_sections_and_calibrated_extrusion(self):
        from core.managed_config import MANAGED_END
        generated = GENERATED + b'[extruder]\nrotation_distance: 22\n'
        first = build_managed_config_plan(generated, None, {})
        files = {item.remote_name: item.content for item in first.artifacts}
        files[ROOT_REMOTE] = files[ROOT_REMOTE].replace(b'rotation_distance: 22', b'rotation_distance: 23.7')
        macro = b'[gcode_macro USER_CUSTOM]\ngcode: M117 keep\n'
        files[ROOT_REMOTE] = files[ROOT_REMOTE].replace(MANAGED_END.encode(), macro + MANAGED_END.encode())
        second = build_managed_config_plan(generated, None, files)
        root = next(item.content for item in second.artifacts if item.remote_name == ROOT_REMOTE)
        self.assertIn(macro, root)
        self.assertIn(b'rotation_distance: 23.7', root)
        files = {item.remote_name: item.content for item in second.artifacts}
        self.assertEqual(build_managed_config_plan(generated, None, files).changed_artifacts, ())

    def test_cli_local_installation_reaches_complete_and_renders_success(self):
        import hashlib
        import kace
        from core.deployer import _config_result_to_workflow
        from core.firmware_workflow import create_checkpoint, transition_checkpoint, write_checkpoint, load_checkpoint, FirmwareWorkflowState as State
        from tests.regression.test_main_integration import _WIZARD_USER_DATA_WITH_PARSED
        user = {**_WIZARD_USER_DATA_WITH_PARSED, 'mcu_type': 'lpc1769', 'mcu_path': '/dev/serial/by-id/test', 'language': 'Español'}
        artifact = self.root / 'firmware.bin'
        artifact.write_bytes(b'firmware')
        checkpoint = transition_checkpoint(create_checkpoint(user), State.ARTIFACT_READY, artifact={
            'path': str(artifact), 'final_filename': 'firmware.bin',
            'sha256': hashlib.sha256(b'firmware').hexdigest(), 'size_bytes': 8,
            'method': 'MANUAL', 'strategy': 'SD_CARD', 'instructions': [], 'build': {'mcu': 'lpc1769'},
        })
        checkpoint = transition_checkpoint(checkpoint, State.VERIFYING_MCU)
        checkpoint = transition_checkpoint(checkpoint, State.MCU_VERIFIED, verified_serial_path=user['mcu_path'], flash_evidence_recorded_at=1)
        checkpoint = transition_checkpoint(checkpoint, State.CONFIG_GENERATED)
        checkpoint = transition_checkpoint(checkpoint, State.READY_TO_DEPLOY)
        checkpoint_path = str(self.root / 'firmware-workflow.json')
        write_checkpoint(checkpoint, checkpoint_path)
        from core.translations import set_lang, get_lang
        self.addCleanup(set_lang, get_lang())
        set_lang('Español')
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {'KACE_AUTO': '1', 'KACE_FIRMWARE_WORKFLOW_PATH': checkpoint_path}))
            for name in ('print_kace_banner', 'print_summary', 'time.sleep'):
                stack.enter_context(patch('kace.' + name))
            stack.enter_context(patch('kace.check_display_compatibility', return_value=[]))
            stack.enter_context(patch('kace.extract_mcu_serial', return_value=user['mcu_path']))
            stack.enter_context(patch('kace.os.path.isfile', return_value=True))
            stack.enter_context(patch('kace.numbered_select', return_value='moonraker'))
            stack.enter_context(patch('kace.deploy_moonraker', side_effect=lambda _: _config_result_to_workflow(self.transaction())))
            wizard = stack.enter_context(patch('kace.run_wizard', side_effect=AssertionError('must resume')))
            output = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            with self.assertRaises(SystemExit) as exited:
                kace.main()
        self.assertEqual(exited.exception.code, 0)
        self.assertEqual(load_checkpoint(checkpoint_path)['state'], 'COMPLETE')
        self.assertIn('Instalación de KACE completada', output.getvalue())
        self.assertIn('commissioning', output.getvalue())
        wizard.assert_not_called()


class RecoveryPresentationTests(unittest.TestCase):
    def setUp(self):
        from core.translations import get_lang, get_mode, set_lang, set_mode
        self.addCleanup(set_lang, get_lang())
        self.addCleanup(set_mode, get_mode())

    def test_late_states_do_not_offer_firmware_copy_or_mcu_verification(self):
        import kace
        for state in ('MCU_VERIFIED', 'CONFIG_GENERATED', 'READY_TO_DEPLOY', 'DEPLOYING'):
            checkpoint = {'state': state, 'artifact': {'path': 'firmware.bin'}, 'wizard_data': {'language': 'Español'}}
            with patch('kace.load_checkpoint', return_value=checkpoint), patch('firmware.detector.discover_mcu_hardware', return_value={}), patch('kace.numbered_select', return_value='continue') as select, patch.dict(os.environ, {'KACE_AUTO': '0'}):
                kace._resume_firmware_workflow()
            choices = select.call_args.kwargs['choices']
            self.assertEqual([item['value'] for item in choices], ['continue', 'new'])
            self.assertNotIn(state, select.call_args.args[0])

    def test_pending_workflow_is_checked_before_dashboard(self):
        import kace
        with patch('kace._resume_firmware_workflow', side_effect=RuntimeError('checked first')), patch('core.dashboard.run_dashboard') as dashboard:
            with self.assertRaisesRegex(RuntimeError, 'checked first'):
                kace.main()
            dashboard.assert_not_called()

    def test_beginner_never_gets_technical_diff_question(self):
        from core.deployer import _interactive_configuration_review
        from core.configuration_review import build_configuration_review
        review = build_configuration_review(build_managed_config_plan(GENERATED, None, {}))
        prompts = []
        with patch('core.translations.get_mode', return_value='Beginner'), contextlib.redirect_stdout(io.StringIO()) as output:
            _interactive_configuration_review(review, lambda prompt, **kw: prompts.append(prompt) or True)
        self.assertEqual(len(prompts), 1)
        self.assertNotIn('diff', prompts[0])
        self.assertNotIn('--- remote/', output.getvalue())

    def test_new_messages_have_all_catalogs_and_success_is_commissioning(self):
        for key in ('installation.complete', 'firmware.resume.pending', 'firmware.resume.discard', 'deploy.remote_unsupported', 'deploy.local_active', 'menu.default'):
            self.assertEqual(set(UI_STRINGS[key]), {'English', 'Español', 'Português'})
        self.assertIn('commissioning', UI_STRINGS['installation.complete']['Español'])
        self.assertNotIn('lista para imprimir', UI_STRINGS['installation.complete']['Español'])
