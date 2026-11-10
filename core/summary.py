from core.translations import t
from core.motion_model import PrinterMotionSpace, PrintableGeometryError
from core.bed_mesh import generate_bed_mesh_config
from core.probe_configuration import resolve_probe_configuration, apply_probe_compatibility_context
from copy import deepcopy
from core.terminal import RESET, SECTION, SUCCESS, WARNING
from wcwidth import wcswidth
import shutil
import textwrap
import os
import sys


def print_installation_complete(*, stream=None, color=None):
    """Present a completed live installation; the caller owns durable evidence."""
    stream = stream or sys.stdout
    if color is None:
        color = (os.environ.get("NO_COLOR") is None
                 and os.environ.get("TERM", "").casefold() != "dumb"
                 and bool(getattr(stream, "isatty", lambda: False)()))
    width = min(88, max(20, shutil.get_terminal_size(fallback=(80, 24)).columns - 2))

    def line(text="", role=RESET, *, prefix="  "):
        for part in textwrap.wrap(str(text), width=width - len(prefix),
                                  break_on_hyphens=False) or [""]:
            styled = f"{role}{part}{RESET}" if color and part else part
            print(prefix + styled if part else "", file=stream)

    line()
    line("─" * (width - 2), SECTION)
    line(t("installation.complete.title"), SUCCESS)
    line("─" * (width - 2), SECTION)
    line()
    for key in ("firmware", "configuration", "klipper"):
        line("✓ " + t("installation.complete." + key), SUCCESS)
    line()
    line(t("installation.complete.next"), SECTION)
    line(t("installation.complete.commissioning"))
    line(t("installation.complete.calibration"), WARNING)
    line()
    banner_width = min(width - 2, 42)
    line("┌" + "─" * (banner_width - 2) + "┐", SUCCESS)
    line("│" + "HAPPY PRINTING!".center(banner_width - 2) + "│", SUCCESS)
    line("└" + "─" * (banner_width - 2) + "┘", SUCCESS)
    stream.flush()

def print_summary(user_data: dict, parsed_data: dict = None):
    """Print generated configuration before application and installation verification."""
    # Use the same authoritative probe values as generation without changing the
    # accepted wizard/checkpoint data while presenting its digest.
    user_data = deepcopy(user_data)
    probe_configuration = resolve_probe_configuration(user_data)
    apply_probe_compatibility_context(user_data, probe_configuration)
    Y, C, R = WARNING, SECTION, RESET

    width = min(102, max(22, shutil.get_terminal_size(fallback=(80, 24)).columns - 2))
    labels = ("printer_profile", "board", "mcu", "kinematics", "build_volume", "probe",
              "probe_offsets", "driver_type", "driver_mode", "display", "web_interface",
              "hotend_thermistor", "bed_thermistor", "printable_bed", "nozzle_reachable",
              "probeable_bed", "homed_origin", "mesh_min", "mesh_max", "probe_count", "mesh_algorithm")
    col_w = min(width - 18, max(wcswidth(t("summary." + key).rstrip(":") + ":") for key in labels))
    separator = "═" * (width - 2)

    def _text(text, *, color=RESET, indent="  "):
        for line in textwrap.wrap(str(text), width=width - len(indent),
                                  break_on_hyphens=False) or [""]:
            print(f"{indent}{color}{line}{R}")

    def _row(label: str, value: str) -> str:
        label = str(label).rstrip(":") + ":"
        prefix = f"  {label}{' ' * max(0, col_w - wcswidth(label))} "
        lines = textwrap.wrap(prefix + str(value), width=width,
                              subsequent_indent="    ", break_on_hyphens=False)
        return R + "\n".join(lines)

    def _has_val(v) -> bool:
        if v is None:
            return False
        s = str(v).strip()
        return s != "" and s.lower() not in ("none", "null")

    print("")
    print(f"  {C}{separator}{R}")
    _text(t("summary.generated_title"), color=C)
    print(f"  {C}{separator}{R}")
    print("")

    _text(t("summary.hardware_group"), color=C)

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

    # 2. Kinematics, Build Volume
    kin = user_data.get('kinematics')
    x = user_data.get('x_size')
    y = user_data.get('y_size')
    z = user_data.get('z_size')

    if _has_val(kin):
        print(_row(t("summary.kinematics"), kin))
    if _has_val(x) and _has_val(y) and _has_val(z):
        print(_row(t("summary.build_volume"), f"{x} × {y} × {z} mm"))

    # 4. Driver Type, Driver Mode
    driver = user_data.get('driver_type')
    mode = user_data.get('driver_mode')

    if _has_val(driver):
        print(_row(t("summary.driver_type"), driver))
        if "TMC" in str(driver) and _has_val(mode):
            print(_row(t("summary.driver_mode"), mode))

    if user_data.get("motor_directions"):
        from core.motor_direction import effective_direction_pin
        print("")
        _text(t("motor.review"), color=C)
        for motor in user_data["motor_directions"]:
            print(_row(motor, effective_direction_pin(parsed_data, user_data, motor)))

    # 5. Display, Web Interface
    disp = user_data.get('display_choice')
    web = user_data.get('web_interface')
    if user_data.get("web_interface_preserved"):
        web = t("software.preserved", includes=", ".join(user_data["web_interface_preserved"]))
    if user_data.get("web_interface_review_required"):
        web = t("software.preserved_unverified")

    if _has_val(disp):
        # strip "recommended:" or "manual:" prefix if present
        clean_disp = disp
        if ":" in disp:
            clean_disp = disp.split(":", 1)[1]
        print(_row(t("summary.display"), clean_disp))
    if _has_val(web):
        print(_row(t("summary.web_interface"), web))

    # 6. Thermistors
    hotend = user_data.get('hotend_thermistor')
    bed = user_data.get('bed_thermistor')

    if _has_val(hotend):
        print(_row(t("summary.hotend_thermistor"), hotend))
    if _has_val(bed):
        print(_row(t("summary.bed_thermistor"), bed))

    # 3. Probe, Probe Offsets
    probe = user_data.get('probe')
    px = user_data.get('probe_x_offset')
    py = user_data.get('probe_y_offset')

    if _has_val(probe):
        print("")
        _text(t("summary.probe_group"), color=C)
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

    # 6b. Motion Model & Bed Mesh
    print("")
    _text(t("summary.motion_model"), color=C)
    try:
        space = PrinterMotionSpace(user_data)
    except PrintableGeometryError as exc:
        space = None
        _text(str(exc), color=Y)

    if space is not None:
        printable = space.printable_bed_area()
        pb_x = f"X [{printable['x'][0]:g}, {printable['x'][1]:g}],"
        pb_y = f"Y [{printable['y'][0]:g}, {printable['y'][1]:g}]"
        print(_row(t("summary.printable_bed"), f"{pb_x} {pb_y}"))

        nr_x = f"X [{space.x_min:g}, {space.x_max:g}],"
        nr_y = f"Y [{space.y_min:g}, {space.y_max:g}],"
        nr_z = f"Z [{space.z_min:g}, {space.z_max:g}]"
        print(_row(t("summary.nozzle_reachable"), f"{nr_x} {nr_y} {nr_z}"))

        if probe_configuration.generates_bed_mesh:
            p_bed = space.probeable_bed_area()
            pr_x = f"X [{p_bed['x'][0]:g}, {p_bed['x'][1]:g}],"
            pr_y = f"Y [{p_bed['y'][0]:g}, {p_bed['y'][1]:g}]"
            print(_row(t("summary.probeable_bed"), f"{pr_x} {pr_y}"))

        ho_x = f"X [{space.x_endstop:g}],"
        ho_y = f"Y [{space.y_endstop:g}],"
        ho_z = f"Z [{space.z_endstop:g}]"
        if probe_configuration.uses_virtual_z_endstop:
            offset = probe_configuration.resolved_offsets.z
            # Structured probes render 0 until calibrated; raw custom probes carry
            # their explicit trigger offset. The physical Z endstop is replaced.
            ho_z = t("summary.probe_homed_z", offset=f"{offset if offset is not None else 0:g}")
        print(_row(t("summary.homed_origin"), f"{ho_x} {ho_y} {ho_z}"))
    print("")

    if space is not None and probe_configuration.generates_bed_mesh and parsed_data:
        user_ctx = dict(user_data)
        user_ctx["motion_space"] = space.to_dict()
        bm = generate_bed_mesh_config(space, user_ctx, parsed_data,
                                      probe_configuration=probe_configuration)
        if bm:
            _text(t("summary.generated_mesh"), color=C)
            print(_row(t("summary.mesh_min"), bm['mesh_min']))
            print(_row(t("summary.mesh_max"), bm['mesh_max']))
            print(_row(t("summary.probe_count"), bm['probe_count']))
            print(_row(t("summary.mesh_algorithm"), bm['algorithm']))
            print("")

    # 7. Generated Files
    from core.nozzle_bed_visualizer import print_nozzle_bed_preview
    print_nozzle_bed_preview(user_data)
    print('')
    _text(t('summary.generated_files'), color=C)
    _text("~/kace/printer.cfg", indent="    ")
    if user_data.get("macros_generated"):
        _text("~/kace/macros.cfg", indent="    ")
    if user_data.get("firmware_path"):
        # BoardContract artifacts live in an identity-specific nested directory.
        # Preserve the real path instead of suggesting a non-existent ~/kace copy.
        _text(user_data['firmware_path'], indent="    ")
    print("")

    _text(t('summary.next_steps'), color=C)
    steps = ["summary.review_generated", "summary.choose_application", "summary.follow_verification"]
    if user_data.get("pending_firmware_deployment") or user_data.get("firmware_compilation_skipped"):
        steps.insert(1, "summary.firmware_pending_step")
    for index, key in enumerate(steps, 1):
        _text(f"{index}. {t(key)}", indent="    ")
    print("")

    print(f"  {C}{separator}{R}")
    _text(t("summary.application_pending"), color=Y)
    print(f"  {C}{separator}{R}")
    print("")
