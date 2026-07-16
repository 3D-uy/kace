"""
tests/unit/test_moonraker_deployer.py
Unit tests for the Deployer state machine in core/moonraker_deployer.py.

Covers all terminal states (DONE, FAILED_FLASH, CONFIG_ERROR, TIMEOUT, ABORTED)
plus the specific interaction between the safe-wrapper exception narrowing and
the KeyboardInterrupt->ABORTED cancellation path:

  Fix-1 (safe wrappers catch _NETWORK_ERRORS) vs
  Fix-5 (KeyboardInterrupt caught in _wait_for_reconnect -> ABORTED)

The key invariant: _NETWORK_ERRORS must be a strict subset of Exception so that
KeyboardInterrupt (a BaseException, not Exception) propagates through the
wrappers unimpeded and reaches the cancellation handler.
"""

import io
import unittest
from unittest.mock import patch
from core.moonraker_deployer import Deployer, DeploymentManifest, McuTarget, DeployState


# ── Shared fixtures ───────────────────────────────────────────────────────────

MANIFEST = DeploymentManifest(
    targets=[McuTarget("mcu", "kace-a1b2c3d")],
    printer_cfg_path="/fake/printer.cfg",
)

MANIFEST_TWO = DeploymentManifest(
    targets=[
        McuTarget("mcu",          "kace-a1b2c3d"),
        McuTarget("mcu toolboard", "kace-a1b2c3d"),
    ],
    printer_cfg_path="/fake/printer.cfg",
)


class MockClient:
    """Configurable mock Moonraker client."""

    def __init__(self, states, versions_seq, *, raise_on_state=None, raise_on_versions=None):
        self._states   = list(states)
        self._versions = list(versions_seq)
        self._si = 0
        self._vi = 0
        self._raise_on_state    = raise_on_state    or {}
        self._raise_on_versions = raise_on_versions or {}
        self.applied   = False
        self.restarted = False
        self._verify_results = {}

    def verify_file_exists(self, filename: str) -> bool:
        return self._verify_results.get(filename, True)

    def get_klippy_state(self):
        idx = self._si
        self._si += 1
        exc = self._raise_on_state.get(idx)
        if exc is not None:
            raise exc()
        return self._states[idx] if idx < len(self._states) else "ready"

    def get_mcu_versions(self):
        idx = self._vi
        self._vi += 1
        exc = self._raise_on_versions.get(idx)
        if exc is not None:
            raise exc()
        return self._versions[idx] if idx < len(self._versions) else {"mcu": "kace-a1b2c3d"}

    def upload_and_apply_config(self, p, m=None):
        self.applied = True

    def firmware_restart(self):
        self.restarted = True


def _fast_deployer(client, manifest=MANIFEST, reconnect_timeout=5.0):
    d = Deployer(client, manifest)
    d.DISCONNECT_COOLDOWN_S = 0
    d.DISCONNECT_TIMEOUT_S  = 0.1
    d.RECONNECT_TIMEOUT_S   = reconnect_timeout
    d.POLL_INTERVAL_S       = 0.01
    d.POLL_BACKOFF_MAX_S    = 0.02
    return d


class TestMoonrakerDeployer(unittest.TestCase):
    pass
    # ── DONE ──────────────────────────────────────────────────────────────────────

    def test_done_disconnect_observed(self):
        client = MockClient(
            states=["disconnected", "ready"],
            versions_seq=[{"mcu": "kace-a1b2c3d"}],
        )
        result = _fast_deployer(client).run()
        self.assertEqual(result.state, DeployState.DONE)
        self.assertTrue(client.applied)
        self.assertTrue(client.restarted)
        self.assertEqual(result.mcu_versions, {"mcu": "kace-a1b2c3d"})


    def test_done_no_disconnect_observed(self):
        """Fast reboot: disconnect window missed, correct firmware -> DONE with warning."""
        client = MockClient(
            states=["ready"] * 20,
            versions_seq=[{"mcu": "kace-a1b2c3d"}],
        )
        with patch('sys.stdout', new_callable=io.StringIO) as mock_stdout:
            result = _fast_deployer(client).run()
            self.assertEqual(result.state, DeployState.DONE)
            self.assertIn("power-cycle may not have triggered", mock_stdout.getvalue())


    # ── FAILED_FLASH ──────────────────────────────────────────────────────────────

    def test_failed_flash_wrong_version(self):
        client = MockClient(
            states=["disconnected", "ready"],
            versions_seq=[{"mcu": "old-version"}],
        )
        result = _fast_deployer(client).run()
        self.assertEqual(result.state, DeployState.FAILED_FLASH)
        self.assertIn("running old firmware", result.detail)
        self.assertFalse(client.applied)


    def test_single_snapshot_prevents_missing_mcu_race(self):
        """Verify that reusing the same snapshot prevents missing-MCU races in run()."""
        # Even if the underlying get_mcu_versions is dynamic or could return an empty dict
        # on a subsequent call, the Deployer's use of a single snapshot guarantees consistency
        # and results in a successful DONE state.
        client = MockClient(
            states=["disconnected", "ready"],
            versions_seq=[{"mcu": "kace-a1b2c3d"}, {}],  # Second returned dict would be empty if queried again
        )
        result = _fast_deployer(client).run()
        self.assertEqual(result.state, DeployState.DONE)


    def test_check_versions_defensive_not_visible_handling(self):
        """Directly test that _check_versions correctly handles and reports missing targets."""
        # This checks _check_versions in isolation to confirm the defensive not_visible
        # branch functions correctly even though the higher-level Deployer flow prevents
        # this branch from being reachable during a standard state machine run.
        d = _fast_deployer(MockClient([], []))
        wrong, missing = d._check_versions({"mcu": "kace-a1b2c3d"})
        self.assertFalse(wrong)
        self.assertFalse(missing)

        # Test missing targets
        wrong_missing, missing_only = d._check_versions({})
        self.assertFalse(wrong_missing)
        self.assertEqual(missing_only, ["mcu"])


    # ── CONFIG_ERROR ──────────────────────────────────────────────────────────────

    def test_config_error_shutdown(self):
        client = MockClient(states=["disconnected", "shutdown"], versions_seq=[])
        result = _fast_deployer(client).run()
        self.assertEqual(result.state, DeployState.CONFIG_ERROR)
        self.assertFalse(client.applied)


    def test_config_error_error_state(self):
        client = MockClient(states=["disconnected", "error"], versions_seq=[])
        result = _fast_deployer(client).run()
        self.assertEqual(result.state, DeployState.CONFIG_ERROR)


    # ── TIMEOUT ───────────────────────────────────────────────────────────────────

    def test_timeout_never_ready(self):
        client = MockClient(states=["startup"] * 500, versions_seq=[{}] * 500)
        result = _fast_deployer(client, reconnect_timeout=0.05).run()
        self.assertEqual(result.state, DeployState.TIMEOUT)
        self.assertFalse(client.applied)


    # ── ABORTED vs NETWORK_ERROR interaction ──────────────────────────────────────

    def test_aborted_keyboard_interrupt_during_reconnect(self):
        """
        THE critical interaction test: Fix-1 exception narrowing vs Fix-5 ABORTED.

        KeyboardInterrupt must propagate THROUGH _safe_klippy_state() because
        _NETWORK_ERRORS is a strict Exception subset, and KeyboardInterrupt inherits
        from BaseException (not Exception) -- so it is not caught by the wrapper.

        It then reaches _wait_for_reconnect's `except KeyboardInterrupt:` block
        and returns (ABORTED, {}).

        Regression signal: if this test returns TIMEOUT instead of ABORTED, it
        means the safe wrapper was widened to catch BaseException or bare `except:`,
        silently eating the Ctrl-C and letting the loop run to timeout instead.
        """
        client = MockClient(
            states=["disconnected"],                 # disconnect phase completes
            versions_seq=[],
            raise_on_state={1: KeyboardInterrupt},   # first reconnect poll -> KBI
        )
        result = _fast_deployer(client, reconnect_timeout=5.0).run()
        self.assertEqual(result.state, DeployState.ABORTED)
        self.assertIn("Cancelled by user", result.detail)
        self.assertFalse(client.applied)


    def test_network_oserror_does_not_abort(self):
        """
        Inverse: an OSError during the reconnect loop must be swallowed (Fix-1),
        not treated as ABORTED (Fix-5). The loop should keep polling after the error.
        """
        client = MockClient(
            states=["disconnected", "ready"],
            versions_seq=[{"mcu": "kace-a1b2c3d"}],
            raise_on_state={1: OSError},   # first reconnect poll raises OSError -> retry
        )
        # After the OSError the next poll returns "ready" from the states list
        result = _fast_deployer(client, reconnect_timeout=5.0).run()
        self.assertEqual(result.state, DeployState.DONE)


    def test_attribute_error_propagates(self):
        """
        Programming bugs in the client adapter must NOT be silently masked.
        An AttributeError is not a network error; it must propagate as a crash.
        """
        client = MockClient(
            states=[],
            versions_seq=[],
            raise_on_state={0: AttributeError},   # raised on first state call
        )
        with self.assertRaises(AttributeError):
            _fast_deployer(client).run()


    # ── CAN toolboard lag ─────────────────────────────────────────────────────────

    def test_can_toolboard_lag(self):
        """Mainboard reconnects first; CAN toolboard appears on the second poll."""
        class CanLagClient:
            def __init__(self):
                self._sc = 0
                self._vc = 0
                self.applied = self.restarted = False

            def get_klippy_state(self):
                self._sc += 1
                return "disconnected" if self._sc == 1 else "ready"

            def get_mcu_versions(self):
                self._vc += 1
                if self._vc == 1:
                    return {"mcu": "kace-a1b2c3d"}                        # toolboard lagging
                return {"mcu": "kace-a1b2c3d", "mcu toolboard": "kace-a1b2c3d"}

            def upload_and_apply_config(self, p, m=None): self.applied   = True
            def firmware_restart(self):                    self.restarted = True
            def verify_file_exists(self, filename: str) -> bool: return True

        client = CanLagClient()
        result = _fast_deployer(client, MANIFEST_TWO).run()
        self.assertEqual(result.state, DeployState.DONE)
        self.assertIn("mcu toolboard", result.mcu_versions)


    # ── Single-snapshot guarantee (Fix 3) ────────────────────────────────────────

    def test_single_mcu_versions_call_per_run(self):
        """get_mcu_versions() must be called exactly once per connect phase.
        With Phase 6 added, we have two connect phases (pre-flash verify and post-restart config verify),
        so it should be called exactly twice."""
        call_count = {"n": 0}

        class CountingClient:
            def get_klippy_state(self): return "ready"
            def get_mcu_versions(self):
                call_count["n"] += 1
                return {"mcu": "kace-a1b2c3d"}
            def upload_and_apply_config(self, p, m=None): pass
            def firmware_restart(self): pass
            def verify_file_exists(self, filename: str) -> bool: return True

        result = _fast_deployer(CountingClient()).run()
        self.assertEqual(result.state, DeployState.DONE)
        self.assertEqual(call_count["n"], 2)

    # ── dev-deploy / verify_firmware=False ────────────────────────────────────────

    def test_dev_deploy_skips_fingerprint_mismatch(self):
        """When verify_firmware=False, fingerprint check is skipped, and it finishes DONE."""
        client = MockClient(
            states=["disconnected", "ready"],
            versions_seq=[{"mcu": "old-or-mismatched-version"}],
        )
        d = _fast_deployer(client)
        d.verify_firmware = False
        
        with patch('sys.stdout', new_callable=io.StringIO) as mock_stdout:
            result = d.run()
            self.assertEqual(result.state, DeployState.DONE)
            self.assertTrue(client.applied)
            self.assertTrue(client.restarted)
            self.assertIn("firmware fingerprint check skipped", mock_stdout.getvalue())

    # ── DeploymentSnapshot attached to result ─────────────────────────────────

    def test_snapshot_attached_to_done_result(self):
        """A DeploymentSnapshot passed to Deployer must be surfaced on the DeployResult."""
        from core.snapshot import DeploymentSnapshot
        client = MockClient(
            states=["disconnected", "ready"],
            versions_seq=[{"mcu": "kace-a1b2c3d"}],
        )
        snap = DeploymentSnapshot(
            deployment_id="test-uuid",
            timestamp="2026-01-01T00:00:00+00:00",
            board="btt_octopus",
            kace_version="1.0",
            firmware_fingerprint="mcu=kace-a1b2c3d",
            mcus=("mcu",),
            dev_deploy=False,
            config_files={"printer.cfg": b"[printer]\n"},
        )
        d = _fast_deployer(client)
        d.snapshot = snap
        result = d.run()
        self.assertEqual(result.state, DeployState.DONE)
        self.assertIs(result.snapshot, snap)
        self.assertEqual(result.snapshot.deployment_id, "test-uuid")

    # ── Phase 6 Targeted Verification Tests ───────────────────────────────────

    def test_verify_config_success(self):
        """Klipper restarts, disconnects, then comes back up and reaches ready -> DONE."""
        client = MockClient(
            states=["disconnected", "ready", "disconnected", "ready"],
            versions_seq=[{"mcu": "kace-a1b2c3d"}],
        )
        result = _fast_deployer(client).run()
        self.assertEqual(result.state, DeployState.DONE)
        self.assertTrue(client.applied)
        self.assertTrue(client.restarted)

    def test_verify_config_error_triggers_config_error_state(self):
        """Klipper restarts, disconnects, then comes back but has a config error (shutdown/error) -> CONFIG_ERROR."""
        client = MockClient(
            states=["disconnected", "ready", "disconnected", "shutdown"],
            versions_seq=[{"mcu": "kace-a1b2c3d"}],
        )
        result = _fast_deployer(client).run()
        self.assertEqual(result.state, DeployState.CONFIG_ERROR)
        self.assertIn("Klipper reported shutdown/error with the new configuration", result.detail)
        self.assertTrue(client.applied)
        self.assertTrue(client.restarted)

    def test_verify_config_timeout_triggers_timeout_state(self):
        """Klipper restarts, disconnects, but never comes back online within the timeout -> TIMEOUT."""
        # Phase 1 disconnect sees "disconnected".
        # Phase 2 reconnect sees "ready".
        # Phase 6 disconnect sees "disconnected".
        # Phase 6 reconnect sees "disconnected" indefinitely (times out).
        client = MockClient(
            states=["disconnected", "ready", "disconnected"] + ["disconnected"] * 10,
            versions_seq=[{"mcu": "kace-a1b2c3d"}],
        )
        result = _fast_deployer(client, reconnect_timeout=0.05).run()
        self.assertEqual(result.state, DeployState.TIMEOUT)
        self.assertIn("Printer did not come back online after configuration update", result.detail)
        self.assertTrue(client.applied)
        self.assertTrue(client.restarted)

    # ── Upload Verification Phase Tests ──────────────────────────────────────────

    def test_upload_verification_success(self):
        """Both config files are found on target after upload -> DONE."""
        client = MockClient(
            states=["disconnected", "ready", "disconnected", "ready"],
            versions_seq=[{"mcu": "kace-a1b2c3d"}],
        )
        # Default _verify_results returns True for all filenames
        result = _fast_deployer(client).run()
        self.assertEqual(result.state, DeployState.DONE)
        self.assertTrue(client.applied)
        self.assertTrue(client.restarted)

    def test_upload_verification_file_missing_fails(self):
        """printer.cfg not found on target after upload -> FAILED_UPLOAD."""
        client = MockClient(
            states=["disconnected", "ready"],
            versions_seq=[{"mcu": "kace-a1b2c3d"}],
        )
        client._verify_results["printer.cfg"] = False
        result = _fast_deployer(client).run()
        self.assertEqual(result.state, DeployState.FAILED_UPLOAD)
        self.assertIn("printer.cfg not found on target after upload", result.detail)
        self.assertTrue(client.applied)
        self.assertFalse(client.restarted)  # should halt before restart

    def test_upload_verification_exception_fails(self):
        """Exception raised during file existence check -> FAILED_UPLOAD."""
        client = MockClient(
            states=["disconnected", "ready"],
            versions_seq=[{"mcu": "kace-a1b2c3d"}],
        )

        def _raise(*args, **kwargs):
            raise ConnectionError("connection reset by peer")

        client.verify_file_exists = _raise
        result = _fast_deployer(client).run()
        self.assertEqual(result.state, DeployState.FAILED_UPLOAD)
        self.assertIn("Could not verify printer.cfg on target", result.detail)
        self.assertTrue(client.applied)
        self.assertFalse(client.restarted)  # should halt before restart



