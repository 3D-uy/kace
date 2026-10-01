"""K14: Cheetah V2.0 identity from the pinned official profile header.

Klipper fe4eb865, config/generic-fysetc-cheetah-v2.0.cfg specifies
STM32F401 and 32KiB. Metadata must not grant a firmware flashing target.
"""

import pytest

from core.wizard.steps.hardware import _load_mcu_search_terms
from core.wizard.steps.sensors import _get_mcu_for_board
from firmware.boards.resolver import BoardResolver, ResolutionStatus
from firmware.derivation import derive_config


PROFILE = "generic-fysetc-cheetah-v2.0.cfg"


def test_cheetah_v2_identity_reaches_sensor_consumer():
    assert _get_mcu_for_board(PROFILE) == "stm32f401"
    terms = _load_mcu_search_terms()
    assert "cheetah-v2.0" in terms["stm32f401"]
    assert "cheetah-v2.0" not in terms.get("stm32f042", [])


def test_cheetah_v2_legacy_derivation_keeps_official_bootloader():
    config = derive_config(_get_mcu_for_board(PROFILE), hint="usb")
    assert config["CONFIG_FLASH_START"] == "0x8000"
    assert config["CONFIG_MCU_STM32F401"] == "y"
    # Legacy preparation is not evidence of a validated Kconfig build or flash.
    assert BoardResolver().resolve(PROFILE).status is ResolutionStatus.NOT_FOUND


@pytest.mark.parametrize("profile", [
    "generic-fysetc-cheetah-v1.1.cfg",
    "generic-fysetc-cheetah-v1.2.cfg",
    "generic-fysetc-cheetah-v3.0.cfg",
])
def test_other_cheetah_revisions_do_not_inherit_v2_metadata(profile):
    assert _get_mcu_for_board(profile) == ""
    assert BoardResolver().resolve(profile).status is ResolutionStatus.NOT_FOUND
