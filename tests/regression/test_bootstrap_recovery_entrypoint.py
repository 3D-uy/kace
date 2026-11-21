"""Recovery guidance must retain the selected preflight owner."""
import os
import subprocess

import pytest

from tests.regression.test_bootstrap_config_defaults import BOOTSTRAP, _find_bash


@pytest.mark.skipif(not _find_bash(), reason="bash is required")
@pytest.mark.parametrize("studio_context", ["0", "1"])
@pytest.mark.parametrize("checkpoint_status", [0, 1], ids=["pending", "absent"])
def test_recovery_hint_uses_the_launch_route(studio_context, checkpoint_status):
    script = BOOTSTRAP.read_text(encoding="utf-8")
    start = script.index('if [ "$INSTALL_OK" -ne 1 ]; then')
    end = script.index("\nfi\n", start) + len("\nfi\n")
    harness = r"""
set -eu
has_pending_checkpoint() { return "$CHECKPOINT_STATUS"; }
log_warn() { printf '%s\n' "$1"; }
emit_bootstrap_terminal() { printf '%s %s %s\n' "$1" "$2" "$3"; }
"""
    environment = dict(os.environ, STUDIO_PREFLIGHT_CONTEXT=studio_context,
                       CHECKPOINT_STATUS=str(checkpoint_status), INSTALL_OK="0", INSTALL_EXIT="2")
    result = subprocess.run(
        [_find_bash(), "-c", harness + script[start:end]],
        env=environment, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 2, result.stderr
    if checkpoint_status:
        assert result.stdout.splitlines() == ["workflow_cancelled CANCELLED 2"]
        return
    assert result.stdout.splitlines()[-1] == "workflow_cancelled RECOVERY_AVAILABLE 2"
    if studio_context == "1":
        assert "Resume installation" in result.stdout
        assert "KACE Studio" in result.stdout
        assert "running kace" not in result.stdout
    else:
        assert "running kace" in result.stdout
        assert "KACE Studio" not in result.stdout
