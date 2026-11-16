"""Existing dependency trees must prove both identity and clean bytes before reuse."""
import os
from pathlib import Path
import subprocess

import pytest

from tests.regression.test_bootstrap_minimal_mutation import _find_bash

BOOTSTRAP = Path(__file__).resolve().parents[2] / "scripts/bootstrap.sh"
pytestmark = pytest.mark.skipif(_find_bash() is None, reason="bash is required")


@pytest.mark.parametrize("mode", ["clean", "modified", "staged", "untracked", "origin", "status_error"])
def test_existing_pinned_checkout_rejects_unverified_worktree(tmp_path, mode):
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    sentinel = checkout / "custom.py"
    sentinel.write_bytes(b"operator file must remain untouched")
    command = r'''
set -euo pipefail
export KACE_BOOTSTRAP_LIB_ONLY=1
source "$1"
run_as_printer() {
    shift 3
    case "$1" in
        rev-parse) printf '%s\n' '1111111111111111111111111111111111111111' ;;
        remote)
            if [ "$MODE" = origin ]; then echo https://example.invalid/foreign.git;
            else echo https://example.invalid/expected.git; fi ;;
        status)
            case "$MODE" in
                modified) echo ' M scripts/install.sh' ;;
                staged) echo 'M  scripts/install.sh' ;;
                untracked) echo '?? klippy/extras/custom.py' ;;
                status_error) return 7 ;;
            esac ;;
        *) echo "unexpected command: $*" >&2; return 90 ;;
    esac
}
ensure_pinned_git_checkout Test https://example.invalid/expected.git \
    1111111111111111111111111111111111111111 "$2"
'''
    result = subprocess.run([_find_bash(), "-c", command, "test", BOOTSTRAP.as_posix(), checkout.as_posix()],
                            text=True, capture_output=True, timeout=15, env=dict(os.environ, MODE=mode))
    assert (result.returncode == 0) == (mode == "clean"), result.stdout + result.stderr
    assert sentinel.read_bytes() == b"operator file must remain untouched"
