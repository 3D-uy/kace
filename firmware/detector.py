import glob
import re
import os
import questionary
from core.style import custom_style

def discover_mcu_hardware(interactive=True):
    """
    Auto-discovers the connected printer MCU via USB serial.

    Priority order (matches KACE / Klipper documentation):
      1. /dev/serial/by-id/*    — persistent symlinks, best option
      2. /dev/serial/by-path/*  — fallback if udev didn't create by-id links
      3. /dev/ttyUSB*           — raw USB-Serial adapters (CH340, CP2102, etc.)
      4. /dev/ttyACM*           — raw USB CDC-ACM devices (most STM32/RP2040)
      5. printer.cfg serial:    — read existing Klipper config as last resort

    NOTE: ttyAMA0 / ttyS0 are the Pi's own GPIO UART pins, NOT a printer MCU.
          They are deliberately excluded from the search.

    Returns a dict with:
      - mcu_path    e.g. /dev/serial/by-id/usb-Klipper_stm32f446xx_...-if00
      - derived_mcu e.g. stm32f446xx  (None if port found but not Klipper)
      - hint        e.g. usb / uart / can / manual / skip
    """
    import sys

    while True:
        # 1. Persistent by-id symlinks (best — survives reboots, survives USB hubs)
        ports = glob.glob('/dev/serial/by-id/*')

        # 2. by-path fallback (Debian Bookworm sometimes doesn't populate by-id)
        if not ports:
            ports = glob.glob('/dev/serial/by-path/*')

        # 3. Raw device nodes (board not yet running Klipper, or kernel without udev rules)
        if not ports:
            ports.extend(sorted(glob.glob('/dev/ttyUSB*')))
            ports.extend(sorted(glob.glob('/dev/ttyACM*')))

        # 4. printer.cfg scrape — last resort if udev is completely broken
        if not ports:
            cfg_candidates = [
                "~/printer_data/config/printer.cfg",
                "~/klipper_config/printer.cfg",
                "~/printer.cfg",
            ]
            for p in cfg_candidates:
                cfg_path = os.path.expanduser(p)
                if os.path.isfile(cfg_path):
                    try:
                        with open(cfg_path, "r") as f:
                            content = f.read()
                        mcu_match = re.search(
                            r'\[mcu\][^\[]*serial:\s*([^\s\n]+)', content, re.MULTILINE
                        )
                        if mcu_match:
                            found_port = mcu_match.group(1).strip()
                            if found_port not in ports:
                                ports.append(found_port)
                            break
                    except Exception:
                        pass

        context = {"mcu_path": None, "derived_mcu": None, "hint": None}

        if not ports:
            if not interactive:
                return context
            
            print("\n\033[91m[!] No MCU serial devices detected.\033[0m")
            print("\033[93mPlease verify the following hardware diagnostics:\033[0m")
            print("  \033[96m• USB Connection\033[0m: Ensure the USB cable is securely connected to both the Pi and the board. Try another cable/port.")
            print("  \033[96m• Firmware\033[0m: Verify Klipper firmware has been flashed to the controller. If in bootloader mode, it won't appear.")
            print("  \033[96m• Board Power\033[0m: Verify the board is powered on (check status LEDs or power supply switches).")
            print("  \033[96m• Permissions\033[0m: Verify that the current user has access to serial devices (e.g. member of 'dialout').\n")
            
            ans = questionary.select(
                "How would you like to proceed?",
                choices=[
                    {"name": "🔄  Retry hardware discovery", "value": "retry"},
                    {"name": "⌨️   Skip / Enter serial path manually", "value": "manual"},
                    {"name": "❌  Quit", "value": "quit"}
                ],
                style=custom_style
            ).ask()

            if ans == "retry":
                continue
            elif ans == "manual":
                manual_path = questionary.text(
                    "Enter serial path manually (e.g. /dev/ttyUSB0, COM3, or leave blank to skip MCU detection):",
                    style=custom_style
                ).ask()
                if manual_path and manual_path.strip():
                    context["mcu_path"] = manual_path.strip()
                    context["hint"] = "manual"
                # Return context whether or not user gave a path — caller handles None mcu_path
                return context
            else:
                print("\033[93mExiting KACE.\033[0m")
                sys.exit(0)

        if interactive:
            if len(ports) == 1:
                choice = ports[0]
                print(f"\n\033[92m[✔ ] Connected MCU auto-detected:\033[0m \033[96m{choice}\033[0m\n")
            else:
                choice = questionary.select(
                    "Select connected MCU:", choices=ports, style=custom_style
                ).ask()

                if choice is None:
                    print("\033[93mExiting KACE.\033[0m")
                    sys.exit(0)
        else:
            # Non-interactive: prefer Klipper-flashed by-id paths, else first available
            klipper_ports = [p for p in ports if "klipper" in p.lower()]
            choice = klipper_ports[0] if klipper_ports else ports[0]

        context["mcu_path"] = choice

        # Parse MCU chip name and connection type from the symlink name
        # e.g. usb-Klipper_stm32f446xx_1D003600105350534E303620-if00
        #      usb-Klipper_lpc1769_16A0FF0AA8943BAF26B5685CC22000F5-if00
        match = re.search(r'(usb|can|uart)[_-]Klipper_([a-zA-Z0-9]+)', choice, re.IGNORECASE)
        if match:
            context["hint"] = match.group(1).lower()
            context["derived_mcu"] = match.group(2).lower()
        else:
            # Unrecognised path — derive hint from device name only
            if "usb" in choice.lower() or "ttyUSB" in choice or "ttyACM" in choice:
                context["hint"] = "usb"
            elif "can" in choice.lower():
                context["hint"] = "can"

        return context
