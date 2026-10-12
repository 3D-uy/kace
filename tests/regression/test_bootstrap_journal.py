"""Exercise journal provisioning with fake services and temporary config only."""
import pytest

from tests.regression import test_bootstrap_config_defaults as defaults


pytestmark = pytest.mark.skipif(not defaults._find_bash(), reason="bash is required")


@pytest.fixture(scope="module")
def shell():
    defaults.TestBootstrapConfigDefaults.setUpClass()
    return defaults.TestBootstrapConfigDefaults()


def provision(shell, directory, *, failure=""):
    command = r'''
systemctl() {
    printf 'SERVICE:%s\n' "$*"
    [ "$FAILURE" != restart ]
}
journalctl() {
    printf 'JOURNAL:%s\n' "$*"
    [ "$FAILURE" != "$1" ]
}
systemd-analyze() {
    cat "$target"
    if [ "$FAILURE" = override ]; then printf '\n[Journal]\nStorage=volatile\n'; fi
}
FAILURE="''' + failure + r'''"
ensure_persistent_journal "$1"
'''
    return shell._run_bootstrap_library(command, directory)


def test_config_survives_relaunch_without_changing_other_dropins(shell, tmp_path):
    directory = tmp_path / "journald.conf.d"
    directory.mkdir()
    unrelated = directory / "90-operator.conf"
    unrelated.write_bytes(b"[Journal]\nForwardToConsole=no\n")
    for _ in range(2):
        result = provision(shell, directory)
        assert result.returncode == 0, result.stderr + result.stdout
        config = (directory / "60-kace-diagnostics.conf").read_text()
        assert "Storage=persistent\n" in config
        assert "SystemMaxUse=64M\n" in config
        assert "SystemKeepFree=128M\n" in config
        assert "MaxRetentionSec=7day\n" in config
        assert "SyncIntervalSec=30s\n" in config
        assert unrelated.read_bytes() == b"[Journal]\nForwardToConsole=no\n"
        assert [line for line in result.stdout.splitlines() if line.startswith(("SERVICE:", "JOURNAL:"))] == [
            "SERVICE:restart systemd-journald", "JOURNAL:--flush", "JOURNAL:--sync",
        ]


@pytest.mark.parametrize("failure", ["restart", "--flush", "--sync"])
def test_activation_failure_is_reported_and_retry_reactivates(shell, tmp_path, failure):
    directory = tmp_path / "journald.conf.d"
    result = provision(shell, directory, failure=failure)
    assert result.returncode != 0
    assert "Persistent system journal configured" not in result.stdout
    retry = provision(shell, directory)
    assert retry.returncode == 0, retry.stderr
    assert "SERVICE:restart systemd-journald" in retry.stdout
    assert "JOURNAL:--sync" in retry.stdout


def test_unowned_config_is_not_replaced(shell, tmp_path):
    target = tmp_path / "60-kace-diagnostics.conf"
    target.write_bytes(b"[Journal]\nStorage=volatile\n")
    result = provision(shell, tmp_path)
    assert result.returncode != 0
    assert target.read_bytes() == b"[Journal]\nStorage=volatile\n"
    assert "SERVICE:" not in result.stdout


def test_failed_write_does_not_restart_services(shell, tmp_path):
    directory = tmp_path / "not-a-directory"
    directory.write_bytes(b"keep")
    result = provision(shell, directory)
    assert result.returncode != 0
    assert "SERVICE:" not in result.stdout
    assert directory.read_bytes() == b"keep"


def test_later_volatile_override_stops_before_restart(shell, tmp_path):
    result = provision(shell, tmp_path, failure="override")
    assert result.returncode != 0
    assert "Effective journal storage is not persistent" in result.stderr
    assert "SERVICE:" not in result.stdout


def test_bootstrap_enables_diagnostics_before_packages():
    source = defaults.BOOTSTRAP.read_text(encoding="utf-8")
    assert source.index("if ! ensure_persistent_journal; then") < source.index('log_stage "PACKAGES"')
    assert 'emit_bootstrap_terminal "workflow_failed" "SYSTEM_JOURNAL" 1' in source
