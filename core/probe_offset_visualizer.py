# core/probe_offset_visualizer.py
#
# Probe Offset Visualizer — KACE
#
# Provides run_probe_offset_step() which is inserted immediately after probe
# selection in the wizard (step 7). Only runs when probe != "None".
#
# Design principles:
#   - Zero new dependencies (pure stdlib + sys.stdout ANSI)
#   - Works over SSH and on Raspberry Pi hardware
#   - No animations, no heavy redraws — one clean redraw per input
#   - Educational: shows the spatial relationship between nozzle and probe
#   - Live preview: bed view redraws after each offset entry
#
# Return contract (keys merged into user_data by wizard.py):
#   probe_x_offset : str   — signed float string, e.g. "-38.0"
#   probe_y_offset : str   — signed float string, e.g. "0.0"
#
# Future compatibility:
#   probe_x_offset + probe_y_offset enable:
#     - automatic safe bed_mesh bounds calculation
#     - invalid probe reach warnings
#     - safe_z_home adaptation
#     - reachable-area preview

import sys
import questionary
from core.style import custom_style
from core.translations import t

# ── ANSI color constants (SSH/Pi-safe subset) ────────────────────────────────
_CY  = "\033[96m"   # cyan   — info / borders
_GR  = "\033[92m"   # green  — nozzle symbol / success
_YL  = "\033[93m"   # yellow — probe symbol / warnings
_RD  = "\033[91m"   # red    — out-of-range errors
_DIM = "\033[2m"    # dim    — legend / secondary text
_B   = "\033[1m"    # bold
_RS  = "\033[0m"    # reset

# Symbols — intentionally ASCII-friendly for all terminal encodings
_NOZZLE = "N"   # nozzle position
_PROBE  = "P"   # probe position
_OVERLAP = "X"  # nozzle/probe overlap

# Bed preview dimensions (terminal characters)
_BED_W = 14   # inner width
_BED_H = 7    # inner height


def _offset_to_cell(offset_mm: float, bed_mm: float, cells: int, center_idx: int) -> int:
    """Convert a physical offset (mm) relative to bed center into a grid cell index.

    Args:
        offset_mm:  physical offset in mm
        bed_mm:     full bed dimension in mm
        cells:      number of grid cells (width or height)
        center_idx: center grid cell index corresponding to offset = 0
    """
    if offset_mm >= 0:
        max_dist = (cells - 1) - center_idx
        scale = max_dist / (bed_mm / 2.0) if bed_mm > 0 else 1.0
        cell = center_idx + int(round(offset_mm * scale))
        return max(center_idx, min(cells - 1, cell))
    else:
        max_dist = center_idx
        scale = max_dist / (bed_mm / 2.0) if bed_mm > 0 else 1.0
        cell = center_idx + int(round(offset_mm * scale))
        return max(0, min(center_idx, cell))


def _render_bed(
    x_off: float,
    y_off: float,
    bed_w: float,
    bed_h: float,
) -> list[str]:
    """Render the ASCII bed preview as a list of terminal strings.

    Nozzle (N) is always at the center (index 6 on Row 3).
    Probe (P) moves relative to nozzle based on (x_off, y_off).

    The grid uses X = horizontal, Y = vertical (positive Y = upward / "back of bed").

    Args:
        x_off: probe X offset in mm (relative to nozzle)
        y_off: probe Y offset in mm (relative to nozzle)
        bed_w: bed width in mm (X dimension)
        bed_h: bed height in mm (Y dimension)

    Returns:
        List of ready-to-print strings (with ANSI codes).
    """
    # Define base grid template
    grid = [
        list("     [+]      "), # Row 0 (Grid Row 0)
        list(" 2         1  "), # Row 1 (Grid Row 1)
        list("              "), # Row 2 (Grid Row 2)
        list("[-]   N    [+]"), # Row 3 (Grid Row 3)
        list("              "), # Row 4 (Grid Row 4)
        list(" 4         3  "), # Row 5 (Grid Row 5)
        list("     [-]      "), # Row 6 (Grid Row 6)
    ]

    nx = 6
    ny = 3

    # Probe position — positive Y offset = back of bed = lower row index
    # Use high-resolution limit of 50mm for mapping to the visual grid (max_range represents total bed size, which is halved in _offset_to_cell)
    max_range = 100.0
    px = _offset_to_cell(x_off, max_range, 14, nx)
    py = _offset_to_cell(-y_off, max_range, 7, ny)

    overlap = (px == nx and py == ny)
    if not overlap:
        grid[py][px] = _PROBE
    else:
        grid[ny][nx] = _OVERLAP

    # Build layout lines
    left_labels = ["  ", "  ", "L ", "E ", "F ", "T ", "  ", "  ", "  "]
    right_labels = ["", "", " R", " I", " G", " H", " T", "", ""]
    comments = [
        "",
        "",
        "      <-- Example \"1\" (right+,  back+)",
        "      <-- Example \"2\" ( left-,  back+)",
        "      <-- Nozzle",
        "      <-- Example \"3\" (right+, front-)",
        "      <-- Example \"4\" ( left-, front-)",
        "",
        ""
    ]

    lines = []

    # 1. Top border
    lines.append(f"  {_CY}+---- {_B}BACK{_RS}{_CY} ----+{_RS}")

    # 2. Grid rows
    for r_idx in range(7):
        rendered_row = ""
        for ch in grid[r_idx]:
            if ch == _NOZZLE:
                rendered_row += f"{_GR}{_B}{_NOZZLE}{_RS}"
            elif ch == _PROBE:
                rendered_row += f"{_YL}{_B}{_PROBE}{_RS}"
            elif ch == _OVERLAP:
                rendered_row += f"{_YL}{_B}{_OVERLAP}{_RS}"
            elif ch in ["1", "2", "3", "4"]:
                rendered_row += f"{_DIM}{ch}{_RS}"
            elif ch in ["[", "]", "+", "-"]:
                rendered_row += f"{_CY}{ch}{_RS}"
            else:
                rendered_row += ch

        left = left_labels[r_idx + 1]
        right = right_labels[r_idx + 1]
        comment = comments[r_idx + 1]

        left_colored = f"{_DIM}{left[0]}{_RS}{left[1]}" if left.strip() else left
        right_colored = f"{right[0]}{_DIM}{right[1]}{_RS}" if right.strip() else right
        comment_colored = f"{_DIM}{comment}{_RS}" if comment else ""

        line = f"{left_colored}{_CY}|{_RS}{rendered_row}{_CY}|{_RS}{right_colored}{comment_colored}"
        lines.append(line)

    # 3. Bottom border
    lines.append(f"  {_CY}O---- {_B}FRONT{_RS}{_CY} ---+{_RS}")

    return lines


def _print_frame(
    x_off: float,
    y_off: float,
    bed_w: float,
    bed_h: float,
    probe_name: str,
    out_of_range_msg: str = "",
) -> None:
    """Print the full probe offset visualization frame.

    Designed for sequential printing (one full frame at a time).
    Each call to _print_frame() simply prints — no cursor manipulation
    is used, keeping it SSH/Pi safe.
    """
    print()
    print(f"  {_CY}{_B}Probe Offset Preview{_RS}  {_DIM}({probe_name}){_RS}")
    print(f"  {_DIM}N = Nozzle  ·  P = Probe (X = Overlap){_RS}")
    print()

    bed_lines = _render_bed(x_off, y_off, bed_w, bed_h)
    for line in bed_lines:
        print(line)

    # Coordinate labels
    x_label = f"X: {x_off:+.1f} mm"
    y_label = f"Y: {y_off:+.1f} mm"
    print(f"\n  {_DIM}{x_label}   {y_label}{_RS}")

    # Use high-resolution limit of 50mm for mapping to the visual grid (max_range represents total bed size, which is halved in _offset_to_cell)
    max_range = 100.0
    px = _offset_to_cell(x_off, max_range, 14, 6)
    py = _offset_to_cell(-y_off, max_range, 7, 3)
    overlap = (px == 6 and py == 3)

    if overlap:
        print(f"  {_YL}[!] Nozzle and probe overlap — confirm offsets are correct{_RS}")

    if out_of_range_msg:
        print(f"  {_RD}{out_of_range_msg}{_RS}")

    print()


def _validate_offset(value: str) -> bool | str:
    """questionary validator: accepts signed floats or integers only."""
    v = value.strip()
    if not v:
        return True   # allow empty → will use default
    try:
        float(v)
        return True
    except ValueError:
        return "Enter a number (e.g. -38, 0, 23.5)"


def _check_reachability(
    x_off: float,
    y_off: float,
    user_data: dict,
) -> str:
    """Return a warning string if the probe offset pushes the probe outside bed bounds.

    Uses PrinterMotionSpace to compute physical limits and probeable range on the bed.
    """
    temp_data = dict(user_data)
    temp_data["probe_x_offset"] = str(x_off)
    temp_data["probe_y_offset"] = str(y_off)

    from core.motion_model import PrinterMotionSpace
    space = PrinterMotionSpace(temp_data)

    printable = space.printable_bed_area()
    probeable = space.probeable_bed_area()

    issues = []
    bed_x_min, bed_x_max = printable["x"]
    prob_x_min, prob_x_max = probeable["x"]
    bed_y_min, bed_y_max = printable["y"]
    prob_y_min, prob_y_max = probeable["y"]

    if prob_x_min > bed_x_min:
        issues.append(f"Probe cannot reach left edge of bed (misses first {prob_x_min:.1f} mm)")
    if prob_x_max < bed_x_max:
        issues.append(f"Probe cannot reach right edge of bed (misses last {bed_x_max - prob_x_max:.1f} mm)")

    if prob_y_min > bed_y_min:
        issues.append(f"Probe cannot reach front edge of bed (misses first {prob_y_min:.1f} mm)")
    if prob_y_max < bed_y_max:
        issues.append(f"Probe cannot reach back edge of bed (misses last {bed_y_max - prob_y_max:.1f} mm)")

    # Also keep the soft warning if offsets are extremely large
    if abs(x_off) > space.x_size * 0.9:
        issues.append(f"X offset ({x_off:+.1f} mm) is extremely large relative to bed size")
    if abs(y_off) > space.y_size * 0.9:
        issues.append(f"Y offset ({y_off:+.1f} mm) is extremely large relative to bed size")

    return "  ".join(issues)


def run_probe_offset_step(
    user_data: dict,
    board_filename: str = "",
) -> dict:
    """Run the interactive probe offset entry + live visualization step.

    Prompts the user for X and Y probe offsets relative to the nozzle,
    redrawing the ASCII bed preview after each entry.

    Skips automatically if probe == "None" (should not be called in that case,
    but is safe to call regardless).

    Args:
        user_data:      Current wizard user_data dict (read for probe, x_size, y_size)
        board_filename: Board filename (informational only, not used for logic)

    Returns:
        Dict with keys:
          probe_x_offset: str — signed offset in mm (e.g. "-38.0")
          probe_y_offset: str — signed offset in mm (e.g. "0.0")
        Caller merges these into user_data.
    """
    probe_name = user_data.get("probe", "None")

    result = {
        "probe_x_offset": "0",
        "probe_y_offset": "0",
    }

    # Graceful no-op if probe was not selected
    if probe_name == "None":
        return result

    try:
        bed_w = float(user_data.get("x_size", 235))
        bed_h = float(user_data.get("y_size", 235))
    except (ValueError, TypeError):
        bed_w, bed_h = 235.0, 235.0

    # Working values — updated on each input
    x_off = 0.0
    y_off = 0.0

    while True:
        # ── Print initial/current frame ────────────────────────────────────────
        _print_frame(x_off, y_off, bed_w, bed_h, probe_name)

        print(f"  {_CY}Enter the distance from the nozzle to the probe tip.{_RS}")
        print(f"  {_DIM}  Negative X = probe is LEFT of nozzle{_RS}")
        print(f"  {_DIM}  Positive X = probe is RIGHT of nozzle{_RS}")
        print(f"  {_DIM}  Negative Y = probe is in FRONT of nozzle{_RS}")
        print(f"  {_DIM}  Positive Y = probe is BEHIND nozzle{_RS}")
        print()

        # ── X offset ─────────────────────────────────────────────────────────────
        raw_x = questionary.text(
            t("wizard.probe_x_offset") or "Probe X offset from nozzle (mm, e.g. -38 or 0):",
            default=f"{x_off:.1f}" if x_off != 0.0 else "0",
            validate=_validate_offset,
            style=custom_style,
        ).ask()

        if raw_x is None:
            # Ctrl+C or escape → signal back to caller
            result["probe_x_offset"] = "__back__"
            return result

        raw_x = raw_x.strip() or "0"
        try:
            x_off = float(raw_x)
        except ValueError:
            x_off = 0.0

        warn = _check_reachability(x_off, y_off, user_data)
        _print_frame(x_off, y_off, bed_w, bed_h, probe_name, warn)

        # ── Y offset ─────────────────────────────────────────────────────────────
        raw_y = questionary.text(
            t("wizard.probe_y_offset") or "Probe Y offset from nozzle (mm, e.g. 0 or 25):",
            default=f"{y_off:.1f}" if y_off != 0.0 else "0",
            validate=_validate_offset,
            style=custom_style,
        ).ask()

        if raw_y is None:
            result["probe_y_offset"] = "__back__"
            return result

        raw_y = raw_y.strip() or "0"
        try:
            y_off = float(raw_y)
        except ValueError:
            y_off = 0.0

        warn = _check_reachability(x_off, y_off, user_data)
        _print_frame(x_off, y_off, bed_w, bed_h, probe_name, warn)

        # ── Confirm offsets ──────────────────────────────────────────────────────
        choice_yes = t("wizard.probe_confirm_yes") or "Yes, continue"
        choice_retry = t("wizard.probe_confirm_retry") or "No, re-enter offsets"
        choice_back = t("choice.back") or "Back"
        choice_quit = t("choice.quit") or "Quit"

        ans = questionary.select(
            t("wizard.probe_confirm_offsets") or "Are these probe offsets correct?",
            choices=[
                {"name": choice_yes, "value": "yes"},
                {"name": choice_retry, "value": "retry"},
                {"name": choice_back, "value": "back"},
                {"name": choice_quit, "value": "quit"},
            ],
            style=custom_style,
        ).ask()

        if ans == "quit" or ans is None:
            sys.exit(0)
        elif ans == "back":
            result["probe_x_offset"] = "__back__"
            return result
        elif ans == "retry":
            # Loop again, maintaining current values as defaults
            continue
        else:
            # "yes"
            break

    # ── Final confirmation frame ──────────────────────────────────────────────
    print(f"  {_GR}✓  Probe offset confirmed: X={x_off:+.1f} mm, Y={y_off:+.1f} mm{_RS}")
    print(f"  {_DIM}  Z offset will be calibrated later with PROBE_CALIBRATE.{_RS}\n")

    result["probe_x_offset"] = f"{x_off}"
    result["probe_y_offset"] = f"{y_off}"
    return result
