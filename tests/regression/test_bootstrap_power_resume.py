"""Bootstrap relaunches recover verified power settings without hardware IO."""
import json

import pytest

from tests.regression import test_bootstrap_config_defaults as defaults


pytestmark = pytest.mark.skipif(not defaults._find_bash(), reason="bash is required")

BASE_CONFIG = "[server]\nport: 7125\n\n[file_manager]\nenable_object_processing: True\n"
MANAGED_BLOCK = (
    "\n# BEGIN KACE MANAGED: power\n[power printer]\ntype: gpio\npin: !gpio21\n"
    "restart_klipper_when_powered: true\ninitial_state: on\noff_when_shutdown: false\n"
    "# END KACE MANAGED: power\n"
)
LIGHTS = "\n[power lights]\ntype: gpio\npin: gpiochip0/gpio6\n"
STATE = {
    "schema": "kace-power/v1", "revision": 7, "enabled": True,
    "device": "printer", "pin": "gpiochip0/gpio21", "active_low": True,
    "restart_klipper_when_powered": True, "initial_state": "on",
    "off_when_shutdown": False,
}


@pytest.fixture(scope="module")
def shell():
    # Composition avoids collecting the imported TestCase's existing test methods.
    defaults.TestBootstrapConfigDefaults.setUpClass()
    return defaults.TestBootstrapConfigDefaults()


def inputs(root, *, content=BASE_CONFIG + MANAGED_BLOCK, state=STATE):
    home = root / "home"
    config = home / "printer_data/config/moonraker.conf"
    config.parent.mkdir(parents=True)
    if content is not None:
        config.write_bytes(content.encode("utf-8"))
    state_path = home / ".config/kace/power.json"
    if state is not None:
        state_path.parent.mkdir(parents=True)
        payload = state if isinstance(state, str) else json.dumps(state, indent=2, sort_keys=True) + "\n"
        state_path.write_bytes(payload.encode("utf-8"))
    return config, home, state_path


def resume(shell, config, home, *, requested=""):
    command = """
PRINTER_HOME="$2"
PRINTER_USER="$(id -un)"
PRINTER_GROUP="$PRINTER_USER"
POWER_CONFIG_PATH="$2/.config/kace/power.json"
chown() { return 0; }
POWER_RELAY=""
POWER_DEVICE=""
POWER_GPIO=""
POWER_ACTIVE_LOW=""
POWER_RESTART_KLIPPER=""
POWER_INITIAL_STATE=""
POWER_OFF_WHEN_SHUTDOWN=""
POWER_RELAY_RESTORED=0
""" + requested + """
resolve_power_relay_settings "$POWER_CONFIG_PATH" "$1"
printf 'RESOLVED:%s:%s:%s:%s:%s:%s:%s:%s\n' "$POWER_RELAY" "$POWER_DEVICE" "$POWER_GPIO" \
    "$POWER_ACTIVE_LOW" "$POWER_RESTART_KLIPPER" "$POWER_INITIAL_STATE" \
    "$POWER_OFF_WHEN_SHUTDOWN" "$POWER_RELAY_RESTORED"
begin_power_reconciliation "$1"
ensure_moonraker_config "$1" "$2/printer_data/comms/klippy.sock"
persist_power_controller_config
commit_power_reconciliation
"""
    return shell._run_bootstrap_library(command, config, home)


def assert_rejected_without_changes(root, result):
    assert result.returncode != 0, result.stdout + result.stderr
    assert "RESOLVED:" not in result.stdout
    assert not list(root.rglob("*.kace-power-backup.*"))
    assert not list(root.rglob("*.part"))


@pytest.mark.parametrize("position", ["end", "middle"])
def test_relaunch_without_seed_preserves_config_and_revision(shell, tmp_path, position):
    block = MANAGED_BLOCK
    if position == "middle":
        block = block.replace("# END KACE MANAGED: power", "locked_while_printing: true\n# local relay comment\n# END KACE MANAGED: power")
    content = BASE_CONFIG + block + (LIGHTS if position == "middle" else "")
    config, home, state_path = inputs(tmp_path, content=content)
    original_config, original_state = config.read_bytes(), state_path.read_bytes()
    for _ in range(2):
        result = resume(shell, config, home)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "RESOLVED:true:printer:21:true:true:on:false:1" in result.stdout
        assert config.read_bytes() == original_config
        assert state_path.read_bytes() == original_state


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_relaunch_preserves_saved_formatting_and_extra_metadata(shell, tmp_path, newline):
    config, home, state_path = inputs(tmp_path)
    state = dict(STATE, operator_note="keep this metadata")
    original = (json.dumps(state, indent=4).replace("\n", newline) + newline).encode("utf-8")
    state_path.write_bytes(original)
    result = resume(shell, config, home)
    assert result.returncode == 0, result.stdout + result.stderr
    assert state_path.read_bytes() == original
        assert not list(tmp_path.rglob("*.kace-power-backup.*"))


INVALID_STATES = [
    {**STATE, "schema": 1}, {**STATE, "schema": "unknown"},
    {**STATE, "enabled": 1}, {**STATE, "active_low": "true"},
    {**STATE, "restart_klipper_when_powered": 1}, {**STATE, "off_when_shutdown": None},
    {**STATE, "revision": True}, {**STATE, "revision": 0},
    {**STATE, "pin": "gpiochip1/gpio21"}, {**STATE, "pin": "gpio21"},
    {**STATE, "pin": "gpiochip0/gpio1000"},
    {**STATE, "device": "printer; touch unsafe"},
    {**STATE, "device": "$(touch unsafe)"},
    {**STATE, "initial_state": "on; touch unsafe"},
    {key: value for key, value in STATE.items() if key != "active_low"},
    {key: value for key, value in STATE.items() if key != "device"},
    "invalid JSON", "[]", "null",
]


@pytest.mark.parametrize("state", INVALID_STATES, ids=[
    "legacy-schema", "unknown-schema", "enabled-integer", "active-low-string",
    "restart-integer", "shutdown-null", "revision-boolean", "revision-zero",
    "unsupported-chip", "unqualified-pin", "oversize-pin", "device-semicolon",
    "device-substitution", "initial-state-injection", "missing-active-low",
    "missing-device", "invalid-json", "json-list", "json-null",
])
def test_invalid_persisted_settings_abort_before_modification(shell, tmp_path, state):
    config, home, state_path = inputs(tmp_path, state=state)
    original_config, original_state = config.read_bytes(), state_path.read_bytes()
    result = resume(shell, config, home)
    assert_rejected_without_changes(tmp_path, result)
    assert config.read_bytes() == original_config
    assert state_path.read_bytes() == original_state


@pytest.mark.parametrize("content", [
    BASE_CONFIG,
    BASE_CONFIG + MANAGED_BLOCK.replace("!gpio21", "!gpio20"),
    BASE_CONFIG + MANAGED_BLOCK.replace("initial_state: on", "initial_state: off"),
    BASE_CONFIG + MANAGED_BLOCK.replace("# BEGIN KACE MANAGED: power\n", ""),
    BASE_CONFIG + MANAGED_BLOCK.replace("# END KACE MANAGED: power", "# END KACE MANAGED: power\n# END KACE MANAGED: power"),
    BASE_CONFIG + MANAGED_BLOCK.replace("# BEGIN KACE MANAGED: power\n", "") +
        "\n# BEGIN KACE MANAGED: power\n[power lights]\ntype: gpio\npin: gpio6\n",
], ids=["missing-block", "pin-edit", "initial-state-edit", "missing-marker",
        "duplicate-marker", "marker-wrong-owner"])
def test_persisted_and_live_mismatch_requires_manual_recovery(shell, tmp_path, content):
    config, home, state_path = inputs(tmp_path, content=content)
    original_config, original_state = config.read_bytes(), state_path.read_bytes()
    result = resume(shell, config, home)
    assert_rejected_without_changes(tmp_path, result)
    assert config.read_bytes() == original_config
    assert state_path.read_bytes() == original_state


@pytest.mark.parametrize("content", [BASE_CONFIG + MANAGED_BLOCK, BASE_CONFIG + LIGHTS],
                         ids=["managed", "unmanaged"])
def test_missing_state_with_existing_power_does_not_infer_disabled(shell, tmp_path, content):
    config, home, state_path = inputs(tmp_path, content=content, state=None)
    original = config.read_bytes()
    result = resume(shell, config, home)
    assert_rejected_without_changes(tmp_path, result)
    assert config.read_bytes() == original
    assert not state_path.exists()


@pytest.mark.parametrize("requested", ['POWER_GPIO=21\n', 'POWER_DEVICE=printer\n', 'POWER_ACTIVE_LOW=true\n'])
def test_partial_requested_settings_are_not_masked_by_persisted_state(shell, tmp_path, requested):
    config, home, state_path = inputs(tmp_path)
    original_config, original_state = config.read_bytes(), state_path.read_bytes()
    result = resume(shell, config, home, requested=requested)
    assert_rejected_without_changes(tmp_path, result)
    assert config.read_bytes() == original_config
    assert state_path.read_bytes() == original_state


def test_explicit_disable_still_removes_only_managed_device(shell, tmp_path):
    config, home, state_path = inputs(tmp_path, content=BASE_CONFIG + LIGHTS + MANAGED_BLOCK)
    result = resume(shell, config, home, requested="POWER_RELAY=false\n")
    assert result.returncode == 0, result.stdout + result.stderr
    content = config.read_text(encoding="utf-8")
    assert "[power printer]" not in content
    assert "KACE MANAGED: power" not in content
    assert LIGHTS.strip() in content
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["enabled"] is False
    assert state["device"] is None and state["pin"] is None
    assert state["revision"] == STATE["revision"] + 1


def test_first_boot_without_power_still_defaults_to_disabled(shell, tmp_path):
    config, home, state_path = inputs(tmp_path, content=None, state=None)
    result = resume(shell, config, home)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "RESOLVED:false:" in result.stdout
    assert "[power " not in config.read_text(encoding="utf-8")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["enabled"] is False and state["revision"] == 1


def test_disabled_state_with_managed_config_is_not_silently_reconciled(shell, tmp_path):
    disabled = {**STATE, "enabled": False, "device": None, "pin": None,
                "active_low": False, "initial_state": "off",
                "restart_klipper_when_powered": False, "off_when_shutdown": True}
    config, home, state_path = inputs(tmp_path, state=disabled)
    original_config, original_state = config.read_bytes(), state_path.read_bytes()
    result = resume(shell, config, home)
    assert_rejected_without_changes(tmp_path, result)
    assert config.read_bytes() == original_config
    assert state_path.read_bytes() == original_state


def test_coherent_disabled_state_preserves_revision_and_other_power(shell, tmp_path):
    disabled = {**STATE, "enabled": False, "device": None, "pin": None,
                "active_low": False, "initial_state": "off",
                "restart_klipper_when_powered": False, "off_when_shutdown": True}
    config, home, state_path = inputs(tmp_path, content=BASE_CONFIG + LIGHTS, state=disabled)
    original_config, original_state = config.read_bytes(), state_path.read_bytes()
    for _ in range(2):
        result = resume(shell, config, home)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "RESOLVED:false:::false:false:off:true:1" in result.stdout
        assert config.read_bytes() == original_config
        assert state_path.read_bytes() == original_state


def test_main_resolves_settings_before_backups_or_config_mutation():
    source = defaults.BOOTSTRAP.read_text(encoding="utf-8")
    main = source[source.index("# ── Resolve Printer User Home Directory"):]
    resolution = main.index("if ! resolve_power_relay_settings")
    mutation = main.index('mkdir -p "$PRINTER_HOME/printer_data/config"')
    backup = main.index('begin_power_reconciliation "$PRINTER_HOME/printer_data/config/moonraker.conf"')
    assert resolution < mutation < backup
