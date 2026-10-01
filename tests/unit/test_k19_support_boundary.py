"""Preparation-only transport stays explicit on selection and saved reuse."""
from unittest.mock import patch

import pytest

from core.firmware_wizard import _select_board_serial
from core.translations import t, get_lang, set_lang
from firmware.board_serial import SAPPHIRE


@pytest.mark.parametrize('language', ['English', 'Español', 'Português'])
@pytest.mark.parametrize('saved', [False, True])
def test_direct_uart_limit_is_visible_without_changing_preparation(language, saved, capsys):
    previous = get_lang()
    try:
        set_lang(language)
        with patch.dict('os.environ', {'KACE_AUTO':'1' if saved else '0'}), \
             patch('core.firmware_wizard.numbered_select', return_value='USART1') as menu:
            assert _select_board_serial(SAPPHIRE[0], 'USART1' if saved else None) == 'USART1'
        assert t('deployment.robin.direct_uart_limit') in capsys.readouterr().out
        if saved:
            menu.assert_not_called()
        else:
            choice = next(c for c in menu.call_args.kwargs['choices'] if c['value']=='USART1')
            assert choice['name'] == t('deployment.robin.direct_uart_choice')
    finally:
        set_lang(previous)


def test_usb_bridge_is_not_labeled_as_unsupported_direct_uart(capsys):
    assert _select_board_serial(SAPPHIRE[0], 'USART3') == 'USART3'
    assert not capsys.readouterr().out
