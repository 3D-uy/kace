# core/display_wizard.py
#
# Hardware-Aware Display Setup Step — KACE
#
# Provides run_display_setup_step() which is called from wizard.py as a
# dedicated step in the configuration wizard.
#
# Design principles:
#   - Safe recommendations first, advanced overrides second
#   - Unsafe combinations NEVER appear as plug-and-play
#   - Unknown hardware revisions default to experimental
#   - Manual override is allowed but gated behind progressive confirmations
#   - RP2040 3.3V_only voltage rules are high-priority safety enforcement
#
# Return contract (dict merged into user_data):
#   display_choice      : "none" | "recommended:<key>" | "manual:<key>" | "override:<key>"
#   display_section     : str | None   — Klipper section name (e.g. "uc1701")
#   display_compat_class: str | None   — compatibility class of chosen display
#   display_risk_accepted: bool        — True if user acknowledged warnings in wizard
#
# Future scalability:
#   This module follows the "peripheral advisor" pattern. The same structure
#   (category → recommendation → manual override with risk analysis) can be
#   replicated for CAN devices, ADXL345, relay boards, etc.

import sys
import questionary

from core.style import custom_style
from core.translations import t
from .exceptions import WizardExit
from core.display_checker import (
    get_recommended_displays,
    get_all_selectable_displays,
    get_display_catalog,
    run_manual_selection_analysis,
)

_BACK = "__back__"
_QUIT = "__quit__"

# ── Friendly name lookup cache — built once from the public API ─────────────
# Maps section_key → friendly_name string. Populated on first use via
# _init_friendly_cache(). Using a lazy init avoids import-time side-effects
# while keeping lookups O(1) after the first call.
_FRIENDLY_CACHE: dict[str, str] = {}
_FRIENDLY_CACHE_READY = False

def _init_friendly_cache() -> None:
    global _FRIENDLY_CACHE_READY
    if _FRIENDLY_CACHE_READY:
        return
    for key, entry in get_all_selectable_displays():
        _FRIENDLY_CACHE[key] = entry.get("friendly_name", key)
    _FRIENDLY_CACHE_READY = True


def _friendly(section_key: str) -> str:
    """Return the friendly_name for a display section key, or the key itself."""
    _init_friendly_cache()
    return _FRIENDLY_CACHE.get(section_key, section_key)


# ── ANSI color helpers ──────────────────────────────────────────────────────
_G   = "\033[92m"          # green — fully compatible
_Y   = "\033[93m"          # amber — compatible_with_adapter
_O   = "\033[38;5;208m"    # orange — experimental
_R   = "\033[91m"          # red — unsafe / danger
_C   = "\033[96m"          # cyan — info
_B   = "\033[1m"           # bold
_RS  = "\033[0m"           # reset
_W   = "\033[97m"          # bright white
_M   = "\033[96m"          # cyan
_DIM = "\033[2m"           # dim

# Badge glyphs and colors per compatibility class
_CLASS_BADGE = {
    "fully_compatible":        (_G,  "✅"),
    "compatible_with_adapter": (_Y,  "🟡"),
    "experimental":            (_O,  "🟠"),
    "unsafe":                  (_R,  "🔴"),
}


_PT_STYLE = {
    "fully_compatible":        "fg:#4caf50",       # green
    "compatible_with_adapter": "fg:#f5a623",       # amber
    "experimental":            "fg:#ff9800",       # orange
    "unsafe":                  "fg:#cc5454",       # red
}

_VALIDATION_BADGE = {
    "ok":     (_G, "✅"),
    "warn":   (_Y, "⚠️ "),
    "danger": (_R, "🔴"),
}






def _print_board_context(board_filename: str, detected_mcu: str) -> None:
    """Print a compact board hardware summary before recommendations."""
    if not board_filename and not detected_mcu:
        return
    print(f"\n  {_M}{_B}Detected Board Hardware:{_RS}")
    if board_filename:
        print(f"  {_C}  Board  :{_RS} {board_filename}")
    if detected_mcu:
        print(f"  {_C}  MCU    :{_RS} {detected_mcu.upper()}")
    print("")


def _print_risk_panel(analysis: dict, display_key: str) -> None:
    """Render the full risk analysis panel for a manually-selected display."""
    comp_class = analysis.get("compatibility_class", "experimental")
    color, badge = _CLASS_BADGE.get(comp_class, (_C, "?"))
    label = t(f"display.class_{comp_class}")
    confidence = analysis.get("confidence_level", "Unknown")

    border = _R if comp_class == "unsafe" else _Y if comp_class in ("compatible_with_adapter", "experimental") else _G

    print(f"\n  {border}{_B}{'─' * 54}{_RS}")
    print(f"  {border}{_B}  ⚡ Hardware Risk Analysis: {_friendly(display_key)}{_RS}")
    print(f"  {border}{_B}{'─' * 54}{_RS}\n")

    # Compatibility summary
    print(f"  {_B}Compatibility :{_RS}  {color}{badge} {label}{_RS}")
    print(f"  {_B}Confidence    :{_RS}  {color}{confidence}{_RS}\n")

    # Voltage validation
    v = analysis.get("voltage_validation", {})
    vr, vd = v.get("result", "warn"), v.get("detail", "")
    vc, vb = _VALIDATION_BADGE.get(vr, (_C, "?"))
    print(f"  {_B}Voltage       :{_RS}  {vc}{vb}{_RS} {vd}")

    # Interface validation
    i = analysis.get("interface_validation", {})
    ir, id_ = i.get("result", "warn"), i.get("detail", "")
    ic, ib = _VALIDATION_BADGE.get(ir, (_C, "?"))
    print(f"  {_B}Interface     :{_RS}  {ic}{ib}{_RS} {id_}\n")

    # Damage risks
    risks = analysis.get("damage_risks", [])
    if risks:
        print(f"  {_R}{_B}⚠️  What Can Be Permanently Damaged:{_RS}")
        for r in risks:
            print(f"    {_R}•{_RS} {r}")
        print("")

    # Required modifications
    mods = analysis.get("required_modifications", [])
    if mods:
        print(f"  {_W}{_B}🔧 Required Modifications:{_RS}")
        for m in mods:
            print(f"    {_W}•{_RS} {m}")
        print("")

    # Adapter requirements
    adapters = analysis.get("adapter_requirements", [])
    if adapters:
        print(f"  {_Y}{_B}🔌 Adapter Requirements:{_RS}")
        for a in adapters:
            print(f"    {_Y}•{_RS} {a}")
        print("")

    # Cable orientation risks
    cable = analysis.get("cable_orientation_risks", [])
    if cable:
        print(f"  {_O}{_B}🔗 Cable Orientation Risks:{_RS}")
        for c in cable:
            print(f"    {_O}•{_RS} {c}")
        print("")

    # Firmware mode requirements
    fw = analysis.get("firmware_mode_requirements", [])
    if fw:
        print(f"  {_C}{_B}💾 Firmware Mode Requirements:{_RS}")
        for f in fw:
            print(f"    {_C}•{_RS} {f}")
        print("")

    # Notes
    notes = analysis.get("notes", [])
    if notes:
        print(f"  {_DIM}Notes:{_RS}")
        for n in notes:
            print(f"    {_DIM}•{_RS} {n}")
        print("")

    print(f"  {border}{_B}{'─' * 54}{_RS}\n")


def _confirm_risk(analysis: dict, display_key: str) -> bool:
    """Gate-check the user based on the compatibility class of the analysis.

    Returns True if the user accepted (or no confirmation needed).
    Returns False if the user declined or pressed Ctrl+C.
    """
    comp_class = analysis.get("compatibility_class", "experimental")

    if comp_class == "fully_compatible":
        return True

    elif comp_class == "compatible_with_adapter":
        ans = questionary.confirm(
            t("wizard.display_confirm_experimental"),
            default=True,
            style=custom_style,
        ).ask()
        return bool(ans)

    elif comp_class == "experimental":
        ans = questionary.confirm(
            t("wizard.display_confirm_experimental"),
            default=False,
            style=custom_style,
        ).ask()
        return bool(ans)

    elif comp_class == "unsafe":
        # Hard gate: requires explicit typed acknowledgement
        print(f"\n  {_R}{_B}⛔ This display combination carries a HIGH RISK of permanent hardware damage.{_RS}")
        print(f"  {_R}KACE will generate a commented-out config with safety markers — NOT plug-and-play.{_RS}\n")
        ans = questionary.text(
            t("wizard.display_confirm_unsafe"),
            style=custom_style,
        ).ask()
        return (ans or "").strip().lower() == "i accept the risk"

    return False


def _build_recommended_choices(
    recommended: dict,
    board_filename: str,
    detected_mcu: str,
) -> list:
    """Build the questionary choices list for the recommended display screen.

    Groups by compatibility class in safety order. Unsafe displays are excluded
    from this list — they're only accessible via Manual Search.
    """
    choices = []

    order = ["fully_compatible", "compatible_with_adapter", "experimental"]

    for class_key in order:
        entries = recommended.get(class_key, [])
        if not entries:
            continue

        # Separator (questionary separator using dynamic localized string)
        color, badge = _CLASS_BADGE[class_key]
        label = t(f"display.class_{class_key}")
        choices.append(questionary.Separator(f"  {badge} {label}"))

        for section_key, entry, hw_info in entries:
            friendly = _friendly(section_key)
            choices.append({
                "name":  f"  {friendly}",
                "value": f"pick:{section_key}",
            })

    # Divider + advanced options
    choices.append(questionary.Separator("──────────────────────────────────"))
    choices.append({
        "name":  [
            ("", "  "),
            ("fg:#00bcd4", "🔍  Manual Search / Advanced Selection...")
        ],
        "value": "__manual__",
    })
    choices.append({"name": t("choice.back"), "value": _BACK})
    choices.append({"name": t("choice.quit"), "value": _QUIT})

    return choices


def _run_manual_search(
    board_filename: str,
    detected_mcu: str,
    parsed_cfg: dict,
) -> tuple[str, dict] | tuple[None, None]:
    """Manual/Advanced search step.

    Shows an autocomplete over all selectable display section keys + friendly names.
    After selection, immediately runs run_manual_selection_analysis() and prints
    the full risk panel. Returns (display_key, analysis) on accepted selection,
    or (None, None) on back/cancel.
    """
    all_displays = get_all_selectable_displays()

    # Build autocomplete list: "friendly_name (section_key)"
    autocomplete_choices = []
    key_by_label = {}
    for section_key, entry in all_displays:
        friendly = entry.get("friendly_name", section_key)
        label = f"{friendly}  [{section_key}]"
        autocomplete_choices.append(label)
        key_by_label[label] = section_key
        # Also allow raw section key lookup
        key_by_label[section_key] = section_key

    print(f"\n  {_C}All displays, including experimental and unsafe combinations, are shown here.{_RS}")
    print(f"  {_Y}Selecting an unsafe display will not make it plug-and-play — KACE always{_RS}")
    print(f"  {_Y}generates safety comments and TODO markers for risky combinations.{_RS}\n")

    raw = questionary.autocomplete(
        t("wizard.display_manual_prompt"),
        choices=autocomplete_choices,
        style=custom_style,
    ).ask()

    if raw is None:
        return None, None

    # Resolve back to section key
    display_key = key_by_label.get(raw)
    if not display_key:
        # Try partial match
        raw_lower = raw.lower().strip()
        for section_key, _ in all_displays:
            if raw_lower in section_key or section_key in raw_lower:
                display_key = section_key
                break
    if not display_key:
        print(f"\n  {_Y}Could not resolve display key from input. Please try again.{_RS}\n")
        return None, None

    # Run full analysis
    analysis = run_manual_selection_analysis(
        display_key,
        board_filename,
        detected_mcu,
        parsed_cfg,
    )

    # Print full risk panel
    _print_risk_panel(analysis, display_key)

    return display_key, analysis


def run_display_setup_step(
    user_data:      dict,
    parsed_cfg:     dict,
    board_filename: str,
) -> dict:
    """Run the interactive display setup step.

    Implements Steps A→E of the guided display selection flow:

      A: "Do you want to use a display?" (no / category / I already know)
      B: Board-aware recommendation list grouped by compatibility class
      C: Manual search with full risk analysis panel
      D: Risk confirmation gate
      E: Return updated display keys

    Args:
        user_data:      Current wizard user_data dict (read-only context)
        parsed_cfg:     Parsed board config (used for EXP pin detection)
        board_filename: Selected board filename

    Returns:
        Dict with keys: display_choice, display_section,
                        display_compat_class, display_risk_accepted
        The caller (wizard.py) merges these into user_data.
    """
    detected_mcu  = user_data.get("mcu_type", "") or ""
    result = {
        "display_choice":       None,
        "display_section":      None,
        "display_compat_class": None,
        "display_risk_accepted": False,
    }

    # ── Pre-compute recommendations once ─────────────────────────────────────
    # This is deliberately done before Step A so the UI feels instant when
    # the user enters Step B without waiting for classification.
    recommended = get_recommended_displays(board_filename, detected_mcu, parsed_cfg)
    catalog = get_display_catalog()

    # ── Step A: Top-level display intent ─────────────────────────────────────
    while True:
        _print_board_context(board_filename, detected_mcu)

        # Build category choices from the catalog (skip unsafe_reference)
        category_choices = [
            {
                "name":  f"  🟢  {t('wizard.display_no_display')}",
                "value": "none",
            },
        ]

        visible_categories = ["basic_lcd", "touchscreen", "oled_mini"]
        for cat_id in visible_categories:
            cat = catalog.get(cat_id, {})
            if cat:
                category_choices.append({
                    "name":  f"  {cat.get('label', cat_id)}",
                    "value": f"cat:{cat_id}",
                })

        category_choices.extend([
            {
                "name":  f"  🔍  {t('wizard.display_manual_mode')}",
                "value": "__manual__",
            },
            {"name": t("choice.back"), "value": _BACK},
            {"name": t("choice.quit"), "value": _QUIT},
        ])

        ans_a = questionary.select(
            t("wizard.display_use_prompt"),
            choices=category_choices,
            style=custom_style,
        ).ask()

        if ans_a is None or ans_a == _QUIT:
            raise WizardExit()
        if ans_a == _BACK:
            result["display_choice"] = _BACK
            return result

        # ── No display ────────────────────────────────────────────────────────
        if ans_a == "none":
            result["display_choice"]       = "none"
            result["display_section"]      = None
            result["display_compat_class"] = None
            result["display_risk_accepted"] = True
            print(f"\n  {_G}[OK]  No display selected. KACE will omit display sections from the config.{_RS}\n")
            return result

        # ── Manual search directly from Step A ───────────────────────────────
        if ans_a == "__manual__":
            display_key, analysis = _run_manual_search(board_filename, detected_mcu, parsed_cfg)
            if display_key is None:
                continue  # Back to Step A

            accepted = _confirm_risk(analysis, display_key)
            if not accepted:
                continue  # Back to Step A

            comp_class = analysis.get("compatibility_class", "experimental")
            choice_prefix = "override" if comp_class == "unsafe" else "manual"
            result["display_choice"]        = f"{choice_prefix}:{display_key}"
            result["display_section"]       = display_key
            result["display_compat_class"]  = comp_class
            result["display_risk_accepted"] = True
            return result

        # ── Category selected → Step B ────────────────────────────────────────
        if ans_a.startswith("cat:"):
            cat_id = ans_a[4:]

            while True:
                # ── Step B: Recommended display list ──────────────────────────
                print(f"\n  {_B}{t('wizard.display_recommended_header')}{_RS}")

                # Filter recommended buckets to only the members of this category
                cat_members = set(catalog.get(cat_id, {}).get("members", []))

                filtered_recommended: dict[str, list] = {
                    "fully_compatible":        [],
                    "compatible_with_adapter": [],
                    "experimental":            [],
                    "unsafe":                  [],
                }
                for class_key, entries in recommended.items():
                    for entry_tuple in entries:
                        if entry_tuple[0] in cat_members:
                            filtered_recommended[class_key].append(entry_tuple)

                choices_b = _build_recommended_choices(
                    filtered_recommended, board_filename, detected_mcu
                )

                ans_b = questionary.select(
                    t("wizard.display_category_prompt"),
                    choices=choices_b,
                    style=custom_style,
                ).ask()

                if ans_b is None or ans_b == _QUIT:
                    raise WizardExit()
                if ans_b == _BACK:
                    break  # Back to Step A

                if ans_b == "__manual__":
                    # ── Step C: Manual search from Step B ─────────────────────
                    display_key, analysis = _run_manual_search(board_filename, detected_mcu, parsed_cfg)
                    if display_key is None:
                        continue  # Back to Step B

                    accepted = _confirm_risk(analysis, display_key)
                    if not accepted:
                        continue  # Back to Step B

                    comp_class = analysis.get("compatibility_class", "experimental")
                    choice_prefix = "override" if comp_class == "unsafe" else "manual"
                    result["display_choice"]        = f"{choice_prefix}:{display_key}"
                    result["display_section"]       = display_key
                    result["display_compat_class"]  = comp_class
                    result["display_risk_accepted"] = True
                    return result

                if ans_b.startswith("pick:"):
                    display_key = ans_b[5:]

                    # ── Step D: Risk summary for recommended pick ──────────────
                    # Run analysis even for recommended to show condensed summary
                    analysis = run_manual_selection_analysis(
                        display_key, board_filename, detected_mcu, parsed_cfg
                    )
                    comp_class = analysis.get("compatibility_class", "experimental")

                    # For fully compatible picks, skip the full panel — just confirm
                    if comp_class != "fully_compatible":
                        _print_risk_panel(analysis, display_key)

                    accepted = _confirm_risk(analysis, display_key)
                    if not accepted:
                        continue  # Back to Step B

                    choice_prefix = "override" if comp_class == "unsafe" else "recommended"
                    result["display_choice"]        = f"{choice_prefix}:{display_key}"
                    result["display_section"]       = display_key
                    result["display_compat_class"]  = comp_class
                    result["display_risk_accepted"] = True

                    color, badge = _CLASS_BADGE.get(comp_class, (_G, "✅"))
                    print(f"\n  {color}{badge} Display selected: {_friendly(display_key)}{_RS}\n")
                    return result

        # Fallback: loop back to Step A for any unhandled value
