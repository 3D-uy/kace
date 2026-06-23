# Firmware module for KACE
from .firmware_generator import generate_firmware_config
from .validator import validate_config

try:
    from .builder import build_firmware_orchestrator
    from .derivation import derive_config
    from .detector import discover_mcu_hardware
    _HAS_INTERACTIVE = True
except ImportError:
    build_firmware_orchestrator = None
    derive_config = None
    discover_mcu_hardware = None
    _HAS_INTERACTIVE = False

__all__ = [
    "generate_firmware_config",
    "validate_config"
]
if _HAS_INTERACTIVE:
    __all__.extend([
        "build_firmware_orchestrator",
        "derive_config",
        "discover_mcu_hardware"
    ])

