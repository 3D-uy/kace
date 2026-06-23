import os
from core.translations import t
from core.motion_model import PrinterMotionSpace
from core.bed_mesh import generate_bed_mesh_config

def print_summary(user_data: dict, parsed_data: dict = None):
    """Print final summary with full configuration digest and next steps."""
    G  = "\033[92m"   # green
    Y  = "\033[93m"   # yellow / value
    C  = "\033[96m"   # cyan / accent
    B  = "\033[1m"    # bold
    D  = "\033[2m"    # dim
    R  = "\033[0m"    # reset
    M  = "\033[96m"   # cyan / section headers

    col_w = 30   # label column width

    def _row(label: str, value: str) -> str:
        pad = " " * max(0, col_w - len(label))
        return f"  {label}{pad}{value}"

    def _has_val(v) -> bool:
        if v is None:
            return False
        s = str(v).strip()
        return s != "" and s.lower() not in ("none", "null")

    print("")
    print(f"  {G}══════════════════════════════════════════════════════════════{R}")
    print(f"    ✅  {t('summary.title') or 'Configuration Summary'}")
    print(f"  {G}══════════════════════════════════════════════════════════════{R}")
    print("")

    # 1. Printer Profile, Board, MCU
    profile = user_data.get('printer_profile')
    board = user_data.get('board')
    mcu = user_data.get('mcu_type')

    if _has_val(profile):
        print(_row(t("summary.printer_profile"), profile))
    if _has_val(board):
        print(_row(t("summary.board"), board))
    if _has_val(mcu):
        print(_row(t("summary.mcu"), mcu.upper()))

    if _has_val(profile) or _has_val(board) or _has_val(mcu):
        print("")

    # 2. Kinematics, Build Volume
    kin = user_data.get('kinematics')
    x = user_data.get('x_size')
    y = user_data.get('y_size')
    z = user_data.get('z_size')

    if _has_val(kin):
        print(_row(t("summary.kinematics"), kin))
    if _has_val(x) and _has_val(y) and _has_val(z):
        print(_row(t("summary.build_volume"), f"{x} × {y} × {z} mm"))

    if _has_val(kin) or (_has_val(x) and _has_val(y) and _has_val(z)):
        print("")

    # 3. Probe, Probe Offsets
    probe = user_data.get('probe')
    px = user_data.get('probe_x_offset')
    py = user_data.get('probe_y_offset')

    if _has_val(probe):
        print(_row(t("summary.probe"), probe))
        if _has_val(px) and _has_val(py):
            # Format offset signs nicely
            try:
                fx = float(px)
                sx = f"+{fx}" if fx > 0 else f"{fx}"
            except ValueError:
                sx = px
            try:
                fy = float(py)
                sy = f"+{fy}" if fy > 0 else f"{fy}"
            except ValueError:
                sy = py
            print(_row(t("summary.probe_offsets"), f"X = {sx}   Y = {sy}"))
        print("")

    # 4. Driver Type, Driver Mode
    driver = user_data.get('driver_type')
    mode = user_data.get('driver_mode')

    if _has_val(driver):
        print(_row(t("summary.driver_type"), driver))
        if "TMC" in str(driver) and _has_val(mode):
            print(_row(t("summary.driver_mode"), mode))
        print("")

    # 5. Display, Web Interface
    disp = user_data.get('display_choice')
    web = user_data.get('web_interface')

    if _has_val(disp):
        # strip "recommended:" or "manual:" prefix if present
        clean_disp = disp
        if ":" in disp:
            clean_disp = disp.split(":", 1)[1]
        print(_row(t("summary.display"), clean_disp))
    if _has_val(web):
        print(_row(t("summary.web_interface"), web))

    if _has_val(disp) or _has_val(web):
        print("")

    # 6. Thermistors
    hotend = user_data.get('hotend_thermistor')
    bed = user_data.get('bed_thermistor')

    if _has_val(hotend):
        print(_row(t("summary.hotend_thermistor"), hotend))
    if _has_val(bed):
        print(_row(t("summary.bed_thermistor"), bed))

    if _has_val(hotend) or _has_val(bed):
        print("")

    # 6b. Motion Model & Bed Mesh
    space = PrinterMotionSpace(user_data)
    print(f"  {C}[Motion Model]{R}")
    
    pb_x = f"X [0, {space.x_size:g}],"
    pb_y = f"Y [0, {space.y_size:g}]"
    print(_row(t("summary.printable_bed"), f"{pb_x:<18} {pb_y}"))
    
    nr_x = f"X [{space.x_min:g}, {space.x_max:g}],"
    nr_y = f"Y [{space.y_min:g}, {space.y_max:g}],"
    nr_z = f"Z [{space.z_min:g}, {space.z_max:g}]"
    print(_row(t("summary.nozzle_reachable"), f"{nr_x:<18} {nr_y:<18} {nr_z}"))
    
    if user_data.get("probe") != "None":
        p_bed = space.probeable_bed_area()
        pr_x = f"X [{p_bed['x'][0]:g}, {p_bed['x'][1]:g}],"
        pr_y = f"Y [{p_bed['y'][0]:g}, {p_bed['y'][1]:g}]"
        print(_row(t("summary.probeable_bed"), f"{pr_x:<18} {pr_y}"))
        
    ho_x = f"X [{space.x_endstop:g}],"
    ho_y = f"Y [{space.y_endstop:g}],"
    ho_z = f"Z [{space.z_endstop:g}]"
    print(_row(t("summary.homed_origin"), f"{ho_x:<18} {ho_y:<18} {ho_z}"))
    print("")

    if user_data.get("probe") != "None" and parsed_data:
        user_ctx = dict(user_data)
        user_ctx["motion_space"] = space.to_dict()
        bm = generate_bed_mesh_config(space, user_ctx, parsed_data)
        if bm:
            print(f"  {C}[Generated Bed Mesh]{R}")
            print(_row("Mesh Min:", bm['mesh_min']))
            print(_row("Mesh Max:", bm['mesh_max']))
            print(_row("Probe Count:", bm['probe_count']))
            print(_row("Algorithm:", bm['algorithm']))
            print("")

    # 7. Generated Files
    print(f"  {t('summary.generated_files')}")
    print("    ~/kace/printer.cfg")
    if user_data.get("macros_generated"):
        print("    ~/kace/macros.cfg")
    if user_data.get("firmware_path"):
        print(f"    ~/kace/{os.path.basename(user_data['firmware_path'])}")
    print("")

    print(f"  {t('summary.next_steps')}")
    print(f"    1.  {t('summary.step1') or 'Flash firmware to your board'}")
    print(f"    2.  {t('summary.step2') or 'Upload printer.cfg to Klipper'}")
    print(f"    3.  {t('summary.step3') or 'Restart Klipper'}")
    print("")

    print(f"  {G}══════════════════════════════════════════════════════════════{R}")
    print(f"  🎉  {t('summary.happy_printing')}")
    print(f"  {G}══════════════════════════════════════════════════════════════{R}")
    print("")
