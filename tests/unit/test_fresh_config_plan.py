"""A fresh plan does not import old configuration or saved calibrations."""

from core.managed_config import build_fresh_config_plan
from tests.unit.test_initial_macros_layout import MACROS
from tests.unit.test_root_include_placement import generated


def test_fresh_plan_uses_new_files_and_retains_original_bytes_for_review():
    old_root = (b"[include missing-old.cfg]\n[heater_bed]\ncontrol: pid\n"
                b"#*# <---------------------- SAVE_CONFIG ---------------------->\n"
                b"#*# [heater_bed]\n#*# control = pid\n#*# pid_kp = 12\n")
    old_macros = b"[gcode_macro OLD]\ngcode: M117 OLD\n"
    files = {"printer.cfg": old_root, "macros.cfg": old_macros, "mainsail.cfg": b""}
    plan = build_fresh_config_plan(generated("English", "\n"), MACROS, files)
    artifacts = {item.remote_name: item for item in plan.artifacts}
    assert artifacts["printer.cfg"].previous == old_root
    assert artifacts["macros.cfg"].previous == old_macros
    assert b"missing-old.cfg" not in artifacts["printer.cfg"].content
    assert b"SAVE_CONFIG ---------------------->" not in artifacts["printer.cfg"].content
    assert b"gcode_macro OLD" not in artifacts["macros.cfg"].content
