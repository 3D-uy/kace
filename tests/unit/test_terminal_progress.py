"""Tests for the native terminal view of InstallationWorkflow events."""

import io
import os
import unittest
from unittest.mock import patch

from core.moonraker_deployer import JsonEventSink
from core.terminal_progress import (
    MILESTONES,
    TERMINAL_ERRORS,
    TerminalProgressRenderer,
    WorkflowEventEmitter,
)


class FakeTTY(io.StringIO):
    def isatty(self):
        return True


def event(sequence=1, state="FIRMWARE_COPIED", workflow_id="workflow-123456", detail="ok"):
    return {
        "schema": 1,
        "workflow_id": workflow_id,
        "sequence": sequence,
        "state": state,
        "detail": detail,
    }


class TerminalProgressRendererTests(unittest.TestCase):
    def test_interactive_terminal_redraws_one_native_panel(self):
        output = FakeTTY()
        renderer = TerminalProgressRenderer(output, interactive=True)

        renderer.start()
        renderer(event(state="MCU_ABSENT", detail="physical MCU absent"))

        rendered = output.getvalue()
        self.assertIn(renderer.ENTER_ALTERNATE, rendered)
        self.assertGreaterEqual(rendered.count(renderer.CLEAR_HOME), 2)
        self.assertIn("KACE installation [workflow]", rendered)
        self.assertIn("[x] Firmware media prepared", rendered)
        self.assertIn("[>] Safe media installation", rendered)
        self.assertIn("[ ] Installation completed", rendered)
        self.assertIn("Press Ctrl+C to cancel safely.", rendered)

    def test_non_tty_output_is_linear_ascii_without_ansi(self):
        output = io.StringIO()
        renderer = TerminalProgressRenderer(output, interactive=False)

        renderer(event(sequence=4, state="MOONRAKER_ONLINE", detail="reachable"))

        rendered = output.getvalue()
        self.assertEqual(rendered.count("\n"), 1)
        self.assertIn("[KACE workflow #004]", rendered)
        self.assertIn("[CURRENT", rendered)
        self.assertIn("MOONRAKER_ONLINE: reachable", rendered)
        self.assertNotIn("\033", rendered)

    def test_limited_terminal_and_ci_disable_dynamic_ansi(self):
        for environment in ({"TERM": "dumb"}, {"TERM": "xterm-256color", "CI": "true"}):
            with self.subTest(environment=environment):
                output = FakeTTY()
                with patch.dict(os.environ, environment, clear=True):
                    renderer = TerminalProgressRenderer(output)
                    renderer(event())
                self.assertFalse(renderer.interactive)
                self.assertNotIn("\033", output.getvalue())

    def test_repeated_and_out_of_order_events_are_ignored(self):
        output = io.StringIO()
        renderer = TerminalProgressRenderer(output, interactive=False)

        renderer(event(sequence=2, state="MCU_PRESENT"))
        renderer(event(sequence=2, state="MCU_PRESENT"))
        renderer(event(sequence=1, state="MCU_ABSENT"))

        self.assertEqual(output.getvalue().count("\n"), 1)

    def test_done_is_the_only_successful_terminal_rendering(self):
        output = FakeTTY()
        renderer = TerminalProgressRenderer(output, interactive=True)
        renderer(event(sequence=10, state="DONE", detail="deployment validated"))

        rendered = output.getvalue()
        self.assertIn("Status: DONE", rendered)
        self.assertIn(renderer.LEAVE_ALTERNATE, rendered)
        final_snapshot = rendered.split(renderer.LEAVE_ALTERNATE, 1)[1]
        self.assertEqual(final_snapshot.count("[x]"), len(MILESTONES))

    def test_every_terminal_error_is_rendered_clearly(self):
        for state in TERMINAL_ERRORS:
            with self.subTest(state=state):
                output = io.StringIO()
                renderer = TerminalProgressRenderer(output, interactive=False)
                renderer(event(state=state, detail="terminal failure"))
                self.assertIn(f"[ERROR", output.getvalue())
                self.assertIn(state, output.getvalue())
                self.assertNotIn("[DONE", output.getvalue())

    def test_ctrl_c_cancellation_event_is_rendered_as_cancelled(self):
        output = io.StringIO()
        renderer = TerminalProgressRenderer(output, interactive=False)
        renderer(event(state="CANCELLED", detail="cancelled by user"))

        self.assertIn("[ERROR", output.getvalue())
        self.assertIn("CANCELLED: cancelled by user", output.getvalue())

    def test_renderer_failure_does_not_block_structured_event_sink(self):
        protocol = io.StringIO()

        def broken_renderer(_event):
            raise RuntimeError("terminal unavailable")

        emitter = WorkflowEventEmitter(JsonEventSink(protocol), broken_renderer)
        emitter(event(state="DONE"))

        self.assertIn(JsonEventSink.PREFIX, protocol.getvalue())
        self.assertIn('"state": "DONE"', protocol.getvalue())

    def test_dynamic_protocol_line_is_available_but_cleared_before_panel(self):
        output = FakeTTY()
        renderer = TerminalProgressRenderer(output, interactive=True)
        renderer.start()
        emitter = WorkflowEventEmitter(JsonEventSink(output), renderer)

        emitter(event(state="MCU_PRESENT"))

        rendered = output.getvalue()
        marker_at = rendered.index(JsonEventSink.PREFIX)
        redraw_at = rendered.index(renderer.CLEAR_HOME, marker_at)
        self.assertLess(marker_at, redraw_at)


if __name__ == "__main__":
    unittest.main()
