"""Fresh-host routing and missing optional SSH support stay recoverable."""
import builtins
import copy
import os
from unittest.mock import Mock

import pytest

import kace
from core import config_transaction, deployer
from core.exceptions import WizardExit
from core.translations import get_lang, set_lang, t


@pytest.fixture(autouse=True)
def interactive(monkeypatch):
    language = get_lang()
    monkeypatch.setenv('KACE_AUTO', '0')
    yield
    set_lang(language)


@pytest.mark.parametrize('language', ['English', 'Español', 'Português'])
def test_fresh_pi_offers_local_install_and_excludes_missing_ssh_before_credentials(monkeypatch, capsys, language):
    set_lang(language)
    monkeypatch.setattr(config_transaction, 'local_moonraker_available', lambda: True)
    monkeypatch.setattr(deployer, 'ssh_deployment_available', lambda: False)
    monkeypatch.setattr(kace, 'simple_input', lambda *a, **k: pytest.fail('No credentials before route'))
    monkeypatch.setattr(kace, 'password_input', lambda *a, **k: pytest.fail('No SSH password'))
    def select(prompt, choices):
        assert [c['value'] for c in choices] == ['none', 'local', 'usb', 'moonraker']
        return 'moonraker'
    monkeypatch.setattr(kace, 'numbered_select', select)
    assert kace._select_configuration_deployment() == 'moonraker'
    text=' '.join(capsys.readouterr().out.split())
    assert ' '.join(t('deploy.ssh_unavailable').split()) in text
    assert ' '.join(t('deploy.local_help').split()) in text
    assert ' '.join(t('deploy.remote_unsupported').split()) not in text


def test_ssh_dependency_disappearing_at_selection_returns_to_methods(monkeypatch):
    monkeypatch.setattr(config_transaction, 'local_moonraker_available', lambda: True)
    available=iter([True, False, False])
    monkeypatch.setattr(deployer, 'ssh_deployment_available', lambda: next(available))
    answers=iter(['ssh','moonraker'])
    monkeypatch.setattr(kace, 'numbered_select', lambda *a, **k: next(answers))
    assert kace._select_configuration_deployment() == 'moonraker'


def test_deployment_menu_ctrl_c_returns_cancelled_selection(monkeypatch):
    monkeypatch.setattr(config_transaction, 'local_moonraker_available', lambda: False)
    monkeypatch.setattr(deployer, 'ssh_deployment_available', lambda: False)
    monkeypatch.setattr(kace, 'numbered_select', Mock(side_effect=WizardExit))
    assert kace._select_configuration_deployment() is None


def test_missing_paramiko_check_is_quiet_and_never_installs(monkeypatch, capsys):
    original = builtins.__import__
    def without_paramiko(name, *a, **kw):
        if name == 'paramiko': raise ImportError('synthetic optional dependency absent')
        return original(name, *a, **kw)
    monkeypatch.setattr(builtins, '__import__', without_paramiko)
    assert not deployer.ssh_deployment_available()
    assert capsys.readouterr().out == ''
    assert deployer._require_paramiko() is None
    assert t('deploy.ssh_unavailable') in capsys.readouterr().out


def test_local_candidate_does_not_require_a_generated_or_active_cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(config_transaction.os, 'name', 'posix')
    monkeypatch.setattr(config_transaction.os.path, 'expanduser', lambda p: str(tmp_path/'config'))
    assert not config_transaction.local_moonraker_available()
    (tmp_path/'config').mkdir()
    assert config_transaction.local_moonraker_available()
    assert not (tmp_path/'config/printer.cfg').exists()


@pytest.mark.skipif(os.name != 'posix', reason='Local installation requires POSIX filesystem authority')
def test_fresh_local_route_retains_moonraker_path_authority(tmp_path, monkeypatch):
    config = tmp_path/'config'
    config.mkdir()
    active = str(config/'printer.cfg')
    def response(url, **kw):
        if url.endswith('/printer/info'): return True, '', {'result': {'config_file': active}}
        assert url.endswith('/server/files/roots')
        return True, '', {'result': [{'name': 'config', 'path': str(config)}]}
    monkeypatch.setattr('core.moonraker._get', response)
    transport=config_transaction.configuration_transport('127.0.0.1')
    assert isinstance(transport, config_transaction.LocalMoonrakerConfigTransport)
    assert transport.read_files(['printer.cfg']) == {'printer.cfg': None}
    assert transport.supports_conditional_write(None)
    assert not (config/'printer.cfg').exists()
    active=str(tmp_path/'foreign/printer.cfg')
    with pytest.raises(config_transaction.ConfigConflictError):
        config_transaction.configuration_transport('127.0.0.1')
    assert not (config/'printer.cfg').exists()
    active=str(config/'printer.cfg')
    transport.validate_activation_target()
    transport.upload_if_unchanged('printer.cfg',b'first installation',None)
    assert (config/'printer.cfg').read_bytes()==b'first installation'
    (config/'printer.cfg').write_bytes(b'external edit')
    with pytest.raises(config_transaction.ConfigConflictError):
        transport.upload_if_unchanged('printer.cfg',b'replacement',b'first installation')
    assert (config/'printer.cfg').read_bytes()==b'external edit'


@pytest.mark.parametrize('host', ['localhost', '127.0.0.1', '[::1]'])
def test_non_posix_loopback_never_acquires_local_filesystem_authority(monkeypatch, host):
    monkeypatch.setattr(config_transaction.os, 'name', 'nt')
    request = Mock(side_effect=AssertionError('No local path discovery on non-POSIX hosts'))
    monkeypatch.setattr('core.moonraker._get', request)
    transport = config_transaction.configuration_transport(host)
    assert type(transport) is config_transaction.MoonrakerConfigTransport
    assert not transport.supports_conditional_write(b'existing')
    request.assert_not_called()


def test_remote_http_replacement_remains_unsupported():
    transport=config_transaction.configuration_transport('fixture-printer.invalid')
    assert type(transport) is config_transaction.MoonrakerConfigTransport
    assert not transport.supports_conditional_write(b'existing')


@pytest.mark.parametrize('language', ['English','Español','Português'])
@pytest.mark.parametrize('answer,inverted,unverified', [('normal',False,False),('inverted',True,False),('unknown',False,True)])
def test_polarity_guide_does_not_infer_or_change_pin_pullup_offsets(monkeypatch, capsys, language, answer, inverted, unverified):
    from core.wizard.steps import sensors
    set_lang(language)
    user=dict(custom_probe_pin='P1.27',custom_probe_pullup=True,custom_probe_z_offset='')
    before=copy.deepcopy(user)
    monkeypatch.setattr(sensors,'numbered_select',lambda *a,**k: answer)
    assert sensors._step_custom_probe_signal_option(user,'inverted')=='done'
    assert user == dict(before,custom_probe_inverted=inverted,custom_probe_polarity_unverified=unverified)
    guide=t('wizard.probe_signal.guide')
    assert all(s in guide for s in ('!','QUERY_PROBE','open','TRIGGERED'))
    assert len(guide) <= 200 and '\n' not in guide
    text=' '.join(capsys.readouterr().out.split())
    assert ' '.join(guide.split()) in text
