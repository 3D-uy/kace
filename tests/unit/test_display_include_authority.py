"""Include indirection cannot qualify generated display hardware."""
from unittest.mock import Mock, patch

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.managed_config import build_managed_config_plan
from tests.unit.test_config_transaction import GENERATED, FakeTransport
from tests.unit.test_display_publication import display, VALID


PANEL = display('st7920', VALID['st7920'])


@pytest.mark.parametrize('origin', ['hardware', 'macros', 'manual'])
@pytest.mark.parametrize('nested', [False, True])
@pytest.mark.parametrize('noop', [False, True])
def test_include_authority_follows_generated_roots(tmp_path, origin, nested, noop):
    # Macro include paths are relative to kace/generated-macros.cfg.
    prefix = 'kace/' if origin == 'macros' else ''
    target = 'panels/entry.cfg' if nested else 'panels/display.cfg'
    include = f'[include {target}]\n'.encode()
    files = {'printer.cfg': include if origin == 'manual' else b'# user root\n',
             prefix+'panels/display.cfg': PANEL}
    if nested:
        files[prefix+'panels/entry.cfg'] = b'[include display.cfg]\n'
    hardware = GENERATED + (include if origin == 'hardware' else b'')
    macros = include if origin == 'macros' else None
    if noop:
        files.update({a.remote_name: a.content for a in build_managed_config_plan(hardware, macros, files).artifacts})
    transport, events, review = FakeTransport(files), [], Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, hardware, macros, activation='none',
        review=review, verify_existing_ready=noop, state_sink=lambda *event: events.append(event),
        snapshot_root=str(tmp_path/'snapshots')).run()
    if origin == 'manual':
        expected = ConfigTransactionState.COMMITTED if noop else ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
        assert result.state == expected, result
        assert transport.files[prefix+'panels/display.cfg'] == PANEL
        assert any(w.code == 'display-hardware-unverified' for w in review.call_args.args[0].validation.warnings)
    else:
        assert result.state == ConfigTransactionState.PRECONDITION_FAILED, result
        assert 'display hardware' in result.detail
        assert transport.files == files
        assert not any(c[0] in ('upload', 'delete', 'restart') for c in transport.calls)
        assert not any(state == 'DONE' for state, _ in events)
        review.assert_not_called()


@pytest.mark.parametrize('content', [b'# [display]\n# lcd_type: st7920\n', b'[display_status]\n'])
def test_generated_external_software_or_comments_remain_allowed(tmp_path, content):
    files = {'printer.cfg': b'# user\n', 'dashboard.cfg': content}
    transport = FakeTransport(files)
    result = ConfigDeploymentTransaction(transport, GENERATED+b'[include dashboard.cfg]\n', None,
        activation='none', snapshot_root=str(tmp_path/'snapshots')).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION, result


def test_later_manual_override_does_not_qualify_generated_include(tmp_path):
    files = {'printer.cfg': PANEL, 'panel.cfg': b'[display]\nlcd_type: st7920\ncs_pin: PC4\n'}
    transport = FakeTransport(files)
    result = ConfigDeploymentTransaction(transport, GENERATED+b'[include panel.cfg]\n', None,
        activation='none', snapshot_root=str(tmp_path/'snapshots')).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED, result
    assert 'display hardware' in result.detail
    assert transport.files == files


def test_shared_manual_and_generated_include_keeps_generated_gate(tmp_path):
    include = b'[include panel.cfg]\n'
    files = {'printer.cfg': include, 'panel.cfg': PANEL}
    transport = FakeTransport(files)
    result = ConfigDeploymentTransaction(transport, GENERATED+include, None,
        activation='none', snapshot_root=str(tmp_path/'snapshots')).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED, result
    assert 'display hardware' in result.detail
    assert transport.files == files


@pytest.mark.parametrize('include,files', [
    (b'[include missing.cfg]\n', {}),
    (b'[include cycle.cfg]\n', {'cycle.cfg': b'[include cycle.cfg]\n'}),
    (b'[include ../outside.cfg]\n', {}),
    (b'[include panels/*.cfg]\n', {}),
])
def test_unreviewable_generated_graph_cannot_write(tmp_path, include, files):
    files = {'printer.cfg': b'# existing\n', **files}
    transport = FakeTransport(files)
    result = ConfigDeploymentTransaction(transport, GENERATED+include, None,
        activation='none', snapshot_root=str(tmp_path/'snapshots')).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED, result
    assert transport.files == files
    assert not any(c[0] in ('upload', 'delete', 'restart') for c in transport.calls)


def test_combined_firmware_installation_rejects_include_before_physical_work():
    from core.deployer import deploy_firmware_installation
    from core.moonraker_deployer import DeployState
    from tests.unit.test_deployer import FirmwareInstallationPreconditionTests
    user = FirmwareInstallationPreconditionTests()._user()
    files = {'printer.cfg': b'# original\n', 'panel.cfg': PANEL}
    transport = FakeTransport(files)
    with patch('core.deployer._generated_config_bytes', return_value=(
            'unused', GENERATED+b'[include panel.cfg]\n', None)), patch(
            'core.deployer._preflight_check', return_value=True), patch(
            'core.config_transaction.configuration_transport', return_value=transport), patch(
            'core.deployer._interactive_configuration_review') as review:
        result = deploy_firmware_installation(user)
    assert result.state == DeployState.FAILED_PRECONDITION, result
    assert 'display hardware' in result.detail
    user['firmware_deployment_service'].execute.assert_not_called()
    review.assert_not_called()
    assert transport.files == files
    assert not any(c[0] in ('upload', 'delete', 'restart') for c in transport.calls)


def test_include_changed_after_review_cannot_publish(tmp_path):
    files = {'printer.cfg': b'# original\n', 'panel.cfg': b'[display_status]\n'}
    transport = FakeTransport(files)

    def change_after_review(_):
        transport.files['panel.cfg'] = PANEL
        return True

    result = ConfigDeploymentTransaction(transport, GENERATED+b'[include panel.cfg]\n', None,
        activation='none', review=change_after_review, snapshot_root=str(tmp_path/'snapshots')).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED, result
    assert transport.files == {**files, 'panel.cfg': PANEL}
    assert not any(c[0] in ('upload', 'delete', 'restart') for c in transport.calls)
