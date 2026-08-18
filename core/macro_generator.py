# core/macro_generator.py
# Klipper source: https://www.klipper3d.org/Command_Templates.html
#
import os
from core.reconciler import write_text_atomically
from core.translations import t


def _format_coordinate(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")

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
    park_x, park_y, park_z = positions["park"]
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
    G91
    G1 E50 F100
    G90

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
    G90
    G1 X{_format_coordinate(park_x)} Y{_format_coordinate(park_y)} Z{_format_coordinate(park_z)} F3000

# {t('macro.load_filament.desc')}
[gcode_macro LOAD_FILAMENT]
description: {t('macro.load_filament.desc')}
gcode:
    G91
    G1 E50 F300
    G90

# {t('macro.unload_filament.desc')}
[gcode_macro UNLOAD_FILAMENT]
description: {t('macro.unload_filament.desc')}
gcode:
    G91
    G1 E-50 F300
    G90

"""
    
    os.makedirs(output_dir, exist_ok=True)
    macros_path = os.path.join(output_dir, 'macros.cfg')
    
    write_text_atomically(macros_path, macros_content)
        
    return macros_path
