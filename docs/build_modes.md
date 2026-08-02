# KACE Firmware Build Modes

This document explains the three firmware build paths available in KACE, how to
identify which mode is active, and how to obtain a real, flashable Klipper binary
from the Docker development environment.

---

## 1. Mock Build (Default — Docker Dev Container)

**What it is:**
Inside the KACE Docker development container a lightweight script is installed
at `/usr/local/bin/make` that intercepts all `make` invocations and writes a
fixed placeholder file to `out/`:

```
MOCK BINARY     → klipper.bin   (12 bytes)
MOCK UF2        → klipper.uf2   (12 bytes)
MOCK HEX        → klipper.elf.hex (12 bytes)
```

**Why it exists:**
The mock make allows the full KACE wizard — including the MCU derivation,
firmware configuration summary, and deployment flow — to be exercised without
needing a live cross-compiler or minutes of actual ARM/AVR compilation.
This keeps the development feedback loop fast (< 1 second per "compile").

**How to recognize it:**
* KACE prints a yellow `⚠ MOCK BUILD MODE` banner at the start of every build.
* After the build completes, a prominent warning block is shown:

  ```
  Development Mode Detected
  Using mock compiler.

  Generated firmware files are placeholders and cannot be flashed.
  ```

* The Docker entrypoint menu shows `⚠ BUILD MODE: MOCK` at the top of each
  iteration.

**Artefact size gate:**
After every build, KACE checks the size of the output artifact.
If it is smaller than `FIRMWARE_MINIMUM_SIZE_BYTES` (currently **10 KB**),
an additional warning is printed with the exact size and a recovery hint.
This acts as a last-resort safety net even if the banner was missed.

> **⚠ Never flash a mock firmware to a real printer.**
> Mock artefacts contain only the literal string `"MOCK BINARY"` and have no
> valid ELF/UF2/HEX structure. Attempting to flash them will fail harmlessly,
> but the board will remain unflashed.

---

## 2. Real Build (Docker Real Build Mode)

**What it is:**
When `KACE_REAL_BUILD=1` is active, KACE bypasses the mock make script and
invokes the real `make` binary at `/usr/bin/make` directly.
The Docker image already ships the following cross-compilation toolchains:

| Toolchain            | Targets                         |
|----------------------|---------------------------------|
| `arm-none-eabi-gcc`  | STM32, LPC176x, RP2040, …       |
| `avr-gcc`            | ATmega2560, ATmega1284p, …      |
| `build-essential`    | Native Linux MCU targets        |

**How to activate:**

```bash
# Option A — environment variable
KACE_REAL_BUILD=1 python3 kace.py

# Option B — CLI flag
python3 kace.py --real-build

```

**What changes:**
* The build mode banner shows `✓ REAL BUILD MODE` in green.
* `make` resolves to `/usr/bin/make` (the real GNU Make).
* Klipper is actually compiled using the cross-compiler; real ELF/BIN/UF2
  output is produced.
* The firmware size gate will not fire (real binaries exceed 10 KB easily).

**Extracting the firmware from the container:**

After a successful real build, KACE copies the firmware to `~/kace/` inside
the container. To copy it to your host machine:

```bash
# Find the container name or ID
docker ps

# Copy from container to host (replace <container> and <dest>)
docker cp kace-container:/root/kace/klipper.bin ./klipper.bin

# For RP2040
docker cp kace-container:/root/kace/klipper.uf2 ./klipper.uf2

# For AVR
docker cp kace-container:/root/kace/klipper.elf.hex ./klipper.elf.hex
```

---

## 3. Automated Regression Build Tests

**What they are:**
`tests/regression/test_mcu_builds.py` contains a test suite that verifies KACE
can successfully drive a *real* Klipper compilation end-to-end for each
supported MCU architecture.

| Test | MCU | Expected Output |
|------|-----|-----------------|
| `test_lpc1769_build`   | LPC1769        | `klipper.bin`     |
| `test_stm32f103_build` | STM32F103      | `klipper.bin`     |
| `test_stm32f446_build` | STM32F446      | `klipper.bin`     |
| `test_rp2040_build`    | RP2040         | `klipper.uf2`     |
| `test_atmega2560_build`| ATmega2560 AVR | `klipper.elf.hex` |

**How to run:**

```bash
# From inside the Docker container
cd /workspace
python3 tests/run_tests.py
```

The test suite automatically:
1. Clones Klipper from GitHub if `~/klipper` doesn't exist.
2. Sets `KACE_REAL_BUILD=1` for the duration of each build test so the real
   cross-compiler is used (instead of the mock).
3. Asserts the output binary is larger than `FIRMWARE_MINIMUM_SIZE_BYTES`
   (10 KB) to confirm a real build occurred.
4. Skips automatically if the required cross-compiler isn't found (e.g. on
   Windows or a CI environment without the ARM toolchain).

**How this differs from mock builds:**
The regression tests are *always* real builds — they are the automated
equivalent of running `KACE_REAL_BUILD=1 python3 kace.py`.

---

## Comparison Table

| Feature                        | Mock Build           | Real Build                  | Regression Test              |
|--------------------------------|----------------------|-----------------------------|------------------------------|
| **Trigger**                    | Default in container | `KACE_REAL_BUILD=1` / `--real-build` | `python3 tests/run_tests.py` |
| **Toolchain**                  | Bash script          | `arm-none-eabi-gcc`, `avr-gcc` | Same as real build          |
| **Compile time**               | < 1 second           | 30 s – 3 min                | 30 s – 3 min per MCU         |
| **Output size**                | 12 bytes             | 30 KB – 500 KB              | 30 KB – 500 KB               |
| **Can be flashed?**            | ❌ Never              | ✅ Yes                       | ✅ Yes                        |
| **Build mode banner**          | `⚠ MOCK BUILD MODE` | `✓ REAL BUILD MODE`         | `✓ REAL BUILD MODE`          |
| **Size warning fired?**        | ✅ Yes                | ❌ No                        | ❌ No                         |

---

## Centralized Constant

The firmware size threshold is defined once in `firmware/build_mode.py`:

```python
FIRMWARE_MINIMUM_SIZE_BYTES: int = 10 * 1024   # 10 KB
```

This constant is imported by:
- `firmware/builder.py` — triggers `print_size_warning()`
- `tests/regression/test_mcu_builds.py` — used in the `assertGreater` size
  assertion to verify a real binary was produced

To adjust the threshold for a custom toolchain or MCU, change this constant
in one place and all consumers will automatically pick up the new value.
