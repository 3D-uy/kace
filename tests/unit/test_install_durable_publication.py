"""Exercise the standalone installer's journal in disposable directories only."""
from pathlib import Path
import os
import shlex
import subprocess
import types

import pytest


SOURCE = Path(__file__).resolve().parents[2] / "install.sh"


@pytest.fixture
def journal():
    source = SOURCE.read_text(encoding="utf-8")
    marker = "<<'KACE_RUNTIME_TRANSACTION_PY'\n"
    assert marker in source, "installer must recover without importing a mixed runtime"
    code = source.split(marker, 1)[1].split("\nKACE_RUNTIME_TRANSACTION_PY", 1)[0]
    module = types.ModuleType("installer_journal_under_test")
    exec(compile(code, str(SOURCE), "exec"), module.__dict__)
    return module


@pytest.fixture
def runtime(tmp_path):
    live = tmp_path / "kace"
    stage = tmp_path / ".kace-install.test"
    backup = tmp_path / ".kace-backup.test"
    names = [".git", ".kace-runtime-commit", "kace.py", "VERSION", "core"]
    for folder in (live, stage, backup):
        folder.mkdir()
    for folder, version in ((live, "old"), (stage, "new")):
        for name in names:
            if name in ("core", ".git"):
                (folder / name).mkdir()
                (folder / name / "payload").write_text(version)
            else:
                (folder / name).write_text(version)
    (live / "printer.cfg").write_text("user configuration")
    return live, stage, backup, names


@pytest.mark.parametrize("moves", range(11))
def test_relaunch_recovers_after_every_rename(journal, runtime, moves):
    live, stage, backup, names = runtime
    previous = {name: journal.fingerprint(live / name) for name in names}
    journal.begin(live, stage, backup, names)
    operations = [(a, b) for name in names for a, b in (
        (live / name, backup / name), (stage / name, live / name))]
    for src, dest in operations[:moves]:
        src.rename(dest)  # no EXIT handler: model abrupt termination
    journal.recover(live)
    journal.recover(live)  # repeated recovery is idempotent
    assert {name: journal.fingerprint(live / name) for name in names} == previous
    assert (live / "printer.cfg").read_text() == "user configuration"


def test_first_install_recovers_absent_paths(journal, runtime):
    live, stage, backup, names = runtime
    names = ["requirements.txt"]
    (stage / names[0]).write_text("new requirements")
    journal.begin(live, stage, backup, names)
    (stage / names[0]).rename(live / names[0])
    journal.recover(live)
    assert not (live / names[0]).exists()
    assert (stage / names[0]).is_file()


def test_external_edit_is_not_overwritten(journal, runtime):
    live, stage, backup, names = runtime
    journal.begin(live, stage, backup, names)
    (live / "kace.py").rename(backup / "kace.py")
    (stage / "kace.py").rename(live / "kace.py")
    (live / "kace.py").write_text("external edit")
    with pytest.raises(RuntimeError, match="conflict"):
        journal.recover(live)
    assert (live / "kace.py").read_text() == "external edit"
    assert (backup / "kace.py").read_text() == "old"
    assert journal.journal_path(live).exists()


def test_recovery_can_itself_be_interrupted(journal, runtime, monkeypatch):
    live, stage, backup, names = runtime
    journal.begin(live, stage, backup, names)
    for name in names:
        (live / name).rename(backup / name)
        (stage / name).rename(live / name)
    original = journal.rename
    count = 0

    def fail_after_move(src, dest):
        nonlocal count
        original(src, dest)
        count += 1
        if count == 3:
            raise OSError("interrupted recovery")

    monkeypatch.setattr(journal, "rename", fail_after_move)
    with pytest.raises(OSError, match="interrupted"):
        journal.recover(live)
    monkeypatch.setattr(journal, "rename", original)
    journal.recover(live)
    assert (live / "kace.py").read_text() == "old"
    assert (live / "core/payload").read_text() == "old"


def test_ready_runtime_is_not_rolled_back_after_wrapper_publication(journal, runtime):
    live, stage, backup, names = runtime
    journal.begin(live, stage, backup, names)
    for name in names:
        (live / name).rename(backup / name)
        (stage / name).rename(live / name)
    journal.ready(live)
    with pytest.raises(RuntimeError, match="wrapper"):
        journal.recover(live, rollback_only=True)
    journal.recover(live)
    assert (live / "kace.py").read_text() == "new"
    assert (backup / "kace.py").read_text() == "old"


def test_journal_fsync_failure_precedes_any_runtime_move(journal, runtime, monkeypatch):
    live, stage, backup, names = runtime
    monkeypatch.setattr(journal, "sync_dir", lambda path: (_ for _ in ()).throw(OSError("fsync")))
    with pytest.raises(OSError, match="fsync"):
        journal.begin(live, stage, backup, names)
    assert (live / "kace.py").read_text() == "old"
    assert (stage / "kace.py").read_text() == "new"


def test_journal_cannot_redirect_recovery_outside_install_parent(journal, runtime, tmp_path):
    import json
    live, stage, backup, names = runtime
    journal.begin(live, stage, backup, names)
    path = journal.journal_path(live)
    record = json.loads(path.read_text())
    record["backup"] = str(tmp_path.parent)
    path.write_text(json.dumps(record))
    with pytest.raises(RuntimeError, match="path"):
        journal.recover(live)
    assert (live / "kace.py").read_text() == "old"


def test_reinstall_identical_runtime_still_recovers(journal, runtime):
    import shutil
    live, stage, backup, names = runtime
    for name in names:
        if (live / name).is_dir():
            shutil.copytree(live / name, stage / name, dirs_exist_ok=True)
        else:
            shutil.copy2(live / name, stage / name)
    journal.begin(live, stage, backup, names)
    for name in names[:3]:
        (live / name).rename(backup / name)
        (stage / name).rename(live / name)
    journal.recover(live)
    assert (live / "kace.py").read_text() == "old"


def test_changes_during_recovery_are_detected(journal, runtime, monkeypatch):
    live, stage, backup, names = runtime
    journal.begin(live, stage, backup, names)
    for name in names:
        (live / name).rename(backup / name)
        (stage / name).rename(live / name)
    original = journal.rename

    def edit_another_file(src, dest):
        original(src, dest)
        (backup / "kace.py").write_text("concurrent edit")

    monkeypatch.setattr(journal, "rename", edit_another_file)
    with pytest.raises(RuntimeError, match="source changed"):
        journal.recover(live)
    assert (backup / "kace.py").read_text() == "concurrent edit"
    assert journal.journal_path(live).exists()


def test_ready_refuses_changed_published_bytes(journal, runtime):
    live, stage, backup, names = runtime
    journal.begin(live, stage, backup, names)
    for name in names:
        (live / name).rename(backup / name)
        (stage / name).rename(live / name)
    (live / "kace.py").write_text("unexpected change")
    with pytest.raises(RuntimeError, match="published runtime changed"):
        journal.ready(live)
    assert journal.journal_path(live).exists()


def shell_fixture(runtime):
    live, stage, backup, names = runtime
    source = SOURCE.read_text(encoding="utf-8")
    helpers = source[source.index("_runtime_transaction() {"):source.index("# ── Banner")]
    variables = {
        "INSTALL_DIR": str(live), "INSTALL_PARENT": str(live.parent),
        "STAGING_DIR": str(stage), "BACKUP_DIR": str(backup),
        "RUNTIME_JOURNAL": str(live.parent / ".kace-runtime-transaction.json"),
        "PUBLICATION_ACTIVE": "0", "RUNTIME_COMMITTED": "0",
        "INSTALL_LOCK_HELD": "1",
        "PUBLISHED_PATHS": "", "_RUNTIME_PATHS": " ".join(names),
    }
    setup = "set -euo pipefail\n" + "\n".join(
        f"{name}={shlex.quote(value)}" for name, value in variables.items()) + "\n" + helpers
    start = source.index('read -r -a runtime_paths <<< "$_RUNTIME_PATHS"')
    publication = source[start:source.index("\nPUBLISHED_COMMIT=", start)]
    return setup, publication


@pytest.mark.skipif(os.name == "nt", reason="real SIGKILL/fsync requires Linux; run isolated Linux gate")
@pytest.mark.parametrize("kill_after", range(1, 11))
def test_real_shell_killed_between_renames_recovers(journal, runtime, kill_after):
    setup, publication = shell_fixture(runtime)
    hook = f'''
count=0
mv() {{
    command mv "$@"
    count=$((count+1))
    if [ "$count" -eq {kill_after} ]; then kill -KILL "$$"; fi
}}
'''
    stopped = subprocess.run(["bash", "-c", setup + hook + publication], capture_output=True, text=True, timeout=20)
    assert stopped.returncode == -9, stopped.stderr
    restored = subprocess.run(["bash", "-c", setup + "\n_runtime_transaction recover\n"], capture_output=True, text=True, timeout=20)
    assert restored.returncode == 0, restored.stderr
    live, _, _, _ = runtime
    assert (live / "kace.py").read_text() == "old"
    assert (live / "core/payload").read_text() == "old"
    assert (live / "printer.cfg").read_text() == "user configuration"


@pytest.mark.skipif(os.name == "nt", reason="integrated Bash/Linux durability gate")
@pytest.mark.parametrize("journal_removed", [False, True])
def test_shell_keeps_committed_runtime_and_backup_on_finalization_failure(runtime, journal_removed):
    setup, publication = shell_fixture(runtime)
    failure = '\nrm -- "$RUNTIME_JOURNAL"\n' if journal_removed else "\n"
    script = setup + publication + '''
_runtime_transaction ready
RUNTIME_COMMITTED=1
PUBLICATION_ACTIVE=0
''' + failure + "false\n"
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=20)
    assert result.returncode == 1
    assert "finalization failed" in result.stderr
    live, stage, backup, _ = runtime
    assert (live / "kace.py").read_text() == "new"
    assert (backup / "kace.py").read_text() == "old"
    assert stage.is_dir()


@pytest.mark.skipif(os.name == "nt", reason="integrated Bash/Linux durability gate")
def test_missing_journal_does_not_trigger_unverified_rollback(runtime):
    setup, publication = shell_fixture(runtime)
    result = subprocess.run(
        ["bash", "-c", setup + publication + '\nrm -- "$RUNTIME_JOURNAL"\nfalse\n'],
        capture_output=True, text=True, timeout=20)
    assert result.returncode == 1
    assert "refusing unverified rollback" in result.stderr
    live, stage, backup, _ = runtime
    assert (live / "kace.py").read_text() == "new"
    assert (backup / "kace.py").read_text() == "old"
    assert stage.is_dir()


@pytest.mark.skipif(os.name == "nt", reason="real flock/launcher gate requires Linux")
def test_generated_wrapper_refuses_active_or_unfinished_install(runtime, tmp_path):
    import fcntl
    live, _, _, _ = runtime
    setup, _ = shell_fixture(runtime)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    expected = "a" * 40
    git = binaries / "git"
    git.write_text(f"#!/bin/sh\nprintf '%s\\n' '{expected}'\n")
    git.chmod(0o755)
    interpreter = live / "venv/bin/python"
    interpreter.parent.mkdir(parents=True)
    marker = tmp_path / "launched"
    interpreter.write_text("#!/bin/sh\ntouch " + shlex.quote(str(marker)) + "\n")
    interpreter.chmod(0o755)
    (live / ".kace-runtime-commit").write_text(expected)
    source = SOURCE.read_text(encoding="utf-8")
    start = source.index('# ── Step 5: Create global wrapper')
    wrapper_step = source[start:source.index('# The wrapper now resolves', start)]
    wrapper = binaries / "kace"
    shell = setup + f'''
EXPECTED_COMMIT={expected}
KACE_BIN={shlex.quote(str(wrapper))}
G= R= B= Y= C=
_run_root() {{ "$@"; }}
id() {{ echo 0; }}
''' + wrapper_step
    built = subprocess.run(["bash", "-c", shell], capture_output=True, text=True, timeout=20)
    assert built.returncode == 0, built.stderr
    env = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ['PATH'])
    lock = tmp_path / ".kace-install.lock"
    with lock.open('w') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        blocked = subprocess.run([str(wrapper)], env=env, capture_output=True, timeout=5)
        assert blocked.returncode == 75
        assert not marker.exists()
    journal = tmp_path / ".kace-runtime-transaction.json"
    journal.write_text("unfinished")
    blocked = subprocess.run([str(wrapper)], env=env, capture_output=True, timeout=5)
    assert blocked.returncode == 75
    assert not marker.exists()
    journal.unlink()
    journal.symlink_to(tmp_path / "missing-journal-target")
    blocked = subprocess.run([str(wrapper)], env=env, capture_output=True, timeout=5)
    assert blocked.returncode == 75
    assert not marker.exists()
    journal.unlink()
    allowed = subprocess.run([str(wrapper)], env=env, capture_output=True, timeout=5)
    assert allowed.returncode == 0, allowed.stderr
    assert marker.is_file()


@pytest.mark.skipif(os.name == "nt", reason="real flock exclusion requires Linux")
def test_rejected_second_installer_cannot_recover_owners_journal(journal, runtime):
    import fcntl
    live, stage, backup, names = runtime
    journal.begin(live, stage, backup, names)
    (live / "core").rename(backup / "core")
    (stage / "core").rename(live / "core")
    original = journal.journal_path(live).read_bytes()
    identities = {str(p): journal.fingerprint(p) for p in (live, stage, backup)}
    setup, _ = shell_fixture(runtime)
    source = SOURCE.read_text(encoding="utf-8")
    start = source.index('LOCK_FILE="$INSTALL_PARENT/.kace-install.lock"')
    lock_step = source[start:source.index('# Recover before fetching', start)]
    with (live.parent / ".kace-install.lock").open('w') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        result = subprocess.run(
            ["bash", "-c", setup + '\nINSTALL_LOCK_HELD=0\nE= R=\n' + lock_step],
            capture_output=True, text=True, timeout=5)
    assert result.returncode == 1
    assert "already running" in result.stderr
    assert journal.journal_path(live).read_bytes() == original
    assert {str(p): journal.fingerprint(p) for p in (live, stage, backup)} == identities


@pytest.mark.skipif(os.name == "nt", reason="directory fsync failure and Bash cleanup require Linux")
@pytest.mark.parametrize("transition", ["ready", "finish"])
def test_shell_preserves_copies_when_commit_directory_fsync_fails(journal, runtime, transition):
    """Fail the directory fsync after ready replacement or finish unlink, not before."""
    live, stage, backup, names = runtime
    old = {name: journal.fingerprint(live / name) for name in names}
    new = {name: journal.fingerprint(stage / name) for name in names}
    setup, publication = shell_fixture(runtime)
    # Inject into this disposable shell's embedded helper only. File fsync and
    # all preceding directory fsync calls still execute their real syscalls.
    injection = '''
_real_fsync = os.fsync

def _injected_directory_fsync(fd):
    fault = os.environ.get('KACE_TEST_DIRECTORY_FSYNC_FAILURE')
    parent = Path(sys.argv[1]).resolve().parent
    info = os.fstat(fd)
    parent_info = parent.stat()
    if fault and stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == (parent_info.st_dev, parent_info.st_ino):
        path = parent / '.kace-runtime-transaction.json'
        ready_visible = path.exists() and json.loads(path.read_text())['phase'] == 'ready'
        if (fault == 'ready' and ready_visible) or (fault == 'finish' and not path.exists()):
            raise OSError('injected directory fsync failure after ' + fault)
    return _real_fsync(fd)

os.fsync = _injected_directory_fsync

'''
    assert setup.count("def main():\n") == 1
    setup = setup.replace("def main():\n", injection + "def main():\n", 1)
    if transition == "ready":
        tail = '\nKACE_TEST_DIRECTORY_FSYNC_FAILURE=ready _runtime_transaction ready\n'
    else:
        tail = '''
_runtime_transaction ready
RUNTIME_COMMITTED=1
PUBLICATION_ACTIVE=0
KACE_TEST_DIRECTORY_FSYNC_FAILURE=finish _runtime_transaction finish
'''
    result = subprocess.run(
        ["bash", "-c", setup + publication + tail],
        capture_output=True, text=True, timeout=20)
    assert result.returncode == 1, result.stderr
    assert 'injected directory fsync failure after ' + transition in result.stderr
    assert {name: journal.fingerprint(live / name) for name in names} == new
    assert {name: journal.fingerprint(backup / name) for name in names} == old
    assert stage.is_dir()
    assert (live / "printer.cfg").read_text() == "user configuration"
    if transition == "ready":
        assert journal.read_record(live)['phase'] == 'ready'
        assert 'runtime committed; wrapper completion' in result.stderr
        # Once the fault disappears, recovery can keep the new runtime; it must
        # never silently restore the older runtime after the ready boundary.
        journal.recover(live)
        assert {name: journal.fingerprint(live / name) for name in names} == new
        assert {name: journal.fingerprint(backup / name) for name in names} == old
    else:
        assert not journal.journal_path(live).exists()
        assert 'finalization failed' in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="Bash launcher lifecycle requires Linux")
def test_interactive_failure_after_unlock_does_not_recover_new_transaction(runtime):
    live, stage, backup, _ = runtime
    setup, _ = shell_fixture(runtime)
    source = SOURCE.read_text(encoding="utf-8")
    start = source.index('_safe_remove_transaction_dir "$STAGING_DIR"', source.index('# ── Done'))
    tail = source[start:]
    script = setup + '''
exec 9>"$INSTALL_PARENT/.kace-install.lock"
flock -n 9
C= R=
sleep() { :; }
new_session() {
    printf 'owned by a later installer' > "$RUNTIME_JOURNAL"
    return 9
}
ACTIVE_KACE_BIN=new_session
''' + tail
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=5)
    assert result.returncode == 9, result.stderr
    assert (live.parent / ".kace-runtime-transaction.json").read_text() == "owned by a later installer"
    assert not stage.exists()
    assert backup.is_dir()
    assert "Recovery failed" not in result.stderr
