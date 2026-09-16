import os
import platform
import posixpath
import shutil
import sys
import tempfile

from core.known_hosts import (
    get_known_hosts_path,
    known_hosts_lock,
    persist_host_keys_atomically,
)
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
    from core.firmware_workflow import (
        DeploymentInvariantError,
        enforce_deployment_invariants,
    )
    from core.pin_validator import validate_required_sections, validate_pins_for_mcu

    # This is the shared live-deployment boundary used by SSH, Moonraker and
    # the composed firmware transaction.  Interactive choices cannot override
    # missing firmware/MCU/serial evidence here.
    try:
        enforce_deployment_invariants(cfg_path, user_data)
    except DeploymentInvariantError as exc:
        print("\033[91m[!] Deployment safety gate FAILED:\033[0m")
        for blocker in str(exc).split("; "):
            print(f"\033[91m    • {blocker}\033[0m")
        print("\033[93m    Resume the firmware workflow from its last valid checkpoint.\033[0m")
        return False

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

    Acceptance is staged in the client. The surrounding trust transaction
    persists it atomically before the connection is returned to a caller.
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

        # Stage the accepted key in memory. Durable publication is owned by
        # _connect_ssh_client while it still holds the trust-store lock.
        client.get_host_keys().add(hostname, algo, key)


def _connect_ssh_client(paramiko, hostname, **connect_kwargs):
    """Connect under one serialized, fail-closed host-trust transaction."""
    known_hosts_path = get_known_hosts_path()
    client = paramiko.SSHClient()
    try:
        with known_hosts_lock(known_hosts_path):
            client.load_system_host_keys()
            client.load_host_keys(known_hosts_path)
            client.set_missing_host_key_policy(_InteractiveHostKeyPolicy())
            client.connect(hostname, **connect_kwargs)
            persist_host_keys_atomically(
                paramiko,
                client,
                known_hosts_path,
                lock_held=True,
            )
        return client
    except Exception:
        client.close()
        raise




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


def _interactive_configuration_review(review, yes_no_fn, *, destination=False) -> bool:
    from core.configuration_review import render_configuration_review
    from core.translations import get_lang

    language = get_lang()
    print("\n" + render_configuration_review(review, language=language))
    if review.diff:
        advanced_prompt = {
            "English": "Show full technical diff?",
            "Español": "¿Mostrar el diff técnico completo?",
            "Português": "Mostrar o diff técnico completo?",
        }.get(language, "Show full technical diff?")
        if yes_no_fn(advanced_prompt, default=False):
            print("\n--- Technical diff ---")
            print(review.diff)
    if not review.validation.valid:
        return False
    if not review.changed_files:
        return True
    prompts = {
        "English": "Write this managed configuration to the selected destination?" if destination else "Apply this configuration to Klipper?",
        "Español": "¿Escribir esta configuración gestionada en el destino seleccionado?" if destination else "¿Aplicar esta configuración a Klipper?",
        "Português": "Gravar esta configuração gerenciada no destino selecionado?" if destination else "Aplicar esta configuração ao Klipper?",
    }
    return bool(yes_no_fn(prompts.get(language, prompts["English"]), default=False))


def _review_configuration_export(review, yes_no_fn) -> bool:
    return _interactive_configuration_review(review, yes_no_fn, destination=True)


def _select_config_activation():
    """Ask how to activate only after the managed diff was accepted."""
    from core.menu import numbered_select
    from core.translations import t

    activation = numbered_select(
        t("moonraker.restart_prompt"),
        choices=[
            {"name": t("moonraker.restart_firmware"), "value": "firmware"},
            {"name": t("moonraker.restart_service"), "value": "service"},
            {"name": t("moonraker.restart_skip"), "value": "none"},
        ],
    ) or "none"
    return "none" if activation == "skip" else activation


def _run_config_transaction(
    transport,
    user_data,
    activation,
    generated=None,
    *,
    activation_selector=None,
):
    from core.config_transaction import ConfigDeploymentTransaction
    from core.menu import yes_no

    hardware_path, hardware, macros = generated or _generated_config_bytes()
    if not _preflight_check(hardware_path, user_data, yes_no):
        return failed(
            WorkflowOutcome.PRECONDITION_FAILED,
            "generated hardware configuration failed deployment preflight.",
        )

    def _review_configuration(review):
        return _interactive_configuration_review(review, yes_no)

    state_sink = None
    checkpoint = user_data.get("workflow_checkpoint")
    if isinstance(checkpoint, dict) and checkpoint.get("workflow_id"):
        from core.moonraker_deployer import JsonEventSink

        event_output = JsonEventSink()
        runtime_id = f"{checkpoint['workflow_id']}-config"
        sequence = [0]

        def state_sink(state, detail):
            sequence[0] += 1
            event_output({
                "schema": 1,
                "workflow_id": runtime_id,
                "sequence": sequence[0],
                "state": state,
                "detail": detail,
            })

    transaction = ConfigDeploymentTransaction(
        transport,
        hardware,
        macros,
        activation=activation,
        review=_review_configuration,
        activation_selector=activation_selector,
        board=user_data.get("board", ""),
        kace_version=_KACE_VERSION,
        state_sink=state_sink,
        verify_existing_ready=checkpoint is not None,
    )
    result = transaction.run()
    if result.rollback_succeeded is False:
        print(f"\033[91m[!] Rollback incomplete: {result.detail}\033[0m")
    elif result.rollback_succeeded:
        print("\033[92m[OK] Rollback restored byte-identical configuration and Klipper Ready.\033[0m")
    return _config_result_to_workflow(result)


def _verify_running_firmware_checkpoint(user_data, host, port, api_key=None):
    """Return a failure unless Klipper reports this checkpoint's exact build."""
    checkpoint = user_data.get("workflow_checkpoint")
    if not isinstance(checkpoint, dict):
        # Existing configuration-only workflows have no firmware checkpoint.
        return None

    from core.firmware_workflow import FirmwareWorkflowError, verify_running_firmware

    try:
        versions = _MoonrakerClient(host, int(port), api_key=api_key).get_mcu_versions()
        reported = verify_running_firmware(
            checkpoint,
            versions,
            mcu_name=str(user_data.get("mcu_name") or "mcu"),
        )
    except (FirmwareWorkflowError, OSError, TimeoutError, ValueError) as exc:
        return failed(
            WorkflowOutcome.FIRMWARE_FAILED,
            f"Klipper firmware verification failed after deployment: {exc}",
        )
    print(f"\033[92m[OK] Klipper reports compiled firmware {reported}.\033[0m")
    return workflow_success(f"Configuration deployed and firmware {reported} verified.")


def deploy_config(user_data):
    """Deploy configuration through the shared verified transaction over SFTP."""
    from core.config_transaction import SftpConfigTransport

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
        ssh = _connect_ssh_client(
            paramiko,
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
        transport = SftpConfigTransport(
            sftp,
            config_dir,
            user_data["host"],
            int(user_data.get("moonraker_port", 7125)),
            user_data.get("moonraker_api_key") or None,
        )
        result = _run_config_transaction(
            transport,
            user_data,
            "none",
            generated,
            activation_selector=_select_config_activation,
        )
        if not result.ok:
            return result
        verified = _verify_running_firmware_checkpoint(
            user_data,
            user_data["host"],
            int(user_data.get("moonraker_port", 7125)),
            user_data.get("moonraker_api_key") or None,
        )
        return verified or result
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
    from core.menu import password_input, simple_input, yes_no
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
    result = _run_config_transaction(
        MoonrakerConfigTransport(host, port, api_key or None),
        user_data,
        "none",
        activation_selector=_select_config_activation,
    )
    if not result.ok:
        return result
    verified = _verify_running_firmware_checkpoint(user_data, host, port, api_key or None)
    return verified or result


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
                review=lambda review: _review_configuration_export(review, yes_no),
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
        from core.translations import t
        
        artifact_key = "deployment.artifact_config" if artifact_type == "config" else \
                       "deployment.artifact_firmware" if artifact_type == "firmware" else "deployment.artifact_all"
        name_prompt = t(artifact_key)
                      
        is_non_windows = platform.system() != "Windows"
        is_docker = os.path.exists('/.dockerenv') or os.environ.get('KACE_DOCKER') == '1'
        
        while True:
            prompt_key = "deployment.removable_prompt_windows"
            if is_docker:
                prompt_key = "deployment.removable_prompt_docker"
            elif is_non_windows:
                prompt_key = "deployment.removable_prompt_posix"
            dest = simple_input(
                t(prompt_key, artifact=name_prompt)
            )
            
            if not dest:
                return cancelled("Removable-media deployment cancelled.")
                
            if is_non_windows and (dest.strip().startswith(tuple(f"{c}:" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")) or '\\' in dest):
                if is_docker:
                    print(f"\033[91m[Error] {t('deployment.windows_path_docker_error')}\033[0m\n")
                else:
                    print(f"\033[91m[Error] {t('deployment.windows_path_posix_error')}\033[0m\n")
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
    """Copy artifacts to a folder local to the device running KACE."""
    try:
        from core.menu import simple_input
        from core.translations import t
        
        artifact_key = "deployment.artifact_config" if artifact_type == "config" else \
                       "deployment.artifact_firmware" if artifact_type == "firmware" else "deployment.artifact_all"
        name_prompt = t(artifact_key)
                      
        is_non_windows = platform.system() != "Windows"
        is_docker = os.path.exists('/.dockerenv') or os.environ.get('KACE_DOCKER') == '1'
        
        while True:
            prompt_key = "deployment.local_prompt_windows" if not is_non_windows else "deployment.local_prompt_posix"
            dest = simple_input(
                t(prompt_key, artifact=name_prompt)
            )
            
            if not dest:
                return cancelled("Local deployment cancelled.")
 
            if is_non_windows and (dest.strip().startswith(tuple(f"{c}:" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")) or '\\' in dest):
                if is_docker:
                    print(f"\033[91m[Error] {t('deployment.windows_path_docker_error')}\033[0m\n")
                else:
                    print(f"\033[91m[Error] {t('deployment.windows_path_posix_error')}\033[0m\n")
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
    from core.config_transaction import MoonrakerConfigTransport, config_destination_lock
    from core.moonraker import DEFAULT_PORT
    from core.moonraker_deployer import DeployResult, DeployState

    try:
        destination = MoonrakerConfigTransport(
            user_data.get("moonraker_host", "localhost"),
            int(user_data.get("moonraker_port", DEFAULT_PORT)),
        )
        lock = config_destination_lock(destination)
    except Exception as exc:
        return DeployResult(
            DeployState.FAILED_PRECONDITION,
            f"configuration destination could not be identified: {exc}",
        )
    with lock:
        return _deploy_firmware_installation_locked(user_data)


def _deploy_firmware_installation_locked(user_data):
    from core.mcu_monitor import McuPresenceMonitor
    from core.config_transaction import (
        MoonrakerConfigTransport, read_config_state, revalidate_config_state,
    )
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
        remote_files = read_config_state(config_transport)
        config_plan = build_managed_config_plan(
            generated_hardware, generated_macros, remote_files
        )
        from core.configuration_review import build_configuration_review
        configuration_review = build_configuration_review(config_plan)
        if not configuration_review.validation.valid:
            _interactive_configuration_review(configuration_review, yes_no)
            return DeployResult(
                DeployState.FAILED_PRECONDITION,
                "semantic configuration validation failed before firmware deployment",
            )
        if config_plan.changed_artifacts and not _interactive_configuration_review(
            configuration_review, yes_no
        ):
            return DeployResult(DeployState.ABORTED, "configuration deployment cancelled")
        snapshot = None
        current_files = revalidate_config_state(config_transport, remote_files)
        if config_plan.changed_artifacts:
            snapshot = create_snapshot(
                {
                    artifact.remote_name: current_files[artifact.remote_name]
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
    profile_usb = getattr(profile, "usb", None)
    expected_vid_pids = tuple(getattr(profile_usb, "application_vid_pids", ()))
    bootloader_vid_pids = tuple(getattr(profile_usb, "bootloader_vid_pids", ()))
    if not expected_vid_pids:
        bundle.cleanup()
        return DeployResult(
            DeployState.FAILED_PRECONDITION,
            "physical firmware strategy has no post-flash application VID:PID contract",
        )

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

    def _confirm_ambiguous_mcu_identity(assessment):
        baseline = assessment.baseline
        candidate = assessment.candidate
        print("\n\033[91m[!] KACE cannot prove that the reenumerated MCU is the same board.\033[0m")
        for reason in assessment.reasons:
            print(f"\033[93m    - {reason}\033[0m")
        print(
            "\033[93m    Captured port/by-path: "
            f"{baseline.physical_port or baseline.physical_path or ', '.join(baseline.by_path) or 'unavailable'}"
            "\033[0m"
        )
        print(
            "\033[93m    Candidate port/by-path: "
            f"{candidate.physical_port or candidate.physical_path or ', '.join(candidate.by_path) or 'unavailable'}"
            "\033[0m"
        )
        print(
            f"\033[93m    Candidate VID:PID: {candidate.vid_pid or 'unavailable'}; "
            f"serial: {candidate.serial or 'unavailable'}\033[0m"
        )
        print(
            f"\033[93m    Evidence score: {assessment.score}/"
            f"{assessment.automatic_threshold} required for automatic acceptance.\033[0m"
        )
        print("\033[91m    Confirm only after physically tracing the cable/controller.\033[0m")
        return bool(
            yes_no(
                "Did you physically verify this candidate is the intended MCU?",
                default=False,
            )
        )

    try:
        monitor = McuPresenceMonitor(
            mcu_path,
            expected_vid_pids=expected_vid_pids,
            bootloader_vid_pids=bootloader_vid_pids,
        )
        return Deployer(
            client,
            manifest,
            # The physical SD workflow never bypasses identity/fingerprint safety,
            # including when the broader CLI was started with --dev-deploy.
            verify_firmware=True,
            snapshot=snapshot,
            before_config_upload=lambda: revalidate_config_state(config_transport, current_files),
            mcu_monitor=monitor,
            power_cycle_prompt=(
                _confirm_power_off
                if method == "MANUAL" and power_controller is not None
                else None
            ),
            media_installation_prompt=(
                _confirm_media_installation if method == "MANUAL" else None
            ),
            identity_confirmation_prompt=_confirm_ambiguous_mcu_identity,
            power_off=power_controller.power_off if power_controller is not None else None,
            power_on=power_controller.power_on if power_controller is not None else None,
            firmware_deploy=_run_firmware_method,
            monitor_before_firmware=(method == "USB"),
        ).run()
    finally:
        bundle.cleanup()
