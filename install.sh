#!/usr/bin/env bash
# ============================================================
#  KACE — Klipper Automated Configuration Ecosystem
#  Install Script
#
#  Verified standalone installation:
#    INSTALL_COMMIT='paste-the-full-40-character-commit-here'
#    EXPECTED_SHA256='paste-the-trusted-sha256-here'  # obtain separately
#    installer=$(mktemp)
#    curl -fsSLo "$installer" "https://raw.githubusercontent.com/3D-uy/KACE/${INSTALL_COMMIT}/install.sh"
#    printf '%s  %s\n' "$EXPECTED_SHA256" "$installer" | sha256sum -c -
#    KACE_SOURCE_REF="$INSTALL_COMMIT" KACE_EXPECTED_COMMIT="$INSTALL_COMMIT" bash "$installer"
#    status=$?; rm -f "$installer"; exit "$status"
#
#  Do not fetch the expected checksum from the same mutable branch as the
#  installer. Obtain it from a matching release or another trusted channel.
#  The Studio bootstrap also supplies KACE_SOURCE_REF so the installer and the
#  repository content are resolved from the same immutable revision.
# ============================================================

set -euo pipefail

# ── Colors ───────────────────────────────────────────────────
G="\033[92m"   # Green
Y="\033[93m"   # Yellow
C="\033[96m"   # Cyan
R="\033[0m"    # Reset
B="\033[1m"    # Bold
E="\033[91m"   # Red (error)

REPO_URL="https://github.com/3D-uy/kace.git"
INSTALL_DIR="$HOME/kace"
KACE_BIN="${KACE_INSTALL_BIN:-/usr/local/bin/kace}"
INSTALL_REF="${KACE_SOURCE_REF:-}"
EXPECTED_COMMIT="${KACE_EXPECTED_COMMIT:-}"
INSTALL_PARENT=$(dirname "$INSTALL_DIR")
STAGING_DIR=""
BACKUP_DIR=""
PUBLICATION_ACTIVE=0
RUNTIME_COMMITTED=0
INSTALL_LOCK_HELD=0
RUNTIME_JOURNAL="$INSTALL_PARENT/.kace-runtime-transaction.json"
ACTIVE_KACE_BIN=""
RUNTIME_COMMIT_FILE=".kace-runtime-commit"

_run_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        return 127
    fi
}

# Standalone installation accepts only an exact Git object identity. Branches
# and tags can move and therefore cannot be installation trust anchors.
if [[ ! "$INSTALL_REF" =~ ^[0-9a-fA-F]{40}$ ]]; then
    echo "Error: KACE_SOURCE_REF must be a full 40-character commit SHA." >&2
    exit 1
fi
INSTALL_REF=$(printf '%s' "$INSTALL_REF" | tr '[:upper:]' '[:lower:]')

case "$KACE_BIN" in
    /*) ;;
    *)
        echo "Error: KACE_INSTALL_BIN must be an absolute path." >&2
        exit 1
        ;;
esac

if [ -z "$EXPECTED_COMMIT" ]; then
    EXPECTED_COMMIT="$INSTALL_REF"
elif [ -n "$EXPECTED_COMMIT" ]; then
    if [[ ! "$EXPECTED_COMMIT" =~ ^[0-9a-fA-F]{40}$ ]]; then
        echo "Error: KACE_EXPECTED_COMMIT must be a full 40-character commit SHA." >&2
        exit 1
    fi
    EXPECTED_COMMIT=$(printf '%s' "$EXPECTED_COMMIT" | tr '[:upper:]' '[:lower:]')
fi
if [ "$EXPECTED_COMMIT" != "$INSTALL_REF" ]; then
    echo "Error: KACE_EXPECTED_COMMIT must match KACE_SOURCE_REF." >&2
    exit 1
fi

_runtime_transaction() {
    python3 - "$INSTALL_DIR" "$@" <<'KACE_RUNTIME_TRANSACTION_PY'
"""Standalone installer recovery prototype; embedded in verified install.sh.

No imports from the installed or staged KACE runtime are safe during recovery.
The caller holds .kace-install.lock for the entire transaction.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

NAMES = frozenset(('.git', '.kace-runtime-commit', 'kace.py', 'VERSION',
                   'requirements.txt', 'requirements-ssh.txt', 'core',
                   'firmware', 'data', 'templates', 'scripts', 'venv'))


def journal_path(live):
    return live.parent / '.kace-runtime-transaction.json'


def sync_dir(path):
    if os.name == 'nt':
        return  # Windows fixture runs do not attest POSIX directory durability.
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def tree(path):
    yield path
    if path.is_dir() and not path.is_symlink():
        for child in sorted(path.iterdir()):
            yield from tree(child)


def fingerprint(path):
    if not path.exists() and not path.is_symlink():
        return None
    digest = hashlib.sha256()
    for entry in tree(path):
        info = entry.lstat()
        mode = stat.S_IMODE(info.st_mode)
        name = entry.relative_to(path).as_posix()
        if stat.S_ISLNK(info.st_mode):
            value = ['link', name, mode, os.readlink(entry)]
        elif stat.S_ISDIR(info.st_mode):
            value = ['dir', name, mode]
        elif stat.S_ISREG(info.st_mode):
            content = hashlib.sha256()
            with entry.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    content.update(block)
            value = ['file', name, mode, content.hexdigest()]
        else:
            raise RuntimeError('unsupported runtime entry: ' + str(entry))
        digest.update(json.dumps(value, ensure_ascii=True).encode() + b'\n')
    return digest.hexdigest()


def sync_tree(path):
    if not path.exists() or path.is_symlink():
        return
    for entry in reversed(list(tree(path))):
        if entry.is_symlink():
            continue
        if entry.is_dir():
            sync_dir(entry)
        elif os.name != 'nt':
            with entry.open('rb') as stream:
                os.fsync(stream.fileno())


def write_record(live, record):
    path = journal_path(live)
    fd, temporary = tempfile.mkstemp(prefix='.kace-journal.', dir=live.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(record, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_dir(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def transaction_dir(live, value, prefix):
    path = Path(value)
    if (not path.is_absolute() or path.parent != live.parent
            or not path.name.startswith(prefix) or path.is_symlink()
            or not path.is_dir() or path.resolve() != path):
        raise RuntimeError('invalid recovery path: ' + str(path))
    return path


def read_record(live):
    path = journal_path(live)
    if path.is_symlink():
        raise RuntimeError('invalid journal path')
    record = json.loads(path.read_text(encoding='utf-8'))
    if (record.get('schema') != 1 or record.get('live') != str(live)
            or record.get('phase') not in ('publishing', 'ready')
            or not isinstance(record.get('paths'), dict) or not record['paths']
            or not set(record['paths']).issubset(NAMES)):
        raise RuntimeError('invalid runtime recovery journal')
    transaction_dir(live, record['stage'], '.kace-install.')
    transaction_dir(live, record['backup'], '.kace-backup.')
    for identities in record['paths'].values():
        if not isinstance(identities, dict) or set(identities) != {'old', 'new'}:
            raise RuntimeError('invalid runtime recovery identities')
        for key, value in identities.items():
            if value is None and key == 'old':
                continue
            if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
                raise RuntimeError('invalid runtime recovery identity')
    return record


def begin(live, stage, backup, names):
    if journal_path(live).exists() or journal_path(live).is_symlink():
        raise RuntimeError('unfinished runtime publication requires recovery')
    transaction_dir(live, str(stage), '.kace-install.')
    transaction_dir(live, str(backup), '.kace-backup.')
    if not names or len(set(names)) != len(names) or not set(names).issubset(NAMES):
        raise RuntimeError('invalid runtime paths')
    if any(backup.iterdir()):
        raise RuntimeError('backup is not empty')
    identities = {}
    for name in names:
        new = fingerprint(stage / name)
        if new is None:
            raise RuntimeError('staged runtime incomplete: ' + name)
        identities[name] = {'old': fingerprint(live / name), 'new': new}
        sync_tree(stage / name)
        sync_tree(live / name)
    for directory in (live, stage, backup, live.parent):
        sync_dir(directory)
    write_record(live, {'schema': 1, 'live': str(live), 'stage': str(stage),
                       'backup': str(backup), 'phase': 'publishing', 'paths': identities})


def rename(src, dest):
    if dest.exists() or dest.is_symlink():
        raise RuntimeError('recovery conflict: destination exists: ' + str(dest))
    os.rename(src, dest)
    sync_dir(src.parent)
    sync_dir(dest.parent)


def verify_ready(live, record):
    for name, identities in record['paths'].items():
        if fingerprint(live / name) != identities['new']:
            raise RuntimeError('recovery conflict: published runtime changed: ' + name)


def ready(live):
    record = read_record(live)
    verify_ready(live, record)
    record['phase'] = 'ready'
    write_record(live, record)


def clear(live):
    journal_path(live).unlink()
    sync_dir(live.parent)


def recover(live, rollback_only=False):
    if not journal_path(live).exists() and not journal_path(live).is_symlink():
        return
    record = read_record(live)
    if record['phase'] == 'ready':
        if rollback_only:
            raise RuntimeError('runtime committed; wrapper completion requires rerunning the verified installer')
        verify_ready(live, record)
        clear(live)
        print('Recovered verified new runtime; this install must recreate its wrapper. '
              'Previous runtime retained at ' + record['backup'], file=sys.stderr)
        return
    stage, backup = Path(record['stage']), Path(record['backup'])
    moves = []
    # Restore metadata last so old commit-bound launchers reject intermediate trees.
    names = sorted(record['paths'], key=lambda name: (name in ('.git', '.kace-runtime-commit'), name))
    for name in names:
        identities = record['paths'][name]
        old, new = identities['old'], identities['new']
        actual, staged, saved = (fingerprint(folder / name) for folder in (live, stage, backup))
        if actual == old and saved is None and staged == new:
            continue
        if saved != old or actual not in (None, new) or staged not in (None, new):
            raise RuntimeError('recovery conflict: ' + name)
        if actual == new:
            if staged is not None:
                raise RuntimeError('recovery conflict: duplicate new path: ' + name)
            moves.append((live / name, stage / name, new))
        elif staged != new:
            raise RuntimeError('recovery conflict: missing new path: ' + name)
        if old is not None:
            moves.append((backup / name, live / name, old))
    # Validate the complete plan before moving anything; retain evidence on conflict.
    for src, dest, expected in moves:
        if fingerprint(src) != expected:
            raise RuntimeError('recovery conflict: source changed: ' + str(src))
        rename(src, dest)
    for name, identities in record['paths'].items():
        if fingerprint(live / name) != identities['old']:
            raise RuntimeError('recovery conflict: restored runtime changed: ' + name)
    clear(live)
    print('Recovered previous runtime; retained transaction copies at ' + str(stage)
          + ' and ' + str(backup), file=sys.stderr)


def main():
    live = Path(sys.argv[1]).resolve()
    action = sys.argv[2]
    if action == 'begin':
        begin(live, Path(sys.argv[3]).resolve(), Path(sys.argv[4]).resolve(), sys.argv[5:])
    elif action == 'sync-file':
        for value in sys.argv[3:]:
            sync_tree(Path(value))
    elif action == 'sync':
        for value in sys.argv[3:]:
            sync_dir(Path(value))
    elif action == 'recover':
        recover(live)
    elif action == 'rollback':
        recover(live, rollback_only=True)
    elif action == 'ready':
        ready(live)
    elif action == 'finish':
        record = read_record(live)
        if record['phase'] != 'ready':
            raise RuntimeError('runtime not committed')
        verify_ready(live, record)
        clear(live)
    else:
        raise RuntimeError('unknown recovery action')


if __name__ == '__main__':
    main()

KACE_RUNTIME_TRANSACTION_PY
}

_safe_remove_transaction_dir() {
    local path="$1"
    case "$path" in
        "$INSTALL_PARENT"/.kace-install.*|"$INSTALL_PARENT"/.kace-backup.*)
            [ ! -e "$path" ] || rm -rf -- "$path"
            ;;
        "") ;;
        *)
            echo "Refusing to remove unexpected installer path: $path" >&2
            return 1
            ;;
    esac
}

rollback_publication() {
    if [ -n "${RUNTIME_JOURNAL:-}" ] && { [ -e "$RUNTIME_JOURNAL" ] || [ -L "$RUNTIME_JOURNAL" ]; }; then
        _runtime_transaction rollback || return 1
        PUBLICATION_ACTIVE=0
        return 0
    fi
    if [ "$PUBLICATION_ACTIVE" -eq 1 ]; then
        echo "Publication journal is missing; refusing unverified rollback. Preserve transaction copies for recovery." >&2
        return 1
    fi
    return 0
}

_cleanup_installer() {
    local status=$?
    trap - EXIT INT TERM
    # A rejected second installer must never recover the owner's transaction.
    if [ "${INSTALL_LOCK_HELD:-0}" -ne 1 ]; then
        exit "$status"
    fi
    if [ "$status" -ne 0 ]; then
        if [ "${RUNTIME_COMMITTED:-0}" -eq 1 ]; then
            echo "Runtime committed but finalization failed; rerun the verified installer. Preserved $STAGING_DIR and $BACKUP_DIR." >&2
            exit "$status"
        fi
        if ! rollback_publication; then
            echo "Recovery failed; preserved runtime copies in $STAGING_DIR and $BACKUP_DIR for manual recovery." >&2
            exit 1
        fi
    fi
    _safe_remove_transaction_dir "$STAGING_DIR" || status=1
    _safe_remove_transaction_dir "$BACKUP_DIR" || status=1
    exit "$status"
}

trap _cleanup_installer EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# ── Banner ───────────────────────────────────────────────────
clear 2>/dev/null || true
SUBTITLE="KACE Installer"

# The runtime has not been verified yet, so this early installer heading must
# not manufacture a KACE version. The success banner below reads VERSION from
# the published immutable runtime.
echo ""
echo -e "  ${C}──────────────────────────────────────────${R}"
echo -e "  ${B}${C}  $SUBTITLE${R}"
echo -e "  ${C}──────────────────────────────────────────${R}"
echo ""

# ── Step 1: System dependencies ──────────────────────────────
# Report broken hostname resolution, but leave this system-owned policy to the OS.
if command -v getent &>/dev/null && command -v hostname &>/dev/null; then
    _HOSTNAME=$(hostname)
    if [ -n "$_HOSTNAME" ] && ! getent hosts "$_HOSTNAME" &>/dev/null; then
        echo -e "  ${Y}⚠ Local hostname '${_HOSTNAME}' is not resolvable.${R}"
        echo -e "  ${Y}  Correct DNS or /etc/hosts through the OS configuration if sudo warns.${R}"
    fi
fi

echo -e "${C}[1/5]${R} Checking system dependencies..."
if ! command -v git >/dev/null 2>&1 || \
        ! command -v python3 >/dev/null 2>&1 || \
        ! python3 -c 'import venv' >/dev/null 2>&1 || \
        ! command -v flock >/dev/null 2>&1; then
    if command -v apt-get &>/dev/null; then
        _run_root apt-get update -qq
        _run_root apt-get install -y git python3-venv util-linux -qq
    elif command -v apt &>/dev/null; then
        _run_root apt update -qq
        _run_root apt install -y git python3-venv util-linux -qq
    else
        echo -e "${E}  Missing git, Python venv, or flock and no apt package manager is available.${R}" >&2
        exit 1
    fi
fi

for required_command in git python3 flock grep mktemp mv; do
    if ! command -v "$required_command" >/dev/null 2>&1; then
        echo -e "${E}  Required command is unavailable: ${required_command}.${R}" >&2
        exit 1
    fi
done
echo -e "${G}  ✔ Dependencies verified${R}"

if ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
    echo -e "${E}  KACE requires Python 3.11 or newer.${R}" >&2
    exit 1
fi

mkdir -p "$INSTALL_PARENT"
if [ -L "$INSTALL_DIR" ]; then
    echo -e "${E}  Refusing to install through symlinked path: ${INSTALL_DIR}.${R}" >&2
    exit 1
fi
if [ -e "$INSTALL_DIR" ] && [ ! -d "$INSTALL_DIR" ]; then
    echo -e "${E}  Installation path exists but is not a directory: ${INSTALL_DIR}.${R}" >&2
    exit 1
fi

LOCK_FILE="$INSTALL_PARENT/.kace-install.lock"
exec 9>"$LOCK_FILE"
chmod 600 "$LOCK_FILE"
if ! flock -n 9; then
    echo -e "${E}  Another KACE installation is already running.${R}" >&2
    exit 1
fi
INSTALL_LOCK_HELD=1

# Recover before fetching or publishing another runtime. This helper is part of
# the verified installer and never imports the potentially mixed installed code.
_runtime_transaction recover

# ── Step 2: Clone or update KACE repository ──────────────────
# Only runtime files are checked out — docs, tests, docker, CI,
# and non-essential root files (jobs.json, CHANGELOG, test_run.log…)
# are excluded to minimize download size on the Pi.
#
# Cone mode (default) always pulls ALL root-level files.
# Non-cone mode lets us whitelist exact paths.
_SPARSE_PATTERNS="/kace.py
/VERSION
/requirements.txt
/requirements-ssh.txt
/core/
/firmware/
/data/
/templates/
/scripts/cc_wrapper.py
/scripts/board_contract_cc_wrapper.py"

# Check if sparse checkout is supported (requires Git >= 2.25)
_git_supports_sparse() {
    local ver major minor
    ver=$(git --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1)
    major=$(echo "$ver" | cut -d. -f1)
    minor=$(echo "$ver" | cut -d. -f2)
    [ "${major:-0}" -gt 2 ] || { [ "${major:-0}" -eq 2 ] && [ "${minor:-0}" -ge 25 ]; }
}

echo -e "${C}[2/5]${R} Syncing KACE repository..."
STAGING_DIR=$(mktemp -d "$INSTALL_PARENT/.kace-install.XXXXXX")
git -C "$STAGING_DIR" init --quiet
git -C "$STAGING_DIR" remote add origin "$REPO_URL"

if _git_supports_sparse; then
    git -C "$STAGING_DIR" sparse-checkout init --no-cone
    printf '%s\n' "$_SPARSE_PATTERNS" | \
        git -C "$STAGING_DIR" sparse-checkout set --no-cone --stdin
    git -C "$STAGING_DIR" fetch origin "$INSTALL_REF" --depth=1 \
        --filter=blob:none --quiet
else
    git -C "$STAGING_DIR" fetch origin "$INSTALL_REF" --depth=1 --quiet
fi

FETCHED_COMMIT=$(git -C "$STAGING_DIR" rev-parse --verify 'FETCH_HEAD^{commit}')
FETCHED_COMMIT=$(printf '%s' "$FETCHED_COMMIT" | tr '[:upper:]' '[:lower:]')
if [ -n "$EXPECTED_COMMIT" ] && [ "$FETCHED_COMMIT" != "$EXPECTED_COMMIT" ]; then
    echo -e "${E}  Fetched commit does not match the expected immutable revision.${R}" >&2
    echo "Expected: $EXPECTED_COMMIT" >&2
    echo "Fetched:  $FETCHED_COMMIT" >&2
    exit 1
fi

git -C "$STAGING_DIR" -c advice.detachedHead=false checkout --detach FETCH_HEAD --quiet
ACTUAL_COMMIT=$(git -C "$STAGING_DIR" rev-parse --verify HEAD)
ACTUAL_COMMIT=$(printf '%s' "$ACTUAL_COMMIT" | tr '[:upper:]' '[:lower:]')
if [ "$ACTUAL_COMMIT" != "$FETCHED_COMMIT" ]; then
    echo -e "${E}  Checked-out runtime does not match the fetched commit.${R}" >&2
    exit 1
fi
if [ -n "$EXPECTED_COMMIT" ] && [ "$ACTUAL_COMMIT" != "$EXPECTED_COMMIT" ]; then
    echo -e "${E}  Checked-out runtime does not match the expected commit.${R}" >&2
    exit 1
fi
echo -e "${G}  ✔ Repository staged at ${ACTUAL_COMMIT}${R}"


# ── Step 3: Install Python dependencies ──────────────────────
echo -e "${C}[3/5]${R} Installing Python packages in isolated venv..."
python3 -m venv "$STAGING_DIR/venv"
# Enforce hashes to protect against PyPI substitution attacks
"$STAGING_DIR/venv/bin/python" -m pip install \
    --require-hashes -r "$STAGING_DIR/requirements.txt" -q

# venv-generated console/activation scripts contain the absolute creation
# path. Rewrite only that exact prefix while the environment is still staged,
# so the published venv does not retain references to a directory we delete.
KACE_VENV_FROM="$STAGING_DIR" KACE_VENV_TO="$INSTALL_DIR" \
    python3 - "$STAGING_DIR/venv" <<'PY'
import os
import sys
from pathlib import Path

source = os.environ["KACE_VENV_FROM"].encode()
target = os.environ["KACE_VENV_TO"].encode()
venv = Path(sys.argv[1])
candidates = [venv / "pyvenv.cfg"]
candidates.extend(path for path in (venv / "bin").iterdir() if path.is_file() and not path.is_symlink())
for path in candidates:
    data = path.read_bytes()
    if b"\0" not in data and source in data:
        path.write_bytes(data.replace(source, target))
PY

if grep -R -I -F -l -- "$STAGING_DIR" "$STAGING_DIR/venv/bin" "$STAGING_DIR/venv/pyvenv.cfg" \
        >/dev/null 2>&1; then
    echo -e "${E}  Staged virtual environment still contains transient paths.${R}" >&2
    exit 1
fi
echo -e "${G}  ✔ Python dependencies verified (isolated venv)${R}"

# ── Step 4: Configure executable permissions ─────────────────
echo -e "${C}[4/5]${R} Configuring permissions..."
# The launcher invokes kace.py through Python. Preserve the tracked file mode
# so Studio can verify the installed runtime with Git during recovery.
printf '%s\n' "$ACTUAL_COMMIT" > "$STAGING_DIR/$RUNTIME_COMMIT_FILE"

# Publish only installer-owned runtime paths. Generated printer configs,
# firmware artifacts, deployment manifests, snapshots, and any other files in
# ~/kace remain untouched. A failure before the durable runtime commit restores
# verified previous paths from the same-filesystem backup. A later wrapper
# failure retains the complete new runtime and requires installer completion.
_RUNTIME_PATHS=".git $RUNTIME_COMMIT_FILE kace.py VERSION requirements.txt requirements-ssh.txt core firmware data templates scripts venv"
for item in $_RUNTIME_PATHS; do
    if [ ! -e "$STAGING_DIR/$item" ] && [ ! -L "$STAGING_DIR/$item" ]; then
        echo -e "${E}  Staged runtime is incomplete: ${item} is missing.${R}" >&2
        exit 1
    fi
done

mkdir -p "$INSTALL_DIR"
BACKUP_DIR=$(mktemp -d "$INSTALL_PARENT/.kace-backup.XXXXXX")
read -r -a runtime_paths <<< "$_RUNTIME_PATHS"
_runtime_transaction begin "$STAGING_DIR" "$BACKUP_DIR" "${runtime_paths[@]}"
PUBLICATION_ACTIVE=1
for item in $_RUNTIME_PATHS; do
    if [ -e "$INSTALL_DIR/$item" ] || [ -L "$INSTALL_DIR/$item" ]; then
        mv -- "$INSTALL_DIR/$item" "$BACKUP_DIR/$item"
        _runtime_transaction sync "$INSTALL_DIR" "$BACKUP_DIR"
    fi
    mv -- "$STAGING_DIR/$item" "$INSTALL_DIR/$item"
    _runtime_transaction sync "$STAGING_DIR" "$INSTALL_DIR"
done

PUBLISHED_COMMIT=$(git -C "$INSTALL_DIR" rev-parse --verify HEAD)
PUBLISHED_COMMIT=$(printf '%s' "$PUBLISHED_COMMIT" | tr '[:upper:]' '[:lower:]')
if [ "$PUBLISHED_COMMIT" != "$ACTUAL_COMMIT" ]; then
    echo -e "${E}  Published runtime does not match the verified staged commit.${R}" >&2
    exit 1
fi
if [ "$(tr -d '\r\n' < "$INSTALL_DIR/$RUNTIME_COMMIT_FILE")" != "$EXPECTED_COMMIT" ]; then
    echo -e "${E}  Published runtime pin does not match the expected commit.${R}" >&2
    exit 1
fi
if ! PYTHONDONTWRITEBYTECODE=1 "$INSTALL_DIR/venv/bin/python" -c 'import jinja2, questionary, yaml'; then
    echo -e "${E}  Published virtual environment failed its import preflight.${R}" >&2
    exit 1
fi

# Load and validate the actual version from the published immutable runtime.
KACE_VERSION="v$(tr -d '\r\n' < "$INSTALL_DIR/VERSION")"
if [[ ! "$KACE_VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(\.[0-9]+)?([.-][0-9A-Za-z.-]+)?$ ]]; then
    echo -e "${E}  Published runtime contains an invalid VERSION: ${KACE_VERSION}.${R}" >&2
    exit 1
fi
echo -e "${G}  ✔ Permissions applied${R}"

# Commit the complete verified runtime before the wrapper can change. After
# this durable boundary, a failed wrapper update is completed by rerunning this
# installer; rolling back the runtime could mismatch an already-published wrapper.
_runtime_transaction ready
RUNTIME_COMMITTED=1
PUBLICATION_ACTIVE=0

# ── Step 5: Create global wrapper ────────────────────────────
echo -e "${C}[5/5]${R} Finalizing installation..."
if [ "$(id -u)" -eq 0 ] || command -v sudo &>/dev/null; then
    WRAPPER_TEMP=$(_run_root mktemp "$(dirname "$KACE_BIN")/.kace.XXXXXX")
    if ! printf '%s\n' \
        '#!/usr/bin/env bash' \
        'set -euo pipefail' \
        "expected_commit=\"$EXPECTED_COMMIT\"" \
        "install_dir=\"$INSTALL_DIR\"" \
        'exec 8>>"$install_dir/../.kace-install.lock"' \
        'if ! flock -s -n 8 || [ -e "$install_dir/../.kace-runtime-transaction.json" ] || [ -L "$install_dir/../.kace-runtime-transaction.json" ]; then' \
        '    echo "KACE runtime installation requires completion; rerun the verified installer." >&2' \
        '    exit 75' \
        'fi' \
        'pinned_commit=$(tr -d '\''\r\n'\'' < "$install_dir/.kace-runtime-commit")' \
        'actual_commit=$(git -C "$install_dir" rev-parse --verify HEAD 2>/dev/null)' \
        'if [ "$pinned_commit" != "$expected_commit" ] || [ "$actual_commit" != "$expected_commit" ]; then' \
        '    echo "KACE runtime does not match the bootstrap-pinned commit $expected_commit." >&2' \
        '    exit 70' \
        'fi' \
        "exec \"$INSTALL_DIR/venv/bin/python\" \"$INSTALL_DIR/kace.py\" \"\$@\"" | \
            _run_root tee "$WRAPPER_TEMP" >/dev/null; then
        _run_root rm -f -- "$WRAPPER_TEMP" || true
        exit 1
    fi
    _run_root chmod 0755 "$WRAPPER_TEMP"
    _runtime_transaction sync-file "$WRAPPER_TEMP"
    _run_root mv -f -- "$WRAPPER_TEMP" "$KACE_BIN"
    _runtime_transaction sync "$(dirname "$KACE_BIN")"
    ACTIVE_KACE_BIN="$KACE_BIN"
    echo -e "${G}  ✔ Global wrapper command created: ${B}kace${R} → ${KACE_BIN}${R}"
else
    # Fallback: add to user's PATH via ~/.local/bin
    FALLBACK_BIN="$HOME/.local/bin"
    mkdir -p "$FALLBACK_BIN"
    WRAPPER_TEMP=$(mktemp "$FALLBACK_BIN/.kace.XXXXXX")
    printf '%s\n' \
        '#!/usr/bin/env bash' \
        'set -euo pipefail' \
        "expected_commit=\"$EXPECTED_COMMIT\"" \
        "install_dir=\"$INSTALL_DIR\"" \
        'exec 8>>"$install_dir/../.kace-install.lock"' \
        'if ! flock -s -n 8 || [ -e "$install_dir/../.kace-runtime-transaction.json" ] || [ -L "$install_dir/../.kace-runtime-transaction.json" ]; then' \
        '    echo "KACE runtime installation requires completion; rerun the verified installer." >&2' \
        '    exit 75' \
        'fi' \
        'pinned_commit=$(tr -d '\''\r\n'\'' < "$install_dir/.kace-runtime-commit")' \
        'actual_commit=$(git -C "$install_dir" rev-parse --verify HEAD 2>/dev/null)' \
        'if [ "$pinned_commit" != "$expected_commit" ] || [ "$actual_commit" != "$expected_commit" ]; then' \
        '    echo "KACE runtime does not match the bootstrap-pinned commit $expected_commit." >&2' \
        '    exit 70' \
        'fi' \
        "exec \"$INSTALL_DIR/venv/bin/python\" \"$INSTALL_DIR/kace.py\" \"\$@\"" \
        > "$WRAPPER_TEMP"
    chmod 0755 "$WRAPPER_TEMP"
    _runtime_transaction sync-file "$WRAPPER_TEMP"
    mv -f -- "$WRAPPER_TEMP" "$FALLBACK_BIN/kace"
    _runtime_transaction sync "$FALLBACK_BIN"
    ACTIVE_KACE_BIN="$FALLBACK_BIN/kace"
    echo -e "${Y}  ⚠ sudo not available. Created fallback wrapper at ${FALLBACK_BIN}/kace${R}"
    echo -e "${Y}  ⚠ Make sure ${FALLBACK_BIN} is in your PATH:${R}"
    echo -e "${Y}     export PATH=\"\$HOME/.local/bin:\$PATH\"${R}"
fi

# The wrapper now resolves the new runtime. Discard the backup only after that
# final publication point; generated files were never moved.
_runtime_transaction finish
RUNTIME_COMMITTED=0
PUBLICATION_ACTIVE=0
_safe_remove_transaction_dir "$BACKUP_DIR"
BACKUP_DIR=""

# ── Done ─────────────────────────────────────────────────────
echo ""
echo -e "  ${G}══════════════════════════════════════════${R}"
echo -e "  ${B}${G}  ✅ KACE ${KACE_VERSION} installed successfully!${R}"
echo -e "  ${G}══════════════════════════════════════════${R}"
echo ""
if [ "${KACE_NO_LAUNCH:-0}" = "1" ]; then
    echo -e "  ${C}KACE launch skipped for unattended provisioning.${R}"
    exit 0
fi

_safe_remove_transaction_dir "$STAGING_DIR"
STAGING_DIR=""
INSTALL_LOCK_HELD=0
exec 9>&-  # The launcher acquires its own shared runtime lock.
echo -e "  ${C}Launching KACE...${R}"
sleep 1
# Reconnect stdin to the terminal so interactive prompts (questionary) work
exec < /dev/tty || true
set +e
"$ACTIVE_KACE_BIN"
KACE_EXIT=$?
set -e
exit "$KACE_EXIT"
