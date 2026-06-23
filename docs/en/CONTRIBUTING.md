# Contributing to KACE

Thank you for considering a contribution to KACE.
This guide explains how to add new boards, create snapshots, and submit safe PRs.

## Repository Structure

KACE is managed in the primary repository:

- **`3D-uy/kace` (Production/Stable)**: The main stable, user-facing repository. Production installer scripts target this channel.

---

## Development Setup

```bash
git clone https://github.com/3D-uy/kace.git
cd kace
pip install -r requirements.txt
```

Run the test suite to verify your environment:

```bash
python3 tests/run_tests.py --verbose
```

All 21 tests must pass before any contribution is accepted.

---

## Dependency Management & Development Setup

KACE enforces secure dependency installations via hash verification. The Python dependencies are defined in `.in` files and compiled to `.txt` files with hashes using `pip-tools`.

- **Core Dependencies**: Defined in `requirements.in` and compiled to `requirements.txt`.
- **Optional SSH Dependencies**: Defined in `requirements-ssh.in` and compiled to `requirements-ssh.txt` (which are lazily installed on-demand with hash checking).

> [!IMPORTANT]
> **Do NOT edit `requirements.txt` or `requirements-ssh.txt` directly.** Any manual edits will be overwritten the next time dependencies are compiled.

To add or update a dependency:
1. Edit `requirements.in` (for core dependencies) or `requirements-ssh.in` (for optional SSH dependencies).
2. Install `pip-tools` if you haven't already:
   ```bash
   pip install pip-tools
   ```
3. Compile the dependencies to generate the pinned hash files:
   ```bash
   # Regenerate core dependencies
   pip-compile --generate-hashes requirements.in
   
   # Regenerate SSH/optional dependencies
   pip-compile --generate-hashes requirements-ssh.in
   ```
4. Commit both the `.in` file and the updated `.txt` file.

---

## Adding a New Board

KACE's board data lives entirely in `data/boards.yaml`. Adding a new board
requires **only a YAML edit** — no Python changes needed.

### Step 1 — Add the board to `boards[]`

Find (or create) the right `mcu` group and add your board's search term:

```yaml
boards:
  - mcu: stm32f103
    search_terms:
      - creality-v4.2.2
      - creality-v4.2.7
      - skr-mini-e3
      - your-new-board      # ← add here
    bltouch:
      your-new-board:       # ← substring of the Klipper config filename
        sensor_pin: "^PA7"  # Z-min pin with pull-up if required
        control_pin: "PB0"  # Servo/control pin
```

The `search_terms` list entries must be substrings of the official Klipper
config filename (e.g. `generic-your-new-board.cfg` → `your-new-board`).

If your board uses a different MCU not yet listed, add a new `boards[]` entry
with the correct `mcu` value from `firmware/detector.py`.

### Step 2 — Verify the firmware pattern exists

Check that `mcu_firmware[]` has a pattern for your board's MCU family.
If your board uses `stm32f103`, `stm32f4`, `lpc1769`, or `rp2040` — it's
already covered. If you need a new MCU family, add a new entry:

```yaml
mcu_firmware:
  - pattern: "your-new-mcu"   # must be before any generic parent pattern
    arch: stm32
    mach: STM32
    flash_start: "0x8000"
    set_mcu_flag: true
```

> **Order matters.** More specific patterns must appear before generic ones.
> Run `python3 tests/run_tests.py --yaml-check` to validate precedence.

### Step 3 — Validate the YAML

```bash
python3 tests/run_tests.py --yaml-check
```

This checks schema, required fields, and pattern order. Fix any errors before continuing.

### Step 4 — Add a regression snapshot

Create a mock config string in `tests/regression/test_snapshot_expansion.py`
following the existing examples:

```python
MOCK_YOUR_BOARD = """
[stepper_x]
step_pin: PA0
...
"""

def test_your_board_snapshot(self):
    """Regression snapshot for Your Board (STM32Fxxx)."""
    self._run_snapshot(
        "your-board-expected",
        MOCK_YOUR_BOARD,
        "generic-your-new-board.cfg",
        "/dev/serial/by-id/usb-Klipper_stm32fxxx_mock-if00",
    )
```

Generate the golden fixture:

```bash
python3 tests/run_tests.py --update-snapshots
```

Verify the snapshot looks correct, then run the full suite:

```bash
python3 tests/run_tests.py --verbose
```

### Step 5 — Submit your PR

All 21+ tests must pass. The CI pipeline will run automatically on your PR.

---

## PR Checklist

Before opening a PR, verify all of the following:

- [ ] `python3 tests/run_tests.py --verbose` → all tests pass
- [ ] `python3 tests/run_tests.py --yaml-check` → YAML valid
- [ ] Snapshot files committed alongside code changes (if output changed)
- [ ] `CHANGELOG.md` `[Unreleased]` section updated
- [ ] No hardcoded English strings added to UI (use `t()` from `core/translations.py`)
- [ ] No `sys.exit()` calls added outside `kace.py` entry point
- [ ] No new external dependencies added without discussion

---

## Code Style

- Python 3.11+ features are fine.
- Follow existing patterns in each module — no new abstraction layers.
- All board data goes in `data/boards.yaml`, not in Python.
- All user-facing strings go through `t()`, not hardcoded.
- All new modules that load optional data must have a hardcoded fallback dict.

---

## Architecture Freeze

The core architecture is intentionally stable. Please do not propose:

- New abstraction layers in `core/` or `firmware/`
- Schema changes to `boards.yaml` without discussion
- Changes to the Jinja2 template that break existing snapshots silently

If a major refactor is needed, open an issue first describing the motivation.

---

## Getting Help

Open an issue on [GitHub](https://github.com/3D-uy/kace/issues) with:
- Your board model
- The Klipper config filename (`generic-xxx.cfg`)
- The MCU chip on your board
- What KACE currently generates vs what you expect
