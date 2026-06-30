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
# Runtime files needed on the Pi — docs/assets are excluded from sparse clone
# Root-level files (kace.py, requirements.txt, etc.) are included automatically
_SPARSE_DIRS="core firmware data templates"

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
    git -C "$INSTALL_DIR" checkout -f tags/"$INSTALL_TAG"
    echo -e "${G}  ✔ Repository updated to ${INSTALL_TAG}${R}"
else
    echo -e "  Cloning KACE (${INSTALL_TAG}) into ${Y}${INSTALL_DIR}${R}..."
    if _git_supports_sparse; then
        git clone --depth 1 --branch "$INSTALL_TAG" --filter=blob:none --sparse "$REPO_URL" "$INSTALL_DIR" --quiet
        git -C "$INSTALL_DIR" sparse-checkout set $_SPARSE_DIRS
        echo -e "${G}  ✔ Repository cloned (optimized — tag ${INSTALL_TAG} — docs excluded)${R}"
    else
        git clone --depth 1 --branch "$INSTALL_TAG" "$REPO_URL" "$INSTALL_DIR" --quiet
        echo -e "${G}  ✔ Repository cloned (tag ${INSTALL_TAG})${R}"
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
