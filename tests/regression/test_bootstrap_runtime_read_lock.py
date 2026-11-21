"""Checkpoint diagnostics must not import a runtime being replaced by install.sh."""
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

import pytest


BOOTSTRAP = Path(__file__).resolve().parents[2] / "scripts/bootstrap.sh"
pytestmark = pytest.mark.skipif(os.name != "posix", reason="requires real POSIX flock; Git Bash does not qualify this lock")


@pytest.fixture
def checkpoint_reader(request, tmp_path):
    # Root-run container suites also exercise the real non-root diagnostic.
    if os.geteuid() == 0:
        import pwd
        account = pwd.getpwnam("nobody")
        area = tempfile.TemporaryDirectory()
        request.addfinalizer(area.cleanup)
        tmp_path = Path(area.name)
        os.chown(tmp_path, account.pw_uid, account.pw_gid)
    home = tmp_path / "home"
    runtime = home / "kace"
    (runtime / "venv/bin").mkdir(parents=True)
    (runtime / "core").mkdir()
    (runtime / "core/__init__.py").write_text("")
    # The module is synthetic: no real checkpoint, MCU, service or user path.
    (runtime / "core/firmware_workflow.py").write_text('''
import errno
import fcntl
import os
from pathlib import Path

Path(os.environ["READ_MARKER"]).write_text("imported")

def load_checkpoint(path, verify_artifact):
    assert path == "firmware-workflow.json" and verify_artifact is True
    with Path(os.environ["READ_LOCK"]).open("r") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            assert error.errno in (errno.EACCES, errno.EAGAIN)
            Path(os.environ["LOCK_MARKER"]).write_text("shared lock retained")
        else:
            raise RuntimeError("runtime read was not protected by a shared lock")
    return {"state": os.environ.get("CHECKPOINT_STATE", "DEPLOYING")}
''')
    python = runtime / "venv/bin/python"
    python.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + ' -B "$@"\n')
    python.chmod(0o755)
    lock = home / ".kace-install.lock"
    lock.write_text("")
    source = BOOTSTRAP.read_text(encoding="utf-8")
    def function(name):
        start = source.index(name + "() {")
        return source[start:source.index("\n}", start) + 2]

    script = function("run_as_printer") + "\n" + function("has_pending_checkpoint")
    script += '\nPRINTER_USER=${PRINTER_USER:-$(id -un)}\nhas_pending_checkpoint\n'
    script_path = tmp_path / "read-checkpoint.sh"
    script_path.write_text(script)
    env = dict(os.environ, PRINTER_HOME=str(home), READ_LOCK=str(lock),
               READ_MARKER=str(tmp_path / "imported"), LOCK_MARKER=str(tmp_path / "locked"),
               PYTHONDONTWRITEBYTECODE="1")
    return home, lock, script_path, env


def run_reader(fixture, **extra):
    _, _, script, env = fixture
    identity = {}
    if os.geteuid() == 0:
        import pwd
        account = pwd.getpwnam("nobody")
        identity = dict(user=account.pw_uid, group=account.pw_gid, extra_groups=[])
    return subprocess.run(["/bin/bash", str(script)], env={**env, **extra}, **identity,
                          capture_output=True, text=True, timeout=5)


def assert_not_imported(fixture, result):
    assert result.returncode != 0
    assert not Path(fixture[3]["READ_MARKER"]).exists()


def test_exclusive_installer_blocks_diagnostic_before_runtime_import(checkpoint_reader):
    import fcntl
    with checkpoint_reader[1].open("r") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert_not_imported(checkpoint_reader, run_reader(checkpoint_reader))


@pytest.mark.parametrize("kind", ["regular", "dangling-symlink"])
def test_unfinished_journal_blocks_diagnostic_before_runtime_import(checkpoint_reader, kind):
    home, _, _, _ = checkpoint_reader
    journal = home / ".kace-runtime-transaction.json"
    if kind == "regular":
        journal.write_text("unfinished")
    else:
        journal.symlink_to(home / "absent-target")
    assert_not_imported(checkpoint_reader, run_reader(checkpoint_reader))


def test_missing_lock_is_not_created_by_bootstrap_diagnostic(checkpoint_reader):
    lock = checkpoint_reader[1]
    lock.unlink()
    assert_not_imported(checkpoint_reader, run_reader(checkpoint_reader))
    assert not lock.exists()


def test_missing_flock_does_not_fall_back_to_unprotected_import(checkpoint_reader, tmp_path):
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    assert_not_imported(checkpoint_reader, run_reader(checkpoint_reader, PATH=str(empty_bin)))


def test_pending_checkpoint_is_read_under_shared_lock(checkpoint_reader):
    result = run_reader(checkpoint_reader)
    assert result.returncode == 0, result.stderr
    assert Path(checkpoint_reader[3]["LOCK_MARKER"]).read_text() == "shared lock retained"


def test_complete_checkpoint_is_not_reported_as_pending(checkpoint_reader):
    result = run_reader(checkpoint_reader, CHECKPOINT_STATE="COMPLETE")
    assert result.returncode != 0
    assert Path(checkpoint_reader[3]["LOCK_MARKER"]).read_text() == "shared lock retained"

@pytest.mark.skipif(os.name != "posix" or os.geteuid() != 0, reason="requires disposable Linux root")
def test_root_diagnostic_drops_uid_and_rejects_root_target(checkpoint_reader):
    import pwd
    home, _, script, env = checkpoint_reader
    directory = home.parent
    account = pwd.getpwnam("nobody")
    reader = home / "kace/venv/bin/python"
    # Read only the effective identity. This stand-in never imports runtime code.
    reader.write_text("#!/bin/sh\nid -u > " + shlex.quote(str(directory / "effective-uid")) + "\n")
    result = subprocess.run(["/bin/bash", str(script)], env={**env, "PRINTER_USER": account.pw_name})
    assert result.returncode == 0
    marker = directory / "effective-uid"
    assert marker.read_text().strip() == str(account.pw_uid)
    marker.unlink()
    result = subprocess.run(["/bin/bash", str(script)], env={**env, "PRINTER_USER": "root"})
    assert result.returncode != 0 and not marker.exists()
