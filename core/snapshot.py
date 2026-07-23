# core/snapshot.py
#
# DeploymentSnapshot — immutable point-in-time record of a printer's configuration
# state captured before a KACE deployment begins.
#
# Design principles:
#   - The dataclass is frozen: nothing downstream may mutate it.
#   - capture_snapshot() never raises to the caller; a network failure returns None.
#   - restore_snapshot() always uploads includes before printer.cfg (safe order).
#   - Zero additional dependencies — only stdlib + existing core/moonraker.py helpers.

from __future__ import annotations

import datetime
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from core.moonraker import download_printer_cfg, upload_printer_cfg, restart_firmware


# ── Public dataclass ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DeploymentSnapshot:
    """Immutable record of a printer's configuration state at backup time.

    Captured before a deployment begins so that any subsequent failure can
    be reversed by calling restore_snapshot().

    Fields
    ------
    deployment_id : str
        UUID4 string — stable identifier across rollback retries for the
        same deployment attempt.
    timestamp : str
        ISO-8601 UTC timestamp at the moment of capture.
    board : str
        Board identifier string from the KACE manifest (e.g. "btt_octopus_pro_446").
        Empty string for config-only deployments that did not compile firmware.
    kace_version : str
        KACE version string at capture time, or "unknown".
    firmware_fingerprint : str
        Semicolon-separated "mcu_name=version" pairs describing the MCU firmware
        versions that were running at backup time (before the new flash).
        Empty string when the printer was unreachable or had no MCUs visible.
    mcus : tuple[str, ...]
        Ordered tuple of MCU Moonraker object names from the deployment manifest,
        e.g. ("mcu",) or ("mcu", "mcu toolboard").
    dev_deploy : bool
        True when the --dev-deploy flag was active for this deployment.
    config_files : dict[str, bytes]
        Mapping of filename -> raw bytes for every configuration file that was
        successfully downloaded from Moonraker's config root at backup time.
        Always includes "printer.cfg" if it existed on the target.
    """
    deployment_id: str
    timestamp: str
    board: str
    kace_version: str
    firmware_fingerprint: str
    mcus: Tuple[str, ...]
    dev_deploy: bool
    config_files: Dict[str, bytes] = field(default_factory=dict, hash=False, compare=False)


# ── Public helpers ────────────────────────────────────────────────────────────

def capture_snapshot(
    host: str,
    port: int,
    filenames: List[str],
    *,
    manifest_mcus: Tuple[str, ...] = (),
    api_key: Optional[str] = None,
    dev_deploy: bool = False,
    board: str = "",
    kace_version: str = "unknown",
    firmware_fingerprint: str = "",
) -> Optional[DeploymentSnapshot]:
    """Download configuration files from Moonraker and build a DeploymentSnapshot.

    Parameters
    ----------
    host, port : str, int
        Moonraker connection target.
    filenames : list[str]
        Filenames to attempt to download from the config root.  Files that are
        absent or return an error are silently skipped — their absence does not
        prevent capture.
    manifest_mcus : tuple[str, ...]
        MCU Moonraker object names from the current deployment manifest.
    api_key : str | None
        Optional Moonraker API key.
    dev_deploy : bool
        Whether --dev-deploy is active.
    board : str
        Board identifier string.
    kace_version : str
        KACE version string.
    firmware_fingerprint : str
        MCU version string(s) at capture time (already queried by the caller
        who has Moonraker access at this point).  Pass "" if not yet known.

    Returns
    -------
    DeploymentSnapshot | None
        None if Moonraker is completely unreachable (connection-level failure
        on every download attempt). A partial snapshot (with fewer files) is
        returned if only some downloads fail — backup failure must never abort
        a deployment.
    """
    captured: Dict[str, bytes] = {}
    any_attempted = False

    for filename in filenames:
        any_attempted = True
        try:
            ok, data = download_printer_cfg(host, port, filename, api_key=api_key)
            if ok and isinstance(data, bytes):
                captured[filename] = data
        except (OSError, ConnectionError, TimeoutError):
            # Network error for this file — skip silently.
            pass
        except Exception as _snap_err:
            if os.environ.get("KACE_DEBUG") == "1":
                print(f"[DEBUG] Unexpected error capturing snapshot for '{filename}': {_snap_err}")

    # If we attempted downloads but got nothing at all, Moonraker was unreachable.
    # Returning None lets the caller decide whether to abort or proceed without backup.
    if any_attempted and not captured:
        return None

    return DeploymentSnapshot(
        deployment_id=str(uuid.uuid4()),
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        board=board,
        kace_version=kace_version,
        firmware_fingerprint=firmware_fingerprint,
        mcus=tuple(manifest_mcus),
        dev_deploy=dev_deploy,
        config_files=dict(captured),
    )


def restore_snapshot(
    snapshot: DeploymentSnapshot,
    host: str,
    port: int,
    *,
    api_key: Optional[str] = None,
    issue_restart: bool = True,
) -> List[str]:
    """Re-upload all files from a snapshot in safe order, then restart Klipper.

    Upload order:
        1. All files except printer.cfg (in insertion order).
        2. printer.cfg last — it references the include files so it must be
           uploaded after all includes are already in place.

    Parameters
    ----------
    snapshot : DeploymentSnapshot
        The snapshot to restore.
    host, port : str, int
        Moonraker connection target.
    api_key : str | None
        Optional Moonraker API key.
    issue_restart : bool
        If True (default), issue a FIRMWARE_RESTART after all files are uploaded.
        Set to False in tests or when the caller wants to control the restart.

    Returns
    -------
    list[str]
        Names of files that failed to upload.  An empty list means full success.
        The restart is still attempted even if some files failed, to leave Klipper
        in the best possible state with whatever was successfully restored.
    """
    failed: List[str] = []

    # Build upload order: includes first, printer.cfg last.
    ordered = [f for f in snapshot.config_files if f != "printer.cfg"]
    if "printer.cfg" in snapshot.config_files:
        ordered.append("printer.cfg")

    for filename in ordered:
        file_bytes = snapshot.config_files[filename]
        tmp_path = None
        try:
            # Write bytes to a temp file so upload_printer_cfg can read it.
            # R2-03: Create file and store tmp_path before writing to guarantee
            # cleanup in finally block even if tmp.write() raises an exception.
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".cfg")
            tmp_path = tmp.name
            with tmp:
                tmp.write(file_bytes)
            ok, msg = upload_printer_cfg(host, port, tmp_path, filename=filename, api_key=api_key)
            if not ok:
                failed.append(filename)
        except Exception:
            failed.append(filename)
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    if issue_restart:
        try:
            restart_firmware(host, port, api_key=api_key)
        except Exception:
            pass  # Restart failure is non-fatal for the restore operation itself.

    return failed
