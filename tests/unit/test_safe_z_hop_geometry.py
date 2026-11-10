"""GEO-04: safe-Z hop is a coordinate target, not merely a travel distance."""
import copy

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from core.pin_validator import _read_pin_config
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_effective_xy_geometry import _generate, _context, _destination
from tests.unit.test_generator import _parsed, _user


@pytest.mark.parametrize("hop", ["10", "-1", "nan", "inf"])
def test_bad_effective_hop_blocks_even_when_rail_span_is_sufficient(tmp_path, hop):
    content = _generate(tmp_path)
    context = _context(tmp_path, content)
    remote = _destination(content,
        "[stepper_z]\nposition_min: -20\nposition_max: 5\n"
        f"[safe_z_home]\nz_hop: {hop}\n")
    original = copy.deepcopy(remote)
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    result = validate_configuration_plan(plan)
    assert any(e.code == "safe-z-hop" for e in result.errors)
    transport = FakeTransport(remote)
    transaction = ConfigDeploymentTransaction(
        transport, content, None, geometry_context=context, activation="firmware",
        snapshot_root=str(tmp_path / "snapshots"), confirm=lambda _: pytest.fail("Invalid hop cannot be approved"),
    ).run()
    assert transaction.state is not ConfigTransactionState.COMMITTED
    assert not any(call[0] in ("upload", "restart") for call in transport.calls)
    assert transport.files == original


@pytest.mark.parametrize("minimum,maximum,hop", [
    ("-20", "5", "0"), ("-20", "5", "5"), ("0", "10", "10"),
    ("0", "10.001", "10"), ("0", "9.999", "9.999"),
])
def test_compatible_effective_hop_remains_valid(tmp_path, minimum, maximum, hop):
    content = _generate(tmp_path)
    plan = build_managed_config_plan(content, None, _destination(content,
        f"[stepper_z]\nposition_min: {minimum}\nposition_max: {maximum}\n"
        f"[safe_z_home]\nz_hop: {hop}\n"), geometry_context=_context(tmp_path, content))
    assert validate_configuration_plan(plan).valid


def test_generation_rejects_default_ten_when_z_max_is_five(tmp_path):
    with pytest.raises(GenerationError, match="z_hop"):
        _generate(tmp_path, z_size="5", z_position_max="5")
    assert not (tmp_path / "printer.cfg").exists()
    assert not (tmp_path / "printer.cfg.provenance.json").exists()


@pytest.mark.parametrize("source", ["user", "board", "profile"])
@pytest.mark.parametrize("hop", ["0", "5", "10"])
def test_explicit_hop_survives_generation_and_saved_inputs(tmp_path, source, hop):
    parsed = _parsed(bltouch={"sensor_pin": "^PB8", "control_pin": "PB9"})
    # The small pre-calibration rail [-2, 5] puts the zero trigger outside
    # Klipper's inference quarters. Keep this hop-preservation fixture valid
    # with an explicit direction, without changing its hop or travel limits.
    user = _user(probe="BLTouch", z_size="5" if float(hop) <= 5 else "250",
                 homing_positive_dir_z="False")
    if source == "user":
        user["safe_z_home_z_hop"] = hop
    elif source == "board":
        parsed["safe_z_home"] = {"home_xy_position": "117.5,117.5", "z_hop": hop}
    else:
        user["_profile_parsed"] = {"safe_z_home": {"z_hop": hop}}
    from core.firmware_workflow import persistable_wizard_data
    restored = persistable_wizard_data(user)
    for name, inputs in (("initial", user), ("restored", restored)):
        result = generate_config(parsed, inputs, output_path=str(tmp_path / (name + ".cfg")), verbose=False)
        assert float(_read_pin_config(result["content"])[0]["safe_z_home"]["z_hop"]) == float(hop)


@pytest.mark.parametrize("hop", ["-1", "nan", "inf", "251", ""])
def test_invalid_selected_hop_cannot_be_silently_replaced(tmp_path, hop):
    with pytest.raises(GenerationError, match="z_hop"):
        _generate(tmp_path, safe_z_home_z_hop=hop)


def test_disagreeing_source_hops_require_explicit_selection(tmp_path):
    parsed = _parsed(bltouch={"sensor_pin": "^PB8", "control_pin": "PB9"},
                     safe_z_home={"z_hop": "5"})
    user = _user(probe="BLTouch", _profile_parsed={"safe_z_home": {"z_hop": "10"}})
    with pytest.raises(GenerationError, match="z_hop"):
        generate_config(parsed, user, output_path=str(tmp_path / "printer.cfg"), verbose=False)
    user["safe_z_home_z_hop"] = "0"
    result = generate_config(parsed, user, output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert _read_pin_config(result["content"])[0]["safe_z_home"]["z_hop"] == "0"


@pytest.mark.parametrize("minimum,maximum,hop,valid", [
    (2, 20, 1, False), (2, 20, 0, True), (-20, 5, 10, False),
    (-20, 5, 5, True), (0, 10, None, True),
])
def test_lift_target_semantics_for_physical_z(minimum, maximum, hop, valid):
    from core.homing_source import validate_safe_z_hop
    sections = {"stepper_z": {"position_min": minimum, "position_max": maximum, "endstop_pin": "PA1"},
                "safe_z_home": {} if hop is None else {"z_hop": hop}}
    if valid:
        validate_safe_z_hop(sections)
    else:
        with pytest.raises(GenerationError, match="z_hop"):
            validate_safe_z_hop(sections)


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
def test_hop_diagnostic_keeps_value_and_range_in_normal_review(tmp_path, language):
    from core.configuration_review import build_configuration_review, render_configuration_review
    content = _generate(tmp_path)
    plan = build_managed_config_plan(content, None, _destination(content,
        "[stepper_z]\nposition_max: 5\n[safe_z_home]\nz_hop: 10\n"),
        geometry_context=_context(tmp_path, content))
    rendered = render_configuration_review(build_configuration_review(plan), language=language)
    assert "z_hop (10)" in rendered
    assert "position_max" in rendered


def test_small_physical_z_without_safe_home_keeps_working(tmp_path):
    result = generate_config(_parsed(), _user(z_size="5"), output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert "safe_z_home" not in _read_pin_config(result["content"])[0]


@pytest.mark.parametrize("raw", [
    "# [safe_z_home]\n# z_hop: 0\n",
    "[safe_z_home]\nhome_xy_position: 100,100\n# z_hop: 0\n",
    "# [safe_z_home]\n# z_hop: nan\n",
])
def test_commented_hop_never_becomes_a_selected_clearance(tmp_path, raw):
    from core.scraper import parse_config
    parsed = _parsed(bltouch={"sensor_pin": "^PB8", "control_pin": "PB9"})
    discovery = parse_config(raw, keep_comments=True)
    parsed.update({key: value for key, value in discovery.items()
                   if key == "safe_z_home" or key.startswith("_safe_z_hop")})
    result = generate_config(parsed, _user(probe="BLTouch"),
                             output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert _read_pin_config(result["content"])[0]["safe_z_home"]["z_hop"] == "10"


def test_saved_active_raw_profile_zero_hop_is_recovered_without_parsed_cache(tmp_path):
    from core.firmware_workflow import persistable_wizard_data, restore_wizard_data
    user = _user(probe="BLTouch", raw_config="[safe_z_home]\nz_hop: 0\n")
    restored = restore_wizard_data(persistable_wizard_data(user))
    result = generate_config(_parsed(bltouch={"sensor_pin": "^PB8", "control_pin": "PB9"}),
                             restored, output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert _read_pin_config(result["content"])[0]["safe_z_home"]["z_hop"] == "0"


@pytest.mark.parametrize("source", ["board", "profile"])
@pytest.mark.parametrize("explicit_override", [False, True])
def test_changed_legacy_hop_source_requires_reload_even_with_override(source, explicit_override):
    from core.homing_source import resolve_safe_z_hop
    parsed, user = {}, {"z_position_min": 0, "z_position_max": 250}
    legacy = {"safe_z_home": {"z_hop": "5"}}
    raw = "[safe_z_home]\nz_hop: 0\n"
    if source == "board":
        parsed, user["board_raw_config"] = legacy, raw
    else:
        user.update(_profile_parsed=legacy, raw_config=raw)
    if explicit_override:
        user["safe_z_home_z_hop"] = "0"
    with pytest.raises(GenerationError, match="z_hop.*reload"):
        resolve_safe_z_hop(parsed, user)


@pytest.mark.parametrize("source", ["board", "profile"])
def test_legacy_commented_cache_uses_active_raw_authority(source):
    from core.homing_source import resolve_safe_z_hop
    parsed, user = {}, {"z_position_min": 0, "z_position_max": 250}
    legacy = {"safe_z_home": {"z_hop": "0"}}
    raw = "# [safe_z_home]\n# z_hop: 0\n"
    if source == "board":
        parsed, user["board_raw_config"] = legacy, raw
    else:
        user.update(_profile_parsed=legacy, raw_config=raw)
    assert resolve_safe_z_hop(parsed, user) == "10"


def test_active_raw_hop_conflict_requires_selection_and_explicit_zero_wins():
    from core.homing_source import resolve_safe_z_hop
    board = {"safe_z_home": {"z_hop": "5"}}
    user = {"z_position_min": 0, "z_position_max": 250,
            "board_raw_config": "[safe_z_home]\nz_hop: 5\n",
            "raw_config": "[safe_z_home]\nz_hop: 0\n"}
    with pytest.raises(GenerationError, match="z_hop.*differs"):
        resolve_safe_z_hop(board, user)
    user["safe_z_home_z_hop"] = "0"
    assert resolve_safe_z_hop(board, user) == "0"
