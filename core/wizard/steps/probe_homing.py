"""Review probe-based Z homing before preparing firmware or resuming generation."""
import copy
import os
import shutil
import textwrap

from core.exceptions import GenerationError
from core.custom_probe import CustomProbeConfig, CustomProbeValidationError
from core.menu import numbered_select, simple_input, yes_no
from core.profile_values import ValueProvenance, mark_user_override, resolve_generation_values
from core.probe_configuration import (
    apply_probe_compatibility_context,
    apply_probe_homing_defaults,
    resolve_probe_configuration,
    validate_probe_homing_geometry,
)
from core.translations import t
from core.validators import questionary_numeric_validator
from core.wizard.runner import _BACK


def _probe_homing_sections(user_data):
    draft = copy.deepcopy(user_data)
    probe = resolve_probe_configuration(draft)
    if not probe.uses_virtual_z_endstop:
        return {}
    values, provenance = resolve_generation_values(
        draft.get("board_parsed") or {}, draft, validate_motors=False,
    )
    for key in ("z_position_min", "z_position_max"):
        if key not in values or provenance.get(key) == ValueProvenance.UNRESOLVED.value:
            raise GenerationError(f"{key} is unresolved; review the explicit value.")
    draft.update(values)
    apply_probe_compatibility_context(draft, probe)
    apply_probe_homing_defaults(draft, provenance)
    # Structured probes currently render the pre-calibration offset 0. Custom
    # probes expose the offset parsed from their authoritative raw section.
    section = probe.structured_section_name or "probe"
    rail = {
        "endstop_pin": "probe:z_virtual_endstop",
        "position_min": draft["z_position_min"],
        "position_max": draft["z_position_max"],
    }
    # Match the template: inferred directions remain omitted for Klipper to
    # resolve from the probe trigger, while explicit directions are emitted.
    if (draft.get("homing_positive_dir_z")
            and provenance.get("homing_positive_dir_z") != ValueProvenance.INFERRED.value):
        rail["homing_positive_dir"] = draft["homing_positive_dir_z"]
    return {
        "stepper_z": rail,
        section: {"z_offset": probe.resolved_offsets.z if probe.resolved_offsets.z is not None else 0},
    }


def validate_wizard_probe_homing_geometry(user_data):
    """Validate the generator's resolved Z range without prompts or mutations."""
    validate_probe_homing_geometry(_probe_homing_sections(user_data))


def probe_homing_review_required(user_data):
    """Show the wizard's range panel only when its effective values need review."""
    try:
        validate_wizard_probe_homing_geometry(user_data)
    except GenerationError:
        return True
    return False


def _staged_minimum(user_data, value):
    staged = copy.deepcopy(user_data)
    staged["z_position_min"] = str(value).strip()
    mark_user_override(staged, "z_position_min")
    validate_wizard_probe_homing_geometry(staged)
    return staged


def review_probe_homing_geometry(user_data, *, force=False, back_label=None):
    """Return False on cancellation; publish only an explicitly confirmed edit."""
    sections = _probe_homing_sections(user_data)
    if not sections:
        return True
    try:
        validate_probe_homing_geometry(sections)
        valid = True
    except GenerationError:
        valid = False
    if valid and not force:
        return True
    if os.environ.get("KACE_AUTO") == "1":
        validate_probe_homing_geometry(sections)
        raise GenerationError(t("wizard.probe_homing.manual"))

    rail = sections["stepper_z"]
    offset = next(options["z_offset"] for name, options in sections.items() if name != "stepper_z")
    preparation = None
    if not valid and float(offset) == 0:
        try:
            preparation = _staged_minimum(user_data, "0")
        except GenerationError:
            pass
    rejected_value = None
    custom_probe = user_data.get("custom_probe")
    settings = user_data.get("custom_probe_settings")
    settings_offset = (settings.get("z_offset", "supplied") if isinstance(settings, dict)
                       else getattr(settings, "z_offset", "supplied"))
    provisional = float(offset) == 0 and (not isinstance(custom_probe, CustomProbeConfig)
                                          or settings_offset is None)
    # Only the guided optional value (also retained in checkpoints) proves that
    # calibration was deferred. A supplied/imported numeric zero does not.
    deferred = provisional and isinstance(custom_probe, CustomProbeConfig) and settings_offset is None
    # The deferred decision is already made. Ask only for the physical limit
    # change, without an intervening menu that asks the user to choose it again.
    direct_review = deferred and preparation is not None and not force
    if direct_review:
        width = max(20, shutil.get_terminal_size(fallback=(80, 24)).columns - 2)
        print("\n" + textwrap.fill(t("wizard.probe_z.deferred_context"), width=width))
        if yes_no(t("wizard.probe_z.confirm_deferred_minimum",
                    old=rail["position_min"], new=preparation["z_position_min"]), default=False):
            user_data.clear()
            user_data.update(preparation)
            return True
    while True:
        width = max(20, shutil.get_terminal_size(fallback=(80, 24)).columns - 2)
        if deferred and not direct_review:
            print("\n" + textwrap.fill(t("wizard.probe_z.deferred_title"), width=width))
        summary = t("wizard.review_z.summary", minimum=rail["position_min"],
                    maximum=rail["position_max"], offset=offset)
        if not direct_review:
            print("\n" + textwrap.fill(summary, width=width))
        if deferred and not direct_review:
            print("\n" + textwrap.fill(t("wizard.probe_z.deferred_context"), width=width) + "\n")
        elif not deferred:
            print(textwrap.fill(t("wizard.probe_z.definition"), width=width))
        if provisional and not deferred:
            print(textwrap.fill(t("wizard.probe_z.calibration_later"), width=width))
        if (not valid and not direct_review) or rejected_value is not None:
            message = t("wizard.review_z.zero_conflict", minimum=rail["position_min"])
            if preparation is None:
                message = t("wizard.review_z.range", minimum=(rejected_value if rejected_value is not None
                                                              else rail["position_min"]),
                            maximum=rail["position_max"], offset=offset)
            if deferred:
                message = ("" if valid else t(
                    "wizard.probe_z.deferred_minimum" if preparation is not None
                    else "wizard.probe_z.deferred_range",
                    minimum=rail["position_min"], maximum=rail["position_max"]))
            if rejected_value is not None:
                message = (t("wizard.review_z.rejected", value=rejected_value) + " " + message).strip()
            print(textwrap.fill(message, width=width))
        choices = []
        if valid:
            choices.append({"name": t("choice.continue"), "value": "continue"})
        if not deferred and isinstance(custom_probe, CustomProbeConfig) and custom_probe.z_offset is not None:
            choices.append({"name": t("wizard.probe_z.known"), "value": "offset"})
        if preparation is not None and not direct_review:
            label = ("wizard.probe_z.review_minimum" if deferred else
                     "wizard.probe_z.prepare_later" if provisional else "wizard.review_z.prepare_zero")
            choices.append({"name": t(label), "value": "prepare_zero"})
        choices.append({"name": t("wizard.probe_z.edit_minimum" if deferred else
                                  "wizard.probe_z.mechanical_minimum"), "value": "edit"})
        choices.append({"name": back_label or t("wizard.probe_z.back_review"), "value": "cancel"})
        action = numbered_select(t("wizard.probe_z.minimum_prompt" if deferred else
                                   "wizard.profile_review_prompt"), choices=choices, require_explicit=True)
        if action == "continue" and valid:
            return True
        if action == "offset" and not deferred:
            # Reuse the same typed/raw editor as the probe review. A cancelled or
            # incompatible edit never changes the accepted probe or its limits.
            from core.wizard.steps.sensors import _stage_known_custom_probe_offset
            value = simple_input(t("wizard.probe_z.known_input"),
                                 validate=questionary_numeric_validator, back_value=_BACK)
            if value is None or value == _BACK:
                continue
            try:
                staged = _stage_known_custom_probe_offset(user_data, value)
                validate_wizard_probe_homing_geometry(staged)
            except (GenerationError, CustomProbeValidationError):
                print(textwrap.fill(t("wizard.probe_z.offset_rejected", value=value,
                                      minimum=rail["position_min"], maximum=rail["position_max"]),
                                    width=width))
                continue
            if yes_no(t("wizard.probe_z.confirm_offset", old=offset, new=value), default=False):
                user_data.clear()
                user_data.update(staged)
                return True
            continue
        if action not in ("edit", "prepare_zero"):
            return False
        if action == "prepare_zero":
            if preparation is None:
                continue
            staged = copy.deepcopy(preparation)
        else:
            default = None
            if preparation is not None:
                default = "0"
            elif valid:
                default = str(rail["position_min"])
            value = simple_input(t("wizard.probe_homing.minimum_input"), default=default,
                                 validate=questionary_numeric_validator, back_value=_BACK)
            if value is None or str(value).strip().lower() in (_BACK, "<", "back", "volver"):
                return False
            try:
                staged = _staged_minimum(user_data, value)
            except GenerationError:
                rejected_value = str(value).strip()
                continue
        # A range compatible with a placeholder does not calibrate the probe or
        # certify its mechanical clearance. The user confirms the limit change.
        print("\n" + textwrap.fill(t("wizard.review_z.clearance"), width=width) + "\n")
        if yes_no(t("wizard.review_z.confirm", old=rail["position_min"], new=staged["z_position_min"]),
                  default=False):
            user_data.clear()
            user_data.update(staged)
            return True
