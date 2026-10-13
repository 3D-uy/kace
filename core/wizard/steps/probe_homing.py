"""Review probe-based Z homing before preparing firmware or resuming generation."""
import copy
import os

from core.exceptions import GenerationError
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
    return {
        "stepper_z": {
            "endstop_pin": "probe:z_virtual_endstop",
            "position_min": draft["z_position_min"],
            "position_max": draft["z_position_max"],
        },
        section: {"z_offset": probe.resolved_offsets.z if probe.resolved_offsets.z is not None else 0},
    }


def validate_wizard_probe_homing_geometry(user_data):
    """Validate the generator's resolved Z range without prompts or mutations."""
    validate_probe_homing_geometry(_probe_homing_sections(user_data))


def review_probe_homing_geometry(user_data, *, force=False):
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

    while True:
        rail = sections["stepper_z"]
        offset = next(options["z_offset"] for name, options in sections.items() if name != "stepper_z")
        print("\n" + t("wizard.probe_homing.summary", minimum=rail["position_min"],
                         maximum=rail["position_max"], offset=offset))
        if not valid:
            print(t("wizard.probe_homing.invalid"))
        choices = []
        if valid:
            choices.append({"name": t("choice.continue"), "value": "continue"})
        choices.extend([
            {"name": t("wizard.probe_homing.edit"), "value": "edit"},
            {"name": t("wizard.probe_homing.cancel"), "value": "cancel"},
        ])
        action = numbered_select(t("wizard.profile_review_prompt"), choices=choices, require_explicit=True)
        if action == "continue" and valid:
            return True
        if action != "edit":
            return False
        value = simple_input(t("wizard.z_position_min"), default=str(rail["position_min"]),
                             validate=questionary_numeric_validator, back_value=_BACK)
        if value is None or str(value).strip().lower() in (_BACK, "<", "back", "volver"):
            return False
        staged = copy.deepcopy(user_data)
        staged["z_position_min"] = str(value).strip()
        mark_user_override(staged, "z_position_min")
        try:
            validate_wizard_probe_homing_geometry(staged)
        except GenerationError:
            print(t("wizard.probe_homing.invalid"))
            continue
        if yes_no(t("wizard.probe_homing.confirm", old=rail["position_min"], new=staged["z_position_min"]),
                  default=False):
            user_data.clear()
            user_data.update(staged)
            return True
