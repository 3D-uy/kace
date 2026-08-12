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
PUBLISHED_PATHS=""
PUBLICATION_ACTIVE=0

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
    [ "$PUBLICATION_ACTIVE" -eq 1 ] || return 0
    echo "Installation publication failed; restoring the previous runtime." >&2
    local item failed_path
    for item in $PUBLISHED_PATHS; do
        if [ -e "$INSTALL_DIR/$item" ] || [ -L "$INSTALL_DIR/$item" ]; then
            failed_path="$STAGING_DIR/.failed-${item#.}"
            mv -- "$INSTALL_DIR/$item" "$failed_path" || return 1
        fi
        if [ -e "$BACKUP_DIR/$item" ] || [ -L "$BACKUP_DIR/$item" ]; then
            mv -- "$BACKUP_DIR/$item" "$INSTALL_DIR/$item" || return 1
        fi
    done
    PUBLICATION_ACTIVE=0
}

_cleanup_installer() {
    local status=$?
    trap - EXIT INT TERM
    if [ "$status" -ne 0 ]; then
        rollback_publication || status=1
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
VERSION="v0.9.3.3"

# Cosmetic fallback banner for early install phase
echo ""
echo -e "  ${C}──────────────────────────────────────────${R}"
echo -e "  ${B}${C}  $SUBTITLE $VERSION${R}"
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
/scripts/cc_wrapper.py"

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
chmod +x "$STAGING_DIR/kace.py"

# Publish only installer-owned runtime paths. Generated printer configs,
# firmware artifacts, deployment manifests, snapshots, and any other files in
# ~/kace remain untouched. A failure before wrapper publication restores every
# replaced runtime path from the same-filesystem backup.
_RUNTIME_PATHS=".git kace.py VERSION requirements.txt requirements-ssh.txt core firmware data templates scripts venv"
for item in $_RUNTIME_PATHS; do
    if [ ! -e "$STAGING_DIR/$item" ] && [ ! -L "$STAGING_DIR/$item" ]; then
        echo -e "${E}  Staged runtime is incomplete: ${item} is missing.${R}" >&2
        exit 1
    fi
done

mkdir -p "$INSTALL_DIR"
BACKUP_DIR=$(mktemp -d "$INSTALL_PARENT/.kace-backup.XXXXXX")
PUBLICATION_ACTIVE=1
for item in $_RUNTIME_PATHS; do
    PUBLISHED_PATHS="$PUBLISHED_PATHS $item"
    if [ -e "$INSTALL_DIR/$item" ] || [ -L "$INSTALL_DIR/$item" ]; then
        mv -- "$INSTALL_DIR/$item" "$BACKUP_DIR/$item"
    fi
    mv -- "$STAGING_DIR/$item" "$INSTALL_DIR/$item"
done

PUBLISHED_COMMIT=$(git -C "$INSTALL_DIR" rev-parse --verify HEAD)
PUBLISHED_COMMIT=$(printf '%s' "$PUBLISHED_COMMIT" | tr '[:upper:]' '[:lower:]')
if [ "$PUBLISHED_COMMIT" != "$ACTUAL_COMMIT" ]; then
    echo -e "${E}  Published runtime does not match the verified staged commit.${R}" >&2
    exit 1
fi
if ! "$INSTALL_DIR/venv/bin/python" -c 'import jinja2, questionary, yaml'; then
    echo -e "${E}  Published virtual environment failed its import preflight.${R}" >&2
    exit 1
fi

# Load actual version dynamically from the published immutable runtime.
VERSION="v$(tr -d '\r\n' < "$INSTALL_DIR/VERSION")"
echo -e "${G}  ✔ Permissions applied${R}"

# ── Step 5: Create global wrapper ────────────────────────────
echo -e "${C}[5/5]${R} Finalizing installation..."
if [ "$(id -u)" -eq 0 ] || command -v sudo &>/dev/null; then
    WRAPPER_TEMP=$(_run_root mktemp "$(dirname "$KACE_BIN")/.kace.XXXXXX")
    if ! printf '%s\n' \
        '#!/usr/bin/env bash' \
        "exec \"$INSTALL_DIR/venv/bin/python\" \"$INSTALL_DIR/kace.py\" \"\$@\"" | \
            _run_root tee "$WRAPPER_TEMP" >/dev/null; then
        _run_root rm -f -- "$WRAPPER_TEMP" || true
        exit 1
    fi
    _run_root chmod 0755 "$WRAPPER_TEMP"
    _run_root mv -f -- "$WRAPPER_TEMP" "$KACE_BIN"
    echo -e "${G}  ✔ Global wrapper command created: ${B}kace${R} → ${KACE_BIN}${R}"
else
    # Fallback: add to user's PATH via ~/.local/bin
    FALLBACK_BIN="$HOME/.local/bin"
    mkdir -p "$FALLBACK_BIN"
    WRAPPER_TEMP=$(mktemp "$FALLBACK_BIN/.kace.XXXXXX")
    printf '%s\n' \
        '#!/usr/bin/env bash' \
        "exec \"$INSTALL_DIR/venv/bin/python\" \"$INSTALL_DIR/kace.py\" \"\$@\"" \
        > "$WRAPPER_TEMP"
    chmod 0755 "$WRAPPER_TEMP"
    mv -f -- "$WRAPPER_TEMP" "$FALLBACK_BIN/kace"
    echo -e "${Y}  ⚠ sudo not available. Created fallback wrapper at ${FALLBACK_BIN}/kace${R}"
    echo -e "${Y}  ⚠ Make sure ${FALLBACK_BIN} is in your PATH:${R}"
    echo -e "${Y}     export PATH=\"\$HOME/.local/bin:\$PATH\"${R}"
fi

# The wrapper now resolves the new runtime. Discard the backup only after that
# final publication point; generated files were never moved.
PUBLICATION_ACTIVE=0
_safe_remove_transaction_dir "$BACKUP_DIR"
BACKUP_DIR=""

# ── Done ─────────────────────────────────────────────────────
echo ""
echo -e "  ${G}══════════════════════════════════════════${R}"
echo -e "  ${B}${G}  ✅ KACE installed successfully!${R}"
echo -e "  ${G}══════════════════════════════════════════${R}"
echo ""
if [ "${KACE_NO_LAUNCH:-0}" = "1" ]; then
    echo -e "  ${C}KACE launch skipped for unattended provisioning.${R}"
    exit 0
fi

echo -e "  ${C}Launching KACE...${R}"
sleep 1
# Reconnect stdin to the terminal so interactive prompts (questionary) work
exec < /dev/tty || true
cd "$INSTALL_DIR"
set +e
./venv/bin/python kace.py
KACE_EXIT=$?
set -e
exit "$KACE_EXIT"
