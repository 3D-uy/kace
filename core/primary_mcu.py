"""Board-owned restart policy; endpoint selection remains with the MCU workflow."""
from collections.abc import Mapping

from core.exceptions import GenerationError

SOURCE = '_primary_mcu_active_options'
METHODS = frozenset({'arduino', 'cheetah', 'command', 'rpi_usb'})


def validate_mcu_connection_options(sections):
    """Check configured transport options, without inferring device identity."""
    for name, options in sections.items():
        if name != 'mcu' and not name.startswith('mcu '):
            continue
        serial = str(options.get('serial', ''))
        pipe_or_can = ('canbus_uuid' in options
                       or serial.startswith(('/tmp/klipper_host_', '/dev/rpmsg_')))
        if 'baud' in options:
            if pipe_or_can:
                raise GenerationError(f'[{name}] baud is not consumed for CAN or host/PRU pipes.')
            try:
                baud = int(str(options['baud']).strip())
            except (TypeError, ValueError, OverflowError):
                raise GenerationError(f'[{name}] baud must be an integer at least 2400.') from None
            if baud < 2400:
                raise GenerationError(f'[{name}] baud must be an integer at least 2400.')
        if 'restart_method' in options:
            _check(options['restart_method'], options)


def _check(method, connection):
    if not isinstance(method, str) or method not in METHODS:
        raise GenerationError(f'MCU restart: invalid restart_method {method!r}.')
    serial = str(connection.get('serial', ''))
    if 'canbus_uuid' in connection or serial.startswith(('/tmp/klipper_host_', '/dev/rpmsg_')):
        raise GenerationError('MCU restart: restart_method is not consumed for CAN or host/PRU pipes; review the selected connection.')


def selected_restart_method(board, endpoint):
    source = board.get(SOURCE, board.get('mcu', {}))
    if not isinstance(source, Mapping):
        raise GenerationError('MCU restart: malformed selected-board source; reload the board.')
    if 'restart_method' in source:
        method = source['restart_method']
        _check(method, source)
    else:
        # Preserve the existing LPC fallback only when no board policy exists.
        method = 'command' if any(mcu in str(endpoint).lower() for mcu in ('lpc1768', 'lpc1769')) else None
    if method is not None:
        _check(method, {'serial': endpoint})
    return method


def validate_primary_restart(sections, *, expected=None):
    actual = sections.get('mcu', {})
    if 'restart_method' in actual:
        _check(actual['restart_method'], actual)
    if expected is not None and actual.get('restart_method') != expected:
        raise GenerationError('MCU restart: selected-board restart_method is missing or changed; regenerate or resolve the include before deployment.')


def validate_source_restart(board, sections):
    endpoint = sections.get('mcu', {}).get('serial', '')
    expected = selected_restart_method(board, endpoint)
    validate_primary_restart(sections, expected=expected)
