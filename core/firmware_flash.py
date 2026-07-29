"""Verification for firmware copied to a printer-controller SD card."""

from core.moonraker import DEFAULT_PORT, get_klipper_state, get_mcu_versions
from core.moonraker_deployer import (
    Deployer,
    DeployResult,
    DeployState,
    DeploymentManifest,
    McuTarget,
)


class _MoonrakerFirmwareClient:
    """Minimal Moonraker adapter for the verification-only workflow."""

    def __init__(self, host: str, port: int, api_key: str = None):
        self.host = host
        self.port = port
        self.api_key = api_key

    def get_klippy_state(self) -> str:
        return get_klipper_state(self.host, self.port, api_key=self.api_key)

    def get_mcu_versions(self) -> dict:
        return get_mcu_versions(self.host, self.port, api_key=self.api_key)


def verify_sd_card_flash(
    expected_version: str,
    mcu_name: str = "mcu",
    host: str = "localhost",
    port: int = DEFAULT_PORT,
    api_key: str = None,
    disconnect_cooldown_s: float = 2.0,
    disconnect_timeout_s: float = 45.0,
    reconnect_timeout_s: float = 180.0,
    poll_interval_s: float = 1.0,
) -> DeployResult:
    """Verify a physical SD-card flash after a printer-only power cycle.

    The Raspberry Pi remains on, so a temporary Klippy/Moonraker interruption
    is the expected signal that the printer controller went offline. The
    timeout parameters keep the default conservative while allowing callers
    and offline tests to tune the wait without changing global defaults.
    """
    manifest = DeploymentManifest(
        targets=[McuTarget(name=mcu_name, expected_version=expected_version)],
        printer_cfg_path="",
    )
    verifier = Deployer(_MoonrakerFirmwareClient(host, port, api_key), manifest)
    verifier.DISCONNECT_COOLDOWN_S = disconnect_cooldown_s
    verifier.DISCONNECT_TIMEOUT_S = disconnect_timeout_s
    verifier.RECONNECT_TIMEOUT_S = reconnect_timeout_s
    verifier.POLL_INTERVAL_S = poll_interval_s

    # Reuse Deployer's established polling and version validation primitives;
    # unlike Deployer.run(), this workflow intentionally never uploads config.
    verifier.state = DeployState.AWAITING_DISCONNECT
    if not verifier._wait_for_disconnect():
        return DeployResult(
            DeployState.TIMEOUT,
            "Printer MCU disconnect was not detected after the requested power cycle",
        )

    verifier.state = DeployState.AWAITING_RECONNECT
    outcome, versions = verifier._wait_for_reconnect(allow_transient_config_error=True)
    if outcome is verifier._ReconnectOutcome.ABORTED:
        return DeployResult(DeployState.ABORTED, "Cancelled during firmware verification")
    if outcome is verifier._ReconnectOutcome.TIMEOUT:
        return DeployResult(DeployState.TIMEOUT, "Printer did not come back online in time")
    if outcome is verifier._ReconnectOutcome.CONFIG_ERROR:
        return DeployResult(DeployState.CONFIG_ERROR, "Klipper reported shutdown/error after the power cycle")

    verifier.state = DeployState.VERIFYING_FIRMWARE
    wrong_version, not_visible = verifier._check_versions(versions)
    if wrong_version or not_visible:
        details = []
        if wrong_version:
            details.append("running old firmware: " + ", ".join(wrong_version))
        if not_visible:
            details.append("missing from Moonraker: " + ", ".join(not_visible))
        return DeployResult(DeployState.FAILED_FLASH, "; ".join(details), mcu_versions=versions)

    verifier.state = DeployState.DONE
    return DeployResult(DeployState.DONE, "Firmware verified after power cycle", mcu_versions=versions)
