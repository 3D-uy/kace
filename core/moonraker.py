# core/moonraker.py
#
# Moonraker REST API client for KACE.
# Handles config upload and printer restart via Moonraker's HTTP API.
#
# Design principles:
#   - Zero additional dependencies — uses only Python stdlib (urllib).
#   - All functions return (success: bool, message: str) tuples.
#   - No exceptions escape this module; all errors are caught and
#     returned as structured (False, error_message) results.
#   - Plain HTTP only; HTTPS/TLS support can be added in a future pass.

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

# ── Default Moonraker connection constants ──────────────────────
DEFAULT_PORT = 7125
_TIMEOUT     = 8   # seconds — generous enough for a Pi on local network


# ── Internal helpers ─────────────────────────────────────────────

def _base_url(host: str, port: int) -> str:
    """Build the Moonraker base URL from host and port."""
    host = host.strip().rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    return f"{host}:{port}"


def _get(url: str, api_key: str = None) -> tuple[bool, str, dict]:
    """Perform a GET request and return (success, message, json_body)."""
    try:
        headers = {"Accept": "application/json"}
        if api_key:
            headers["X-Api-Key"] = api_key
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
            return True, "OK", body
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.reason}", {}
    except urllib.error.URLError as e:
        return False, f"Connection error: {e.reason}", {}
    except Exception as e:
        return False, f"Unexpected error: {e}", {}


def _post(url: str, data: bytes = b"", content_type: str = "application/json", api_key: str = None) -> tuple[bool, str, dict]:
    """Perform a POST request and return (success, message, json_body)."""
    try:
        headers = {
            "Content-Type": content_type,
            "Accept": "application/json",
        }
        if api_key:
            headers["X-Api-Key"] = api_key
        req = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
            return True, "OK", body
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8", errors="replace"))
            msg = detail.get("error", {}).get("message", e.reason)
        except Exception:
            msg = e.reason
        return False, f"HTTP {e.code}: {msg}", {}
    except urllib.error.URLError as e:
        return False, f"Connection error: {e.reason}", {}
    except Exception as e:
        return False, f"Unexpected error: {e}", {}


def _post_multipart(url: str, field_name: str, filename: str, file_bytes: bytes, root: str = "config", api_key: str = None) -> tuple[bool, str, dict]:
    """POST a file as multipart/form-data to the Moonraker file upload endpoint."""
    boundary = uuid.uuid4().hex
    crlf = b"\r\n"

    # Build multipart body manually — no external library needed.
    parts = []

    # 'root' field (Moonraker requires this to know which virtual filesystem root)
    parts.append(f"--{boundary}".encode())
    parts.append(b'Content-Disposition: form-data; name="root"')
    parts.append(b"")
    parts.append(root.encode())

    # File field
    parts.append(f"--{boundary}".encode())
    parts.append(
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"'.encode()
    )
    parts.append(b"Content-Type: text/plain; charset=utf-8")
    parts.append(b"")
    parts.append(file_bytes)

    parts.append(f"--{boundary}--".encode())

    body = crlf.join(parts)
    content_type = f"multipart/form-data; boundary={boundary}"

    return _post(url, data=body, content_type=content_type, api_key=api_key)


# ── Public API ───────────────────────────────────────────────────

def check_moonraker(host: str, port: int = DEFAULT_PORT, api_key: str = None) -> tuple[bool, str]:
    """Probe Moonraker reachability via GET /server/info.

    Returns:
        (True, moonraker_version_string) on success.
        (False, error_message) on failure.
    """
    url = f"{_base_url(host, port)}/server/info"
    ok, msg, body = _get(url, api_key=api_key)
    if not ok:
        return False, msg
    version = body.get("result", {}).get("moonraker_version", "unknown")
    return True, f"Moonraker {version}"


def upload_printer_cfg(host: str, port: int, cfg_path: str, filename: str = None, api_key: str = None) -> tuple[bool, str]:
    """Upload a configuration file to Moonraker's config root via /server/files/upload.

    If filename is not explicitly provided, it defaults to the basename of the cfg_path.
    """
    cfg_path = os.path.expanduser(cfg_path)
    if not os.path.isfile(cfg_path):
        return False, f"Config file not found: {cfg_path}"

    try:
        with open(cfg_path, "rb") as f:
            file_bytes = f.read()
    except OSError as e:
        return False, f"Could not read config file: {e}"

    if not filename:
        filename = os.path.basename(cfg_path)

    url = f"{_base_url(host, port)}/server/files/upload"
    ok, msg, body = _post_multipart(
        url,
        field_name="file",
        filename=filename,
        file_bytes=file_bytes,
        root="config",
        api_key=api_key,
    )
    if not ok:
        return False, msg

    # Moonraker returns {"result": {"item": {"path": "printer.cfg", ...}}}
    uploaded_path = body.get("result", {}).get("item", {}).get("path", "printer.cfg")
    return True, uploaded_path


def restart_firmware(host: str, port: int = DEFAULT_PORT, api_key: str = None) -> tuple[bool, str]:
    """Issue a RESTART via POST /printer/restart.

    This reloads printer.cfg and restarts the Klipper host process.
    Equivalent to typing RESTART in the Klipper console.

    Returns:
        (True, "OK") on success.
        (False, error_message) on failure.
    """
    url = f"{_base_url(host, port)}/printer/restart"
    ok, msg, _ = _post(url, data=b"{}", content_type="application/json", api_key=api_key)
    if not ok:
        return False, msg
    return True, "RESTART issued"


def restart_klipper_service(host: str, port: int = DEFAULT_PORT, api_key: str = None) -> tuple[bool, str]:
    """Restart the Klipper system service via Moonraker's machine API.

    POST /machine/services/restart?service=klipper
    This is a harder restart — stops and restarts the klipper systemd service.

    Returns:
        (True, "OK") on success.
        (False, error_message) on failure.
    """
    url = f"{_base_url(host, port)}/machine/services/restart?service=klipper"
    ok, msg, _ = _post(url, data=b"{}", content_type="application/json", api_key=api_key)
    if not ok:
        return False, msg
    return True, "Klipper service restart issued"


def download_printer_cfg(host: str, port: int, filename: str, api_key: str = None) -> tuple[bool, bytes]:
    """Download a file from Moonraker's config root via GET /server/files/config/{filename}.

    Returns:
        (True, file_bytes) on success.
        (False, error_message_bytes) on failure.
    """
    url = f"{_base_url(host, port)}/server/files/config/{filename}"
    try:
        headers = {}
        if api_key:
            headers["X-Api-Key"] = api_key
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return True, resp.read()
    except Exception as e:
        return False, str(e).encode("utf-8")


def check_klipper_ready(host: str, port: int, api_key: str = None) -> tuple[bool, str]:
    """Query Klipper state via GET /printer/info and confirm readiness.

    Returns:
        (True, "ready") if Klipper is ready.
        (False, error_description) if Klipper is not ready or has a boot/config error.
    """
    url = f"{_base_url(host, port)}/printer/info"
    ok, msg, body = _get(url, api_key=api_key)
    if not ok:
        return False, f"unreachable: {msg}"
    
    result = body.get("result", {})
    state = result.get("state", "unknown")
    state_msg = result.get("state_message", "")
    
    # State message often contains errors or warnings if state is not ready
    if state == "ready":
        return True, "ready"
    
    # Capture error state message if present
    err_desc = f"state is '{state}'"
    if state_msg:
        err_desc += f" ({state_msg})"
    return False, err_desc




def get_klipper_state(host: str, port: int = DEFAULT_PORT, api_key: str = None) -> str:
    """Return the exact Klippy state string from GET /printer/info.

    Possible return values:
        "ready"        - Klipper is up and accepting commands
        "startup"      - Klipper is initialising (MCUs not yet connected)
        "shutdown"     - Klipper entered a shutdown state (MCU error etc.)
        "error"        - Klipper encountered a fatal error
        "disconnected" - Moonraker cannot reach klippy
        "unknown"      - Unexpected or unparseable response

    Prefer this over check_klipper_ready() when you need to branch on
    specific states rather than a simple ready/not-ready boolean.
    """
    url = f"{_base_url(host, port)}/printer/info"
    ok, msg, body = _get(url, api_key=api_key)
    if not ok:
        return "disconnected"
    return body.get("result", {}).get("state", "unknown")


def get_mcu_versions(host: str, port: int = DEFAULT_PORT, api_key: str = None) -> dict:
    """Query all MCU objects and return their mcu_version strings.

    Workflow:
      1. GET /printer/objects/list  to discover every Moonraker object name.
      2. Filter for names that are exactly "mcu" or start with "mcu ".
      3. GET /printer/objects/query?<mcu_names>=mcu_version  to fetch versions.

    Returns a dict keyed by Moonraker object name:
        {"mcu": "kace-a1b2c3d", "mcu toolboard": "kace-e4f5a6b"}

    Returns an empty dict on any failure (caller treats empty as "not visible").
    """
    # Step 1: discover available objects
    list_url = f"{_base_url(host, port)}/printer/objects/list"
    ok, _, body = _get(list_url, api_key=api_key)
    if not ok:
        return {}

    all_objects = body.get("result", {}).get("objects", [])
    mcu_names = [o for o in all_objects if o == "mcu" or o.startswith("mcu ")]
    if not mcu_names:
        return {}

    # Step 2: query mcu_version for each MCU object
    # Moonraker query format: /printer/objects/query?obj1=attr&obj2=attr
    # Spaces in object names must be URL-encoded as %20 (not +).
    query_parts = [urllib.parse.quote(name, safe="") + "=mcu_version" for name in mcu_names]
    query_url = f"{_base_url(host, port)}/printer/objects/query?" + "&".join(query_parts)
    ok, _, body = _get(query_url, api_key=api_key)
    if not ok:
        return {}

    status = body.get("result", {}).get("status", {})
    result = {}
    for name in mcu_names:
        obj_data = status.get(name, {})
        version = obj_data.get("mcu_version")
        if version:
            result[name] = version
    return result


def verify_remote_file_exists(host: str, port: int, filename: str, api_key: str = None) -> bool:
    """Verify whether a file exists in the config root by querying server/files/list.

    Returns True if found, False otherwise.
    """
    url = f"{_base_url(host, port)}/server/files/list?root=config"
    ok, _, body = _get(url, api_key=api_key)
    if not ok:
        return False
    
    files = body.get("result", [])
    # result can be a list of file dicts: [{"path": "printer.cfg", ...}]
    for f in files:
        if isinstance(f, dict) and f.get("path") == filename:
            return True
    return False

