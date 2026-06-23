import os
import time
import shutil
import tempfile
import subprocess
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



def build_firmware_orchestrator(mcu_path=None, derived_mcu=None, hint=None, klipper_path="~/klipper", output_dir="~/kace", config_dict=None):
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

    # ── Build-mode banner: shown once at the start of every compile run ──
    print_build_mode_banner()

    # 2. Generate minimal .config
    success, msg = generate_firmware_config(config_dict, klipper_path)
    if not success:
         return {"status": "error", "message": msg}

    # Resolve the correct make binary. On a real system (Pi) this resolves
    # correctly via PATH. In Docker, the mock make at /usr/local/bin/make
    # intercepts calls — which is the intended dev-mode behaviour.
    _make = "make"
    if os.environ.get("KACE_REAL_BUILD") == "1":
        if os.path.exists("/usr/bin/make"):
            _make = "/usr/bin/make"

    wrapper_dir_obj = None
    old_path = os.environ.get("PATH", "")

    try:
        if os.environ.get("KACE_TESTING") == "1":
            # Set up LTO bypass compiler wrapper
            try:
                wrapper_dir_obj = tempfile.TemporaryDirectory(prefix="kace_cc_wrapper_")
                w_dir = wrapper_dir_obj.name
                
                wrapper_code = (
                    "#!/usr/bin/env python3\n"
                    "import sys\n"
                    "import os\n"
                    "import subprocess\n"
                    "\n"
                    "def main():\n"
                    "    cmd_name = os.path.basename(sys.argv[0])\n"
                    "    wrapper_dir = os.path.dirname(os.path.abspath(sys.argv[0]))\n"
                    "    real_compiler = None\n"
                    "    paths = os.environ.get('PATH', '').split(os.pathsep)\n"
                    "    for p in paths:\n"
                    "        if not p:\n"
                    "            continue\n"
                    "        abs_p = os.path.abspath(p)\n"
                    "        if abs_p == wrapper_dir:\n"
                    "            continue\n"
                    "        candidate = os.path.join(p, cmd_name)\n"
                    "        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):\n"
                    "            real_compiler = candidate\n"
                    "            break\n"
                    "    if not real_compiler:\n"
                    "        sys.exit(f'Compiler wrapper error: Could not find real {cmd_name} in PATH')\n"
                    "    args = sys.argv[1:]\n"
                    "    filtered_args = []\n"
                    "    for arg in args:\n"
                    "        if arg.startswith('-flto') or arg == '-fwhole-program' or arg == '-fno-use-linker-plugin':\n"
                    "            continue\n"
                    "        filtered_args.append(arg)\n"
                    "    res = subprocess.run([real_compiler] + filtered_args)\n"
                    "    sys.exit(res.returncode)\n"
                    "if __name__ == '__main__':\n"
                    "    main()\n"
                )
                
                for comp in ["arm-none-eabi-gcc", "avr-gcc"]:
                    wrapper_path = os.path.join(w_dir, comp)
                    with open(wrapper_path, "w", encoding="utf-8") as f:
                        f.write(wrapper_code)
                    os.chmod(wrapper_path, 0o755)
                    
                os.environ["PATH"] = w_dir + os.pathsep + old_path
            except Exception as wrapper_err:
                print(f"Warning: Failed to setup LTO compiler wrapper: {wrapper_err}")

        # 3. Resolve full configuration with olddefconfig
        subprocess.run(
            [_make, "olddefconfig"],
            cwd=klipper_path,
            check=True,
            capture_output=True,
            text=True
        )
        
        # 4. Post-olddefconfig Validation
        val_success, val_msg = validate_config(klipper_path)
        if not val_success:
             return {"status": "error", "message": val_msg}
        
        # 5. Clean and Compile
        subprocess.run(
            [_make, "clean"],
            cwd=klipper_path,
            check=True,
            capture_output=True,
            text=True
        )

        build_cmd = [_make]
        if os.environ.get("KACE_TESTING") != "1":
            try:
                nproc = subprocess.check_output(["nproc"]).decode().strip()
                build_cmd.append(f"-j{nproc}")
            except Exception:
                pass  # Fallback if nproc is not available

        subprocess.run(
            build_cmd,
            cwd=klipper_path,
            check=True,
            capture_output=True,
            text=True
        )

        # After compile: show mock warning if applicable
        print_mock_warning()
            
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
                    }

        return {"status": "error", "message": t("builder.no_binary")}
        
    except subprocess.CalledProcessError as e:
         return {"status": "error", "message": t("builder.make_error", code=e.returncode, error=e.stderr)}
    except FileNotFoundError:
         return {"status": "error", "message": t("builder.make_not_found")}
    except Exception as e:
         return {"status": "error", "message": t("builder.unexpected_error", error=str(e))}
    finally:
        # Restore PATH
        if old_path:
            os.environ["PATH"] = old_path
        else:
            os.environ.pop("PATH", None)
        # Clean up temporary wrapper directory
        if wrapper_dir_obj:
            try:
                wrapper_dir_obj.cleanup()
            except Exception:
                pass
