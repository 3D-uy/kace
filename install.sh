#!/usr/bin/env bash
# ============================================================
#  KACE — Klipper Automated Configuration Ecosystem
#  Install Script
#
#  Quick start (recommended for convenience):
#    bash <(curl -fsSL https://raw.githubusercontent.com/3D-uy/KACE/main/install.sh)
#
#  Security tradeoff: the quick-start command streams network content directly
#  to Bash, so it cannot be inspected or verified before execution.
#
#  Verified installation (recommended when integrity verification matters):
#    INSTALL_REF='vX.Y.Z'  # matching release tag
#    EXPECTED_SHA256='paste-the-trusted-sha256-here'  # obtain separately
#    curl -fsSLo install.sh "https://raw.githubusercontent.com/3D-uy/KACE/${INSTALL_REF}/install.sh"
#    printf '%s  %s\n' "$EXPECTED_SHA256" install.sh | sha256sum -c -
#    bash install.sh  # only after sha256sum reports "install.sh: OK"
#
#  Do not fetch the expected checksum from the same mutable branch as the
#  installer. Obtain it from a matching release or another trusted channel.
#  The Studio bootstrap also supplies KACE_SOURCE_REF so the installer and the
#  repository content are resolved from the same immutable revision.
# ============================================================

set -e

# ── Colors ───────────────────────────────────────────────────
G="\033[92m"   # Green
Y="\033[93m"   # Yellow
C="\033[96m"   # Cyan
R="\033[0m"    # Reset
B="\033[1m"    # Bold
E="\033[91m"   # Red (error)

REPO_URL="https://github.com/3D-uy/kace.git"
INSTALL_DIR="$HOME/kace"
KACE_BIN="/usr/local/bin/kace"
INSTALL_REF="${KACE_SOURCE_REF:-main}"

# Prevent an environment-provided ref from being interpreted as a Git option or
# revision expression. Release tags, branches, and full commit hashes remain valid.
if [[ "$INSTALL_REF" == -* ]] || [[ ! "$INSTALL_REF" =~ ^[A-Za-z0-9._/-]+$ ]] \
        || [[ "$INSTALL_REF" == *..* ]]; then
    echo "Error: invalid KACE source reference: $INSTALL_REF" >&2
    exit 1
fi

# ── Banner ───────────────────────────────────────────────────
clear
SUBTITLE="KACE Installer"
VERSION="v0.9.3.3"

# Cosmetic fallback banner for early install phase
echo ""
echo -e "  ${C}──────────────────────────────────────────${R}"
echo -e "  ${B}${C}  $SUBTITLE $VERSION${R}"
echo -e "  ${C}──────────────────────────────────────────${R}"
echo ""

# ── Step 1: System dependencies ──────────────────────────────
# Fix local hostname resolution if missing (prevents "sudo: unable to resolve host" warnings)
if command -v getent &>/dev/null && command -v hostname &>/dev/null; then
    _HOSTNAME=$(hostname)
    if [ -n "$_HOSTNAME" ] && ! getent hosts "$_HOSTNAME" &>/dev/null; then
        echo -e "  ${Y}⚠ Local hostname '${_HOSTNAME}' is not resolvable.${R}"
        echo -e "  Attempting to add '${_HOSTNAME}' to /etc/hosts to prevent sudo warnings..."
        if command -v sudo &>/dev/null; then
            echo "127.0.1.1 $_HOSTNAME" | sudo tee -a /etc/hosts >/dev/null
            echo -e "  ${G}✔ Added ${_HOSTNAME} to /etc/hosts${R}"
        fi
    fi
fi

echo -e "${C}[1/5]${R} Checking system dependencies..."
if command -v apt-get &>/dev/null; then
    sudo apt-get update -qq
    sudo apt-get install -y git python3-pip python3-venv -qq
    echo -e "${G}  ✔ Dependencies verified (apt)${R}"
elif command -v apt &>/dev/null; then
    sudo apt update -qq
    sudo apt install -y git python3-pip python3-venv -qq
    echo -e "${G}  ✔ Dependencies verified (apt)${R}"
else
    echo -e "${Y}  ⚠ apt not found. Please manually ensure git, python3-pip, and python3-venv are installed.${R}"
fi

if ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
    echo -e "${E}  KACE requires Python 3.11 or newer.${R}" >&2
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

# Non-runtime dirs/files that can be removed after a full clone fallback
_CLEANUP_DIRS="docs tests docker .github scripts MagicMock"
_CLEANUP_FILES="test_run.log jobs.json SWEEP_RESULTS.md REPOSITORY_MANIFEST.md CHANGELOG.md CODE_OF_CONDUCT.md SECURITY.md README.md .gitattributes"

# Check if sparse checkout is supported (requires Git >= 2.25)
_git_supports_sparse() {
    local ver major minor
    ver=$(git --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1)
    major=$(echo "$ver" | cut -d. -f1)
    minor=$(echo "$ver" | cut -d. -f2)
    [ "${major:-0}" -gt 2 ] || { [ "${major:-0}" -eq 2 ] && [ "${minor:-0}" -ge 25 ]; }
}

echo -e "${C}[2/5]${R} Syncing KACE repository..."
if [ -d "$INSTALL_DIR/.git" ]; then
    echo -e "  Existing installation found — updating to ${INSTALL_REF}..."
    git -C "$INSTALL_DIR" fetch origin "$INSTALL_REF" --depth=1
    if [ "$(git -C "$INSTALL_DIR" config --bool core.sparseCheckout 2>/dev/null || true)" = "true" ]; then
        echo "$_SPARSE_PATTERNS" | git -C "$INSTALL_DIR" sparse-checkout set --no-cone --stdin
    fi
    git -C "$INSTALL_DIR" -c advice.detachedHead=false checkout -f FETCH_HEAD
    echo -e "${G}  ✔ Repository updated to ${INSTALL_REF}${R}"
else
    echo -e "  Cloning KACE (${INSTALL_REF}) into ${Y}${INSTALL_DIR}${R}..."
    if _git_supports_sparse; then
        mkdir -p "$INSTALL_DIR"
        git -C "$INSTALL_DIR" init --quiet
        git -C "$INSTALL_DIR" remote add origin "$REPO_URL"
        git -C "$INSTALL_DIR" sparse-checkout init --no-cone
        echo "$_SPARSE_PATTERNS" | git -C "$INSTALL_DIR" sparse-checkout set --no-cone --stdin
        git -C "$INSTALL_DIR" fetch origin "$INSTALL_REF" --depth=1 --filter=blob:none --quiet
        git -C "$INSTALL_DIR" -c advice.detachedHead=false checkout -f FETCH_HEAD --quiet
        echo -e "${G}  ✔ Repository cloned (minimal — runtime files only)${R}"
    else
        # Fallback: full clone, then delete non-runtime files
        git clone --depth 1 --no-checkout "$REPO_URL" "$INSTALL_DIR" --quiet
        git -C "$INSTALL_DIR" fetch origin "$INSTALL_REF" --depth=1 --quiet
        git -C "$INSTALL_DIR" -c advice.detachedHead=false checkout -f FETCH_HEAD --quiet
        for d in $_CLEANUP_DIRS; do rm -rf "$INSTALL_DIR/$d" 2>/dev/null; done
        for f in $_CLEANUP_FILES; do rm -f "$INSTALL_DIR/$f" 2>/dev/null; done
        echo -e "${G}  ✔ Repository cloned (${INSTALL_REF} — non-runtime files removed)${R}"
    fi
fi

# Load actual version dynamically post-clone
if [ -f "$INSTALL_DIR/VERSION" ]; then
    VERSION="v$(cat "$INSTALL_DIR/VERSION" | tr -d '\r\n')"
fi



# ── Step 3: Install Python dependencies ──────────────────────
echo -e "${C}[3/5]${R} Installing Python packages in isolated venv..."
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
# Enforce hashes to protect against PyPI substitution attacks
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" --require-hashes -q
echo -e "${G}  ✔ Python dependencies verified (isolated venv)${R}"

# ── Step 4: Configure executable permissions ─────────────────
echo -e "${C}[4/5]${R} Configuring permissions..."
chmod +x "$INSTALL_DIR/kace.py"
echo -e "${G}  ✔ Permissions applied${R}"

# ── Step 5: Create global symlink ────────────────────────────
echo -e "${C}[5/5]${R} Finalizing installation..."
if command -v sudo &>/dev/null; then
    sudo tee "$KACE_BIN" > /dev/null <<EOF
#!/usr/bin/env bash
exec "$INSTALL_DIR/venv/bin/python" "$INSTALL_DIR/kace.py" "\$@"
EOF
    sudo chmod +x "$KACE_BIN"
    echo -e "${G}  ✔ Global wrapper command created: ${B}kace${R} → ${KACE_BIN}${R}"
else
    # Fallback: add to user's PATH via ~/.local/bin
    FALLBACK_BIN="$HOME/.local/bin"
    mkdir -p "$FALLBACK_BIN"
    tee "$FALLBACK_BIN/kace" > /dev/null <<EOF
#!/usr/bin/env bash
exec "$INSTALL_DIR/venv/bin/python" "$INSTALL_DIR/kace.py" "\$@"
EOF
    chmod +x "$FALLBACK_BIN/kace"
    echo -e "${Y}  ⚠ sudo not available. Created fallback wrapper at ${FALLBACK_BIN}/kace${R}"
    echo -e "${Y}  ⚠ Make sure ${FALLBACK_BIN} is in your PATH:${R}"
    echo -e "${Y}     export PATH=\"\$HOME/.local/bin:\$PATH\"${R}"
fi

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
