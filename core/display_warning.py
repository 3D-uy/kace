# core/display_warning.py
import questionary
from core.style import custom_style
from core.translations import t

def print_display_warning(findings: list) -> bool:
    """Print a formatted ANSI display compatibility warning block.

    For findings with status 'partial' or 'unsupported', prompts the user
    to confirm before continuing. Returns True to continue, False to abort.
    """
    Y  = "\033[93m"   # amber / warning
    R  = "\033[91m"   # red / error
    C  = "\033[96m"   # cyan / info
    G  = "\033[92m"   # green / ok
    B  = "\033[1m"    # bold
    RS = "\033[0m"    # reset
    W  = "\033[97m"   # bright white
    M  = "\033[96m"   # cyan
    O  = "\033[38;5;208m" # orange for experimental

    _CLASS_COLORS = {
        "fully_compatible":        G,
        "compatible_with_adapter": Y,
        "experimental":            O,
        "unsafe":                  R,
    }

    # If all findings are fully_compatible, skip warnings and prompts
    if all(f.get("compatibility_class") == "fully_compatible" for f in findings):
        return True

    # Check if we have any unsafe findings
    has_unsafe = any(f.get("compatibility_class") == "unsafe" for f in findings)
    needs_confirm = any(f.get("compatibility_class") != "fully_compatible" for f in findings)

    border_color = R if has_unsafe else Y

    print("")
    print(f"  {border_color}{B}{'═' * 52}{RS}")
    if has_unsafe:
        print(f"  {border_color}{B}  ⚠️  HARDWARE SAFETY WARNING — DO NOT IGNORE{RS}")
    else:
        print(f"  {border_color}{B}  ⚠️  {t('display.warning_header')}{RS}")
    print(f"  {border_color}{B}{'═' * 52}{RS}")
    print("")
    print(f"  {W}{t('display.oem_explanation')}{RS}")
    print("")

    for finding in findings:
        section = finding.get("section", "?")
        comp_class = finding.get("compatibility_class", "experimental")
        rec = finding.get("recommendation", "none")
        notes = finding.get("notes", [])
        sc = _CLASS_COLORS.get(comp_class, C)

        if comp_class == "compatible_with_adapter":
            status_str = t("display.class_compatible_with_adapter_mod")
        else:
            status_str = t(f"display.class_{comp_class}")
        print(f"  {B}{t('display.section_label')}:{RS} [{section}]   {sc}{B}{status_str}{RS}")

        if comp_class == "unsafe":
            print(f"\n  {R}{B}WHY THIS IS UNSAFE:{RS}")
            for note in notes:
                print(f"    {R}•{RS} {note}")
            
            risks = finding.get("damage_risks", [])
            if risks:
                print(f"\n  {R}{B}WHAT CAN BE PERMANENTLY DAMAGED:{RS}")
                for risk in risks:
                    print(f"    {R}•{RS} {risk}")
            
            mods = finding.get("required_modifications", [])
            if mods:
                print(f"\n  {W}{B}REQUIRED MODIFICATIONS:{RS}")
                for mod in mods:
                    print(f"    {W}•{RS} {mod}")
            
            print(f"\n  {Y}KACE will NOT generate a plug-and-play config for this combination.{RS}")
            print(f"  {Y}Generated config will contain safety comments and TODO markers.{RS}")

        elif comp_class == "compatible_with_adapter":
            print(f"\n  {Y}{B}WHY ADAPTER/MODIFICATION IS REQUIRED:{RS}")
            for note in notes:
                print(f"    {Y}•{RS} {note}")
                
            mods = finding.get("required_modifications", [])
            if mods:
                print(f"\n  {W}{B}REQUIRED ADAPTERS / STEPS:{RS}")
                for mod in mods:
                    print(f"    {W}•{RS} {mod}")
            
            risks = finding.get("damage_risks", [])
            if risks:
                print(f"\n  {Y}{B}POTENTIAL RISKS IF UNMODIFIED:{RS}")
                for risk in risks:
                    print(f"    {Y}•{RS} {risk}")

        else:
            for note in notes:
                print(f"    {C}•{RS} {note}")

        if rec == "disconnect":
            print(f"\n    {R}{B}{t('display.recommendation_disconnect')}{RS}")
        elif rec == "optional":
            print(f"\n    {Y}{t('display.recommendation_optional')}{RS}")

        print("")

    print(f"  {M}{t('display.web_ui_hint')}{RS}")
    print(f"  {C}{t('display.docs_hint')}{RS}")
    print(f"  {border_color}{B}{'─' * 52}{RS}")
    print("")

    if needs_confirm:
        if has_unsafe:
            ans = questionary.text(
                "Type \"I understand the risks\" to continue anyway, or press Enter to abort:",
                style=custom_style
            ).ask()
            if ans != "I understand the risks":
                return False
        else:
            ans = questionary.confirm(
                t("display.continue_prompt"),
                default=True,
                style=custom_style
            ).ask()
            if ans is None or not ans:
                return False
        print("")

    return True
