"""
tests/unit/test_ssh_operations.py
===================================
Comprehensive tests for SSH-specific security and resource management
within the KACE deployment pipeline.

Covers
------
_InteractiveHostKeyPolicy.missing_host_key()
    - Trust rejected → SSHException raised, connection aborted cleanly
    - Trust accepted → key added to client in-memory known_hosts
    - Trust accepted → known_hosts written to disk via save_host_keys()
    - save_host_keys() OSError / generic Exception → swallowed (non-fatal)
    - Fingerprint bytes formatted as colon-separated lowercase hex pairs

deploy_config() — credential handling (SEC-02)
    - Password popped from user_data BEFORE ssh.connect() is called
    - Password value correctly forwarded to connect() (not re-read from user_data)
    - user_data contains no password after call, even when connection fails

deploy_config() — specific exception handlers
    - TimeoutError   → "Connection timed out" diagnostic message
    - OSError        → "Network error" diagnostic message
    - AuthenticationException → "Authentication error" diagnostic message
    - Generic Exception       → "Deployment failed" catch-all message

deploy_config() — resource cleanup (RES-01 — FIXED)
    - sftp.close() and ssh.close() called on successful upload
    - sftp.close() and ssh.close() called even when sftp.put() raises (finally: fix)
    - ssh.close() called on connect() / open_sftp() failure; sftp.close() skipped
      (sftp was None — never opened)
    - sftp.close() failure inside finally: does NOT prevent ssh.close()

deploy_config() — dest_path construction
    - ~/path/printer.cfg  → tilde-expanded, used directly (file path)
    - ~/path/config/      → trailing slash → 'printer.cfg' appended
    - ~/path/config       → bare directory → 'printer.cfg' appended
    - Tilde expansion: ~/ → /home/{user}/
    - macros.cfg goes in posixpath.dirname(dest_file) — co-located with printer.cfg
    - macros.cfg upload skipped when local file is absent
"""

import os
import posixpath
import sys
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

# Stub questionary so tests run on Windows host (it is Docker-only)
if 'questionary' not in sys.modules:
    try:
        import questionary  # noqa: F401
    except ImportError:
        sys.modules['questionary'] = MagicMock()

from core.deployer import _InteractiveHostKeyPolicy, deploy_config

# Global patchers setup for this module
_check_moonraker_patcher = patch('core.moonraker.check_moonraker', return_value=(False, "unreachable"))
_verify_remote_file_exists_patcher = patch('core.moonraker.verify_remote_file_exists', return_value=False)
_download_printer_cfg_patcher = patch('core.moonraker.download_printer_cfg', return_value=(False, b""))
_check_klipper_ready_patcher = patch('core.moonraker.check_klipper_ready', return_value=(False, "unreachable"))
_sleep_patcher = patch('time.sleep')

def setUpModule():
    _check_moonraker_patcher.start()
    _verify_remote_file_exists_patcher.start()
    _download_printer_cfg_patcher.start()
    _check_klipper_ready_patcher.start()
    _sleep_patcher.start()

def tearDownModule():
    _check_moonraker_patcher.stop()
    _verify_remote_file_exists_patcher.stop()
    _download_printer_cfg_patcher.stop()
    _check_klipper_ready_patcher.stop()
    _sleep_patcher.stop()


# ── Shared test helpers ───────────────────────────────────────────────────────

def _make_mock_paramiko():
    """
    Build a mock paramiko module with realistic Exception subclasses.

    AuthenticationException and SSHException are distinct classes so that
    the 'except paramiko.AuthenticationException' branch in deploy_config()
    is matched correctly (a bare MagicMock would not work here).
    """
    class _AuthException(Exception):
        pass

    class _SSHException(Exception):
        pass

    mock_p = MagicMock()
    mock_p.AuthenticationException = _AuthException
    mock_p.SSHException = _SSHException
    return mock_p


def _make_ssh_stack(mock_paramiko=None):
    """
    Build a connected mock (paramiko, SSHClient, SFTPClient) stack.

    Returns (mock_paramiko, mock_client, mock_sftp).
    The mock_client.open_sftp() returns mock_sftp.
    """
    if mock_paramiko is None:
        mock_paramiko = _make_mock_paramiko()
    mock_sftp   = MagicMock()
    mock_client = MagicMock()
    mock_client.open_sftp.return_value = mock_sftp
    mock_paramiko.SSHClient.return_value = mock_client
    return mock_paramiko, mock_client, mock_sftp


# ── _InteractiveHostKeyPolicy ─────────────────────────────────────────────────

class TestInteractiveHostKeyPolicy(unittest.TestCase):
    """
    Security-critical tests for the SSH host-key verification prompt.

    This is the MITM defence layer.  Any regression here could allow an
    attacker to silently intercept SSH credentials in automation mode.
    """

    # ── Fixture helpers ───────────────────────────────────────────────────────

    def _make_key(self, algo='ssh-ed25519', fingerprint_bytes=b'\xab\xcd\xef\x01'):
        key = MagicMock()
        key.get_name.return_value = algo
        key.get_fingerprint.return_value = fingerprint_bytes
        return key

    # ── Trust rejected ────────────────────────────────────────────────────────

    def test_rejected_raises_ssh_exception(self):
        """
        When the user declines trust, SSHException must be raised.
        This aborts the paramiko connection before any data is transmitted.
        """
        policy     = _InteractiveHostKeyPolicy()
        mock_p     = _make_mock_paramiko()
        mock_key   = self._make_key()

        with patch('core.deployer._require_paramiko', return_value=mock_p), \
             patch('questionary.confirm', return_value=MagicMock(ask=lambda: False)), \
             patch('builtins.print'):
            with self.assertRaises(mock_p.SSHException):
                policy.missing_host_key(MagicMock(), '192.168.1.10', mock_key)

    def test_rejected_exception_message_contains_rejected(self):
        """Rejection SSHException message must contain the word 'rejected'."""
        policy     = _InteractiveHostKeyPolicy()
        mock_p     = _make_mock_paramiko()
        mock_key   = self._make_key()

        with patch('core.deployer._require_paramiko', return_value=mock_p), \
             patch('questionary.confirm', return_value=MagicMock(ask=lambda: False)), \
             patch('builtins.print'):
            with self.assertRaises(mock_p.SSHException) as ctx:
                policy.missing_host_key(MagicMock(), '192.168.1.10', mock_key)

        self.assertIn('rejected', str(ctx.exception),
                      "Rejection message must say 'rejected' so the user understands why")

    def test_rejected_exception_message_names_hostname(self):
        """Rejection message must name the specific host that was rejected."""
        policy     = _InteractiveHostKeyPolicy()
        mock_p     = _make_mock_paramiko()
        mock_key   = self._make_key()

        with patch('core.deployer._require_paramiko', return_value=mock_p), \
             patch('questionary.confirm', return_value=MagicMock(ask=lambda: False)), \
             patch('builtins.print'):
            with self.assertRaises(mock_p.SSHException) as ctx:
                policy.missing_host_key(MagicMock(), 'pi.local', mock_key)

        self.assertIn('pi.local', str(ctx.exception),
                      "Rejection message must include the hostname for diagnostics")

    def test_rejected_client_key_add_not_called(self):
        """On rejection, the untrusted key must NOT be added to the client's known_hosts."""
        policy     = _InteractiveHostKeyPolicy()
        mock_p     = _make_mock_paramiko()
        mock_client = MagicMock()
        mock_key   = self._make_key()

        with patch('core.deployer._require_paramiko', return_value=mock_p), \
             patch('questionary.confirm', return_value=MagicMock(ask=lambda: False)), \
             patch('builtins.print'):
            try:
                policy.missing_host_key(mock_client, '192.168.1.10', mock_key)
            except Exception:
                pass

        mock_client.get_host_keys.return_value.add.assert_not_called()

    # ── Trust accepted ────────────────────────────────────────────────────────

    def test_accepted_does_not_raise(self):
        """Trust acceptance must complete without raising any exception."""
        policy   = _InteractiveHostKeyPolicy()
        mock_key = self._make_key()

        with patch('questionary.confirm', return_value=MagicMock(ask=lambda: True)), \
             patch('builtins.print'):
            try:
                policy.missing_host_key(MagicMock(), '192.168.1.10', mock_key)
            except Exception as exc:
                self.fail(f"Trust acceptance unexpectedly raised: {exc!r}")

    def test_accepted_adds_key_to_client_known_hosts(self):
        """
        On acceptance, the host key must be added to the client's in-memory
        known_hosts store so the connection can proceed verified.
        """
        policy      = _InteractiveHostKeyPolicy()
        mock_client = MagicMock()
        mock_key    = self._make_key(algo='ssh-rsa')

        with patch('questionary.confirm', return_value=MagicMock(ask=lambda: True)), \
             patch('builtins.print'):
            policy.missing_host_key(mock_client, '192.168.1.10', mock_key)

        mock_client.get_host_keys().add.assert_called_once_with(
            '192.168.1.10', 'ssh-rsa', mock_key
        )

    def test_accepted_saves_known_hosts_to_disk(self):
        """
        On acceptance, save_host_keys() must be called so future connections
        skip the prompt (standard SSH behaviour — ask once, remember forever).
        """
        policy      = _InteractiveHostKeyPolicy()
        mock_client = MagicMock()
        mock_key    = self._make_key()

        with patch('questionary.confirm', return_value=MagicMock(ask=lambda: True)), \
             patch('builtins.print'):
            policy.missing_host_key(mock_client, '192.168.1.10', mock_key)

        mock_client.save_host_keys.assert_called_once()
        saved_path = mock_client.save_host_keys.call_args[0][0]
        self.assertIn('.ssh',        saved_path, "Known hosts must be saved inside ~/.ssh/")
        self.assertIn('known_hosts', saved_path, "Known hosts file must be named known_hosts")

    # ── save_host_keys failure is non-fatal ───────────────────────────────────

    def test_save_host_keys_oserror_is_non_fatal(self):
        """
        OSError during save_host_keys() must be silently swallowed.
        The key is still trusted for this session even if persistence fails.
        Production scenario: ~/.ssh/ directory has restrictive permissions.
        """
        policy      = _InteractiveHostKeyPolicy()
        mock_client = MagicMock()
        mock_client.save_host_keys.side_effect = OSError('Permission denied')
        mock_key    = self._make_key()

        with patch('questionary.confirm', return_value=MagicMock(ask=lambda: True)), \
             patch('builtins.print'):
            try:
                policy.missing_host_key(mock_client, '192.168.1.10', mock_key)
            except OSError:
                self.fail(
                    "OSError from save_host_keys() must be swallowed — "
                    "connection should proceed even if the file can't be written"
                )

    def test_save_host_keys_generic_exception_is_non_fatal(self):
        """
        Any exception during save_host_keys() must be swallowed.
        The 'except Exception: pass' guard must cover all failure modes.
        """
        policy      = _InteractiveHostKeyPolicy()
        mock_client = MagicMock()
        mock_client.save_host_keys.side_effect = RuntimeError('Unexpected')
        mock_key    = self._make_key()

        with patch('questionary.confirm', return_value=MagicMock(ask=lambda: True)), \
             patch('builtins.print'):
            try:
                policy.missing_host_key(mock_client, '192.168.1.10', mock_key)
            except Exception:
                self.fail("Any exception from save_host_keys() must be swallowed non-fatally")

    # ── Fingerprint formatting ────────────────────────────────────────────────

    def test_fingerprint_formatted_as_colon_separated_hex_pairs(self):
        """
        Fingerprint bytes must be displayed as colon-separated lowercase hex
        pairs — identical to the output of 'ssh-keygen -l -f <key>'.
        Example: b'\\xab\\xcd\\xef' → 'ab:cd:ef'

        This format lets users visually verify the fingerprint against what
        their Pi's initial SSH session or ssh-keyscan would show them.
        """
        policy   = _InteractiveHostKeyPolicy()
        mock_key = self._make_key(fingerprint_bytes=b'\xab\xcd\xef\x12\x34')

        captured = []
        with patch('builtins.print', side_effect=lambda *a, **kw: captured.append(' '.join(map(str, a)))), \
             patch('questionary.confirm', return_value=MagicMock(ask=lambda: True)):
            policy.missing_host_key(MagicMock(), '192.168.1.10', mock_key)

        all_output = '\n'.join(captured)
        self.assertIn('ab:cd:ef:12:34', all_output,
                      "Fingerprint must be formatted as colon-separated lowercase hex pairs")

    def test_fingerprint_all_bytes_covered(self):
        """Every byte in the fingerprint must appear — no truncation."""
        policy   = _InteractiveHostKeyPolicy()
        # 16-byte fingerprint (MD5-style, common in OpenSSH)
        fp_bytes = bytes(range(0, 16))  # 00:01:02:...:0f
        mock_key = self._make_key(fingerprint_bytes=fp_bytes)

        captured = []
        with patch('builtins.print', side_effect=lambda *a, **kw: captured.append(' '.join(map(str, a)))), \
             patch('questionary.confirm', return_value=MagicMock(ask=lambda: True)):
            policy.missing_host_key(MagicMock(), 'mypi', mock_key)

        all_output = '\n'.join(captured)
        expected_fp = ':'.join(f'{b:02x}' for b in fp_bytes)
        self.assertIn(expected_fp, all_output,
                      "Full 16-byte fingerprint must be displayed without truncation")


# ── Credential Handling ───────────────────────────────────────────────────────

class TestDeployConfigCredentialHandling(unittest.TestCase):
    """
    Validates the security property that passwords are removed from user_data
    BEFORE ssh.connect() is called (line 107 of deployer.py: user_data.pop).

    This guarantees that if connect() raises an exception and the caller
    inspects user_data looking for context, the raw password is not exposed.
    """

    def test_password_popped_before_connect_is_called(self):
        """
        user_data['password'] must be absent when ssh.connect() executes.
        We capture this via a side_effect that inspects user_data at call time.
        """
        mock_p, mock_client, _ = _make_ssh_stack()
        user_data = {
            'host':      '192.168.1.10',
            'user':      'pi',
            'password':  'raspberry',
            'dest_path': '~/printer_data/config/printer.cfg',
        }
        state = {'password_present_at_connect': True}  # assume worst case

        def _inspect_connect(*args, **kwargs):
            state['password_present_at_connect'] = 'password' in user_data

        mock_client.connect.side_effect = _inspect_connect

        with patch('core.deployer._require_paramiko', return_value=mock_p), \
             patch('core.deployer.os.path.isfile', return_value=True), \
             patch('core.deployer.os.path.exists', return_value=False), \
             patch('builtins.print'):
            deploy_config(user_data)

        self.assertFalse(
            state['password_present_at_connect'],
            "password must be popped from user_data BEFORE ssh.connect() is called — "
            "it was still present when connect() ran, violating the security property"
        )

    def test_password_not_in_user_data_after_successful_call(self):
        """password must not persist in user_data after deploy_config() returns."""
        mock_p, mock_client, _ = _make_ssh_stack()
        user_data = {
            'host':      '192.168.1.10',
            'user':      'pi',
            'password':  'raspberry',
            'dest_path': '~/printer_data/config/printer.cfg',
        }

        with patch('core.deployer._require_paramiko', return_value=mock_p), \
             patch('core.deployer.os.path.isfile', return_value=True), \
             patch('core.deployer.os.path.exists', return_value=False), \
             patch('builtins.print'):
            deploy_config(user_data)

        self.assertNotIn('password', user_data,
                         "password must be absent from user_data after deploy_config() returns")

    def test_password_not_in_user_data_when_connection_fails(self):
        """
        Even when connect() raises (connection failure), the password must
        already have been removed — it was popped on line 107, before the try block.
        """
        mock_p, mock_client, _ = _make_ssh_stack()
        mock_client.connect.side_effect = TimeoutError('timed out')
        user_data = {
            'host':      '192.168.1.10',
            'user':      'pi',
            'password':  'sensitive',
            'dest_path': '~/printer_data/config/printer.cfg',
        }

        with patch('core.deployer._require_paramiko', return_value=mock_p), \
             patch('core.deployer.os.path.isfile', return_value=True), \
             patch('builtins.print'):
            deploy_config(user_data)

        self.assertNotIn('password', user_data,
                         "password must be gone from user_data even when connection fails")

    def test_connect_called_with_the_popped_password_value(self):
        """
        ssh.connect() must receive the password that was in user_data,
        proving pop() result (not a stale re-read) is forwarded.
        """
        mock_p, mock_client, _ = _make_ssh_stack()
        user_data = {
            'host':      '192.168.1.10',
            'user':      'pi',
            'password':  'raspberry',
            'dest_path': '~/printer_data/config/printer.cfg',
        }

        with patch('core.deployer._require_paramiko', return_value=mock_p), \
             patch('core.deployer.os.path.isfile', return_value=True), \
             patch('core.deployer.os.path.exists', return_value=False), \
             patch('builtins.print'):
            deploy_config(user_data)

        mock_client.connect.assert_called_once_with(
            '192.168.1.10', username='pi', password='raspberry'
        )

    def test_empty_password_when_no_password_in_user_data(self):
        """When user_data has no password key, connect() must be called with password=''."""
        mock_p, mock_client, _ = _make_ssh_stack()
        user_data = {
            'host':      '192.168.1.10',
            'user':      'pi',
            'dest_path': '~/printer_data/config/printer.cfg',
        }

        with patch('core.deployer._require_paramiko', return_value=mock_p), \
             patch('core.deployer.os.path.isfile', return_value=True), \
             patch('core.deployer.os.path.exists', return_value=False), \
             patch('builtins.print'):
            deploy_config(user_data)

        mock_client.connect.assert_called_once_with(
            '192.168.1.10', username='pi', password=''
        )


# ── Exception Handlers ────────────────────────────────────────────────────────

class TestDeployConfigExceptionHandlers(unittest.TestCase):
    """
    Validates that each specific exception type in deploy_config() produces
    the correct diagnostic message.

    deploy_config() has four dedicated except branches (lines 161–168):
        paramiko.AuthenticationException → "Authentication error"
        TimeoutError                     → "Connection timed out"
        OSError                          → "Network error"
        Exception                        → "Deployment failed" (catch-all)

    Each branch is tested independently.
    """

    def _run_with_connect_error(self, exception, mock_p=None):
        """
        Run deploy_config() where ssh.connect() raises the given exception.
        Returns the list of strings passed to print().
        """
        if mock_p is None:
            mock_p = _make_mock_paramiko()
        _, mock_client, _ = _make_ssh_stack(mock_p)
        mock_client.connect.side_effect = exception

        captured = []
        with patch('core.deployer._require_paramiko', return_value=mock_p), \
             patch('core.deployer.os.path.isfile', return_value=True), \
             patch('builtins.print', side_effect=lambda *a, **kw: captured.append(' '.join(map(str, a)))):
            deploy_config({'host': '192.168.1.10', 'user': 'pi', 'dest_path': '~/p'})
        return captured

    def test_timeout_error_prints_connection_timed_out(self):
        """TimeoutError → 'Connection timed out' must appear in output."""
        msgs = self._run_with_connect_error(TimeoutError('timed out'))
        self.assertTrue(
            any('Connection timed out' in m for m in msgs),
            f"Expected 'Connection timed out' but got: {msgs}"
        )

    def test_os_error_prints_network_error(self):
        """OSError (e.g. 'No route to host') → 'Network error' must appear."""
        msgs = self._run_with_connect_error(OSError('Network unreachable'))
        self.assertTrue(
            any('Network error' in m for m in msgs),
            f"Expected 'Network error' but got: {msgs}"
        )

    def test_os_error_message_contains_original_error_text(self):
        """The OSError message string must be embedded in the output for diagnostics."""
        msgs = self._run_with_connect_error(OSError('Connection refused'))
        combined = ' '.join(msgs)
        self.assertIn('Connection refused', combined,
                      "Original OSError text must appear so the user can diagnose the failure")

    def test_authentication_exception_prints_auth_error(self):
        """
        paramiko.AuthenticationException → 'Authentication error' must appear.
        The exception class is monkey-patched onto the mock paramiko module
        so the except branch matches correctly.
        """
        mock_p = _make_mock_paramiko()
        msgs   = self._run_with_connect_error(
            mock_p.AuthenticationException('auth failed'), mock_p=mock_p
        )
        self.assertTrue(
            any('Authentication error' in m for m in msgs),
            f"Expected 'Authentication error' but got: {msgs}"
        )

    def test_generic_exception_prints_deployment_failed(self):
        """A generic Exception is caught by the final catch-all and prints 'Deployment failed'."""
        msgs = self._run_with_connect_error(Exception('Something unexpected'))
        self.assertTrue(
            any('Deployment failed' in m for m in msgs),
            f"Expected 'Deployment failed' but got: {msgs}"
        )

    def test_paramiko_none_returns_without_raising(self):
        """
        If _require_paramiko() returns None (install failed), deploy_config()
        must return immediately without raising any exception.
        """
        user_data = {'host': '192.168.1.10', 'user': 'pi', 'dest_path': '~/p'}
        with patch('core.deployer._require_paramiko', return_value=None), \
             patch('core.deployer.os.path.isfile', return_value=True), \
             patch('builtins.print'):
            try:
                deploy_config(user_data)
            except Exception as exc:
                self.fail(f"paramiko=None case unexpectedly raised: {exc!r}")


# ── Resource Cleanup ──────────────────────────────────────────────────────────

class TestDeployConfigResourceCleanup(unittest.TestCase):
    """
    Validates SFTP and SSH channel closure on every code path.

    RES-01 fix (in deploy_config()):
        ssh = None
        sftp = None
        try:
            ssh = paramiko.SSHClient()
            ...
            sftp = ssh.open_sftp()
            sftp.put(...)          # if this raises → goes to except then finally
        except ...:
            ...
        finally:
            if sftp is not None: sftp.close()   # ← sftp is None if connect() raised
            if ssh  is not None: ssh.close()    # ← always called once ssh is assigned

    Key invariants tested:
      - Success path    : both sftp.close() and ssh.close() called.
      - connect() fails : ssh.close() called; sftp.close() NOT called (sftp=None).
      - open_sftp() fails: same as connect() failure.
      - sftp.put() fails : both closed (sftp was opened before the raise).
      - sftp.close() raises: ssh.close() still called (inner guard in finally).
    """

    def test_sftp_and_ssh_closed_on_successful_upload(self):
        """
        After a successful upload, both sftp.close() and ssh.close() must be
        called exactly once each to release OS-level sockets and channels.
        """
        mock_p, mock_client, mock_sftp = _make_ssh_stack()

        with patch('core.deployer._require_paramiko', return_value=mock_p), \
             patch('core.deployer.os.path.isfile', return_value=True), \
             patch('core.deployer.os.path.exists', return_value=False), \
             patch('builtins.print'):
            deploy_config({
                'host':      '192.168.1.10',
                'user':      'pi',
                'dest_path': '~/printer_data/config/printer.cfg',
            })

        mock_sftp.close.assert_called_once()
        mock_client.close.assert_called_once()

    def test_res01_fix_sftp_and_ssh_closed_when_put_raises(self):
        """
        RES-01 regression guard: after the finally: fix in deploy_config(),
        both sftp.close() and ssh.close() must be called even when sftp.put()
        raises an IOError.

        Previously this test documented the leak (call_count == 0).
        The fix moves close() calls into a finally: block so they always run.

        Original risk: Each retry after a remote permission error leaked one SSH
        connection and one SFTP channel, exhausting the Pi's connection limit.
        """
        mock_p, mock_client, mock_sftp = _make_ssh_stack()
        mock_sftp.put.side_effect = IOError('Remote permission denied')

        with patch('core.deployer._require_paramiko', return_value=mock_p), \
             patch('core.deployer.os.path.isfile', return_value=True), \
             patch('core.deployer.os.path.exists', return_value=False), \
             patch('builtins.print'):
            deploy_config({
                'host':      '192.168.1.10',
                'user':      'pi',
                'dest_path': '~/printer_data/config/printer.cfg',
            })

        # RES-01 fixed: both handles must be closed via finally:
        self.assertEqual(
            mock_sftp.close.call_count, 1,
            "RES-01 fix: sftp.close() must be called via finally: even when sftp.put() raises"
        )
        self.assertEqual(
            mock_client.close.call_count, 1,
            "RES-01 fix: ssh.close() must be called via finally: even when sftp.put() raises"
        )

    def test_sftp_put_called_for_printer_cfg(self):
        """sftp.put() must be invoked with the local printer.cfg path as the source."""
        mock_p, mock_client, mock_sftp = _make_ssh_stack()
        local_cfg = os.path.expanduser('~/kace/printer.cfg')

        with patch('core.deployer._require_paramiko', return_value=mock_p), \
             patch('core.deployer.os.path.isfile', return_value=True), \
             patch('core.deployer.os.path.exists', return_value=False), \
             patch('builtins.print'):
            deploy_config({
                'host':      '192.168.1.10',
                'user':      'pi',
                'dest_path': '~/printer_data/config/printer.cfg',
            })

        srcs = [args[0] for args, _ in mock_sftp.put.call_args_list]
        self.assertIn(local_cfg, srcs,
                      "sftp.put() must use the local ~/kace/printer.cfg as the source file")

    def test_res01_connect_failure_closes_ssh_not_sftp(self):
        """
        RES-01: When connect() raises (TimeoutError), the SSH client was
        created (ssh is not None) but open_sftp() was never called
        (sftp remains None).

        Expected: ssh.close() called exactly once; sftp.close() NOT called.
        """
        mock_p, mock_client, mock_sftp = _make_ssh_stack()
        mock_client.connect.side_effect = TimeoutError('timed out')

        with patch('core.deployer._require_paramiko', return_value=mock_p), \
             patch('core.deployer.os.path.isfile', return_value=True), \
             patch('builtins.print'):
            deploy_config({'host': '192.168.1.10', 'user': 'pi', 'dest_path': '~/p'})

        mock_client.close.assert_called_once()
        # sftp was never opened — its mock.close() must never have been invoked
        mock_sftp.close.assert_not_called()

    def test_res01_auth_failure_closes_ssh_not_sftp(self):
        """
        RES-01: AuthenticationException fires after ssh.connect() — sftp was
        never opened. Same invariant: ssh closed, sftp NOT closed.
        """
        mock_p, mock_client, mock_sftp = _make_ssh_stack()
        mock_client.connect.side_effect = mock_p.AuthenticationException('bad creds')

        with patch('core.deployer._require_paramiko', return_value=mock_p), \
             patch('core.deployer.os.path.isfile', return_value=True), \
             patch('builtins.print'):
            deploy_config({'host': '192.168.1.10', 'user': 'pi', 'dest_path': '~/p'})

        mock_client.close.assert_called_once()
        mock_sftp.close.assert_not_called()

    def test_res01_open_sftp_failure_closes_ssh_only(self):
        """
        RES-01: open_sftp() raises before the sftp variable is assigned.
        Only ssh.close() must be called; sftp.close() must not.
        """
        mock_p, mock_client, mock_sftp = _make_ssh_stack()
        mock_client.open_sftp.side_effect = OSError('SFTP subsystem not available')

        with patch('core.deployer._require_paramiko', return_value=mock_p), \
             patch('core.deployer.os.path.isfile', return_value=True), \
             patch('builtins.print'):
            deploy_config({'host': '192.168.1.10', 'user': 'pi', 'dest_path': '~/p'})

        mock_client.close.assert_called_once()
        mock_sftp.close.assert_not_called()

    def test_res01_sftp_close_error_does_not_prevent_ssh_close(self):
        """
        RES-01: If sftp.close() itself raises (broken channel), the inner
        try/except guard in finally: must swallow it so that ssh.close() is
        still called afterward.

        Without the guard, a broken sftp.close() would propagate as an
        unhandled exception and leave the SSH socket open.
        """
        mock_p, mock_client, mock_sftp = _make_ssh_stack()
        mock_sftp.close.side_effect = Exception('SFTP channel already closed')

        with patch('core.deployer._require_paramiko', return_value=mock_p), \
             patch('core.deployer.os.path.isfile', return_value=True), \
             patch('core.deployer.os.path.exists', return_value=False), \
             patch('builtins.print'):
            try:
                deploy_config({
                    'host':      '192.168.1.10',
                    'user':      'pi',
                    'dest_path': '~/printer_data/config/printer.cfg',
                })
            except Exception as exc:
                self.fail(
                    f"sftp.close() error in finally: must be swallowed — "
                    f"propagated as: {exc!r}"
                )

        # ssh.close() must still have been called despite sftp.close() raising
        mock_client.close.assert_called_once()


# ── Dest Path Construction ────────────────────────────────────────────────────

class TestDeployConfigDestPathConstruction(unittest.TestCase):
    """
    Validates the SSH destination path-building logic in deploy_config()
    (lines 139–157 of deployer.py).

    Three recognised dest_path shapes:
        ~/path/printer.cfg   — file path, used directly after tilde expansion
        ~/path/config/       — trailing slash, 'printer.cfg' appended
        ~/path/config        — bare directory, 'printer.cfg' appended

    macros.cfg always lands in posixpath.dirname(dest_file)/macros.cfg,
    i.e. the same directory as printer.cfg.
    """

    def _run_deploy(self, dest_path, user='pi', has_macros=True):
        """
        Run deploy_config() with the given dest_path.
        Returns list of (src, dst) tuples from sftp.put() calls.
        """
        mock_p, mock_client, mock_sftp = _make_ssh_stack()
        put_calls = []
        mock_sftp.put.side_effect = lambda src, dst: put_calls.append((src, dst))

        with patch('core.deployer._require_paramiko', return_value=mock_p), \
             patch('core.deployer.os.path.isfile', return_value=True), \
             patch('core.deployer.os.path.exists', return_value=has_macros), \
             patch('builtins.print'):
            deploy_config({
                'host':      '192.168.1.10',
                'user':      user,
                'dest_path': dest_path,
            })

        return put_calls

    # ── Tilde expansion ───────────────────────────────────────────────────────

    def test_tilde_expanded_to_home_directory(self):
        """~/ must be replaced with /home/{user}/ for Klipper's standard layout."""
        calls = self._run_deploy('~/printer_data/config/printer.cfg', has_macros=False)
        dest  = calls[0][1]
        self.assertTrue(
            dest.startswith('/home/pi/'),
            f"Expected dest to start with '/home/pi/' but got: {dest!r}"
        )

    def test_tilde_expanded_with_correct_username(self):
        """~/ must expand to the username from user_data, not a hardcoded value."""
        calls = self._run_deploy('~/klipper_cfg/printer.cfg', user='klipper', has_macros=False)
        dest  = calls[0][1]
        self.assertIn('/home/klipper/', dest,
                      "Tilde expansion must use user_data['user'], not 'pi' or another default")

    # ── File-path dest_path ───────────────────────────────────────────────────

    def test_cfg_file_path_used_directly(self):
        """
        A dest_path ending in .cfg must be used as-is.
        'printer.cfg' must NOT be appended a second time.
        """
        calls = self._run_deploy('~/printer_data/config/printer.cfg', has_macros=False)
        dests = [dst for _, dst in calls]
        self.assertEqual(
            dests, ['/home/pi/printer_data/config/printer.cfg'],
            "A dest_path ending in .cfg must not have 'printer.cfg' appended"
        )

    # ── Trailing-slash directory ──────────────────────────────────────────────

    def test_trailing_slash_appends_printer_cfg(self):
        """A dest_path with a trailing '/' is a directory; 'printer.cfg' must be appended."""
        calls = self._run_deploy('~/printer_data/config/', has_macros=False)
        dests = [dst for _, dst in calls]
        self.assertEqual(
            dests, ['/home/pi/printer_data/config/printer.cfg'],
        )

    # ── Bare directory (no trailing slash, no .cfg) ───────────────────────────

    def test_bare_directory_appends_printer_cfg(self):
        """
        A bare directory path (no trailing slash, no .cfg extension) must also
        have 'printer.cfg' appended.  This is the most common user input shape
        (e.g. ~/printer_data/config).
        """
        calls = self._run_deploy('~/printer_data/config', has_macros=False)
        dests = [dst for _, dst in calls]
        self.assertEqual(
            dests, ['/home/pi/printer_data/config/printer.cfg'],
        )

    def test_all_three_shapes_land_on_same_remote_file(self):
        """
        All three dest_path shapes must resolve to the same remote file path.
        Regression guard: any change to path logic must not diverge behaviour
        for equivalent input shapes.
        """
        expected = '/home/pi/printer_data/config/printer.cfg'
        for shape in [
            '~/printer_data/config/printer.cfg',
            '~/printer_data/config/',
            '~/printer_data/config',
        ]:
            with self.subTest(dest_path=shape):
                calls = self._run_deploy(shape, has_macros=False)
                dests = [dst for _, dst in calls]
                self.assertEqual(
                    dests, [expected],
                    f"dest_path={shape!r} resolved to {dests!r}, expected {expected!r}"
                )

    # ── macros.cfg co-location ────────────────────────────────────────────────

    def test_macros_cfg_co_located_with_printer_cfg(self):
        """
        macros.cfg must land in the same directory as printer.cfg
        (posixpath.dirname(dest_file) + '/macros.cfg').
        """
        calls = self._run_deploy('~/printer_data/config/printer.cfg', has_macros=True)
        self.assertEqual(len(calls), 2, "Two sftp.put() calls expected: printer.cfg + macros.cfg")

        printer_dst = next(dst for _, dst in calls if 'printer.cfg' in dst)
        macros_dst  = next(dst for _, dst in calls if 'macros.cfg'  in dst)

        self.assertEqual(
            posixpath.dirname(printer_dst), posixpath.dirname(macros_dst),
            "macros.cfg must reside in the same directory as printer.cfg"
        )

    def test_macros_cfg_not_uploaded_when_absent(self):
        """
        When macros.cfg does not exist locally, only one sftp.put() call must
        occur (printer.cfg only).
        """
        calls = self._run_deploy('~/printer_data/config/printer.cfg', has_macros=False)
        self.assertEqual(len(calls), 1,
                         "Only printer.cfg must be uploaded when local macros.cfg is absent")

    def test_macros_uploaded_when_present(self):
        """When macros.cfg exists locally, exactly two sftp.put() calls must occur."""
        calls = self._run_deploy('~/printer_data/config/printer.cfg', has_macros=True)
        self.assertEqual(len(calls), 2,
                         "Both printer.cfg and macros.cfg must be uploaded when macros.cfg exists")

    def test_macros_dir_correct_for_bare_directory_dest(self):
        """
        REGRESSION GUARD (DEPLOY-07): macros.cfg directory must be the config
        subdirectory, not its parent.

        Risk: If dest_path='~/printer_data/config' (bare), the dirname of the
        assembled dest_file must still yield '…/config', not '…/printer_data'.
        """
        calls = self._run_deploy('~/printer_data/config', has_macros=True)
        macros_dst = next(dst for _, dst in calls if 'macros.cfg' in dst)
        self.assertEqual(
            posixpath.dirname(macros_dst), '/home/pi/printer_data/config',
            "macros.cfg must land in the config dir, not its parent — "
            "check dirname logic for bare-directory dest_path"
        )


if __name__ == '__main__':
    unittest.main()
