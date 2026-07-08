#!/usr/bin/env bash
# ============================================================
#  KACE — Klipper Automated Configuration Ecosystem
#  Install Script
#
#  Safe Usage (inspect & verify script):
#    curl -sSL -o install.sh https://raw.githubusercontent.com/3D-uy/KACE/main/install.sh
#    # verify the installer before running: sha256sum install.sh
#    bash install.sh
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
INSTALL_TAG="v0.9.3.2"

# ── Banner ───────────────────────────────────────────────────
clear
SUBTITLE="KACE Installer"
VERSION="v0.9.3.2"

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
    sudo apt-get install -y git python3-pip -qq
    echo -e "${G}  ✔ Dependencies verified (apt)${R}"
elif command -v apt &>/dev/null; then
    sudo apt update -qq
    sudo apt install -y git python3-pip -qq
    echo -e "${G}  ✔ Dependencies verified (apt)${R}"
else
    echo -e "${Y}  ⚠ apt not found. Please manually ensure git and python3-pip are installed.${R}"
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
/templates/"

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
    echo -e "  Existing installation found — updating to ${INSTALL_TAG}..."
    git -C "$INSTALL_DIR" fetch origin tag "$INSTALL_TAG" --depth=1
    git -C "$INSTALL_DIR" -c advice.detachedHead=false checkout -f tags/"$INSTALL_TAG"
    echo -e "${G}  ✔ Repository updated to ${INSTALL_TAG}${R}"
else
    echo -e "  Cloning KACE (${INSTALL_TAG}) into ${Y}${INSTALL_DIR}${R}..."
    if _git_supports_sparse; then
        git clone --depth 1 --branch "$INSTALL_TAG" --filter=blob:none --sparse "$REPO_URL" "$INSTALL_DIR" --quiet
        # Non-cone mode: only the listed paths are checked out
        git -C "$INSTALL_DIR" sparse-checkout init --no-cone
        echo "$_SPARSE_PATTERNS" | git -C "$INSTALL_DIR" sparse-checkout set --no-cone --stdin
        echo -e "${G}  ✔ Repository cloned (minimal — runtime files only)${R}"
    else
        # Fallback: full clone, then delete non-runtime files
        git clone --depth 1 --branch "$INSTALL_TAG" "$REPO_URL" "$INSTALL_DIR" --quiet
        for d in $_CLEANUP_DIRS; do rm -rf "$INSTALL_DIR/$d" 2>/dev/null; done
        for f in $_CLEANUP_FILES; do rm -f "$INSTALL_DIR/$f" 2>/dev/null; done
        echo -e "${G}  ✔ Repository cloned (tag ${INSTALL_TAG} — non-runtime files removed)${R}"
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
echo -e "  ${C}Launching KACE...${R}"
sleep 1
# Reconnect stdin to the terminal so interactive prompts (questionary) work
exec < /dev/tty || true
cd "$INSTALL_DIR" && ./venv/bin/python kace.py
