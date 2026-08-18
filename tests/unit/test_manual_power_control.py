"""Operator-only relay façade tests; no Moonraker calls leave the process."""

import unittest

from core.power_controller import (
    ManualRelayControl,
    MoonrakerPowerController,
    PowerControllerError,
    PrinterPowerState,
)


class FakeMoonrakerPowerController(MoonrakerPowerController):
    def __init__(self, status="off", *, read_error=None, command_error=None, change=True):
        super().__init__("printer")
        self.status = status
        self.read_error = read_error
        self.command_error = command_error
        self.change = change
        self.get_calls = 0
        self.on_calls = 0
        self.off_calls = 0

    def get_status(self):
        self.get_calls += 1
        if self.read_error:
            raise self.read_error
        return self.status

    def power_on(self, timeout=30.0):
        self.on_calls += 1
        if self.command_error:
            raise self.command_error
        if self.change:
            self.status = "on"
        return self.status

    def power_off(self, timeout=30.0):
        self.off_calls += 1
        if self.command_error:
            raise self.command_error
        if self.change:
            self.status = "off"
        return self.status


class ManualPowerControlTests(unittest.TestCase):
    def test_refresh_displays_on_off_and_unknown_without_mutating(self):
        for raw, expected in (
            ("on", PrinterPowerState.ON),
            ("off", PrinterPowerState.OFF),
            ("init", PrinterPowerState.UNKNOWN),
            ("error", PrinterPowerState.UNKNOWN),
        ):
            with self.subTest(raw=raw):
                controller = FakeMoonrakerPowerController(raw)
                result = ManualRelayControl(controller).refresh()
                self.assertEqual(expected, result.state)
                self.assertEqual(f"Printer power: {expected.value}", result.display)
                self.assertEqual(0, controller.on_calls)
                self.assertEqual(0, controller.off_calls)

    def test_unreachable_and_missing_device_are_unknown(self):
        for message in ("Moonraker unavailable", "POWER_DEVICE missing"):
            controller = FakeMoonrakerPowerController(
                read_error=PowerControllerError(message)
            )
            result = ManualRelayControl(controller).refresh()
            self.assertEqual(PrinterPowerState.UNKNOWN, result.state)
            self.assertFalse(result.confirmed)
            self.assertIn(message, result.detail)

    def test_explicit_on_and_off_are_confirmed_by_fresh_moonraker_read(self):
        controller = FakeMoonrakerPowerController("off")
        control = ManualRelayControl(controller)
        on = control.request_on(timeout=1)
        self.assertEqual(PrinterPowerState.ON, on.state)
        self.assertTrue(on.confirmed)
        self.assertEqual("ON", on.requested_action)
        self.assertEqual(1, controller.on_calls)
        off = control.request_off(timeout=1)
        self.assertEqual(PrinterPowerState.OFF, off.state)
        self.assertTrue(off.confirmed)
        self.assertEqual("OFF", off.requested_action)
        self.assertEqual(1, controller.off_calls)
        self.assertGreaterEqual(controller.get_calls, 2)

    def test_command_return_without_state_change_is_not_success(self):
        controller = FakeMoonrakerPowerController("off", change=False)
        result = ManualRelayControl(controller).request_on(timeout=1)
        self.assertEqual(PrinterPowerState.OFF, result.state)
        self.assertFalse(result.confirmed)
        self.assertEqual(1, controller.on_calls)

    def test_timeout_is_unknown_and_not_confirmed(self):
        controller = FakeMoonrakerPowerController(
            command_error=PowerControllerError("did not reach on")
        )
        result = ManualRelayControl(controller).request_on(timeout=0.01)
        self.assertEqual(PrinterPowerState.UNKNOWN, result.state)
        self.assertFalse(result.confirmed)
        self.assertIn("did not reach on", result.detail)

    def test_no_command_occurs_without_explicit_request_method(self):
        controller = FakeMoonrakerPowerController("off")
        control = ManualRelayControl(controller)
        control.refresh()
        control.refresh()
        self.assertEqual(0, controller.on_calls)
        self.assertEqual(0, controller.off_calls)


if __name__ == "__main__":
    unittest.main()
