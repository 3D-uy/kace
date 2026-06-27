# KACE Deployment System: SSH vs. Moonraker API

This document explains in detail how KACE deploys generated configuration files (`printer.cfg` and `macros.cfg`) to a Klipper-enabled 3D printer. It covers the underlying mechanisms, protocols, security considerations, verification processes, automatic rollback logic, and a comparison to help you choose the best deployment method.

---

## 1. Overview of KACE Deployment

After KACE generates `printer.cfg` and `macros.cfg` (stored locally in `~/kace/`), it offers two primary methods to push these configurations directly to your printer:

1. **SSH / SFTP (Push to Host)**: Directly communicates with the host operating system (e.g. Raspberry Pi) filesystem and systemd manager.
2. **Moonraker API (Web Push & Control)**: Communicates with Moonraker (the API server for Klipper web interfaces like Mainsail/Fluidd) via HTTP.

Additionally, KACE supports **local copying** and **USB/SD card export** for manual installations.

---

## 2. SSH / SFTP Deployment

The SSH deployment mode directly targets the underlying Linux host filesystem.

### How It Works Under the Hood
1. **Library**: KACE uses `paramiko` for SSH and SFTP protocols. This library is imported lazily. If it's not installed, KACE will automatically offer to install it via pip (with hash verification pointing to `requirements-ssh.txt`).
2. **Host Verification**: Unlike basic scripts that insecurely auto-accept SSH keys (making them vulnerable to Man-in-the-Middle attacks), KACE implements a custom interactive host key policy (`_InteractiveHostKeyPolicy`). If a host key is unknown:
   - It displays the key's algorithm and fingerprint.
   - It asks the user for explicit confirmation before connecting.
   - Once trusted, it saves the key to `~/.ssh/known_hosts` for future passwordless verification.
3. **SFTP File Upload**:
   - Establish SFTP channel over SSH.
   - Expand relative destination paths (e.g., `~/printer_data/config/` is resolved relative to the user's home directory).
   - If `printer.cfg` or `macros.cfg` already exists on the remote system, they are renamed to `.bak` files (backup).
   - Upload new files using `sftp.put()`.
4. **Service Restart**:
   - First, KACE probes if Moonraker is active on port 7125.
   - If Moonraker is reachable, Klipper is restarted gracefully via the Moonraker API (using a service restart request).
   - If Moonraker is not reachable, KACE executes a remote shell command to restart the systemd unit:
     ```bash
     sudo -n systemctl restart klipper || systemctl --user restart klipper || systemctl restart klipper
     ```
5. **Post-Deployment Verification**:
   - KACE loops for up to 10 seconds to verify Klipper restarted successfully.
   - It checks systemd status (`systemctl is-active klipper`) and verifies via SFTP that files exist on the host.
   - **On Success**: Backup `.bak` files are deleted automatically.
   - **On Failure**: If Klipper fails to start or files are missing:
     - It fetches logs using `journalctl -u klipper -n 50 --no-pager` (or user/systemd fallbacks) and prints them to assist in troubleshooting.
     - **Automatic Rollback**: It connects back to SFTP, deletes the bad files, renames the `.bak` files back to their original names, and triggers another restart to ensure the printer returns to a working state.

---

## 3. Moonraker API Deployment

The Moonraker REST API deployment utilizes the official HTTP API provided by Moonraker to manage configurations.

### How It Works Under the Hood
1. **Library**: KACE uses Python’s built-in `urllib` library. This ensures zero external dependencies are required for HTTP deployment, making KACE extremely lightweight.
2. **Authentication**: If your Moonraker instance requires an API key, you can provide it. KACE sends it securely via the `X-Api-Key` header.
   - *Security warning*: KACE warns the user if they input an API key over unencrypted HTTP, prompting confirmation before proceeding.
3. **Backup Mechanism**:
   - Queries `server/files/list?root=config` to verify if files already exist.
   - If files exist, KACE downloads `printer.cfg` and `macros.cfg` via GET requests:
     ```http
     GET /server/files/config/printer.cfg
     ```
   - These backups are stored **in-memory** during the transition.
4. **Multipart File Upload**:
   - Uploads files using a manually constructed `multipart/form-data` payload (to avoid external dependencies like `requests`).
   - Endpoint:
     ```http
     POST /server/files/upload
     ```
     With form fields `root="config"` and the file binary.
5. **Granular Restart Options**:
   The user is prompted to select a restart behavior:
   - **Firmware Restart (`firmware`)**: Triggers `POST /printer/firmware_restart`. This reloads Klipper configurations and restarts the MCU connection. Equivalent to sending the `FIRMWARE_RESTART` gcode.
   - **Klipper Service Restart (`service`)**: Triggers `POST /machine/services/restart?service=klipper`. Restarts the host systemd service via Moonraker's OS manager.
   - **Skip (`skip`)**: Does not issue any restart commands.
6. **Post-Deployment Verification**:
   - Loops for 10 seconds checking `GET /printer/info`.
   - Verifies the state changes to `"ready"`.
   - Queries `GET /server/files/list?root=config` to ensure the uploaded files are present.
   - **On Failure / Error State**:
     - **Automatic Rollback**: The in-memory backups are written to temporary files on the host computer and uploaded back to Moonraker. A restart command is sent to restore the previous working state.

---

## 4. SSH vs. Moonraker API: A Detailed Comparison

| Feature | SSH / SFTP Deployment | Moonraker API Deployment |
| :--- | :--- | :--- |
| **Dependencies** | Requires `paramiko` (installed dynamically) | Standard library only (`urllib`) |
| **Credentials Needed**| OS Username and Password / SSH Key | Moonraker IP/Port and optional API Key |
| **Security** | Safe SSH key verification, but exposes OS credentials | Uses API keys; warns on unencrypted HTTP |
| **Restart Capability**| Restarts via Moonraker or fallback Linux commands | Can restart Firmware (graceful) or Klipper Service |
| **Troubleshooting** | Fetches `journalctl` host systemd logs on failure | Limited to state message returned by Moonraker |
| **Backup Storage** | Renamed `.bak` files on the host filesystem | Temporary in-memory download on client |
| **Fallback System** | Rolls back via SFTP filesystem rename | Rolls back via uploading in-memory backups |
| **Reliability** | Works even if Moonraker is completely down | Requires Moonraker API service to be functional |

---

## 5. What is the Best Way to Deploy?

### The Recommended Path: **Moonraker API**
For 95% of setups, **Moonraker API is the best choice**. 

#### Why Moonraker is preferred:
* **Minimal Privileges**: You don't need to share Linux OS credentials (e.g., username/password for SSH) with KACE. You only need the API key or local network access.
* **Graceful restarts**: In Klipper, most configuration changes only require a **Firmware Restart** (`FIRMWARE_RESTART`), which reloads the configuration in seconds without restarting the host service. SSH usually defaults to a service restart, which is slower and drops connection to other services.
* **Compatibility**: Moonraker manages the directories internally (handling the virtual `config` root), meaning KACE doesn't need to know the exact path structure (e.g. `~/printer_data/config` vs `~/klipper_config` vs `~/.config`).
* **Zero Overhead**: Does not require compiling or downloading compilation libraries like `paramiko`.

### When to use SSH Fallback:
* **Initial Setup / Stuck Service**: If Klipper/Moonraker is crashed, frozen, or has not been fully configured yet, SSH can access the host even when the API is dead.
* **Deep Debugging**: When Klipper fails to start due to a major system or driver error, KACE's SSH mode can fetch systemd `journalctl` logs. The Moonraker API cannot provide these detailed OS-level system logs if the daemon is failing to initialize.
* **Multi-Instance OS Configs**: If you run complex custom service wrappers that require physical OS interaction.

---

## 6. How KACE Combines Both (Hybrid Fallback)
KACE is designed to be resilient. When you run a Moonraker deployment:
1. It tries to connect to the Moonraker REST API.
2. If Moonraker is unreachable (e.g., service is down or blocked), KACE automatically prompts you: 
   > *"Would you like to fall back to SSH deployment instead?"*
3. If accepted, KACE asks for your SSH credentials and leverages the SSH pipeline to copy the files and reboot Klipper via systemd.
