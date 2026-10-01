# core/macro_generator.py
# Klipper source: https://www.klipper3d.org/Command_Templates.html
#
import os
from core.reconciler import write_text_atomically
from core.translations import t


def _format_coordinate(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _extrusion_gcode(name: str, distance: int, feed: int) -> str:
    # Klipper renders the whole template before executing its commands. Reject
    # known extrusion errors at that stage, before saving/changing modal state.
    # Each starter macro owns a distinct name; RESTORE must not move XYZ back.
    return f"""    {{% set extruder = printer.toolhead.extruder %}}
    {{% if not extruder or extruder not in printer %}}
        {{ action_raise_error("{name}: no active extruder") }}
    {{% endif %}}
    {{% if not printer[extruder].can_extrude %}}
        {{ action_raise_error("{name}: extruder below minimum extrusion temperature") }}
    {{% endif %}}
    {{% set amount = {abs(distance)} * printer.gcode_move.extrude_factor %}}
    {{% set limit = printer.configfile.settings[extruder].max_extrude_only_distance %}}
    {{% if not amount > 0 or not amount <= limit %}}
        {{ action_raise_error("{name}: requested extrusion exceeds max_extrude_only_distance") }}
    {{% endif %}}
    SAVE_GCODE_STATE NAME=KACE_{name}
    M83
    G1 E{distance} F{feed}
    RESTORE_GCODE_STATE NAME=KACE_{name} MOVE=0"""


def _park_gcode(x: float, y: float) -> str:
    # Work in relative machine-space deltas so G92/SET_GCODE_OFFSET cannot
    # displace the derived XY target. Require the full lift, never clip it.
    return f"""    {{% set th = printer.toolhead %}}
    {{% if 'x' not in th.homed_axes or 'y' not in th.homed_axes or 'z' not in th.homed_axes %}}
        {{ action_raise_error("PARK_HEAD: XYZ must be homed") }}
    {{% endif %}}
    {{% if 'bed_mesh' in printer and printer.bed_mesh.mesh_matrix[0] %}}
        {{ action_raise_error("PARK_HEAD: active bed mesh requires a dedicated parking macro") }}
    {{% endif %}}
    {{% if 'exclude_object' in printer and printer.exclude_object.excluded_objects %}}
        {{ action_raise_error("PARK_HEAD: object exclusion requires a dedicated parking macro") }}
    {{% endif %}}
    {{% set settings = printer.configfile.settings %}}
    {{% if 'bed_tilt' in settings or 'skew_correction' in settings or 'z_thermal_adjust' in settings %}}
        {{ action_raise_error("PARK_HEAD: configured motion transform requires a dedicated parking macro") }}
    {{% endif %}}
    {{% set p = printer.gcode_move.position %}}
    {{% if th.position.x != p.x or th.position.y != p.y or th.position.z != p.z %}}
        {{ action_raise_error("PARK_HEAD: transformed position requires a dedicated parking macro") }}
    {{% endif %}}
    {{% set lo = th.axis_minimum %}}
    {{% set hi = th.axis_maximum %}}
    {{% if not (lo.x <= p.x <= hi.x and lo.y <= p.y <= hi.y and lo.z <= p.z <= hi.z) %}}
        {{ action_raise_error("PARK_HEAD: current position is outside known travel") }}
    {{% endif %}}
    {{% if not (lo.x <= {_format_coordinate(x)} <= hi.x and lo.y <= {_format_coordinate(y)} <= hi.y) %}}
        {{ action_raise_error("PARK_HEAD: destination is outside known travel") }}
    {{% endif %}}
    {{% if not p.z + 5 <= hi.z %}}
        {{ action_raise_error("PARK_HEAD: insufficient Z travel for the required 5 mm lift") }}
    {{% endif %}}
    SAVE_GCODE_STATE NAME=KACE_PARK_HEAD
    G91
    G1 Z5 F3000
    G1 X{{ {_format_coordinate(x)} - p.x }} Y{{ {_format_coordinate(y)} - p.y }} F3000
    RESTORE_GCODE_STATE NAME=KACE_PARK_HEAD MOVE=0"""


def generate_starter_macros(
    output_dir: str,
    motion_space=None,
    *,
    hotend_control: str = "pid",
    bed_control: str = "pid",
) -> str:
    """Generates a beginner-friendly macros.cfg file."""
    if motion_space is None:
        from core.motion_model import PrinterMotionSpace
        motion_space = PrinterMotionSpace({})
    positions = motion_space.starter_macro_positions()
    center_x, center_y, center_z = positions["center"]
    park_x, park_y, _ = positions["park"]
    test_x, test_y, test_z = positions["test"]
    calibration_macros = ""
    if str(hotend_control).strip().casefold() == "pid":
        calibration_macros += f"""# {t('macro.pid_hotend.desc')}
[gcode_macro PID_HOTEND]
description: {t('macro.pid_hotend.desc')}
gcode:
    PID_CALIBRATE HEATER=extruder TARGET=200

"""
    if str(bed_control).strip().casefold() == "pid":
        calibration_macros += f"""# {t('macro.pid_bed.desc')}
[gcode_macro PID_BED]
description: {t('macro.pid_bed.desc')}
gcode:
    PID_CALIBRATE HEATER=heater_bed TARGET=60

"""
    macros_content = f"""# ==============================================================================
# KACE Starter Macros
# ==============================================================================
{calibration_macros}
# {t('macro.test_movement.desc')}
[gcode_macro TEST_MOVEMENT]
description: {t('macro.test_movement.desc')}
gcode:
    G90
    G1 X{_format_coordinate(test_x)} Y{_format_coordinate(test_y)} Z{_format_coordinate(test_z)} F3000

# {t('macro.test_extruder.desc')}
[gcode_macro TEST_EXTRUDER]
description: {t('macro.test_extruder.desc')}
gcode:
{_extrusion_gcode('TEST_EXTRUDER', 50, 100)}

# {t('macro.preheat_pla.desc')}
[gcode_macro PREHEAT_PLA]
description: {t('macro.preheat_pla.desc')}
gcode:
    M140 S60
    M104 S200

# {t('macro.preheat_petg.desc')}
[gcode_macro PREHEAT_PETG]
description: {t('macro.preheat_petg.desc')}
gcode:
    M140 S80
    M104 S240

# {t('macro.home_and_center.desc')}
[gcode_macro HOME_AND_CENTER]
description: {t('macro.home_and_center.desc')}
gcode:
    G28
    G90
    G1 X{_format_coordinate(center_x)} Y{_format_coordinate(center_y)} Z{_format_coordinate(center_z)} F3000

# {t('macro.park_head.desc')}
[gcode_macro PARK_HEAD]
description: {t('macro.park_head.desc')}
gcode:
{_park_gcode(park_x, park_y)}

# {t('macro.load_filament.desc')}
[gcode_macro LOAD_FILAMENT]
description: {t('macro.load_filament.desc')}
gcode:
{_extrusion_gcode('LOAD_FILAMENT', 50, 300)}

# {t('macro.unload_filament.desc')}
[gcode_macro UNLOAD_FILAMENT]
description: {t('macro.unload_filament.desc')}
gcode:
{_extrusion_gcode('UNLOAD_FILAMENT', -50, 300)}

"""
    
    os.makedirs(output_dir, exist_ok=True)
    macros_path = os.path.join(output_dir, 'macros.cfg')
    
    write_text_atomically(macros_path, macros_content)
        
    return macros_path
