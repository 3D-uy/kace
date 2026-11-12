"""Recovery guidance must retain the selected preflight owner."""
import os
import subprocess

import pytest

from tests.regression.test_bootstrap_config_defaults import BOOTSTRAP, _find_bash


@pytest.mark.skipif(not _find_bash(), reason="bash is required")
@pytest.mark.parametrize("studio_context", ["0", "1"])
def test_recovery_hint_uses_the_launch_route(studio_context):
    script = BOOTSTRAP.read_text(encoding="utf-8")
    checkpoint_check = 'raise SystemExit(0 if c and c["state"] != "COMPLETE" else 1)'
    body = script.split(checkpoint_check, 1)[1].split("); then", 1)[1]
    body = body.split("        emit_bootstrap_terminal", 1)[0]
    environment = dict(os.environ, STUDIO_PREFLIGHT_CONTEXT=studio_context)
    result = subprocess.run(
        [_find_bash(), "-c", 'log_warn() { printf "%s\\n" "$1"; };\n' + body],
        env=environment, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    if studio_context == "1":
        assert "Resume installation" in result.stdout
        assert "KACE Studio" in result.stdout
        assert "running kace" not in result.stdout
    else:
        assert "running kace" in result.stdout
        assert "KACE Studio" not in result.stdout
