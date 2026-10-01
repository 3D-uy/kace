# Selected-board enable and power outputs

Byte-for-byte official Klipper profiles at fe4eb8650bd7de4c2100a14eaf09b0965c430e29,
also compared with ce7002bedf37e938bb483572949f3703ac6476cb in the B11 oracle.
CRAMPS machine_enable starts high and shuts down low. CR-10 Smart Pro power stays
high on shutdown; its separate PA0 firmware-startup requirement is not established
by preserving printer.cfg. CRAMPS requires external Beaglebone pinmux and host MCU
setup. These fixtures do not certify either board's complete physical behavior.
