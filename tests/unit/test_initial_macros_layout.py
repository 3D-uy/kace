"""Initial install layout, include precedence and ownership on repeated plans."""
import copy

import pytest

from core.managed_config import (
    HARDWARE_REMOTE, MACROS_REMOTE, ROOT_MACROS_REMOTE, ROOT_MACROS_MARKER,
    MANAGED_BEGIN, MANAGED_END, build_managed_config_plan, effective_hardware_text,
)
from core.translations import translate_comment
from core.config_transaction import read_config_state
from core.configuration_review import validate_configuration_plan, build_configuration_review
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_root_include_placement import generated
from tests.unit.test_configuration_review import _hardware


MACROS = b"[gcode_macro START_PRINT]\ngcode: M117 Ready\n"


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("layout", ["new", "placeholder", "old-managed"])
def test_initial_macros_sit_beside_root_and_include_precedes_hardware(language, newline, layout):
    root = None
    remote = {"printer.cfg": root, "mainsail.cfg": b""}
    if layout == "placeholder":
        remote["printer.cfg"] = b"[printer]\nkinematics: none\n"
    elif layout == "old-managed":
        remote["printer.cfg"] = (
            "# KACE layout: root-v1\n" + MANAGED_BEGIN + "\n[mcu]\nserial: old\n"
            f"[include {MACROS_REMOTE}]\n" + MANAGED_END + "\n"
        ).encode()
        remote[MACROS_REMOTE] = MACROS
    before = copy.deepcopy(remote)
    hardware = generated(language, newline)
    plan = build_managed_config_plan(hardware, MACROS, remote)
    files = {a.remote_name: a.content for a in plan.artifacts}
    assert set(files) == {"printer.cfg", ROOT_MACROS_REMOTE}
    assert files[ROOT_MACROS_REMOTE] == ROOT_MACROS_MARKER + MACROS
    text = files["printer.cfg"].decode()
    includes = "# " + translate_comment("Includes", language)
    assert text.count("[include macros.cfg]") == 1
    assert text.index(includes) < text.index("[include mainsail.cfg]")
    assert text.index("[include mainsail.cfg]") < text.index("[include macros.cfg]") < text.index("[mcu]")
    assert "generated-macros.cfg" not in text
    assert "[gcode_macro START_PRINT]" in effective_hardware_text(plan)
    remote.update(files)
    retry = build_managed_config_plan(hardware, MACROS, remote)
    assert not retry.changed_artifacts
    assert (MACROS_REMOTE not in before or remote[MACROS_REMOTE] == before[MACROS_REMOTE])


def test_owned_root_macros_can_be_updated_or_deselected_without_deleting_file():
    hardware = generated("English", "\n")
    initial = build_managed_config_plan(hardware, MACROS, {"mainsail.cfg": b""})
    remote = {"mainsail.cfg": b"", **{a.remote_name: a.content for a in initial.artifacts}}
    changed = build_managed_config_plan(hardware, MACROS + b"# updated\n", remote)
    assert next(a for a in changed.changed_artifacts if a.remote_name == ROOT_MACROS_REMOTE)
    disabled = build_managed_config_plan(hardware, None, remote)
    assert disabled.remote_names == ("printer.cfg",)
    assert b"[include macros.cfg]" not in disabled.artifacts[0].content
    assert remote[ROOT_MACROS_REMOTE] == ROOT_MACROS_MARKER + MACROS
    remote.update({a.remote_name: a.content for a in disabled.artifacts})
    enabled = build_managed_config_plan(hardware, MACROS, remote)
    assert ROOT_MACROS_REMOTE in enabled.remote_names
    assert MACROS_REMOTE not in enabled.remote_names


@pytest.mark.parametrize("included", [False, True])
def test_unowned_root_macros_are_never_overwritten(included):
    hardware = generated("English", "\n")
    remote = {"printer.cfg": b"[printer]\nkinematics: none\n" +
              (b"[include macros.cfg]\n" if included else b""),
              ROOT_MACROS_REMOTE: b"# external macros\n", "mainsail.cfg": b""}
    plan = build_managed_config_plan(hardware, MACROS, remote)
    assert ROOT_MACROS_REMOTE not in plan.remote_names
    assert (MACROS_REMOTE in plan.remote_names) is not included
    assert (b"[include macros.cfg]" in plan.artifacts[0].content) is included


def test_external_existing_root_keeps_managed_subdirectory_layout():
    plan = build_managed_config_plan(generated("English", "\n"), MACROS,
                                     {"printer.cfg": b"# user root\n", "mainsail.cfg": b""})
    assert HARDWARE_REMOTE in plan.remote_names
    assert MACROS_REMOTE in plan.remote_names
    assert ROOT_MACROS_REMOTE not in plan.remote_names


@pytest.mark.parametrize("external_root", [False, True])
def test_relative_macro_includes_use_actual_publication_directory(external_root):
    dependency = "kace/dependency.cfg" if external_root else "dependency.cfg"
    files = {"mainsail.cfg": b"", dependency: b"[respond]\n"}
    if external_root:
        files["printer.cfg"] = b"# external root\n"
    transport = FakeTransport(files)
    hardware = generated("English", "\n")
    macros = b"[include dependency.cfg]\n" + MACROS
    state = read_config_state(transport, hardware, macros)
    assert state[dependency] == files[dependency]
    plan = build_managed_config_plan(hardware, macros, state)
    assert "[respond]" in effective_hardware_text(plan)


@pytest.mark.parametrize("external_root", [False, True])
def test_macro_semantic_checks_and_review_apply_to_both_paths(external_root):
    files = {"printer.cfg": b"# user root\n"} if external_root else {}
    macros = b"[gcode_macro PID_BED]\ngcode: PID_CALIBRATE HEATER=heater_bed TARGET=60\n"
    plan = build_managed_config_plan(_hardware(bed_control="watermark"), macros, files)
    validation = validate_configuration_plan(plan)
    assert not validation.valid
    assert "heater_bed-pid-macro" in {error.code for error in validation.errors}
    review = build_configuration_review(plan)
    assert any("starter macros" in change for change in review.important_changes)


def test_crlf_file_roundtrip_keeps_root_ownership_and_one_layout_marker():
    hardware = generated("English", "\n")
    plan = build_managed_config_plan(hardware, MACROS, {"mainsail.cfg": b""})
    remote = {"mainsail.cfg": b"", **{
        item.remote_name: item.content.replace(b"\n", b"\r\n") for item in plan.artifacts}}
    updated = build_managed_config_plan(hardware, MACROS, remote)
    files = {item.remote_name: item.content for item in updated.artifacts}
    assert ROOT_MACROS_REMOTE in files and MACROS_REMOTE not in files
    assert files["printer.cfg"].count(b"# KACE layout: root-v1") == 1
    remote.update(files)
    assert not build_managed_config_plan(hardware, MACROS, remote).changed_artifacts
