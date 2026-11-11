"""Boundary for source G28 procedures that KACE cannot yet migrate safely.

This is not print-strategy migration or a validator for arbitrary user macros.
Active source homing overrides need a reviewed equivalent before generation or
source-bound publication can claim the selected hardware is available.
"""
from core.exceptions import GenerationError
import math


SOURCE = '_homing_override_active'
ADDITIONAL_Z_ENDSTOPS = '_additional_z_endstop_source'
SAFE_Z_HOP_SOURCE = '_safe_z_hop_source'


def _z_hop_number(value):
    try:
        hop = float(value)
        if not math.isfinite(hop) or hop < 0:
            raise ValueError()
        return hop
    except (TypeError, ValueError) as exc:
        raise GenerationError('[safe_z_home] z_hop must be a finite, non-negative value.') from exc


def validate_safe_z_hop(sections):
    """Validate the absolute lift target used by Klipper before/after Z homing.

    With an unhomed Z, Klipper first assigns coordinate zero and moves to
    z_hop. With a homed Z below the target it moves to that same coordinate.
    This checks configured limits, not clearance from an unknown physical start.
    """
    if 'safe_z_home' not in sections:
        return
    # The pinned SafeZHoming constructor reads both speeds even with z_hop=0.
    # Omitted options retain Klipper's defaults; finiteness is KACE preflight.
    for option in ('speed', 'z_hop_speed'):
        if option not in sections['safe_z_home']:
            continue
        try:
            value = float(str(sections['safe_z_home'][option]).strip())
        except (TypeError, ValueError):
            raise GenerationError(f'[safe_z_home] {option} must be finite and greater than zero.') from None
        if not math.isfinite(value) or value <= 0:
            raise GenerationError(f'[safe_z_home] {option} must be finite and greater than zero.')
    hop = _z_hop_number(sections['safe_z_home'].get('z_hop', 0))
    if hop == 0:
        return  # Explicitly disabled; no lift target is commanded.
    rail = sections.get('stepper_z', {})
    try:
        minimum, maximum = float(rail.get('position_min', 0)), float(rail['position_max'])
        if not (math.isfinite(minimum) and math.isfinite(maximum)
                and minimum < maximum and minimum <= hop <= maximum):
            raise ValueError()
    except (KeyError, TypeError, ValueError) as exc:
        raise GenerationError(
            f'[safe_z_home] z_hop ({hop:g}) must be within the finite [stepper_z] '
            f'position_min/position_max range [{rail.get("position_min", 0)}, '
            f'{rail.get("position_max", "missing")}]. Review the Z limits or explicitly select a valid hop.'
        ) from exc


def _safe_z_hop_options(parsed):
    if parsed is None:
        return {}
    if not isinstance(parsed, dict) or not isinstance(parsed.get('safe_z_home', {}), dict):
        raise GenerationError('[safe_z_home] z_hop source is malformed; reload it.')
    options = parsed.get('safe_z_home', {})
    if SAFE_Z_HOP_SOURCE in parsed:
        captured = parsed[SAFE_Z_HOP_SOURCE]
        if not isinstance(captured, dict) or set(captured) - {'z_hop'}:
            raise GenerationError('[safe_z_home] z_hop activity evidence is malformed; reload it.')
        if any(key not in options or _z_hop_number(options[key]) != _z_hop_number(value)
               for key, value in captured.items()):
            raise GenerationError('[safe_z_home] z_hop changed after activity capture; reload it.')
        options = captured
    return {key: options[key] for key in ('z_hop',) if key in options}


def _selected_safe_z_hop_options(parsed, raw, label):
    if isinstance(raw, str) and raw.strip():
        from core.scraper import parse_config
        active = _safe_z_hop_options(parse_config(raw))
        if isinstance(parsed, dict):
            if SAFE_Z_HOP_SOURCE in parsed:
                captured = _safe_z_hop_options(parsed)
                mismatch = ({key: _z_hop_number(value) for key, value in captured.items()}
                            != {key: _z_hop_number(value) for key, value in active.items()})
            else:
                # Old discovery maps included comments. Only active raw values
                # require agreement; commented examples never become policy.
                options = parsed.get('safe_z_home', {})
                mismatch = not isinstance(options, dict) or any(
                    key not in options or _z_hop_number(options[key]) != _z_hop_number(value)
                    for key, value in active.items())
            if mismatch:
                raise GenerationError(f'[safe_z_home] z_hop {label} differs from its saved text; reload it.')
        elif parsed is not None:
            raise GenerationError(f'[safe_z_home] z_hop {label} is malformed; reload it.')
        return active
    return _safe_z_hop_options(parsed)


def resolve_safe_z_hop(parsed, user):
    """Preserve active source/selected hop; keep KACE's historical 10mm default."""
    sources = []
    for config, raw, label in ((parsed, user.get('board_raw_config'), 'board'),
                              (user.get('_profile_parsed'), user.get('raw_config'), 'profile')):
        options = _selected_safe_z_hop_options(config, raw, label)
        if 'z_hop' in options:
            sources.append(_z_hop_number(options['z_hop']))
    if 'safe_z_home_z_hop' in user:
        hop = _z_hop_number(user['safe_z_home_z_hop'])
    else:
        if len(set(sources)) > 1:
            raise GenerationError('[safe_z_home] z_hop differs between board and profile; select an explicit value.')
        hop = sources[0] if sources else 10.0
    validate_safe_z_hop({
        'safe_z_home': {'z_hop': hop},
        'stepper_z': {'position_min': user.get('z_position_min', 0),
                      'position_max': user.get('z_position_max', user.get('z_size'))},
    })
    return f'{hop:g}'


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
