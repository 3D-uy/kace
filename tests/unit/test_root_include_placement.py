"""Default include placement is readable without changing Klipper precedence."""
import copy

import pytest

from core.configuration_review import _sections
from core.managed_config import (
    MANAGED_BEGIN, MANAGED_END, ROOT_REMOTE, build_managed_config_plan,
    effective_hardware_text,
)
from core.translations import translate_comment
from tests.unit.test_configuration_review import _hardware


def generated(language, newline):
    title = '# ' + translate_comment('Includes', language)
    return (f'# generated header\n# ----------------\n{title}\n# ----------------\n'
            '[include mainsail.cfg]\n\n' + _hardware().decode().replace(
                '[printer]\n', '[printer]\nmax_velocity: 300\n')).replace('\n', newline).encode()


@pytest.mark.parametrize('language', ['English', 'Español', 'Português'])
@pytest.mark.parametrize('newline', ['\n', '\r\n'])
@pytest.mark.parametrize('layout', ['new', 'placeholder', 'old-header', 'old-tail'])
def test_root_default_include_is_under_components_once_and_retry_is_unchanged(language, newline, layout):
    hardware = generated(language, newline)
    directive = '[include mainsail.cfg]'
    old_hardware = _hardware().decode()
    if layout == 'new':
        old = None
    elif layout == 'placeholder':
        old = (directive + '\n[mcu]\n[printer]\nkinematics: none\n').replace('\n', newline).encode()
    else:
        block = f'{MANAGED_BEGIN}\n{old_hardware}{MANAGED_END}\n'
        body = directive + '\n\n' + block if layout == 'old-header' else block + '\n' + directive + '\n'
        old = ('# KACE layout: root-v1\n' + body).replace('\n', newline).encode()
    remote = {ROOT_REMOTE: old, 'mainsail.cfg': b'[printer]\nmax_velocity: 999\n'}
    original = copy.deepcopy(remote)
    plan = build_managed_config_plan(hardware, None, remote)
    root = next(item.content for item in plan.artifacts if item.remote_name == ROOT_REMOTE).decode()
    title = '# ' + translate_comment('Includes', language)
    assert root.count(directive) == 1
    assert root.index(MANAGED_BEGIN) < root.index(title) < root.index(directive) < root.index('[mcu]')
    assert root.index(directive) < root.index(MANAGED_END)
    # Mainsail defaults still load before, and cannot overwrite generated options.
    assert _sections(effective_hardware_text(plan))['printer']['max_velocity'] == '300'
    files = dict(remote)
    files.update({item.remote_name: item.content for item in plan.artifacts})
    retry = build_managed_config_plan(hardware, None, files)
    assert not retry.changed_artifacts
    assert remote == original


def test_existing_include_comment_user_content_and_save_config_survive_relocation():
    saved = b'#*# <---------------------- SAVE_CONFIG ---------------------->\r\n#*# [extruder]\r\n#*# pid_kp = 41.25  \r\n'
    user = b'# user include comment\r\n[include user.cfg]\r\n[gcode_macro USER]\r\ngcode: M117 Keep\r\n'
    existing = b'# KACE layout: root-v1\r\n[include mainsail.cfg] # keep this comment\r\n' + user + saved
    remote = {ROOT_REMOTE: existing, 'mainsail.cfg': b'', 'user.cfg': b'[respond]\n'}
    plan = build_managed_config_plan(generated('Español', '\r\n'), None, remote)
    root = plan.artifacts[0].content
    assert root.endswith(saved)
    assert user in root
    assert root.count(b'[include mainsail.cfg]') == 1
    assert b'[include mainsail.cfg] # keep this comment' in root
    assert root.index('Componentes Incluidos'.encode()) < root.index(b'[include mainsail.cfg]') < root.index(b'[mcu]')


def test_without_selected_dashboard_preserved_mainsail_uses_empty_components_section():
    hardware = generated('Português', '\n').replace(b'[include mainsail.cfg]\n', b'')
    old = b'# KACE layout: root-v1\n[include mainsail.cfg]\n'
    plan = build_managed_config_plan(hardware, None, {ROOT_REMOTE: old, 'mainsail.cfg': b''})
    root = plan.artifacts[0].content
    assert root.index('Componentes Incluídos'.encode()) < root.index(b'[include mainsail.cfg]') < root.index(b'[mcu]')


def test_user_layout_include_order_is_unchanged():
    old = b'[include user.cfg]\n[include mainsail.cfg] # retained\n[gcode_macro USER]\ngcode: M117 Keep\n'
    plan = build_managed_config_plan(generated('English', '\n'), None,
                                     {ROOT_REMOTE: old, 'mainsail.cfg': b'', 'user.cfg': b''})
    root = plan.artifacts[0].content
    assert root.endswith(old)
    assert root.count(b'[include mainsail.cfg]') == 1


def test_no_components_header_or_misleading_late_heading_keeps_defaults_before_options():
    for hardware in (_hardware(), _hardware() + b'\n# Includes\n# ----\n'):
        hardware = b'[include mainsail.cfg]\n' + hardware
        plan = build_managed_config_plan(hardware, None, {ROOT_REMOTE: None, 'mainsail.cfg': b''})
        root = plan.artifacts[0].content
        assert root.index(MANAGED_BEGIN.encode()) < root.index(b'[include mainsail.cfg]') < root.index(b'[mcu]')
