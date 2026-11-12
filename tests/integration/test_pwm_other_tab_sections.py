"""PWM consumer checks run before simulated publication of preserved config."""
from unittest.mock import Mock
import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.managed_config import build_managed_config_plan
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_effective_xy_geometry import _generate, _context, _assert_no_destination_mutations

PROVIDER = '[sx1509 Expander]\ni2c_address: 62\ni2c_bus: i2c1\n'
HEADER = ('\n#*# <---------------------- SAVE_CONFIG ---------------------->\n'
          '#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.\n#*#\n')
SPECS = {
    'output_pin': ('pin: sx1509_Expander:PIN_0\npwm: true\n', 'hardware_pwm', 'false', True),
    'pwm_tool': ('pin: PG10\n', 'cycle_time', '4', False),
    'pwm_cycle_time': ('pin: PG10\n', 'cycle_time', '4', False),
    'heater_generic': ('heater_pin: sx1509_Expander:PIN_0\nsensor_type: Generic 3950\nsensor_pin: PG11\ncontrol: watermark\nmin_temp: 0\nmax_temp: 100\n', None, None, True),
}


@pytest.mark.parametrize('family', list(SPECS))
@pytest.mark.parametrize('source', ['root', 'include', 'save'])
@pytest.mark.parametrize('noop', [False, True])
def test_tabbed_consumer_rejected_before_write(tmp_path, family, source, noop):
    base = _generate(tmp_path)
    context = _context(tmp_path, base)
    body, option, value, provider = SPECS[family]
    name = family + '\tAudit'
    prefix = PROVIDER if provider else ''
    block = prefix + f'[{name}]\n' + body
    if source == 'save' and option:
        raw = base + b'\n' + block.encode() + HEADER.encode() + f'#*# [{name}]\n#*# {option} = {value}\n'.encode()
        remote = {'printer.cfg': raw}
    else:
        if option:
            block += f'{option}: {value}\n'
        if source == 'include':
            remote = {'printer.cfg': base + b'\n[include user.cfg]\n', 'user.cfg': block.encode()}
        else:
            remote = {'printer.cfg': base + b'\n' + block.encode()}
            if source == 'save':
                remote['printer.cfg'] += HEADER.encode()
    plan = build_managed_config_plan(base, None, remote, geometry_context=context)
    if noop:
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        plan = build_managed_config_plan(base, None, remote, geometry_context=context)
        assert not plan.changed_artifacts
    review = validate_configuration_plan(plan)
    assert not review.valid and any(x.code in ('pwm-output', 'sx1509-pwm') for x in review.errors), review.errors
    transport = FakeTransport(remote)
    before = dict(transport.files)
    confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, base, None, geometry_context=context,
        activation='none', confirm=confirm, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path/'snapshots')).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    _assert_no_destination_mutations(transport, before)
