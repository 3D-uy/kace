# core/macro_generator.py
# Klipper source: https://www.klipper3d.org/Command_Templates.html
#
import os
from core.translations import t

def generate_starter_macros(output_dir: str) -> str:
    """Generates a beginner-friendly macros.cfg file."""
    macros_content = f"""# ==============================================================================
# KACE Starter Macros
# ==============================================================================
# {t('macro.pid_hotend.desc')}
[gcode_macro PID_HOTEND]
description: {t('macro.pid_hotend.desc')}
gcode:
    PID_CALIBRATE HEATER=extruder TARGET=200

# {t('macro.pid_bed.desc')}
[gcode_macro PID_BED]
description: {t('macro.pid_bed.desc')}
gcode:
    PID_CALIBRATE HEATER=heater_bed TARGET=60

# {t('macro.test_movement.desc')}
[gcode_macro TEST_MOVEMENT]
description: {t('macro.test_movement.desc')}
gcode:
    G90
    G1 X20 Y20 Z20 F3000

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
    G1 X110 Y110 Z50 F3000

# {t('macro.park_head.desc')}
[gcode_macro PARK_HEAD]
description: {t('macro.park_head.desc')}
gcode:
    G90
    G1 X10 Y10 Z50 F3000

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
    
    with open(macros_path, 'w', encoding='utf-8') as f:
        f.write(macros_content)
        
    return macros_path
