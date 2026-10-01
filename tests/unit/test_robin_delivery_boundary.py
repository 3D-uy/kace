"""Native Robin firmware must not be presented or copied as an SD-ready image."""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from core.translations import get_lang, set_lang, t
from firmware.board_serial import KINGROON
from firmware.deployment.models import DeploymentExecutionContext, DeploymentMethodId, DeploymentStatus, DeploymentTarget
from firmware.deployment.service import FirmwareDeploymentService
from tests.unit.test_robin_serial import ROUTES, artifact


@pytest.mark.parametrize('board,port', ROUTES)
@pytest.mark.parametrize('language', ['English', 'Español', 'Português'])
def test_native_only_boundary_is_visible_and_persisted(tmp_path, board, port, language):
    previous = get_lang()
    try:
        set_lang(language)
        built = artifact(tmp_path, port)
        events = []
        service = FirmwareDeploymentService(output_dir=str(tmp_path/'prepared'), event_sink=events.append)
        plan = service.plan(built, DeploymentTarget(board, 'stm32f103'), DeploymentMethodId.MANUAL)
        expected_keys = ['deployment.robin.native_only',
                         'deployment.robin.kingroon_name' if board == KINGROON else 'deployment.robin.sapphire_name']
        assert [i.id for i in plan.instructions] == expected_keys
        assert plan.instructions[0].text == t(expected_keys[0], filename='klipper.bin')
        assert 'scripts/update_mks_robin.py' in plan.instructions[0].text
        assert 'make flash' in plan.instructions[0].text
        if board == KINGROON:
            assert 'Robin_nano.bin' in plan.instructions[1].text
            assert 'Robin_nano35.bin' not in plan.instructions[1].text
        else:
            assert 'Robin_nano35.bin' in plan.instructions[1].text
            assert 'Robin_nano43.bin' in plan.instructions[1].text
            assert 'printer.cfg' in plan.instructions[1].text
        prepared = service.prepare(plan)
        media = tmp_path/'media'
        media.mkdir()
        provider = Mock(return_value=str(media))
        runner = Mock()
        result = service.execute(prepared, DeploymentExecutionContext(media_path_provider=provider, command_runner=runner))
        assert result.status is DeploymentStatus.ACTION_REQUIRED and not result.ok
        assert result.error_code == 'PREPARE_ONLY' and not result.executed_automatically
        provider.assert_not_called()
        runner.assert_not_called()
        assert list(media.iterdir()) == []
        assert Path(prepared.staged_path).name == 'klipper.bin'
        assert Path(prepared.staged_path).read_bytes() == Path(built.path).read_bytes()
        manifest = json.loads((tmp_path/'prepared/deployment-manifest.json').read_text())
        assert [i['id'] for i in manifest['deployment']['instructions']] == expected_keys
        assert manifest['deployment']['staged_sha256'] == built.sha256
        assert events[-1]['state'] == 'ACTION_REQUIRED'
    finally:
        set_lang(previous)


@pytest.mark.parametrize('board', ['generic-mks-robin-nano.cfg', 'printer-kingroon-kp3s-2020.cfg.bak', 'unknown.cfg'])
def test_unreviewed_alias_does_not_inherit_robin_instructions(tmp_path, board):
    built = artifact(tmp_path, 'USART3')
    service = FirmwareDeploymentService(output_dir=str(tmp_path/'prepared'), event_sink=lambda _: None)
    plan = service.plan(built, DeploymentTarget(board, 'stm32f103'), DeploymentMethodId.MANUAL)
    assert [i.id for i in plan.instructions] == ['deployment.prepare_only.unsupported']
