"""Boundary for source G28 procedures that KACE cannot yet migrate safely.

This is not print-strategy migration or a validator for arbitrary user macros.
Active source homing overrides need a reviewed equivalent before generation or
source-bound publication can claim the selected hardware is available.
"""
from core.exceptions import GenerationError


SOURCE = '_homing_override_active'
ADDITIONAL_Z_ENDSTOPS = '_additional_z_endstop_source'


def additional_z_endstops(parsed):
    """Read active, board-owned optional inputs for the supported extra Z motors."""
    if not isinstance(parsed, dict):
        return {}
    captured = parsed.get(ADDITIONAL_Z_ENDSTOPS)
    if captured is not None and not isinstance(captured, dict):
        raise GenerationError('Additional Z endstop source is malformed; reload the board.')
    result = {}
    for index in range(1, 4):
        name = f'stepper_z{index}'
        options = parsed.get(name, {})
        value = options.get('endstop_pin') if isinstance(options, dict) else None
        if captured is not None:
            expected = captured.get(name)
            if expected is None:
                continue  # A discovery comment is not an active homing input.
            if value != expected:
                raise GenerationError(f'[{name}] endstop_pin differs from its active source; reload the board.')
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                raise GenerationError(f'[{name}] endstop_pin must not be empty.')
            result[name] = value
    return result


def validate_additional_z_endstops(source, sections, *, z_count=None):
    """Preserve selected independent inputs, including in unfinished publication.

    An omitted optional input intentionally shares the primary rail endstop in
    Klipper. Unselected motors are not required; no new homing strategy is chosen.
    """
    from core.pin_validator import PinAliases, PinAliasError
    from core.probe_configuration import is_probe_virtual_endstop
    for index in range(1, 4):
        name = f'stepper_z{index}'
        if (is_probe_virtual_endstop(sections.get(name, {}).get('endstop_pin', ''))
                and not any(provider in sections for provider in ('probe', 'bltouch'))):
            raise GenerationError(f'[{name}] probe:z_virtual_endstop requires a configured probe.')
    expected = additional_z_endstops(source)
    if not expected:
        return
    try:
        before, after = PinAliases(source), PinAliases(sections)
        def identity(aliases, value):
            if not isinstance(value, str) or not value.strip():
                return None
            token = value.strip()
            prefix = token[:len(token) - len(token.lstrip('^~!'))]
            return aliases.resolve(token), '!' in prefix, '^' in prefix, '~' in prefix
        for name, value in expected.items():
            selected = name in sections if z_count is None else int(name[-1]) < z_count
            if selected and identity(before, value) != identity(after, sections.get(name, {}).get('endstop_pin')):
                raise GenerationError(f'[{name}] endstop_pin is missing or changed from the selected board; '
                                      'reload the board and regenerate before deployment.')
    except PinAliasError as exc:
        raise GenerationError(f'Additional Z endstop: {exc}') from exc


def validate_homing_composition(sections):
    if 'homing_override' in sections and 'safe_z_home' in sections:
        raise GenerationError('[homing_override] and [safe_z_home] cannot be used simultaneously in Klipper.')


def require_supported_source_homing(parsed):
    if not isinstance(parsed, dict):
        return
    activity = parsed.get(SOURCE)
    if 'homing_override' not in parsed and activity is None:
        return
    if activity is False:
        return  # Proven commented discovery example.
    if activity is not True:
        raise GenerationError('[homing_override] source activity is unavailable; reload the selected source.')
    raise GenerationError(
        'The selected source requires [homing_override]. KACE cannot yet migrate or verify '
        'this G28 procedure against the configured hardware; generation/publication is blocked. '
        'A reviewed homing equivalent is required; ordinary G28 or safe_z_home is not assumed equivalent.'
    )


def _check_selection(data, parsed_key, raw_key):
    parsed, raw = data.get(parsed_key), data.get(raw_key)
    if isinstance(raw, str) and raw.strip():
        from core.scraper import parse_config
        authoritative = parse_config(raw, keep_comments=True)
        require_supported_source_homing(authoritative)
        if (isinstance(parsed, dict) and 'homing_override' in parsed and SOURCE not in parsed
                and authoritative.get(SOURCE) is False):
            # Old UI maps included commented examples. Only actual saved text,
            # not a missing section or a profile_loaded flag, recovers activity.
            return
    require_supported_source_homing(parsed)


def require_supported_homing_context(user_data, saved=None):
    """Check both board and separate profile without importing either's G-code.

    Saved obligations cannot disappear by replacing just a live flag/map. Raw
    source is also checked so an old parser's incomplete G-code does not bypass
    this boundary. Generic APIs without selected sources remain source-agnostic.
    """
    if saved is None:
        checkpoint = user_data.get('workflow_checkpoint')
        saved = checkpoint.get('wizard_data', {}) if isinstance(checkpoint, dict) else {}
    for data in (saved, user_data):
        if not isinstance(data, dict):
            continue
        _check_selection(data, 'board_parsed', 'board_raw_config')
        _check_selection(data, '_profile_parsed', 'raw_config')
