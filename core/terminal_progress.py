"""Terminal projection for InstallationWorkflow events.

The workflow remains the only source of truth.  This module consumes the same
event dictionaries sent to KACE Studio and never advances or interprets the
deployment state machine itself.
"""

from __future__ import annotations

import os
import sys
from typing import Callable, Optional


TERMINAL_ERRORS = frozenset({
    "ABORTED",
    "CANCELLED",
    "FAILED_FLASH",
    "TIMEOUT",
    "CONFIG_ERROR",
    "FAILED_UPLOAD",
    "FAILED_MONITOR",
    "FAILED_PRECONDITION",
})

MILESTONES = (
    "Firmware media prepared",
    "Safe media installation",
    "Physical action confirmed",
    "Firmware flashing",
    "MCU reenumerated",
    "MCU identity confirmed",
    "Moonraker connected",
    "Klipper ready",
    "MCU registered",
    "Firmware verified",
    "Configuration installed",
    "Installation completed",
)

# View-only projection from canonical workflow states to milestone positions.
# Values are (last completed milestone, current milestone).
_POSITIONS = {
    "BACKUP": (-1, 0),
    "COPYING_FIRMWARE": (-1, 0),
    "MEDIA_PREPARED": (0, 1),
    "AWAITING_MEDIA_INSTALLATION": (0, 1),
    "AWAITING_POWER_CYCLE": (0, 1),
    "AWAITING_BOOTLOADER": (2, 3),
    "FLASHING": (2, 3),
    "AWAITING_REENUMERATION": (3, 4),
    "AWAITING_MCU_CONFIRMATION": (4, 5),
    "MCU_IDENTITY_CONFIRMED": (5, 6),
    "FIRMWARE_COPIED": (0, 1),
    "MONITOR_ARMED": (0, 1),
    "AWAITING_DISCONNECT": (0, 1),
    "MCU_ABSENT": (0, 1),
    "AWAITING_RECONNECT": (2, 3),
    "MCU_PRESENT": (5, 6),
    "WAITING_MOONRAKER": (5, 6),
    "MOONRAKER_ONLINE": (6, 7),
    "WAITING_KLIPPER_READY": (6, 7),
    "KLIPPER_READY": (7, 8),
    "WAITING_MCU_REGISTRATION": (7, 8),
    "MCU_REGISTERED": (8, 9),
    "VERIFYING_FIRMWARE": (8, 9),
    "FIRMWARE_VERIFIED": (9, 10),
    "APPLYING_CONFIG": (9, 10),
    "VERIFYING_UPLOAD": (9, 10),
    "FIRMWARE_RESTART": (9, 10),
    "VERIFYING_CONFIG": (9, 10),
    "ROLLING_BACK": (9, 10),
    "VERIFYING_ROLLBACK": (9, 10),
    "DONE": (len(MILESTONES) - 1, -1),
}


class WorkflowEventEmitter:
    """Fan out one canonical event to independent, failure-isolated views."""

    def __init__(self, *subscribers: Callable[[dict], None]):
        self.subscribers = subscribers

    def __call__(self, event: dict) -> None:
        for subscriber in self.subscribers:
            try:
                subscriber(event)
            except Exception:
                # Progress output must never change the installation result.
                continue

    def close(self) -> None:
        for subscriber in self.subscribers:
            close = getattr(subscriber, "close", None)
            if close is None:
                continue
            try:
                close()
            except Exception:
                continue


class TerminalProgressRenderer:
    """Render workflow events dynamically on TTYs or linearly elsewhere."""

    ENTER_ALTERNATE = "\033[?1049h"
    LEAVE_ALTERNATE = "\033[?1049l"
    CLEAR_HOME = "\033[2J\033[H"

    def __init__(self, stream=None, *, interactive: Optional[bool] = None):
        self.stream = stream if stream is not None else sys.stdout
        self.interactive = self._detect_interactive() if interactive is None else bool(interactive)
        self._sequences = {}
        self._views = {}
        self._alternate_active = False

    def _detect_interactive(self) -> bool:
        try:
            is_tty = bool(self.stream.isatty())
        except (AttributeError, OSError):
            return False
        term = os.environ.get("TERM", "").strip().lower()
        if not is_tty or term in ("", "dumb", "unknown"):
            return False
        if os.environ.get("CI") or os.environ.get("KACE_TESTING") == "1":
            return False
        return True

    def start(self) -> None:
        if not self.interactive or self._alternate_active:
            return
        # Mark ownership before writing so close() can still attempt to restore
        # the terminal if a partial write or flush fails.
        self._alternate_active = True
        self.stream.write(self.ENTER_ALTERNATE + self.CLEAR_HOME)
        self.stream.write("KACE installation\n\nWaiting for workflow events...\n")
        self.stream.flush()

    @staticmethod
    def _valid_event(event: dict) -> bool:
        if not isinstance(event, dict):
            return False
        workflow_id = event.get("workflow_id")
        sequence = event.get("sequence")
        state = event.get("state")
        return (
            isinstance(workflow_id, str) and bool(workflow_id.strip())
            and isinstance(sequence, int) and not isinstance(sequence, bool) and sequence >= 1
            and isinstance(state, str) and bool(state.strip())
        )

    def __call__(self, event: dict) -> None:
        if not self._valid_event(event):
            return
        workflow_id = event["workflow_id"]
        sequence = event["sequence"]
        if sequence <= self._sequences.get(workflow_id, 0):
            return

        state = event["state"]
        previous = self._views.get(workflow_id)
        progress_state = (
            (previous or {}).get("progress_state", (previous or {}).get("state", ""))
            if state in TERMINAL_ERRORS else state
        )
        view = {
            "workflow_id": workflow_id,
            "sequence": sequence,
            "state": state,
            "detail": event.get("detail", "") if isinstance(event.get("detail", ""), str) else "",
            "progress_state": progress_state,
        }
        self._sequences[workflow_id] = sequence
        self._views[workflow_id] = view

        if self.interactive:
            self.start()
            self._render_dynamic(view)
            if state == "DONE" or state in TERMINAL_ERRORS:
                self.close()
                self._render_snapshot(view)
        else:
            self._render_linear(view)

    def _position(self, view: dict) -> tuple[int, int]:
        state = view["progress_state"] if view["state"] in TERMINAL_ERRORS else view["state"]
        return _POSITIONS.get(state, (-1, 0))

    def _snapshot_lines(self, view: dict) -> list[str]:
        state = view["state"]
        is_done = state == "DONE"
        is_error = state in TERMINAL_ERRORS
        completed_through, current_index = self._position(view)
        short_id = view["workflow_id"][:8]
        status = "DONE" if is_done else (f"ERROR: {state}" if is_error else "IN PROGRESS")
        lines = [f"KACE installation [{short_id}]", f"Status: {status}", ""]
        for index, label in enumerate(MILESTONES):
            if is_done or index <= completed_through:
                marker = "[x]"
            elif index == current_index:
                marker = "[!]" if is_error else "[>]"
            else:
                marker = "[ ]"
            lines.append(f"{marker} {label}")
        lines.extend(["", f"Detail: {view['detail'] or state}"])
        if not is_done and not is_error:
            lines.append("Press Ctrl+C to cancel safely.")
        return lines

    def _render_dynamic(self, view: dict) -> None:
        self.stream.write(self.CLEAR_HOME)
        self.stream.write("\n".join(self._snapshot_lines(view)) + "\n")
        self.stream.flush()

    def _render_snapshot(self, view: dict) -> None:
        self.stream.write("\n".join(self._snapshot_lines(view)) + "\n")
        self.stream.flush()

    def _render_linear(self, view: dict) -> None:
        state = view["state"]
        completed, current = self._position(view)
        if state == "DONE":
            outcome = "DONE"
            progress = f"{len(MILESTONES)}/{len(MILESTONES)}"
        elif state in TERMINAL_ERRORS:
            outcome = "ERROR"
            progress = f"{max(completed + 1, 0)}/{len(MILESTONES)}"
        else:
            outcome = "CURRENT"
            progress = f"{max(current + 1, 1)}/{len(MILESTONES)}"
        detail = view["detail"] or state
        self.stream.write(
            f"[KACE {view['workflow_id'][:8]} #{view['sequence']:03d}] "
            f"[{outcome} {progress}] {state}: {detail}\n"
        )
        self.stream.flush()

    def close(self) -> None:
        if not self._alternate_active:
            return
        self.stream.write(self.LEAVE_ALTERNATE)
        self.stream.flush()
        self._alternate_active = False
