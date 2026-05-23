import os
import platform
import posixpath
import shutil
import subprocess
import sys

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
            # Use check_output instead of check_call to capture errors silently on success,
            # but show them on failure.
            pip_cmd = [sys.executable, "-m", "pip", "install", "paramiko==3.4.0"]
            if platform.system() != "Windows":
                pip_cmd.append("--break-system-packages")
            subprocess.check_output(
                pip_cmd,
                stderr=subprocess.STDOUT
            )
            import paramiko  # noqa: PLC0415
            print("\033[92m[✔] paramiko installed successfully.\033[0m\n")
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


def deploy_config(user_data):
    """Deploys the generated printer.cfg to the Klipper host via SSH/SCP."""
    paramiko = _require_paramiko()
    if paramiko is None:
        return  # error already printed by _require_paramiko

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        print(f"Connecting to {user_data['host']}...")
        ssh.connect(
            user_data['host'],
            username=user_data['user'],
            password=user_data['password']
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
        print(f"Uploading printer.cfg to {dest_file}...")
        cfg_path = os.path.expanduser('~/kace/printer.cfg')
        sftp.put(cfg_path, dest_file)

        sftp.close()
        ssh.close()
    except Exception as e:
        print(f"\033[91mDeployment failed: {e}\033[0m")


def deploy_usb(user_data, artifact_type="all"):
    """Deploys the generated artifact(s) to a USB/SD card."""
    try:
        import questionary
        from core.style import custom_style
        
        name_prompt = "Configuration (printer.cfg)" if artifact_type == "config" else \
                      "Firmware (klipper.bin/.uf2)" if artifact_type == "firmware" else "Configuration and Firmware"
                      
        dest = questionary.text(
            f"Enter USB/SD Card mount path for {name_prompt} (e.g. D:\\ or /media/usb):",
            style=custom_style
        ).ask()
        
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
        
        if artifact_type in ["firmware", "all"]:
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
        import questionary
        from core.style import custom_style
        
        name_prompt = "Configuration (printer.cfg)" if artifact_type == "config" else \
                      "Firmware (klipper.bin/.uf2)" if artifact_type == "firmware" else "Configuration and Firmware"
                      
        dest = questionary.text(
            f"Enter local destination folder path for {name_prompt} (e.g. C:\\3DPrinter or ~/Documents):",
            style=custom_style
        ).ask()
        
        if not dest:
            return

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
        
        if artifact_type in ["firmware", "all"]:
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
    import questionary
    from core.style import custom_style

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
    port = questionary.text(
        "Enter the serial port for flashing:",
        default=default_port,
        style=custom_style
    ).ask()

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
    
    confirm = questionary.confirm("Execute this command now?").ask()
    if confirm:
        print("\n\033[96m>>> Running avrdude...\033[0m")
        try:
            subprocess.run(cmd, check=True)
            print("\n\033[92mSUCCESS:\033[0m Firmware flashed successfully!")
        except subprocess.CalledProcessError as e:
            print(f"\n\033[91mERROR:\033[0m avrdude failed with return code {e.returncode}.")
    else:
        print("\n\033[93mCommand execution cancelled. You can run it manually.\033[0m")

