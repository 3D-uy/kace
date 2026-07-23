import hashlib
import os
import time
import shutil
import tempfile
import subprocess
from typing import Optional
from .derivation import derive_config
from .firmware_generator import generate_firmware_config
from .validator import validate_config
from .build_mode import (
    print_build_mode_banner,
    print_mock_warning,
    print_size_warning,
    FIRMWARE_MINIMUM_SIZE_BYTES,
)
from core.translations import t
from core.exceptions import DerivationAmbiguityError


def _tmp_is_noexec() -> bool:
    """R-07: Return True if /tmp is mounted with the noexec option.

    Reads /proc/mounts (Linux only; returns False on any other OS or read
    error). When /tmp is noexec the LTO cc-wrapper script cannot be executed
    there, causing a compile failure that looks like a generic LTO error.
    """
    try:
        with open("/proc/mounts", "r", encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                # fields: device mountpoint fstype options dump pass
                if len(parts) >= 4 and parts[1] == "/tmp":
                    return "noexec" in parts[3].split(",")
    except OSError:
        pass
    return False


class BuildContext:
    """Constrained execution options for the Klipper build process."""
    def __init__(
        self,
        make_command: str = "make",
        path_override: Optional[str] = None,
        concurrency: Optional[int] = None,
    ):
        self.make_command = make_command
        self.path_override = path_override
        self.concurrency = concurrency


def build_firmware_orchestrator(
    mcu_path=None,
    derived_mcu=None,
    hint=None,
    klipper_path="~/klipper",
    output_dir="~/kace",
    config_dict=None,
    build_context: Optional[BuildContext] = None,
):
    """
    Orchestrates the firmware derivation, generation, validation, and build process.
    Runs headlessly without questionary prompts.
    """
    klipper_path = os.path.expanduser(klipper_path)
    output_dir = os.path.expanduser(output_dir)

    # 1. Derive Configuration if not provided
    if config_dict is None:
        try:
            config_dict = derive_config(derived_mcu, hint)
        except Exception as e:
            return {"status": "error", "message": t("builder.derivation_failed", error=str(e))}

    # Clean stale build binaries in the out path first to prevent old files from being copied
    out_path = os.path.join(klipper_path, "out")
    expected_outputs = ["klipper.bin", "klipper.uf2", "klipper.elf.hex"]
    if os.path.exists(out_path):
        for binary in expected_outputs:
            p = os.path.join(out_path, binary)
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    # Record the build start time
    build_start_time = time.time()

    build_context = build_context or BuildContext()

    # ── Build-mode banner: shown once at the start of every compile run ──
    print_build_mode_banner(build_context.make_command)

    # 2. Generate minimal .config
    success, msg = generate_firmware_config(config_dict, klipper_path)
    if not success:
         return {"status": "error", "message": msg}

    _make = build_context.make_command

    # Merge execution path overrides safely
    sub_env = dict(os.environ)
    if build_context.path_override:
        sub_env["PATH"] = build_context.path_override + os.pathsep + sub_env.get("PATH", "")

    wrapper_dir_obj = None

    try:
        # 3. Resolve full configuration with olddefconfig
        subprocess.run(
            [_make, "olddefconfig"],
            cwd=klipper_path,
            check=True,
            capture_output=True,
            text=True,
            env=sub_env,
        )
        
        # 4. Compute config fingerprint for firmware verification
        # sha256 of the resolved .config is deterministic per build configuration,
        # avoiding shallow-clone / git-describe unreliability (see design notes).
        _config_sha8 = ""
        _klipper_version_override = None
        try:
            _cfg_file = os.path.join(klipper_path, ".config")
            if os.path.isfile(_cfg_file):
                with open(_cfg_file, "rb") as _f:
                    _config_sha8 = hashlib.sha256(_f.read()).hexdigest()[:8]
                _klipper_version_override = f"kace-{_config_sha8}"
        except Exception:
            pass  # non-fatal; version check will be skipped if sha is absent

        # 4b. Post-olddefconfig Validation
        val_success, val_msg = validate_config(klipper_path)
        if not val_success:
             return {"status": "error", "message": val_msg}
        
        # 5. Clean and Compile
        subprocess.run(
            [_make, "clean"],
            cwd=klipper_path,
            check=True,
            capture_output=True,
            text=True,
            env=sub_env,
        )

        build_cmd = [_make]
        # Embed the config fingerprint into the binary so Moonraker can return
        # it via the mcu object's mcu_version field for post-flash verification.
        if _klipper_version_override:
            build_cmd.append(f"KLIPPER_VERSION={_klipper_version_override}")
        if build_context.concurrency is not None:
            if build_context.concurrency > 1:
                build_cmd.append(f"-j{build_context.concurrency}")
        else:
            try:
                nproc = subprocess.check_output(["nproc"], env=sub_env).decode().strip()
                build_cmd.append(f"-j{nproc}")
            except Exception:
                pass  # Fallback if nproc is not available

        try:
            subprocess.run(
                build_cmd,
                cwd=klipper_path,
                check=True,
                capture_output=True,
                text=True,
                env=sub_env,
            )
        except subprocess.CalledProcessError as compile_err:
            stderr_out = compile_err.stderr or ""
            stdout_out = compile_err.stdout or ""
            # R-07: Also trigger the LTO retry when /tmp is mounted noexec,
            # because the cc-wrapper script cannot be executed from /tmp in
            # that configuration, producing failures identical to LTO errors.
            _noexec = _tmp_is_noexec()
            _lto_triggered = (
                "ltrans" in stderr_out
                or "lto-wrapper" in stderr_out
                or "cannot find /tmp/cc" in stderr_out
                or _noexec
            )
            if wrapper_dir_obj is None and _lto_triggered:
                if _noexec:
                    print("\n  \033[93m[!] /tmp is mounted noexec — LTO wrapper script cannot execute there.\033[0m")
                print("\n  \033[93m[!] LTO linker failure detected (likely low memory or toolchain bug).\033[0m")
                print("  \033[93m    Retrying compilation with LTO disabled...\033[0m\n")
                
                try:
                    wrapper_dir_obj = tempfile.TemporaryDirectory(prefix="kace_cc_wrapper_")
                    w_dir = wrapper_dir_obj.name
                    
                    cc_wrapper_src = os.path.join(
                        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "scripts",
                        "cc_wrapper.py"
                    )
                    with open(cc_wrapper_src, "r", encoding="utf-8") as f_src:
                        wrapper_code = f_src.read()
                    
                    for comp in ["arm-none-eabi-gcc", "avr-gcc"]:
                        wrapper_path = os.path.join(w_dir, comp)
                        with open(wrapper_path, "w", encoding="utf-8") as f:
                            f.write(wrapper_code)
                        os.chmod(wrapper_path, 0o755)
                        
                    # Inject wrapper directory to sub_env's PATH
                    sub_env["PATH"] = w_dir + os.pathsep + sub_env.get("PATH", "")
                    
                    # Clean and compile again
                    subprocess.run(
                        [_make, "clean"],
                        cwd=klipper_path,
                        check=True,
                        capture_output=True,
                        text=True,
                        env=sub_env,
                    )
                    subprocess.run(
                        build_cmd,
                        cwd=klipper_path,
                        check=True,
                        capture_output=True,
                        text=True,
                        env=sub_env,
                    )
                except Exception as retry_err:
                    # Q-08: Preserve the retry failure context in the chain so both
                    # the original LTO error and the retry failure are visible.
                    raise compile_err from retry_err
            else:
                raise compile_err

        # After compile: show mock warning if applicable
        print_mock_warning(build_context.make_command)
            
        # 6. Locate output artifact, verify its timestamp is fresh, and copy
        os.makedirs(output_dir, exist_ok=True)
            
        # Determine the expected output artifact based on the CONFIG_MCU architecture
        # We try to read CONFIG_MCU from the generated .config file first, falling back to config_dict
        mcu_arch = ""
        config_path = os.path.expanduser(os.path.join(klipper_path, ".config"))
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("CONFIG_MCU="):
                            mcu_arch = line.split("=", 1)[1].strip().replace('"', '')
                            break
            except Exception:
                pass
        
        if not mcu_arch and config_dict:
            mcu_arch = config_dict.get("CONFIG_MCU", "").replace('"', '').strip()

        # If the architecture is unrecognized or missing, fall back to the heuristic sequential scan
        if mcu_arch == "avr":
            target_binaries = ["klipper.elf.hex"]
        elif mcu_arch == "rp2040":
            target_binaries = ["klipper.uf2"]
        elif mcu_arch in ("stm32", "lpc176x", "esp32"):
            target_binaries = ["klipper.bin"]
        else:
            target_binaries = expected_outputs

        for binary in target_binaries:
            p = os.path.join(out_path, binary)
            if os.path.exists(p):
                # Check modification time to guarantee it was compiled during this run
                # 2-second buffer for file system time resolution tolerances
                if os.path.getmtime(p) >= (build_start_time - 2.0):
                    dest = os.path.join(output_dir, binary)
                    shutil.copy2(p, dest)

                    # ── Firmware size gate ─────────────────────────────────
                    # Emit a warning (not a failure) when the artifact is
                    # suspiciously small — the centralized threshold lives in
                    # build_mode.FIRMWARE_MINIMUM_SIZE_BYTES.
                    artifact_size = os.path.getsize(dest)
                    size_warning = artifact_size < FIRMWARE_MINIMUM_SIZE_BYTES
                    if size_warning:
                        print_size_warning(dest, artifact_size)

                    return {
                        "status": "success",
                        "mcu": derived_mcu,
                        "firmware": binary,
                        "path": dest,
                        "size_warning": size_warning,
                        "size_bytes": artifact_size,
                        "klipper_version": _klipper_version_override or "",
                        "mcu_name": "mcu",
                    }

        return {"status": "error", "message": t("builder.no_binary")}
        
    except subprocess.CalledProcessError as e:
         return {"status": "error", "message": t("builder.make_error", code=e.returncode, error=e.stderr)}
    except FileNotFoundError:
         return {"status": "error", "message": t("builder.make_not_found")}
    except Exception as e:
         return {"status": "error", "message": t("builder.unexpected_error", error=str(e))}
    finally:
        # Clean up temporary wrapper directory
        if wrapper_dir_obj:
            try:
                wrapper_dir_obj.cleanup()
            except Exception:
                pass
