#!/bin/bash
# entrypoint.sh — Docker container entrypoint script for KACE simulation.

# Enable colored console
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color
DIM='\033[2m'

# Check if mock_moonraker is running and stop it
cleanup_moonraker() {
    pkill -f "mock_moonraker.py" 2>/dev/null
}

# Clean folders and services mock files
clean_environment() {
    echo -e "${DIM}[*] Cleaning up simulation environment...${NC}"
    # Clean systemd mock services list
    rm -f /tmp/mock_services

    # Clean home directories
    rm -rf ~/klipper ~/moonraker ~/mainsail ~/fluidd ~/crowsnest ~/printer_data ~/klipper_config

    # Clean dev paths (using /tmp/dev so we don't pollute real /dev inside the container,
    # but wait, KACE checks "/dev/serial/by-id/*" and "/dev/ttyUSB*".
    # In Docker, we can safely write to /dev/ because we are root and it is isolated.
    # So we can clean our mock /dev/serial and ttyUSB devices.
    rm -rf /dev/serial
    rm -f /dev/ttyUSB* /dev/ttyACM*
}

setup_mainsailos() {
    echo -e "${GREEN}[+] Setting up MainsailOS Scenario...${NC}"
    # Services
    echo -e "klipper\nmoonraker\ncrowsnest" > /tmp/mock_services

    # Directories
    mkdir -p ~/klipper ~/moonraker ~/mainsail ~/crowsnest
    mkdir -p ~/printer_data/config

    # MCU: BTT Octopus v1.1 (stm32f446xx)
    mkdir -p /dev/serial/by-id /dev/serial/by-path
    touch /dev/serial/by-id/usb-Klipper_stm32f446xx_Octopus-v1.1-if00
    touch /dev/serial/by-path/platform-fd500000.pcie-usb-0:1.3:1.0-port0

    echo -e "    - Klipper: Installed & Running"
    echo -e "    - Moonraker: Installed & Running (API Mock Port: 7125)"
    echo -e "    - Mainsail: Installed"
    echo -e "    - MCU Symlink: /dev/serial/by-id/usb-Klipper_stm32f446xx_Octopus-v1.1-if00"
}

setup_fluiddpi() {
    echo -e "${GREEN}[+] Setting up FluiddPI Scenario...${NC}"
    # Services
    echo -e "klipper\nmoonraker" > /tmp/mock_services

    # Directories
    mkdir -p ~/klipper ~/moonraker ~/fluidd
    mkdir -p ~/printer_data/config

    # MCU: SKR Pico (rp2040)
    mkdir -p /dev/serial/by-id /dev/serial/by-path
    touch /dev/serial/by-id/usb-Klipper_rp2040_SKRPico-if00
    touch /dev/serial/by-path/platform-fd500000.pcie-usb-0:1.1:1.0-port0

    echo -e "    - Klipper: Installed & Running"
    echo -e "    - Moonraker: Installed & Running (API Mock Port: 7125)"
    echo -e "    - Fluidd: Installed"
    echo -e "    - MCU Symlink: /dev/serial/by-id/usb-Klipper_rp2040_SKRPico-if00"
}

setup_lpc1769() {
    echo -e "${GREEN}[+] Setting up MainsailOS + BTT SKR 1.4 Turbo (LPC1769) Scenario...${NC}"
    # Services
    echo -e "klipper\nmoonraker\ncrowsnest" > /tmp/mock_services

    # Directories
    mkdir -p ~/klipper ~/moonraker ~/mainsail ~/crowsnest
    mkdir -p ~/printer_data/config

    # MCU: BTT SKR 1.4 Turbo (lpc1769)
    mkdir -p /dev/serial/by-id /dev/serial/by-path
    touch /dev/serial/by-id/usb-Klipper_lpc1769_SKR14Turbo-if00
    touch /dev/serial/by-path/platform-fd500000.pcie-usb-0:1.2:1.0-port0

    echo -e "    - Klipper: Installed & Running"
    echo -e "    - Moonraker: Installed & Running (API Mock Port: 7125)"
    echo -e "    - Mainsail: Installed"
    echo -e "    - MCU Symlink: /dev/serial/by-id/usb-Klipper_lpc1769_SKR14Turbo-if00"
}

setup_stm32f103() {
    echo -e "${GREEN}[+] Setting up MainsailOS + Creality v4.2.2 (STM32F103) Scenario...${NC}"
    # Services
    echo -e "klipper\nmoonraker" > /tmp/mock_services

    # Directories
    mkdir -p ~/klipper ~/moonraker ~/mainsail
    mkdir -p ~/printer_data/config

    # MCU: Creality v4.2.2 (stm32f103)
    mkdir -p /dev/serial/by-id /dev/serial/by-path
    touch /dev/serial/by-id/usb-Klipper_stm32f103xe_Creality422-if00
    touch /dev/serial/by-path/platform-fd500000.pcie-usb-0:1.4:1.0-port0

    echo -e "    - Klipper: Installed & Running"
    echo -e "    - Moonraker: Installed & Running (API Mock Port: 7125)"
    echo -e "    - Mainsail: Installed"
    echo -e "    - MCU Symlink: /dev/serial/by-id/usb-Klipper_stm32f103xe_Creality422-if00"
}

setup_atmega2560() {
    echo -e "${GREEN}[+] Setting up MainsailOS + RAMPS 1.4 (ATmega2560) Scenario...${NC}"
    # Services
    echo -e "klipper\nmoonraker" > /tmp/mock_services

    # Directories
    mkdir -p ~/klipper ~/moonraker ~/mainsail
    mkdir -p ~/printer_data/config

    # MCU: RAMPS 1.4 (atmega2560)
    mkdir -p /dev/serial/by-id /dev/serial/by-path
    touch /dev/serial/by-id/usb-Klipper_atmega2560_RAMPS14-if00
    touch /dev/serial/by-path/platform-fd500000.pcie-usb-0:1.5:1.0-port0

    echo -e "    - Klipper: Installed & Running"
    echo -e "    - Moonraker: Installed & Running (API Mock Port: 7125)"
    echo -e "    - Mainsail: Installed"
    echo -e "    - MCU Symlink: /dev/serial/by-id/usb-Klipper_atmega2560_RAMPS14-if00"
}

setup_esp32() {
    echo -e "${GREEN}[+] Setting up MainsailOS + MKS TinyBee (ESP32) Scenario...${NC}"
    # Services
    echo -e "klipper\nmoonraker" > /tmp/mock_services

    # Directories
    mkdir -p ~/klipper ~/moonraker ~/mainsail
    mkdir -p ~/printer_data/config

    # MCU: MKS TinyBee (esp32)
    mkdir -p /dev/serial/by-id /dev/serial/by-path
    touch /dev/serial/by-id/usb-Klipper_esp32_TinyBee-if00
    touch /dev/serial/by-path/platform-fd500000.pcie-usb-0:1.6:1.0-port0

    echo -e "    - Klipper: Installed & Running"
    echo -e "    - Moonraker: Installed & Running (API Mock Port: 7125)"
    echo -e "    - Mainsail: Installed"
    echo -e "    - MCU Symlink: /dev/serial/by-id/usb-Klipper_esp32_TinyBee-if00"
}

setup_atmega1284p() {
    echo -e "${GREEN}[+] Setting up MainsailOS + Melzi (ATmega1284p) Scenario...${NC}"
    # Services
    echo -e "klipper\nmoonraker" > /tmp/mock_services

    # Directories
    mkdir -p ~/klipper ~/moonraker ~/mainsail
    mkdir -p ~/printer_data/config

    # MCU: Melzi (atmega1284p)
    mkdir -p /dev/serial/by-id /dev/serial/by-path
    touch /dev/serial/by-id/usb-Klipper_atmega1284p_Melzi-if00
    touch /dev/serial/by-path/platform-fd500000.pcie-usb-0:1.7:1.0-port0

    echo -e "    - Klipper: Installed & Running"
    echo -e "    - Moonraker: Installed & Running (API Mock Port: 7125)"
    echo -e "    - Mainsail: Installed"
    echo -e "    - MCU Symlink: /dev/serial/by-id/usb-Klipper_atmega1284p_Melzi-if00"
}

setup_cleanpi() {
    echo -e "${GREEN}[+] Setting up Clean Pi / Raspberry Pi OS Scenario...${NC}"
    # No directories, no mock services

    # MCU: Raw board not running Klipper yet (CH340 USB-Serial adapter)
    mkdir -p /dev
    touch /dev/ttyUSB0

    echo -e "    - Klipper: Not Installed"
    echo -e "    - Moonraker: Not Installed"
    echo -e "    - MCU: Raw Serial node at /dev/ttyUSB0 (e.g. Creality board)"
}

setup_dual_mcu() {
    echo -e "${GREEN}[+] Setting up Dual MCU MainsailOS Scenario...${NC}"
    # Services
    echo -e "klipper\nmoonraker" > /tmp/mock_services

    # Directories
    mkdir -p ~/klipper ~/moonraker ~/mainsail
    mkdir -p ~/printer_data/config

    # MCUs: Octopus (stm32f446xx) + SKR Pico (rp2040)
    mkdir -p /dev/serial/by-id
    touch /dev/serial/by-id/usb-Klipper_stm32f446xx_Octopus-v1.1-if00
    touch /dev/serial/by-id/usb-Klipper_rp2040_SKRPico-if00

    echo -e "    - Klipper: Installed & Running"
    echo -e "    - Moonraker: Installed & Running"
    echo -e "    - MCUs: Multiple boards found in /dev/serial/by-id/"
}

start_moonraker_mock() {
    cleanup_moonraker
    python3 /workspace/docker/mock_moonraker.py > /tmp/mock_moonraker.log 2>&1 &
    sleep 0.5
    echo -e "${GREEN}[+] Started Mock Moonraker API daemon on port 7125.${NC}"
}

show_menu() {
    echo -e "\n=============================================="
    echo -e "  ⚙️  KACE DOCKER SIMULATION TESTBED MENU"
    echo -e "=============================================="
    echo -e "Select a Raspberry Pi environment to simulate:"
    echo -e " 1) MainsailOS (Klipper + Moonraker + Mainsail + BTT Octopus v1.1)"
    echo -e " 2) FluiddPI (Klipper + Moonraker + Fluidd + SKR Pico RP2040)"
    echo -e " 3) MainsailOS + BTT SKR 1.4 Turbo (Klipper + Moonraker + LPC1769)"
    echo -e " 4) MainsailOS + Creality v4.2.2 (Klipper + Moonraker + STM32F103)"
    echo -e " 5) MainsailOS + RAMPS 1.4 (Klipper + Moonraker + ATmega2560)"
    echo -e " 6) MainsailOS + MKS TinyBee (Klipper + Moonraker + ESP32)"
    echo -e " 7) MainsailOS + Melzi (Klipper + Moonraker + ATmega1284p)"
    echo -e " 8) Clean Pi OS (No Klipper/Moonraker, raw board at /dev/ttyUSB0)"
    echo -e " 9) Dual MCU Setup (Klipper + Moonraker + Octopus & SKR Pico)"
    echo -e " 10) Drop to Interactive Bash Shell"
    echo -e " 11) Run KACE Automated Test Suite (run_tests.py)"
    echo -e " 12) Exit"
    echo -e "=============================================="
    read -p "Enter choice [1-12]: " choice
}

# Ensure clean state at exit
trap "cleanup_moonraker" EXIT

while true; do
    show_menu
    case $choice in
        1)
            clean_environment
            setup_mainsailos
            start_moonraker_mock
            echo -e "${CYAN}[*] Starting KACE Wizard...${NC}"
            python3 /workspace/kace.py
            ;;
        2)
            clean_environment
            setup_fluiddpi
            start_moonraker_mock
            echo -e "${CYAN}[*] Starting KACE Wizard...${NC}"
            python3 /workspace/kace.py
            ;;
        3)
            clean_environment
            setup_lpc1769
            start_moonraker_mock
            echo -e "${CYAN}[*] Starting KACE Wizard...${NC}"
            python3 /workspace/kace.py
            ;;
        4)
            clean_environment
            setup_stm32f103
            start_moonraker_mock
            echo -e "${CYAN}[*] Starting KACE Wizard...${NC}"
            python3 /workspace/kace.py
            ;;
        5)
            clean_environment
            setup_atmega2560
            start_moonraker_mock
            echo -e "${CYAN}[*] Starting KACE Wizard...${NC}"
            python3 /workspace/kace.py
            ;;
        6)
            clean_environment
            setup_esp32
            start_moonraker_mock
            echo -e "${CYAN}[*] Starting KACE Wizard...${NC}"
            python3 /workspace/kace.py
            ;;
        7)
            clean_environment
            setup_atmega1284p
            start_moonraker_mock
            echo -e "${CYAN}[*] Starting KACE Wizard...${NC}"
            python3 /workspace/kace.py
            ;;
        8)
            clean_environment
            setup_cleanpi
            # Moonraker not running in clean Pi
            cleanup_moonraker
            echo -e "${CYAN}[*] Starting KACE Wizard...${NC}"
            python3 /workspace/kace.py
            ;;
        9)
            clean_environment
            setup_dual_mcu
            start_moonraker_mock
            echo -e "${CYAN}[*] Starting KACE Wizard...${NC}"
            python3 /workspace/kace.py
            ;;
        10)
            echo -e "${CYAN}[*] Dropping to bash shell. Type 'exit' to return to menu.${NC}"
            /bin/bash
            ;;
        11)
            echo -e "${CYAN}[*] Running KACE Test Suite...${NC}"
            python3 /workspace/tests/run_tests.py
            ;;
        12)
            echo -e "${GREEN}Goodbye!${NC}"
            exit 0
            ;;
        *)
            echo -e "${RED}Invalid option, try again.${NC}"
            ;;
    esac
done
