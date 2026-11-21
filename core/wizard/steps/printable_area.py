"""Explicit printable-area review; travel does not establish physical bed size."""
import copy
import math
import os

from core.exceptions import GenerationError, WizardExit
from core.menu import numbered_select, simple_input, _wrapped_prompt_lines
from core.motion_model import (
    PRINTABLE_XY_KEYS, PrintableGeometryError, confirm_printable_xy,
    printable_xy_confirmation_matches, resolve_printable_xy,
)
from core.nozzle_bed_visualizer import print_nozzle_bed_preview
from core.profile_values import mark_user_override
from core.translations import t
from core.validators import questionary_numeric_validator
from core.wizard.runner import _BACK, _QUIT
from core.wizard.ui import _back_choice, _quit_choice


def _bounds(data):
    axes = {}
    try:
        for axis in ('x', 'y'):
            if any(isinstance(data.get(key), bool) for key in (
                    f'{axis}_position_min', f'{axis}_position_max', f'{axis}_size',
                    f'printable_{axis}_min', f'printable_{axis}_max')):
                raise ValueError('boolean geometry')
            low = float(data[f'{axis}_position_min'])
            high = float(data[f'{axis}_position_max'])
            nominal = float(data.get(f'{axis}_size', high))
            if not all(math.isfinite(v) for v in (low, high, nominal)) or low >= high:
                raise ValueError('invalid travel')
            axes[axis] = nominal, low, high
        bounds, _ = resolve_printable_xy(data, axes)
        for axis, (_, low, high) in axes.items():
            if not low <= bounds[f'printable_{axis}_min'] < bounds[f'printable_{axis}_max'] <= high:
                raise ValueError('printable bounds exceed configured travel')
        return {key: str(value).removesuffix('.0') for key, value in bounds.items()}
    except (KeyError, TypeError, ValueError, OverflowError, PrintableGeometryError) as exc:
        raise GenerationError(t('geometry.invalid')) from exc


def frozen_printable_geometry(path, content):
    """Review the rectangle in the provenance bound to these specific CFG bytes."""
    from core.config_geometry import load_geometry_context
    from core.pin_validator import _read_pin_config
    context = load_geometry_context(path, content)
    if context is None:
        raise GenerationError("Generated printable geometry is missing; start a new installation or configuration.")
    sections, _ = _read_pin_config(content.decode("utf-8"))
    review = {}
    for axis in ("x", "y"):
        options = sections.get(f"stepper_{axis}", {})
        for bound in ("min", "max"):
            review[f"printable_{axis}_{bound}"] = getattr(context, f"printable_{axis}_{bound}")
            review[f"{axis}_position_{bound}"] = options.get(f"position_{bound}", 0 if bound == "min" else None)
        review[f"{axis}_position_endstop"] = options.get("position_endstop")
    return review


def _step_printable_area(user_data, *, allow_edit=True):
    staged = copy.deepcopy(user_data)
    if os.environ.get('KACE_AUTO') == '1':
        if printable_xy_confirmation_matches(staged):
            _bounds(staged)
            return 'confirmed'
        raise GenerationError('Automatic mode requires explicit printable XY confirmation.')
    while True:
        explanation = 'geometry.explanation' if allow_edit else 'geometry.fixed_artifact'
        for line in _wrapped_prompt_lines(t(explanation)):
            print('  ' + line)
        try:
            bounds = _bounds(staged)
        except GenerationError as exc:
            if not allow_edit:
                raise
            bounds = None
            print('  ' + str(exc))
        preview = dict(staged)
        if bounds:
            preview.update(bounds)
        print_nozzle_bed_preview(preview)
        if not allow_edit and bounds:
            for axis in ('x', 'y'):
                exact = t('geometry.fixed_bounds', axis=axis.upper(),
                          low=bounds[f'printable_{axis}_min'], high=bounds[f'printable_{axis}_max'])
                for line in _wrapped_prompt_lines(exact):
                    print('  ' + line)
        choices = []
        if bounds:
            choices.append({'name': t('geometry.confirm_action'), 'value': 'confirm'})
        if allow_edit:
            choices.append({'name': t('geometry.edit_action'), 'value': 'edit'})
        choices.extend([_back_choice(), _quit_choice()])
        prompt = 'geometry.choose' if allow_edit else 'geometry.fixed_choose'
        answer = numbered_select(t(prompt), choices=choices, require_explicit=True)
        if answer in (None, _QUIT):
            raise WizardExit()
        if answer == _BACK:
            return _BACK
        if answer == 'confirm' and bounds:
            staged.update(bounds)
            mark_user_override(staged, *PRINTABLE_XY_KEYS)
            confirm_printable_xy(staged)
            user_data.clear()
            user_data.update(staged)
            return 'confirmed'
        if answer != 'edit' or not allow_edit:
            continue
        updates = {}
        for key in PRINTABLE_XY_KEYS:
            axis, bound = key.split('_')[1:]
            try:
                fallback = max(float(staged.get(f'{axis}_position_min', 0)), 0) if bound == 'min' else staged.get(f'{axis}_size', '')
            except (TypeError, ValueError, OverflowError):
                fallback = ''
            current = (bounds or {}).get(key, staged.get(key, fallback))
            value = simple_input(
                t('profile.printable_bound_prompt', field=t(f'profile.printable_{bound}', axis=axis.upper())),
                default=str(current), validate=questionary_numeric_validator, back_value=_BACK)
            if value is None:
                raise WizardExit()
            if value == _BACK:
                break
            updates[key] = value.strip() or str(current)
        if len(updates) != 4:
            continue
        candidate = copy.deepcopy(staged)
        candidate.update(updates)
        mark_user_override(candidate, *updates)
        try:
            _bounds(candidate)
        except GenerationError as exc:
            print('  ' + str(exc))
            continue
        staged = candidate
