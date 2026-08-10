import os
import platform
import posixpath
import shutil
import sys
import tempfile

from core.workflow_outcome import (
    WorkflowOutcome,
    cancelled,
    failed,
    success as workflow_success,
)


def _preflight_check(cfg_path, user_data, yes_no_fn):
    """Run structural + pin validation before any upload.

    Returns True to proceed with deployment, False to abort.
    Fatal issues (missing core sections) always abort. Soft issues
    (pin-namespace mismatches, unrecognized MCU) only warn and let the
    user decide, since we cannot enumerate every valid pin on every board.
    """
    from core.pin_validator import validate_required_sections, validate_pins_for_mcu

    # ── Fatal: structural integrity ───────────────────────────────
    problems = validate_required_sections(cfg_path)
    if problems is None:
        print("\033[93m[!] Could not read printer.cfg for pre-flight check — proceeding anyway.\033[0m")
    elif problems:
        print("\033[91m[!] Pre-flight check FAILED — printer.cfg is not deployable:\033[0m")
        for p in problems:
            print(f"\033[91m    • {p}\033[0m")
        print("\033[93m    Deploying this file would make Klipper fail to start and\033[0m")
        print("\033[93m    can restart-loop (and lock up) a low-memory Raspberry Pi.\033[0m")
        print("\033[93m    Regenerate the config before deploying.\033[0m")
        return False

    # ── Soft: pin namespace vs detected MCU family ────────────────
    mcu = user_data.get('mcu_type') or user_data.get('derived_mcu')
    issues = validate_pins_for_mcu(cfg_path, mcu)
    if issues:
        print(f"\033[93m[!] Pre-flight warning: {len(issues)} pin(s) don't match the '{mcu}' namespace:\033[0m")
        for lineno, field, pin, arch in issues[:10]:
            print(f"\033[93m    • line {lineno} {field}: '{pin}' is not a valid {arch} pin\033[0m")
        if len(issues) > 10:
            print(f"\033[93m    • ...and {len(issues) - 10} more\033[0m")
        print("\033[93m    This usually means a board-profile pin was not remapped to your MCU.\033[0m")
        cont = yes_no_fn("Deploy anyway? (Klipper may reject these pins)", default=False)
        if cont is None or not cont:
            print("\033[93mDeployment cancelled by user.\033[0m")
            return False

    return True





def _sleep_with_progress(seconds):
    """Sleep for the specified duration while printing a visual progress indicator."""
    import time
    sys.stdout.write("Waiting for Klipper to initialize: ")
    sys.stdout.flush()
    for _ in range(seconds):
        time.sleep(1)
        sys.stdout.write(".")
        sys.stdout.flush()
    sys.stdout.write("\n")
    sys.stdout.flush()


def _detect_ram_mb():
    """Best-effort detection of total system RAM in MB.

    Used to scale the verification poll budget down on low-RAM hosts (e.g.
    a 1 GB Pi 3) where tight polling contributes to OOM during a Klipper
    restart loop. Returns None on any failure — callers treat that as
    "unknown, use the default budget".
    """
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    # Field is in kB (1024-byte units).
                    return int(line.split()[1]) // 1024
    except Exception:
        return None
    return None


# paramiko is an optional dependency — only needed for SSH deployment.
# Install it with: pip install -r requirements-ssh.txt
# KACE will never auto-install it at runtime to avoid supply-chain risk.


# ── S-07: Cache the KACE version at module import time ─────────────
# Using a dynamic __import__() inside a deployment function is fragile and
# silently falls back to 'unknown' on any import error. Caching here is safe
# because deployer is always imported after kace.py has run.
try:
    from kace import __version__ as _KACE_VERSION  # noqa: PLC0415
except (ImportError, SystemExit):
    # SystemExit can be raised when kace.py is imported as a module during tests:
    # its top-level argparse sees pytest's -v/--verbose flag as --version and
    # calls sys.exit(0) before __version__ is ever defined.
    _KACE_VERSION = "unknown"


def _require_paramiko():
    """Return the paramiko module, or None if not installed.

    Security note (S-01): KACE deliberately does NOT auto-install paramiko at
    runtime via pip. Doing so would allow an attacker who can write to
    requirements-ssh.txt before the first SSH use to install arbitrary
    packages. Install it manually with:

        pip install -r requirements-ssh.txt
    """
    try:
        import paramiko  # noqa: PLC0415
        return paramiko
    except ImportError:
        print("\n\033[96m[SSH Deployment]\033[0m")
        print("\033[91m[!] SSH support requires the 'paramiko' library, which is not installed.\033[0m")
        print("\033[93m    Install it with one of the following commands and then retry:\033[0m")
        print()
        print("        pip install -r requirements-ssh.txt")
        print("        # or on a system Python (outside venv):")
        print("        pip install -r requirements-ssh.txt --break-system-packages")
        print()
        print("\033[96mContinuing without SSH support...\033[0m\n")
        return None


class _InteractiveHostKeyPolicy:
    """Paramiko MissingHostKeyPolicy that asks the user before connecting.

    WarningPolicy prints a warning and proceeds silently — the user has no
    chance to abort. This policy shows the key fingerprint and requires an
    explicit yes before the connection is made.

    On acceptance the key is saved to ~/.ssh/known_hosts so the prompt
    only appears once per host (standard SSH behaviour).
    """

    def missing_host_key(self, client, hostname, key):
        from core.menu import yes_no

        algo = key.get_name()
        # Format fingerprint as colon-separated hex pairs (e.g. ab:cd:ef:...)
        raw = key.get_fingerprint()
        fingerprint = ':'.join(f'{b:02x}' for b in raw)

        print(f"\n\033[93m[!] Unknown host key for {hostname}\033[0m")
        print(f"    Algorithm  : {algo}")
        print(f"    Fingerprint: {fingerprint}")
        print(f"\033[93m    Verify this fingerprint matches your Pi before continuing.\033[0m\n")

        trust = yes_no(
            f"Trust and connect to {hostname}?",
            default=False,
        )

        if not trust:
            # Raising SSHException aborts the connection cleanly
            paramiko = _require_paramiko()
            raise paramiko.SSHException(
                f"Connection to {hostname} rejected — unknown host key not trusted."
            )

        # Save to known_hosts so the prompt doesn't repeat next time
        client.get_host_keys().add(hostname, algo, key)
        try:
            known_hosts = os.path.expanduser("~/.ssh/known_hosts")
            client.save_host_keys(known_hosts)
        except Exception:
            pass  # Non-fatal — key is still trusted for this session


def _legacy_deploy_config(user_data):
    """Deploys the generated printer.cfg to the Klipper host via SSH/SCP.

    Note (Q2-02): Intentionally mutates user_data by popping 'password' immediately
    to minimize in-memory credential exposure duration.
    """
    # Wipes password from user_data immediately to reduce the credential exposure window
    password = user_data.pop('password', '')
    password_for_reconnect = password
    paramiko = _require_paramiko()
    if paramiko is None:
        return failed(
            WorkflowOutcome.PRECONDITION_FAILED,
            "Paramiko is unavailable; SSH deployment cannot start.",
        )

    # BUG-007: Verify the config file exists locally before attempting upload.
    # sftp.put() raises a cryptic FileNotFoundError that the broad except below
    # would swallow without telling the user the real cause.
    cfg_path = os.path.expanduser('~/kace/printer.cfg')
    if not os.path.isfile(cfg_path):
        print(f"\033[91m[!] Deployment aborted: printer.cfg not found at {cfg_path}\033[0m")
        print("\033[93m    Run 'Generate new config' first to create the file.\033[0m")
        return failed(WorkflowOutcome.PRECONDITION_FAILED, "printer.cfg is missing.")

    # Pre-flight structural integrity check.
    # Pushing a printer.cfg that Klipper can't load causes an instant fatal
    # error → systemd restart-loops Klipper → on a low-RAM Pi the loop OOM-kills
    # sshd/networking and the user loses all access. Catch a malformed file
    # (missing [mcu]/serial/[printer]/steppers — the exact failure seen in the
    # field) BEFORE it reaches the Pi.
    from core.pin_validator import validate_required_sections, validate_pins_for_mcu
    from core.menu import yes_no as _yes_no
    if not _preflight_check(cfg_path, user_data, _yes_no):
        return failed(
            WorkflowOutcome.PRECONDITION_FAILED,
            "printer.cfg failed deployment preflight.",
        )

    # RES-01 fix: declare handles as None so the finally block can safely test
    # whether each resource was successfully created before attempting to close it.
    # This prevents a connect() failure from trying to close an sftp that was
    # never opened, and guarantees cleanup on every exception path.
    ssh = None
    sftp = None
    printer_backup_created = False
    macros_backup_created = False
    deployed_successfully = False
    mr_ok = False
    host = user_data.get('host', '')
    port = user_data.get("moonraker_port", 7125)
    dest_file = ""
    dest_macros = ""
    macros_uploaded = False
    workflow_result = failed(
        WorkflowOutcome.DEPLOYMENT_FAILED,
        "SSH deployment did not complete.",
    )

    try:
        ssh = paramiko.SSHClient()
        # UNSAFE-002: WarningPolicy warns the user on unknown host keys instead
        # of silently accepting them (AutoAddPolicy is MITM-vulnerable).
        # Known hosts are still loaded from ~/.ssh/known_hosts for verification.
        ssh.load_system_host_keys()
        ssh.set_missing_host_key_policy(_InteractiveHostKeyPolicy())

        print(f"Connecting to {user_data['host']}...")
        ssh.connect(
            user_data['host'],
            username=user_data['user'],
            password=password
        )

        sftp = ssh.open_sftp()

        # Expand user path (e.g., ~) if necessary
        dest = user_data['dest_path']
        if dest.startswith('~/'):
            # Simple expansion for common Klipper setups
            dest = dest.replace('~/', f"/home/{user_data['user']}/")

        # Ensure dest is a full file path — if it ends with '/', it's a directory
        if dest.endswith('/') or not dest.endswith('.cfg'):
            dest_file = posixpath.join(dest.rstrip('/'), 'printer.cfg')
        else:
            dest_file = dest

        # Check if remote printer.cfg exists for backup
        try:
            sftp.stat(dest_file)
            sftp.rename(dest_file, dest_file + ".bak")
            printer_backup_created = True
        except FileNotFoundError:
            # File doesn't exist, no backup needed
            pass
        except Exception as e:
            print(f"\033[93mWarning: Failed to backup remote printer.cfg: {e}\033[0m")

        # Check if remote macros.cfg exists for backup
        macros_path = os.path.expanduser('~/kace/macros.cfg')
        dest_macros = posixpath.join(posixpath.dirname(dest_file), 'macros.cfg')
        if os.path.exists(macros_path):
            try:
                sftp.stat(dest_macros)
                sftp.rename(dest_macros, dest_macros + ".bak")
                macros_backup_created = True
            except FileNotFoundError:
                pass
            except Exception as e:
                print(f"\033[93mWarning: Failed to backup remote macros.cfg: {e}\033[0m")

        # Upload printer.cfg
        print(f"Uploading printer.cfg to {dest_file}...")
        sftp.put(cfg_path, dest_file)

        # Upload macros.cfg if it exists
        if os.path.exists(macros_path):
            print(f"Uploading macros.cfg to {dest_macros}...")
            sftp.put(macros_path, dest_macros)
            macros_uploaded = True

        # Trigger restart via Moonraker API if available, else via SSH.
        # The user chooses how aggressively to restart — a full service
        # restart on a low-RAM Pi is the moment most likely to OOM-lock the
        # box, so "Skip" lets them restart manually after sanity-checking.
        from core.moonraker import check_moonraker, check_klipper_ready, restart_klipper_service, verify_remote_file_exists
        from core.translations import t as _t
        from core.menu import numbered_select as _ns

        mr_ok, _ = check_moonraker(host, port)

        restart_choice = _ns(
            _t("moonraker.restart_prompt"),
            choices=[
                {"name": _t("moonraker.restart_skip"),     "value": "skip"},
                {"name": _t("moonraker.restart_service"),  "value": "service"},
            ]
        )
        if restart_choice is None:
            restart_choice = "skip"

        restart_done = False
        if restart_choice == "service":
            if mr_ok:
                print("\033[96m[*]\033[0m Restarting Klipper via Moonraker API...")
                restart_klipper_service(host, port)
            else:
                print("\033[96m[*]\033[0m Restarting Klipper via SSH command...")
                # S-02 Security note: sudo -n (non-interactive) is used here to avoid
                # prompting for a password over the SSH channel. For least-privilege
                # hardening, scope the sudoers entry on the Pi to only this command:
                #
                #   %klipper ALL=(ALL) NOPASSWD: /bin/systemctl restart klipper
                #
                # See KACE security documentation for the recommended sudoers snippet.
                ssh.exec_command(
                    "sudo -n systemctl restart klipper || systemctl --user restart klipper || systemctl restart klipper",
                    timeout=10
                )
            restart_done = True
        else:
            print("\033[93m[*] Restart skipped — Klipper will keep its current config.\033[0m")
            print("\033[93m    Run 'FIRMWARE_RESTART' in the Klipper console when ready to apply.\033[0m")

        # ── Step 6: Post-Deployment Success & Instructions ─────────
        deployed_successfully = True
        workflow_result = workflow_success("Configuration uploaded through SSH.")
        print(f"\n\033[92m[OK] Configuration files successfully uploaded to Klipper host!\033[0m")
        if restart_done:
            print(f"\033[96m[*]\033[0m Klipper restart issued successfully.")
            print(f"\033[93m[!] TIP: If Klipper doesn't load immediately or reports a connection error,\033[0m")
            print(f"\033[93m    we recommend power-cycling (turning OFF and ON) your Raspberry Pi and printer.\033[0m")
        print(f"\033[92m[OK] You can now access Mainsail/Fluidd at: http://{host}/\033[0m")

    except paramiko.AuthenticationException as e:
        workflow_result = failed(WorkflowOutcome.DEPLOYMENT_FAILED, f"SSH authentication failed: {e}")
        print(f"\033[91mDeployment failed: Authentication error — check username and password. Details: {e}\033[0m")
    except TimeoutError as e:
        workflow_result = failed(WorkflowOutcome.DEPLOYMENT_FAILED, f"SSH connection timed out: {e}")
        print(f"\033[91mDeployment failed: Connection timed out — is the Pi powered on and reachable? Details: {e}\033[0m")
    except OSError as e:
        workflow_result = failed(WorkflowOutcome.DEPLOYMENT_FAILED, f"SSH network error: {e}")
        print(f"\033[91mDeployment failed: Network error — {e}\033[0m")
    except Exception as e:
        workflow_result = failed(WorkflowOutcome.DEPLOYMENT_FAILED, f"SSH deployment failed: {e}")
        print(f"\033[91mDeployment failed: {e}\033[0m")
    finally:
        # Perform rollback if backups exist and deployment wasn't successful
        if (printer_backup_created or macros_backup_created) and not deployed_successfully:
            print("\033[93m[!] Initiating automatic rollback of configurations...\033[0m")
            
            # Check if SFTP session is still alive
            sftp_alive = False
            if sftp is not None:
                try:
                    sftp.stat(dest_file or ".")
                    sftp_alive = True
                except Exception:
                    pass

            if not sftp_alive:
                print("\033[93m[!] SSH/SFTP connection is dead. Attempting automatic reconnection for rollback...\033[0m")
                try:
                    if sftp is not None:
                        try:
                            sftp.close()
                        except Exception:
                            pass
                    if ssh is not None:
                        try:
                            ssh.close()
                        except Exception:
                            pass
                    
                    ssh = paramiko.SSHClient()
                    ssh.load_system_host_keys()
                    ssh.set_missing_host_key_policy(_InteractiveHostKeyPolicy())
                    ssh.connect(
                        user_data['host'],
                        username=user_data['user'],
                        password=password_for_reconnect,
                        timeout=10
                    )
                    sftp = ssh.open_sftp()
                    # S-06: Zero out the in-memory password immediately after the
                    # reconnect so it does not linger in the stack frame for the
                    # remainder of the rollback operation.
                    password_for_reconnect = None
                    print("\033[92m[OK] Reconnection successful. Proceeding with rollback...\033[0m")
                except Exception as reconnect_err:
                    print(f"\033[91m[!] Reconnection failed: {reconnect_err}. Automatic rollback aborted.\033[0m")
                    sftp = None

            if sftp is not None:
                if printer_backup_created:
                    try:
                        sftp.remove(dest_file)
                    except Exception as _rm_err:
                        # R-03: Log removal outcome — partial uploads may not create
                        # the file at all, so ENOENT here is expected and non-fatal.
                        if os.environ.get("KACE_DEBUG") == "1":
                            print(f"[DEBUG] sftp.remove({dest_file!r}) skipped/failed: {_rm_err}")
                    try:
                        sftp.rename(dest_file + ".bak", dest_file)
                        print("[OK] Restored printer.cfg")
                    except Exception as e:
                        print(f"Failed to restore printer.cfg from backup: {e}")
                if macros_backup_created:
                    try:
                        sftp.remove(dest_macros)
                    except Exception as _rm_err:
                        # R-03: Same debug-level logging as the printer.cfg removal above.
                        if os.environ.get("KACE_DEBUG") == "1":
                            print(f"[DEBUG] sftp.remove({dest_macros!r}) skipped/failed: {_rm_err}")
                    try:
                        sftp.rename(dest_macros + ".bak", dest_macros)
                        print("[OK] Restored macros.cfg")
                    except Exception as e:
                        print(f"Failed to restore macros.cfg from backup: {e}")
                        
                # Restart Klipper to restore configuration state after rollback
                if mr_ok:
                    try:
                        restart_klipper_service(host, port)
                    except Exception:
                        try:
                            ssh.exec_command(
                                "sudo -n systemctl restart klipper || systemctl --user restart klipper || systemctl restart klipper",
                                timeout=10
                            )
                        except Exception:
                            pass
                else:
                    try:
                        ssh.exec_command(
                            "sudo -n systemctl restart klipper || systemctl --user restart klipper || systemctl restart klipper",
                            timeout=10
                        )
                    except Exception:
                        pass
                print("\033[92m[OK] Rollback complete. Klipper configuration reverted to previous state.\033[0m")

        # Guarantee socket and SFTP channel release on every code path.
        # Inner try/except guards prevent a broken close() from masking the
        # original exception that already fired in the except branches above.
        if sftp is not None:
            try:
                sftp.close()
            except Exception:
                pass
        if ssh is not None:
            try:
                ssh.close()
            except Exception:
                pass

    return workflow_result


def _generated_config_bytes():
    hardware_path = os.path.expanduser("~/kace/printer.cfg")
    macros_path = os.path.expanduser("~/kace/macros.cfg")
    if not os.path.isfile(hardware_path):
        raise FileNotFoundError(f"printer.cfg not found at {hardware_path}")
    with open(hardware_path, "rb") as source:
        hardware = source.read()
    macros = None
    if os.path.isfile(macros_path):
        with open(macros_path, "rb") as source:
            macros = source.read()
    return hardware_path, hardware, macros


def _config_result_to_workflow(result):
    from core.config_transaction import ConfigTransactionState
    from core.workflow_outcome import pending_activation

    if result.state is ConfigTransactionState.COMMITTED:
        return workflow_success(result.detail)
    if result.state is ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION:
        return pending_activation(result.detail)
    if result.state is ConfigTransactionState.CANCELLED:
        return cancelled(result.detail)
    if result.state in {
        ConfigTransactionState.PRECONDITION_FAILED,
        ConfigTransactionState.SNAPSHOT_FAILED,
    }:
        return failed(WorkflowOutcome.PRECONDITION_FAILED, result.detail)
    return failed(WorkflowOutcome.DEPLOYMENT_FAILED, result.detail)


def _run_config_transaction(transport, user_data, activation, generated=None):
    from core.config_transaction import ConfigDeploymentTransaction
    from core.menu import yes_no

    hardware_path, hardware, macros = generated or _generated_config_bytes()
    if not _preflight_check(hardware_path, user_data, yes_no):
        return failed(
            WorkflowOutcome.PRECONDITION_FAILED,
            "generated hardware configuration failed deployment preflight.",
        )

    def _show_diff(diff):
        print("\n\033[96m[*]\033[0m Configuration dry-run diff:")
        print(diff or "(no changes)")

    transaction = ConfigDeploymentTransaction(
        transport,
        hardware,
        macros,
        activation=activation,
        confirm=lambda _diff: bool(yes_no("Apply this configuration diff?", default=False)),
        output=_show_diff,
        board=user_data.get("board", ""),
        kace_version=_KACE_VERSION,
    )
    result = transaction.run()
    if result.rollback_succeeded is False:
        print(f"\033[91m[!] Rollback incomplete: {result.detail}\033[0m")
    elif result.rollback_succeeded:
        print("\033[92m[OK] Rollback restored byte-identical configuration and Klipper Ready.\033[0m")
    return _config_result_to_workflow(result)


def deploy_config(user_data):
    """Deploy configuration through the shared verified transaction over SFTP."""
    from core.config_transaction import SftpConfigTransport
    from core.menu import numbered_select
    from core.translations import t

    password = user_data.pop("password", "")
    try:
        generated = _generated_config_bytes()
    except (OSError, FileNotFoundError) as exc:
        password = None
        print(f"\033[91m[!] Deployment aborted: {exc}\033[0m")
        print("\033[93m    Run 'Generate new config' first and retry.\033[0m")
        return failed(WorkflowOutcome.PRECONDITION_FAILED, str(exc))
    paramiko = _require_paramiko()
    if paramiko is None:
        return failed(WorkflowOutcome.PRECONDITION_FAILED, "Paramiko is unavailable.")

    ssh = None
    sftp = None
    try:
        ssh = paramiko.SSHClient()
        ssh.load_system_host_keys()
        ssh.set_missing_host_key_policy(_InteractiveHostKeyPolicy())
        ssh.connect(
            user_data["host"],
            username=user_data["user"],
            password=password,
            timeout=10,
        )
        sftp = ssh.open_sftp()
        destination = user_data["dest_path"]
        if destination.startswith("~/"):
            destination = destination.replace("~/", f"/home/{user_data['user']}/", 1)
        config_dir = (
            posixpath.dirname(destination)
            if destination.endswith(".cfg")
            else destination.rstrip("/")
        )
        activation = numbered_select(
            t("moonraker.restart_prompt"),
            choices=[
                {"name": t("moonraker.restart_firmware"), "value": "firmware"},
                {"name": t("moonraker.restart_service"), "value": "service"},
                {"name": t("moonraker.restart_skip"), "value": "none"},
            ],
        ) or "none"
        if activation == "skip":
            activation = "none"
        transport = SftpConfigTransport(
            sftp,
            config_dir,
            user_data["host"],
            int(user_data.get("moonraker_port", 7125)),
            user_data.get("moonraker_api_key") or None,
        )
        return _run_config_transaction(transport, user_data, activation, generated)
    except paramiko.AuthenticationException as exc:
        return failed(WorkflowOutcome.DEPLOYMENT_FAILED, f"SSH authentication failed: {exc}")
    except (OSError, TimeoutError) as exc:
        return failed(WorkflowOutcome.DEPLOYMENT_FAILED, f"SSH deployment failed: {exc}")
    except Exception as exc:
        return failed(WorkflowOutcome.DEPLOYMENT_FAILED, f"SSH deployment failed: {exc}")
    finally:
        password = None
        if sftp is not None:
            try:
                sftp.close()
            except Exception:
                pass
        if ssh is not None:
            try:
                ssh.close()
            except Exception:
                pass


def deploy_moonraker(user_data):
    """Deploy configuration through the same transaction over Moonraker."""
    from urllib.parse import urlsplit

    from core.config_transaction import MoonrakerConfigTransport
    from core.menu import numbered_select, password_input, simple_input, yes_no
    from core.moonraker import DEFAULT_PORT, _base_url, check_moonraker
    from core.translations import t

    host = simple_input(t("moonraker.host_prompt"), default=user_data.get("moonraker_host", ""))
    if not host:
        return cancelled("Moonraker deployment cancelled before connecting.")
    port_value = simple_input(
        t("moonraker.port_prompt"),
        default=str(user_data.get("moonraker_port", DEFAULT_PORT)),
    )
    try:
        port = int(port_value) if port_value else DEFAULT_PORT
    except ValueError:
        return failed(WorkflowOutcome.PRECONDITION_FAILED, "Invalid Moonraker port.")
    api_key = simple_input(t("moonraker.api_key_prompt"), default="") or ""
    if api_key and urlsplit(_base_url(host, port)).scheme != "https":
        return failed(
            WorkflowOutcome.PRECONDITION_FAILED,
            "Moonraker API key requires an effective HTTPS URL.",
        )

    ok, detail = check_moonraker(host, port, api_key=api_key)
    if not ok:
        if yes_no(t("moonraker.fallback_ssh"), default=False):
            user_data["host"] = host
            user_data["user"] = simple_input(
                t("kace.ssh_user_prompt"),
                default=os.environ.get("KACE_SSH_USER", "kace"),
            )
            user_data["password"] = password_input(t("kace.ssh_pass_prompt"))
            user_data["dest_path"] = simple_input(
                t("kace.ssh_dest_prompt"), default="~/printer_data/config/"
            )
            if user_data.get("user") and user_data.get("dest_path"):
                return deploy_config(user_data)
            user_data.pop("password", None)
            return cancelled("SSH fallback was not fully configured.")
        return failed(WorkflowOutcome.DEPLOYMENT_FAILED, f"Moonraker is unreachable: {detail}")

    user_data["moonraker_host"] = host
    user_data["moonraker_port"] = port
    activation = numbered_select(
        t("moonraker.restart_prompt"),
        choices=[
            {"name": t("moonraker.restart_firmware"), "value": "firmware"},
            {"name": t("moonraker.restart_service"), "value": "service"},
            {"name": t("moonraker.restart_skip"), "value": "none"},
        ],
    ) or "none"
    if activation == "skip":
        activation = "none"
    return _run_config_transaction(
        MoonrakerConfigTransport(host, port, api_key or None),
        user_data,
        activation,
    )


def _copy_artifacts(user_data, dest, artifact_type) -> bool:
    config_success = artifact_type not in ["config", "all"]
    firmware_success = artifact_type not in ["firmware", "all"]
    if artifact_type in ["config", "all"]:
        from core.config_transaction import (
            ConfigDeploymentTransaction,
            ConfigTransactionState,
            LocalConfigTransport,
        )
        from core.menu import yes_no

        try:
            _, hardware, macros = _generated_config_bytes()
            transaction = ConfigDeploymentTransaction(
                LocalConfigTransport(dest),
                hardware,
                macros,
                activation="none",
                confirm=lambda _diff: bool(yes_no(
                    "Write this managed configuration to the selected destination?",
                    default=False,
                )),
                output=lambda diff: print(
                    "\n\033[96m[*]\033[0m Configuration dry-run diff:\n"
                    + (diff or "(no changes)")
                ),
                board=user_data.get("board", ""),
                kace_version=_KACE_VERSION,
            )
            result = transaction.run()
            config_success = result.state in {
                ConfigTransactionState.COMMITTED,
                ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION,
            }
            if not config_success:
                print(f"\033[91mConfiguration export failed: {result.detail}\033[0m")
        except Exception as exc:
            print(f"\033[91mConfiguration export failed: {exc}\033[0m")
            config_success = False
    
    if artifact_type in ["firmware", "all"]:
        fw_path = user_data.get("firmware_path")
        if fw_path and os.path.exists(os.path.expanduser(fw_path)):
            firmware_bin = os.path.expanduser(fw_path)
            ext = os.path.basename(firmware_bin)
            print(f"Copying firmware {ext} to {dest}...")
            shutil.copy2(firmware_bin, os.path.join(dest, ext))
            firmware_success = True
        else:
            for ext in ['klipper.bin', 'klipper.uf2', 'klipper.elf.hex']:
                firmware_bin = os.path.expanduser(f'~/kace/{ext}')
                if os.path.exists(firmware_bin):
                    print(f"Copying firmware {ext} to {dest}...")
                    shutil.copy2(firmware_bin, os.path.join(dest, ext))
                    firmware_success = True
                    
    return config_success and firmware_success

def deploy_usb(user_data, artifact_type="all"):
    """Deploys the generated artifact(s) to a USB/SD card."""
    try:
        from core.menu import simple_input
        
        name_prompt = "Configuration (printer.cfg)" if artifact_type == "config" else \
                      "Firmware (klipper.bin/.uf2)" if artifact_type == "firmware" else "Configuration and Firmware"
                      
        is_non_windows = platform.system() != "Windows"
        is_docker = os.path.exists('/.dockerenv') or os.environ.get('KACE_DOCKER') == '1'
        
        while True:
            dest = simple_input(
                f"Enter USB/SD Card mount path for {name_prompt} (e.g. D:\\ or /media/usb)"
            )
            
            if not dest:
                return cancelled("Removable-media deployment cancelled.")
                
            if is_non_windows and (dest.strip().startswith(tuple(f"{c}:" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")) or '\\' in dest):
                if is_docker:
                    print("\033[91m[Error] Windows drive paths (containing '\\' or drive letters) are not accessible inside Docker.\033[0m")
                    print("\033[93m        To write to your Windows machine, please use /workspace (e.g., /workspace/outputs).\033[0m\n")
                else:
                    print("\033[91m[Error] Windows drive paths (containing '\\' or drive letters) are not supported on non-Windows platforms.\033[0m\n")
                continue
            break
        
        if not dest or not os.path.isdir(dest):
            print(f"\033[91mDeployment failed: Invalid path or directory does not exist: {dest}\033[0m")
            return failed(
                WorkflowOutcome.PRECONDITION_FAILED,
                f"Invalid removable-media destination: {dest}",
            )
            
        success = _copy_artifacts(user_data, dest, artifact_type)
                    
        if success:
            print("\033[92mUSB Deployment Successful!\033[0m")
            return workflow_success("Configuration copied to removable media.")
        else:
            print("\033[93mNo requested artifacts found to copy.\033[0m")
            return failed(
                WorkflowOutcome.DEPLOYMENT_FAILED,
                "No requested artifacts were available to copy.",
            )
            
    except Exception as e:
        print(f"\033[91mDeployment failed: {e}\033[0m")
        return failed(WorkflowOutcome.DEPLOYMENT_FAILED, f"Removable-media deployment failed: {e}")

def deploy_local(user_data, artifact_type="all"):
    """Copies the requested artifact(s) to a local folder on the PC."""
    try:
        from core.menu import simple_input
        
        name_prompt = "Configuration (printer.cfg)" if artifact_type == "config" else \
                      "Firmware (klipper.bin/.uf2)" if artifact_type == "firmware" else "Configuration and Firmware"
                      
        is_non_windows = platform.system() != "Windows"
        is_docker = os.path.exists('/.dockerenv') or os.environ.get('KACE_DOCKER') == '1'
        
        while True:
            dest = simple_input(
                f"Enter local destination folder path for {name_prompt} (e.g. C:\\3DPrinter or ~/Documents)"
            )
            
            if not dest:
                return cancelled("Local deployment cancelled.")
 
            if is_non_windows and (dest.strip().startswith(tuple(f"{c}:" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")) or '\\' in dest):
                if is_docker:
                    print("\033[91m[Error] Windows drive paths (containing '\\' or drive letters) are not accessible inside Docker.\033[0m")
                    print("\033[93m        To write to your Windows machine, please use /workspace (e.g., /workspace/outputs).\033[0m\n")
                else:
                    print("\033[91m[Error] Windows drive paths (containing '\\' or drive letters) are not supported on non-Windows platforms.\033[0m\n")
                continue
            break
 
        dest = os.path.expanduser(dest)
        
        if not os.path.exists(dest):
            os.makedirs(dest, exist_ok=True)
            
        success = _copy_artifacts(user_data, dest, artifact_type)
                    
        if success:
            print(f"\033[92mSuccessfully saved to {dest}!\033[0m")
            return workflow_success("Configuration copied to a local directory.")
        else:
            print("\033[93mNo requested artifacts found to copy.\033[0m")
            return failed(
                WorkflowOutcome.DEPLOYMENT_FAILED,
                "No requested artifacts were available to copy.",
            )
    except Exception as e:
        print(f"\033[91mSave failed: {e}\033[0m")
        return failed(WorkflowOutcome.DEPLOYMENT_FAILED, f"Local deployment failed: {e}")

class _MoonrakerClient:
    """Thin adapter that wraps core.moonraker functions to match the interface
    expected by core.moonraker_deployer.Deployer."""

    def __init__(self, host: str, port: int, api_key: str = None):
        self._host    = host
        self._port    = port
        self._api_key = api_key

    def get_klippy_state(self) -> str:
        from core.moonraker import get_klipper_state
        return get_klipper_state(self._host, self._port, api_key=self._api_key)

    def get_mcu_versions(self) -> dict:
        from core.moonraker import get_mcu_versions
        return get_mcu_versions(self._host, self._port, api_key=self._api_key)

    def is_moonraker_online(self) -> bool:
        from core.moonraker import check_moonraker
        ok, _ = check_moonraker(self._host, self._port, api_key=self._api_key)
        return ok

    def upload_config(self, local_path: str, remote_name: str):
        from core.moonraker import upload_printer_cfg
        ok, detail = upload_printer_cfg(
            self._host, self._port, local_path,
            filename=remote_name, api_key=self._api_key,
        )
        if not ok:
            raise RuntimeError(f"upload failed for {remote_name}: {detail}")

    def firmware_restart(self):
        from core.moonraker import restart_firmware
        ok, detail = restart_firmware(self._host, self._port, api_key=self._api_key)
        if not ok:
            raise RuntimeError(f"FIRMWARE_RESTART failed: {detail}")

    def restart_moonraker(self):
        from core.moonraker import restart_moonraker_service
        ok, detail = restart_moonraker_service(
            self._host, self._port, api_key=self._api_key
        )
        if not ok:
            raise RuntimeError(f"Moonraker restart failed: {detail}")

    def download_config(self, filename: str) -> tuple:
        from core.moonraker import download_printer_cfg
        return download_printer_cfg(self._host, self._port, filename, api_key=self._api_key)

    def restore_snapshot(self, snapshot) -> list:
        from core.snapshot import restore_snapshot
        return restore_snapshot(
            snapshot, self._host, self._port,
            api_key=self._api_key, issue_restart=False,
        )

def _firmware_execution_context(user_data):
    """Create the interactive runtime capabilities used by deployment methods."""
    from core.menu import simple_input, yes_no
    from firmware.deployment import DeploymentExecutionContext

    def _media_path():
        return simple_input(
            "Enter the mounted removable-media directory for the prepared firmware "
            "(for example /media/usb):"
        )

    return DeploymentExecutionContext(
        confirm=lambda prompt: bool(yes_no(prompt, default=False)),
        media_path_provider=_media_path,
    )


def execute_firmware_deployment(user_data):
    """Execute the prepared firmware strategy without configuration deployment."""
    service = user_data.get("firmware_deployment_service")
    prepared = user_data.get("prepared_firmware_deployment")
    if service is None or prepared is None:
        return None
    result = service.execute(prepared, _firmware_execution_context(user_data))
    print(f"\n[*] {result.detail}")
    return result


def deploy_firmware_installation(user_data):
    """Run firmware delivery and configuration as one verified transaction.

    The selected strategy owns naming, instructions and optional automatic
    flashing. The installation workflow owns physical identity, fingerprint
    verification, configuration upload, restart and rollback.
    """
    from core.mcu_monitor import McuPresenceMonitor
    from core.config_transaction import ConfigDeploymentTransaction, MoonrakerConfigTransport
    from core.managed_config import build_managed_config_plan
    from core.menu import yes_no
    from core.moonraker import DEFAULT_PORT
    from core.power_controller import PowerControllerError, configured_power_controller
    from core.moonraker_deployer import (
        ConfigArtifact, Deployer, DeploymentManifest, DeployResult, DeployState, McuTarget,
    )
    from core.snapshot import create_snapshot
    from firmware.deployment import (
        DeploymentArtifactError,
        DeploymentStrategyId,
        require_deployable_artifact,
    )
    from firmware.identity import FirmwareBuildIdentity

    mcu_path = user_data.get("mcu_path", "")
    prepared = user_data.get("prepared_firmware_deployment")
    service = user_data.get("firmware_deployment_service")
    if prepared is None or service is None:
        return DeployResult(DeployState.FAILED_PRECONDITION, "prepared firmware deployment is unavailable")
    artifact = getattr(getattr(prepared, "plan", None), "artifact", None)
    try:
        require_deployable_artifact(artifact)
    except DeploymentArtifactError as exc:
        return DeployResult(
            DeployState.FAILED_FLASH,
            f"firmware artifact is not deployable: {exc}",
        )
    profile = getattr(getattr(prepared, "plan", None), "profile", None)
    if getattr(profile, "strategy", None) is DeploymentStrategyId.PREPARE_ONLY:
        return DeployResult(
            DeployState.FAILED_PRECONDITION,
            (
                "the selected board strategy only prepares a firmware artifact; "
                "complete its explicit manual procedure before deploying configuration"
            ),
        )
    identity = getattr(artifact, "firmware_identity", None)
    if not isinstance(identity, FirmwareBuildIdentity):
        return DeployResult(DeployState.FAILED_FLASH, "compiled firmware build identity is unavailable")
    if (
        not getattr(artifact, "sha256", "")
        or identity.artifact_sha256 != artifact.sha256
        or identity.artifact_sha256 != getattr(prepared, "sha256", "")
    ):
        return DeployResult(DeployState.FAILED_FLASH, "firmware artifact does not match its build identity")
    if not mcu_path:
        return DeployResult(DeployState.FAILED_MONITOR, "MCU device path is unavailable")

    host = user_data.get("moonraker_host", "localhost")
    port = int(user_data.get("moonraker_port", DEFAULT_PORT))
    api_key = user_data.get("moonraker_api_key") or None
    mcu_name = user_data.get("mcu_name", "mcu")
    client = _MoonrakerClient(host, port, api_key=api_key)

    # Configuration is planned and backed up before any firmware action. A
    # failed/ambiguous read is never interpreted as an empty config root.
    try:
        hardware_path, generated_hardware, generated_macros = _generated_config_bytes()
        if not _preflight_check(hardware_path, user_data, yes_no):
            return DeployResult(
                DeployState.FAILED_PRECONDITION,
                "generated hardware configuration failed deployment preflight",
            )
        config_transport = MoonrakerConfigTransport(host, port, api_key)
        remote_files = config_transport.read_files(ConfigDeploymentTransaction.CANDIDATES)
        config_plan = build_managed_config_plan(
            generated_hardware, generated_macros, remote_files
        )
        diff = config_plan.dry_run_diff()
        print("\n\033[96m[*]\033[0m Configuration dry-run diff:")
        print(diff or "(no changes)")
        for warning in config_plan.warnings:
            print(f"\033[93m[!] {warning}\033[0m")
        if config_plan.changed_artifacts and not yes_no(
            "Apply this configuration diff after firmware verification?", default=False
        ):
            return DeployResult(DeployState.ABORTED, "configuration deployment cancelled")
        snapshot = None
        if config_plan.changed_artifacts:
            snapshot = create_snapshot(
                {
                    artifact.remote_name: artifact.previous
                    for artifact in config_plan.changed_artifacts
                },
                manifest_mcus=(mcu_name,),
                dev_deploy=os.environ.get("KACE_DEV_DEPLOY", "0") == "1",
                board=user_data.get("board", ""),
                kace_version=_KACE_VERSION,
            )
    except Exception as exc:
        return DeployResult(
            DeployState.FAILED_PRECONDITION,
            f"configuration preflight/snapshot failed before firmware deployment: {exc}",
        )

    try:
        power_controller = configured_power_controller(
            host=host, port=port, api_key=api_key
        )
        if power_controller is not None:
            # The same controller backs Studio's button. Firmware work never
            # starts until Moonraker has confirmed the configured device ON.
            power_controller.power_on()
    except PowerControllerError as exc:
        return DeployResult(
            DeployState.FAILED_PRECONDITION,
            f"printer power is not ready: {exc}",
        )

    printer_cfg = os.path.expanduser("~/kace/printer.cfg")
    macros_cfg = os.path.expanduser("~/kace/macros.cfg")
    bundle = tempfile.TemporaryDirectory(prefix="kace-config-transaction-")
    config_artifacts = []
    try:
        for index, artifact in enumerate(config_plan.changed_artifacts):
            local_path = os.path.join(bundle.name, f"{index:02d}.cfg")
            with open(local_path, "wb") as output:
                output.write(artifact.content)
                output.flush()
                os.fsync(output.fileno())
            config_artifacts.append(ConfigArtifact(local_path, artifact.remote_name))
    except Exception as exc:
        bundle.cleanup()
        return DeployResult(
            DeployState.FAILED_PRECONDITION,
            f"could not stage managed configuration: {exc}",
        )
    manifest = DeploymentManifest(
        targets=[McuTarget(mcu_name, identity.reported_version, identity.to_dict())],
        printer_cfg_path=printer_cfg,
        macros_cfg_path=macros_cfg if os.path.isfile(macros_cfg) else None,
        config_artifacts=config_artifacts,
    )

    method = prepared.plan.method.value

    def _run_firmware_method():
        result = service.execute(prepared, _firmware_execution_context(user_data))
        print(f"\n[*] {result.detail}")
        return result

    def _confirm_power_off():
        print("\n\033[93m[!] Firmware media is prepared.\033[0m")
        print("\033[93m    KACE will switch the configured relay OFF before you install it.\033[0m")
        print("\033[93m    Press Ctrl+C or answer no to cancel safely.\033[0m")
        return bool(yes_no("May KACE power off the printer now?", default=False))

    def _confirm_media_installation():
        if power_controller is None:
            print("\n\033[93m[!] Turn the printer OFF, install the prepared firmware media, then turn it ON.\033[0m")
            prompt = "Have you completed the manual media installation and power cycle?"
        else:
            print("\n\033[93m[!] Printer power is confirmed OFF. Install the prepared firmware media now.\033[0m")
            prompt = "Is the media installed and may KACE power the printer on?"
        print("\033[93m    Press Ctrl+C or answer no to cancel safely.\033[0m")
        return bool(yes_no(prompt, default=False))

    try:
        monitor = McuPresenceMonitor(mcu_path)
        return Deployer(
            client,
            manifest,
            # The physical SD workflow never bypasses identity/fingerprint safety,
            # including when the broader CLI was started with --dev-deploy.
            verify_firmware=True,
            snapshot=snapshot,
            mcu_monitor=monitor,
            power_cycle_prompt=(
                _confirm_power_off
                if method == "MANUAL" and power_controller is not None
                else None
            ),
            media_installation_prompt=(
                _confirm_media_installation if method == "MANUAL" else None
            ),
            power_off=power_controller.power_off if power_controller is not None else None,
            power_on=power_controller.power_on if power_controller is not None else None,
            firmware_deploy=_run_firmware_method,
            monitor_before_firmware=(method == "USB"),
        ).run()
    finally:
        bundle.cleanup()


def _legacy_deploy_moonraker(user_data):
    """Deploy printer.cfg to a Klipper host via the Moonraker REST API.

    Workflow:
      1. Prompt for Moonraker host, port, and optional API key.
      2. Probe reachability via GET /server/info.
      3. Upload printer.cfg via POST /server/files/upload.
      4. Optionally trigger FIRMWARE_RESTART or service restart.
      5. On failure, offer to fall back to SSH deployment.
    """
    from core.menu import simple_input, yes_no, numbered_select, password_input
    from core.translations import t
    from core.moonraker import (
        DEFAULT_PORT,
        check_moonraker,
        upload_printer_cfg,
        restart_firmware,
        restart_klipper_service,
        download_printer_cfg,
        check_klipper_ready,
        verify_remote_file_exists,
    )

    # ── Step 1: Gather connection details ─────────────────────────
    host = simple_input(
        t("moonraker.host_prompt"),
        default=user_data.get("moonraker_host", "")
    )

    if not host:
        print("\033[93mMoonraker deployment cancelled.\033[0m")
        return cancelled("Moonraker deployment cancelled before connecting.")

    port_str = simple_input(
        t("moonraker.port_prompt"),
        default=str(user_data.get("moonraker_port", DEFAULT_PORT))
    )

    try:
        port = int(port_str) if port_str else DEFAULT_PORT
    except ValueError:
        port = DEFAULT_PORT

    api_key = simple_input(
        t("moonraker.api_key_prompt"),
        default=""
    ) or ""

    # S-04 Security: Hard-block API key transmission over plain HTTP.
    # An API key sent over http:// is trivially captured by any network observer
    # on the same LAN segment. This is not a soft-confirm — the user must switch
    # to https:// before KACE will proceed with an API key.
    if api_key and host.strip().lower().startswith("http://"):
        print(f"\n\033[91m[!] {t('moonraker.http_warning')}\033[0m")
        print("\033[91m    Sending an API key over plain HTTP exposes it to any observer on the\033[0m")
        print("\033[91m    local network. Change the host to use https:// and try again.\033[0m")
        print(f"\n\033[91m[!] {t('moonraker.http_warning_cancelled')}\033[0m")
        return failed(
            WorkflowOutcome.PRECONDITION_FAILED,
            "Moonraker API key cannot be sent over explicit plain HTTP.",
        )

    # Persist for potential SSH fallback later
    user_data["moonraker_host"] = host
    user_data["moonraker_port"] = port

    # ── Step 2: Probe reachability ────────────────────────────────
    print(f"\n\033[96m[*]\033[0m {t('moonraker.connecting', host=host, port=port)}")
    ok, info = check_moonraker(host, port, api_key=api_key)

    if not ok:
        print(f"\033[91m[!] {t('moonraker.unreachable', host=host, port=port, error=info)}\033[0m")
        # Offer SSH fallback
        fallback = yes_no(
            t("moonraker.fallback_ssh"),
            default=False
        )
        if fallback:
            user_data['host']      = host
            ssh_user = simple_input(
                t("kace.ssh_user_prompt"),
                default=os.environ.get("KACE_SSH_USER", "kace")
            )
            ssh_pass = password_input(t("kace.ssh_pass_prompt"))
            ssh_dest = simple_input(t("kace.ssh_dest_prompt"), default="~/printer_data/config/")
            if user_data['host'] and ssh_user and ssh_dest:
                user_data['user']      = ssh_user
                user_data['dest_path'] = ssh_dest
                user_data['password']  = ssh_pass   # deploy_config pops this immediately
                return deploy_config(user_data)
            # ssh_pass goes out of scope here whether deploy ran or not
            return cancelled("SSH fallback was not fully configured.")
        return failed(
            WorkflowOutcome.DEPLOYMENT_FAILED,
            f"Moonraker is unreachable: {info}",
        )

    print(f"\033[92m[OK] {t('moonraker.connected', version=info)}\033[0m")

    # ── Step 3: Backup existing configs ────────────────────────────
    # capture_snapshot() discovers what files exist in the config root and
    # downloads them into an immutable DeploymentSnapshot. A failure here is
    # non-fatal: if Moonraker is reachable enough to confirm connectivity but
    # a specific download fails, we proceed without that file in the backup.
    from core.snapshot import capture_snapshot, restore_snapshot
    from core.moonraker import list_config_files
    _existing_files = list_config_files(host, port, api_key=api_key)
    _manifest_mcus  = (user_data.get("mcu_name", "mcu"),)
    _board          = user_data.get("board", "")
    _snap = capture_snapshot(
        host, port, _existing_files,
        manifest_mcus=_manifest_mcus,
        api_key=api_key,
        dev_deploy=(os.environ.get("KACE_DEV_DEPLOY", "0") == "1"),
        board=_board,
        kace_version=_KACE_VERSION,  # S-07: use module-level cache instead of dynamic __import__
    )
    # R2-01: Explicit boolean flag tracking whether a valid snapshot was captured
    snapshot_captured = False
    if _snap:
        snapshot_captured = True
        print(f"\033[96m[*]\033[0m Configuration backup captured ({len(_snap.config_files)} file(s)).")
    else:
        print("\033[93m[!] Configuration backup skipped (no files found in config root).\033[0m")

    deployed_successfully = False
    restart_choice = "skip"

    # Pre-flight structural integrity check — same rationale as deploy_config:
    # prevent pushing a config that will make Klipper fatal-loop on the Pi.
    cfg_path = os.path.expanduser("~/kace/printer.cfg")
    if os.path.isfile(cfg_path):
        if not _preflight_check(cfg_path, user_data, yes_no):
            return failed(
                WorkflowOutcome.PRECONDITION_FAILED,
                "printer.cfg failed deployment preflight.",
            )
    else:
        print(f"\033[91m[!] Deployment aborted: printer.cfg not found at {cfg_path}\033[0m")
        print("\033[93m    Run 'Generate new config' first to create the file.\033[0m")
        return failed(WorkflowOutcome.PRECONDITION_FAILED, "printer.cfg is missing.")

    workflow_result = failed(
        WorkflowOutcome.DEPLOYMENT_FAILED,
        "Moonraker deployment did not complete.",
    )
    try:
        # ── Step 4: Upload printer.cfg & macros.cfg ────────────────────────────────
        print(f"\033[96m[*]\033[0m {t('moonraker.uploading')}")
        ok, result = upload_printer_cfg(host, port, cfg_path, api_key=api_key)

        if not ok:
            raise RuntimeError(t('moonraker.upload_fail', error=result))

        # Upload macros.cfg if it exists
        macros_path = os.path.expanduser("~/kace/macros.cfg")
        if os.path.exists(macros_path):
            print(f"\033[96m[*]\033[0m Uploading macros.cfg...")
            ok_m, res_m = upload_printer_cfg(host, port, macros_path, api_key=api_key)
            if not ok_m:
                print(f"\033[91m[!] Failed to upload macros.cfg: {res_m}\033[0m")

        print(f"\033[92m[OK] {t('moonraker.upload_ok')}\033[0m")

        # This is the config-only path. The firmware transaction is owned by
        # deploy_firmware_installation(), so no second transition or upload
        # can be introduced here merely because firmware was compiled earlier.
        restart_choice = numbered_select(
            t("moonraker.restart_prompt"),
            choices=[
                {"name": t("moonraker.restart_firmware"), "value": "firmware"},
                {"name": t("moonraker.restart_service"),  "value": "service"},
                {"name": t("moonraker.restart_skip"),     "value": "skip"},
            ]
        )
        if restart_choice is None:
            restart_choice = "skip"

        if restart_choice == "firmware":
            restart_ok, restart_msg = restart_firmware(host, port, api_key=api_key)
        elif restart_choice == "service":
            restart_ok, restart_msg = restart_klipper_service(host, port, api_key=api_key)
        else:
            restart_ok, restart_msg = True, "skipped"

        if not restart_ok:
            raise RuntimeError(t('moonraker.restart_fail', error=restart_msg))
        if restart_choice != "skip":
            print(f"\033[92m[OK] {t('moonraker.restart_ok')}\033[0m")

        deployed_successfully = True
        workflow_result = workflow_success("Configuration uploaded through Moonraker.")
        print(f"\n\033[92m[OK] Configuration files successfully uploaded to Klipper host!\033[0m")
        print(f"\033[92m[OK] You can now access Mainsail/Fluidd at: http://{host}:{port}/\033[0m")

    except Exception as e:
        workflow_result = failed(
            WorkflowOutcome.DEPLOYMENT_FAILED,
            f"Moonraker deployment failed: {e}",
        )
        print(f"\033[91mMoonraker deployment failed: {e}\033[0m")
    finally:
        # Perform rollback if a snapshot was captured and deployment failed.
        if snapshot_captured and _snap is not None and not deployed_successfully:
            print("\033[93m[!] Initiating automatic rollback of configurations...\033[0m")
            failed_files = restore_snapshot(_snap, host, port, api_key=api_key)
            if failed_files:
                print(f"\033[91m[!] Rollback incomplete — failed to restore: {', '.join(failed_files)}\033[0m")
            else:
                print("\033[92m[OK] Rollback complete. Klipper configuration reverted to previous state.\033[0m")

    return workflow_result
