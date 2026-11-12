"""Homing configuration contracts: declared speeds and virtual-Z direction."""
import pytest

from core.exceptions import GenerationError
from core.homing_source import validate_safe_z_hop
from core.probe_configuration import validate_probe_homing_geometry


@pytest.mark.parametrize("option", ["speed", "z_hop_speed"])
@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf", "bad", None, True])
def test_safe_home_invalid_explicit_speed_rejects_even_when_hop_disabled(option, value):
    with pytest.raises(GenerationError, match=option):
        validate_safe_z_hop({"safe_z_home": {"z_hop": "0", option: value}})


@pytest.mark.parametrize("option", ["speed", "z_hop_speed"])
@pytest.mark.parametrize("value", ["0.001", "5", "50.125", "1e2"])
def test_safe_home_positive_finite_speed_preserves_compatible_values(option, value):
    validate_safe_z_hop({"safe_z_home": {"z_hop": "0", option: value}})


def test_safe_home_omissions_keep_pin_defaults_and_disabled_hop_needs_no_rail():
    validate_safe_z_hop({"safe_z_home": {}})
    validate_safe_z_hop({"safe_z_home": {"z_hop": "0"}})
    validate_safe_z_hop({"stepper_z": {"speed": "0"}})


def virtual(minimum="0", maximum="250", offset="0", direction=None):
    rail = {"endstop_pin": "probe:z_virtual_endstop", "position_min": minimum, "position_max": maximum}
    if direction is not None:
        rail["homing_positive_dir"] = direction
    return {"stepper_z": rail, "bltouch": {"z_offset": offset}}


@pytest.mark.parametrize("value", ["nope", "", "2", "nan"])
def test_virtual_z_invalid_boolean_rejects(value):
    with pytest.raises(GenerationError, match="homing_positive_dir"):
        validate_probe_homing_geometry(virtual(direction=value))


@pytest.mark.parametrize("offset,direction", [("0", "True"), ("250", "False")])
def test_virtual_z_direction_cannot_point_beyond_its_trigger_endpoint(offset, direction):
    with pytest.raises(GenerationError, match="homing_positive_dir"):
        validate_probe_homing_geometry(virtual(offset=offset, direction=direction))


@pytest.mark.parametrize("direction", [None, "True", "False"])
def test_virtual_z_middle_trigger_requires_explicit_direction_only_when_omitted(direction):
    cfg = virtual(offset="125", direction=direction)
    if direction is None:
        with pytest.raises(GenerationError, match="homing_positive_dir"):
            validate_probe_homing_geometry(cfg)
    else:
        validate_probe_homing_geometry(cfg)


@pytest.mark.parametrize("offset,direction", [("0", "False"), ("250", "True"), ("62.5", None), ("187.5", None)])
def test_virtual_z_compatible_endpoint_and_quarter_boundary_remain_valid(offset, direction):
    validate_probe_homing_geometry(virtual(offset=offset, direction=direction))


def test_virtual_z_interior_positive_direction_is_not_universally_forbidden():
    validate_probe_homing_geometry(virtual(minimum="-2", direction="True"))


def test_physical_z_and_probe_fragments_keep_existing_validator_scope():
    validate_probe_homing_geometry({"stepper_z": {"endstop_pin": "PA1", "homing_positive_dir": "nope"}})
    validate_probe_homing_geometry({"stepper_z": {"endstop_pin": "probe:z_virtual_endstop"}})


@pytest.mark.parametrize("direction", ["True", "False"])
@pytest.mark.parametrize("source", ["PROFILE", "USER_OVERRIDE"])
def test_wizard_preserves_explicit_virtual_z_direction_for_middle_trigger(direction, source):
    import copy
    from core.profile_values import mark_profile_values, mark_user_override
    from core.wizard.steps.probe_homing import _probe_homing_sections, validate_wizard_probe_homing_geometry
    from tests.unit.test_probe_homing_contract import wizard_probe_data

    user = wizard_probe_data(minimum="0", offset="175")
    if source == "PROFILE":
        user["_profile_parsed"]["stepper_z"]["homing_positive_dir"] = direction
        mark_profile_values(user, user["_profile_parsed"])
    else:
        user["homing_positive_dir_z"] = direction
        mark_user_override(user, "homing_positive_dir_z")
    original = copy.deepcopy(user)
    validate_wizard_probe_homing_geometry(user)
    assert _probe_homing_sections(user)["stepper_z"]["homing_positive_dir"] == direction
    assert user == original


def test_wizard_does_not_emit_cached_inferred_direction_for_virtual_z():
    from core.wizard.steps.probe_homing import _probe_homing_sections, validate_wizard_probe_homing_geometry
    from tests.unit.test_probe_homing_contract import wizard_probe_data

    user = wizard_probe_data(minimum="0", offset="175")
    user["homing_positive_dir_z"] = "False"
    user["_value_provenance"]["homing_positive_dir_z"] = "INFERRED"
    assert "homing_positive_dir" not in _probe_homing_sections(user)["stepper_z"]
    with pytest.raises(GenerationError, match="homing_positive_dir"):
        validate_wizard_probe_homing_geometry(user)

