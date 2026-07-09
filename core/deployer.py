import os
import platform
import posixpath
import shutil
import subprocess
import sys


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
# It is imported lazily here so users who never use SSH deploy do not
# pay the install cost. On first SSH use, KACE will install it
# automatically via pip if it is not already present.


def _require_paramiko():
    """Return the paramiko module, installing it on-demand if needed."""
    try:
        import paramiko  # noqa: PLC0415
        return paramiko
    except ImportError:
        print("\n\033[96m[SSH Deployment]\033[0m")
        print("\033[93m[*] SSH support requires the 'paramiko' library.\033[0m")
        print("\033[93m[*] Downloading and installing (this may take a moment)...\033[0m")
        try:
            # Locate requirements-ssh.txt relative to this file to enforce hash verification
            current_dir = os.path.dirname(os.path.abspath(__file__))
            req_path = os.path.abspath(os.path.join(current_dir, "..", "requirements-ssh.txt"))
            pip_cmd = [sys.executable, "-m", "pip", "install", "-r", req_path, "--require-hashes"]
            # Only append --break-system-packages if running globally (outside a venv)
            in_venv = sys.prefix != sys.base_prefix or hasattr(sys, 'real_prefix')
            if platform.system() != "Windows" and not in_venv:
                pip_cmd.append("--break-system-packages")
            subprocess.check_output(
                pip_cmd,
                stderr=subprocess.STDOUT
            )
            import importlib
            importlib.invalidate_caches()
            for k in list(sys.modules.keys()):
                if k == 'paramiko' or k.startswith('paramiko.'):
                    sys.modules.pop(k, None)
            import paramiko  # noqa: PLC0415
            print("\033[92m[OK] paramiko installed successfully.\033[0m\n")
            return paramiko
        except subprocess.CalledProcessError as e:
            output = e.output.decode('utf-8', errors='ignore') if e.output else ""
            print(f"\n\033[91m[!] ERROR: Failed to install paramiko automatically.\033[0m")
            if "SSL" in output or "certificate" in output:
                print("\033[93m    System time might be out of sync, causing SSL certificate validation to fail.\033[0m")
            elif "NewConnectionError" in output or "Network is unreachable" in output:
                print("\033[93m    Network unreachable. Please check your internet connection.\033[0m")
            else:
                print(f"\033[93m    Pip error output:\n    {output.strip()}\033[0m")
                
            print("\n\033[96mTo use SSH deployment, please install it manually:\033[0m")
            print("    pip3 install paramiko==3.4.0 --break-system-packages")
            print("\033[96mContinuing without SSH support...\033[0m\n")
            return None
        except Exception as e:
            print(f"\n\033[91m[!] Unexpected error installing paramiko: {e}\033[0m")
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


def deploy_config(user_data):
    """Deploys the generated printer.cfg to the Klipper host via SSH/SCP."""
    # Wipes password from user_data immediately to reduce the credential exposure window
    password = user_data.pop('password', '')
    password_for_reconnect = password
    paramiko = _require_paramiko()
    if paramiko is None:
        return  # error already printed by _require_paramiko

    # BUG-007: Verify the config file exists locally before attempting upload.
    # sftp.put() raises a cryptic FileNotFoundError that the broad except below
    # would swallow without telling the user the real cause.
    cfg_path = os.path.expanduser('~/kace/printer.cfg')
    if not os.path.isfile(cfg_path):
        print(f"\033[91m[!] Deployment aborted: printer.cfg not found at {cfg_path}\033[0m")
        print("\033[93m    Run 'Generate new config' first to create the file.\033[0m")
        return

    # Pre-flight structural integrity check.
    # Pushing a printer.cfg that Klipper can't load causes an instant fatal
    # error → systemd restart-loops Klipper → on a low-RAM Pi the loop OOM-kills
    # sshd/networking and the user loses all access. Catch a malformed file
    # (missing [mcu]/serial/[printer]/steppers — the exact failure seen in the
    # field) BEFORE it reaches the Pi.
    from core.pin_validator import validate_required_sections, validate_pins_for_mcu
    from core.menu import yes_no as _yes_no
    if not _preflight_check(cfg_path, user_data, _yes_no):
        return

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
    port = 7125
    dest_file = ""
    dest_macros = ""
    macros_uploaded = False

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
                ssh.exec_command(
                    "sudo -n systemctl restart klipper || systemctl --user restart klipper || systemctl restart klipper",
                    timeout=10
                )
            restart_done = True
        else:
            print("\033[93m[*] Restart skipped — Klipper will keep its current config.\033[0m")
            print("\033[93m    Run 'FIRMWARE_RESTART' in the Klipper console when ready to apply.\033[0m")

        # ── Verification Loop ──────────────────────────────────────
        # Only verify when we actually restarted; a skipped restart has nothing
        # to wait for, and polling just hammers an already-strained Pi.
        if not restart_done:
            print("\033[92m[OK] Config uploaded. No restart performed — verification skipped.\033[0m")
            deployed_successfully = True
        else:
            print("\033[96m[*]\033[0m Verifying Klipper startup status...")
            import time
            verified = False
            err_msg = ""
            prev_status = None
            same_status_streak = 0

            # RAM-aware poll budget. A 1 GB Pi 3 under restart pressure can
            # barely answer one poll every few seconds; hammering it with 20
            # tight polls contributes to the OOM lockup we're trying to avoid.
            # Scale down on low-RAM hosts and bail early on a detected
            # restart-loop (same non-ready status repeating).
            ram_mb = _detect_ram_mb()
            if ram_mb and ram_mb <= 1024:
                initial_wait = 15        # give a constrained Pi more breathing room
                max_attempts = 8         # 8 × 5s = 40s ceiling
                poll_interval = 5
            else:
                initial_wait = 10
                max_attempts = 20        # 20 × 3s = up to 60s total
                poll_interval = 3

            if ram_mb:
                print(f"\033[96m[*]\033[0m Detected ~{ram_mb} MB RAM — using {max_attempts}×{poll_interval}s poll budget.")

            # Give Klipper time to restart before polling.
            _sleep_with_progress(initial_wait)

            for attempt in range(max_attempts):
                if mr_ok:
                    ready_ok, ready_msg = check_klipper_ready(host, port)
                    files_exist = verify_remote_file_exists(host, port, "printer.cfg")
                    if macros_uploaded:
                        files_exist = files_exist and verify_remote_file_exists(host, port, "macros.cfg")
                    if ready_ok and files_exist:
                        verified = True
                        break
                    else:
                        err_msg = ready_msg if not ready_ok else "Uploaded config files missing on server"
                        time.sleep(poll_interval)
                else:
                    # Fallback to systemd checks over SSH — use sudo -n to avoid password hangs
                    _, stdout_active, _ = ssh.exec_command(
                        "sudo -n systemctl is-active klipper || systemctl --user is-active klipper || systemctl is-active klipper",
                        timeout=10
                    )
                    active_status = stdout_active.read().decode("utf-8").strip()

                    # Check if file exists via SFTP
                    files_exist = True
                    try:
                        sftp.stat(dest_file)
                        if macros_uploaded:
                            sftp.stat(dest_macros)
                    except Exception:
                        files_exist = False

                    if active_status == "active" and files_exist:
                        verified = True
                        break
                    else:
                        err_msg = f"Klipper status is '{active_status}'"
                        if not files_exist:
                            err_msg += " (uploaded files missing on remote)"

                        # Crash-loop early-bail: if Klipper keeps reporting the
                        # same failed/activating state, it's stuck in a systemd
                        # restart loop — stop polling so we don't worsen OOM on
                        # a low-RAM Pi. Also detect the flapping between
                        # 'activating' and 'failed' that's the classic loop.
                        if active_status == prev_status or {active_status, prev_status} <= {"activating", "failed"}:
                            same_status_streak += 1
                        else:
                            same_status_streak = 1
                        prev_status = active_status
                        if same_status_streak >= 3:
                            err_msg += f" — restart loop detected (status '{active_status}' repeating); aborting poll to avoid OOM pressure"
                            break
                        time.sleep(poll_interval)

            if verified:
                print("\033[92m[OK] Post-deployment verification successful! Klipper is running.\033[0m")
                deployed_successfully = True
                # Cleanup remote backups
                if printer_backup_created:
                    try:
                        sftp.remove(dest_file + ".bak")
                    except Exception:
                        pass
                if macros_backup_created:
                    try:
                        sftp.remove(dest_macros + ".bak")
                    except Exception:
                        pass
            else:
                print(f"\033[91m[!] Verification FAILED: {err_msg}\033[0m")

                # Print failed status and journalctl logs
                if not mr_ok:
                    _, stdout_failed, _ = ssh.exec_command(
                        "sudo -n systemctl is-failed klipper || systemctl --user is-failed klipper || systemctl is-failed klipper",
                        timeout=10
                    )
                    failed_status = stdout_failed.read().decode("utf-8").strip()
                    print(f"Klipper systemd failed status: {failed_status}")

                    print("\033[93m[!] Fetching recent Klipper logs via journalctl...\033[0m")
                    _, stdout_journal, _ = ssh.exec_command(
                        "sudo -n journalctl -u klipper -n 50 --no-pager || journalctl --user -u klipper -n 50 --no-pager || journalctl -u klipper -n 50 --no-pager",
                        timeout=15
                    )
                    journal_logs = stdout_journal.read().decode("utf-8")
                    print(journal_logs)

                raise RuntimeError(f"Post-deployment verification failed: {err_msg}")

    except paramiko.AuthenticationException as e:
        print(f"\033[91mDeployment failed: Authentication error — check username and password. Details: {e}\033[0m")
    except TimeoutError as e:
        print(f"\033[91mDeployment failed: Connection timed out — is the Pi powered on and reachable? Details: {e}\033[0m")
    except OSError as e:
        print(f"\033[91mDeployment failed: Network error — {e}\033[0m")
    except Exception as e:
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
                    print("\033[92m[OK] Reconnection successful. Proceeding with rollback...\033[0m")
                except Exception as reconnect_err:
                    print(f"\033[91m[!] Reconnection failed: {reconnect_err}. Automatic rollback aborted.\033[0m")
                    sftp = None

            if sftp is not None:
                if printer_backup_created:
                    try:
                        sftp.remove(dest_file)
                    except Exception:
                        pass
                    try:
                        sftp.rename(dest_file + ".bak", dest_file)
                        print("[OK] Restored printer.cfg")
                    except Exception as e:
                        print(f"Failed to restore printer.cfg from backup: {e}")
                if macros_backup_created:
                    try:
                        sftp.remove(dest_macros)
                    except Exception:
                        pass
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
                return
                
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
            return
            
        success = False
        
        if artifact_type in ["config", "all"]:
            cfg_path = os.path.expanduser('~/kace/printer.cfg')
            if os.path.exists(cfg_path):
                print(f"Copying printer.cfg to {dest}...")
                shutil.copy2(cfg_path, os.path.join(dest, 'printer.cfg'))
                success = True
            
            # Copy macros.cfg if it exists
            macros_path = os.path.expanduser('~/kace/macros.cfg')
            if os.path.exists(macros_path):
                print(f"Copying macros.cfg to {dest}...")
                shutil.copy2(macros_path, os.path.join(dest, 'macros.cfg'))
        
        if artifact_type in ["firmware", "all"]:
            fw_path = user_data.get("firmware_path")
            if fw_path and os.path.exists(os.path.expanduser(fw_path)):
                firmware_bin = os.path.expanduser(fw_path)
                ext = os.path.basename(firmware_bin)
                print(f"Copying firmware {ext} to {dest}...")
                shutil.copy2(firmware_bin, os.path.join(dest, ext))
                success = True
            else:
                for ext in ['klipper.bin', 'klipper.uf2', 'klipper.elf.hex']:
                    firmware_bin = os.path.expanduser(f'~/kace/{ext}')
                    if os.path.exists(firmware_bin):
                        print(f"Copying firmware {ext} to {dest}...")
                        shutil.copy2(firmware_bin, os.path.join(dest, ext))
                        success = True
                    
        if success:
            print("\033[92mUSB Deployment Successful!\033[0m")
        else:
            print("\033[93mNo requested artifacts found to copy.\033[0m")
            
    except Exception as e:
        print(f"\033[91mDeployment failed: {e}\033[0m")

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
                return

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
            
        success = False
        
        if artifact_type in ["config", "all"]:
            cfg_path = os.path.expanduser('~/kace/printer.cfg')
            if os.path.exists(cfg_path):
                print(f"Copying printer.cfg to {dest}...")
                shutil.copy2(cfg_path, os.path.join(dest, 'printer.cfg'))
                success = True
            
            # Copy macros.cfg if it exists
            macros_path = os.path.expanduser('~/kace/macros.cfg')
            if os.path.exists(macros_path):
                print(f"Copying macros.cfg to {dest}...")
                shutil.copy2(macros_path, os.path.join(dest, 'macros.cfg'))
        
        if artifact_type in ["firmware", "all"]:
            fw_path = user_data.get("firmware_path")
            if fw_path and os.path.exists(os.path.expanduser(fw_path)):
                firmware_bin = os.path.expanduser(fw_path)
                ext = os.path.basename(firmware_bin)
                print(f"Copying firmware {ext} to {dest}...")
                shutil.copy2(firmware_bin, os.path.join(dest, ext))
                success = True
            else:
                for ext in ['klipper.bin', 'klipper.uf2', 'klipper.elf.hex']:
                    firmware_bin = os.path.expanduser(f'~/kace/{ext}')
                    if os.path.exists(firmware_bin):
                        print(f"Copying firmware {ext} to {dest}...")
                        shutil.copy2(firmware_bin, os.path.join(dest, ext))
                        success = True
                    
        if success:
            print(f"\033[92mSuccessfully saved to {dest}!\033[0m")
        else:
            print("\033[93mNo requested artifacts found to copy.\033[0m")
            
    except Exception as e:
        print(f"\033[91mSave failed: {e}\033[0m")

def deploy_avrdude(user_data, artifact_path, mcu_type):
    """Deploys firmware via USB using avrdude (for AVR MCUs)."""
    from core.menu import simple_input, yes_no

    if not shutil.which("avrdude"):
        print("\n\033[91mERROR:\033[0m 'avrdude' is not installed or not in PATH.")
        print("\033[93mPlease install it (e.g., 'sudo apt install avrdude') and try again.\033[0m")
        return

    # Try to derive the avrdude mcu part from mcu_type (e.g. atmega1284p -> atmega1284p)
    # Most times user_data['mcu_type'] is already correct, but just in case
    mcu_part = mcu_type.lower() if mcu_type else "atmega2560"
    
    default_port = user_data.get('mcu_path')
    if not default_port or default_port == "TODO" or "TODO" in default_port:
        default_port = "/dev/ttyUSB0"

    print("\n\033[96m>>> AVR Flashing via avrdude\033[0m")
    port = simple_input(
        "Enter the serial port for flashing:",
        default=default_port
    )

    if not port:
        print("\033[93mFlashing cancelled.\033[0m")
        return

    cmd = [
        "avrdude", 
        "-p", mcu_part, 
        "-c", "arduino", 
        "-P", port, 
        "-b", "115200", 
        "-U", f"flash:w:{artifact_path}:i"
    ]
    
    cmd_str = " ".join(cmd)
    print(f"\n\033[93mGenerated Command:\033[0m {cmd_str}")
    
    confirm = yes_no("Execute this command now?")
    if confirm:
        print("\n\033[96m>>> Running avrdude...\033[0m")
        try:
            subprocess.run(cmd, check=True)
            print("\n\033[92mSUCCESS:\033[0m Firmware flashed successfully!")
        except subprocess.CalledProcessError as e:
            print(f"\n\033[91mERROR:\033[0m avrdude failed with return code {e.returncode}.")
    else:
        print("\n\033[93mCommand execution cancelled. You can run it manually.\033[0m")


def deploy_moonraker(user_data):
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
        return

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

    # Warn if using plain HTTP with an API key
    if api_key and host.strip().lower().startswith("http://"):
        warning_ok = yes_no(
            t("moonraker.http_warning"),
            default=False
        )
        if warning_ok is None or not warning_ok:
            print(f"\n\033[91m[!] {t('moonraker.http_warning_cancelled')}\033[0m")
            return

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
                deploy_config(user_data)
            # ssh_pass goes out of scope here whether deploy ran or not
        return

    print(f"\033[92m[OK] {t('moonraker.connected', version=info)}\033[0m")

    # ── Step 3: Backup existing configs ────────────────────────────
    printer_cfg_backup = None
    macros_cfg_backup = None
    
    if verify_remote_file_exists(host, port, "printer.cfg", api_key=api_key):
        dl_ok, dl_data = download_printer_cfg(host, port, "printer.cfg", api_key=api_key)
        if dl_ok:
            printer_cfg_backup = dl_data
            
    if verify_remote_file_exists(host, port, "macros.cfg", api_key=api_key):
        dl_ok, dl_data = download_printer_cfg(host, port, "macros.cfg", api_key=api_key)
        if dl_ok:
            macros_cfg_backup = dl_data

    deployed_successfully = False
    restart_choice = "skip"
    macros_uploaded = False

    # Pre-flight structural integrity check — same rationale as deploy_config:
    # prevent pushing a config that will make Klipper fatal-loop on the Pi.
    cfg_path = os.path.expanduser("~/kace/printer.cfg")
    if os.path.isfile(cfg_path):
        if not _preflight_check(cfg_path, user_data, yes_no):
            return
    else:
        print(f"\033[91m[!] Deployment aborted: printer.cfg not found at {cfg_path}\033[0m")
        print("\033[93m    Run 'Generate new config' first to create the file.\033[0m")
        return

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
            if ok_m:
                macros_uploaded = True
            else:
                print(f"\033[91m[!] Failed to upload macros.cfg: {res_m}\033[0m")

        print(f"\033[92m[OK] {t('moonraker.upload_ok')}\033[0m")

        # ── Step 5: Restart prompt ────────────────────────────────────
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

        if restart_ok:
            if restart_choice != "skip":
                print(f"\033[92m[OK] {t('moonraker.restart_ok')}\033[0m")
        else:
            raise RuntimeError(t('moonraker.restart_fail', error=restart_msg))

        # ── Step 6: Post-Deployment Verification ────────────────────
        if restart_choice != "skip":
            print("\033[96m[*]\033[0m Verifying Klipper startup status...")
            import time
            verified = False
            klipper_err = ""

            # A full service restart takes 15-30s for Klipper+Moonraker to come
            # back up. A firmware-only restart is faster (~5s). Give an initial
            # grace period before polling so we don't burn retries on guaranteed
            # 404s while the service is still spinning up.
            initial_wait = 15 if restart_choice == "service" else 8
            _sleep_with_progress(initial_wait)

            # 20 attempts × 5s = up to 100s total — enough for slow Pi hardware.
            max_attempts = 20
            poll_interval = 5

            for attempt in range(max_attempts):
                ready_ok, ready_msg = check_klipper_ready(host, port, api_key=api_key)
                files_exist = verify_remote_file_exists(host, port, "printer.cfg", api_key=api_key)
                if macros_uploaded:
                    files_exist = files_exist and verify_remote_file_exists(host, port, "macros.cfg", api_key=api_key)

                if ready_ok and files_exist:
                    verified = True
                    break
                else:
                    klipper_err = ready_msg if not ready_ok else "Uploaded config files missing on server"
                    time.sleep(poll_interval)

            if verified:
                print("\033[92m[OK] Post-deployment verification successful! Klipper is Ready.\033[0m")
                deployed_successfully = True
            else:
                raise RuntimeError(f"Verification FAILED: {klipper_err}")
        else:
            deployed_successfully = True

    except Exception as e:
        print(f"\033[91mMoonraker deployment failed: {e}\033[0m")
    finally:
        # Perform rollback if backups exist and deployment wasn't successful
        if (printer_cfg_backup is not None or macros_cfg_backup is not None) and not deployed_successfully:
            print("\033[93m[!] Initiating automatic rollback of configurations...\033[0m")
            
            import tempfile
            if printer_cfg_backup is not None:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".cfg") as tmp:
                    tmp.write(printer_cfg_backup)
                    tmp_name = tmp.name
                try:
                    upload_printer_cfg(host, port, tmp_name, filename="printer.cfg", api_key=api_key)
                    print("[OK] Restored printer.cfg")
                except Exception as rollback_err:
                    print(f"Failed to restore printer.cfg from backup: {rollback_err}")
                finally:
                    try:
                        os.remove(tmp_name)
                    except OSError:
                        pass
            
            if macros_cfg_backup is not None:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".cfg") as tmp:
                    tmp.write(macros_cfg_backup)
                    tmp_name = tmp.name
                try:
                    upload_printer_cfg(host, port, tmp_name, filename="macros.cfg", api_key=api_key)
                    print("[OK] Restored macros.cfg")
                except Exception as rollback_err:
                    print(f"Failed to restore macros.cfg from backup: {rollback_err}")
                finally:
                    try:
                        os.remove(tmp_name)
                    except OSError:
                        pass
            
            # Restart Klipper after restoring configuration
            try:
                if restart_choice == "firmware":
                    restart_firmware(host, port, api_key=api_key)
                else:
                    restart_klipper_service(host, port, api_key=api_key)
            except Exception as restart_err:
                print(f"Failed to restart Klipper during rollback: {restart_err}")
                
            print("\033[92m[OK] Rollback complete. Klipper configuration reverted to previous state.\033[0m")