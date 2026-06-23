import os
os.environ["KACE_TESTING"] = "1"
import shutil
import subprocess
import tempfile
import unittest

from firmware.builder import build_firmware_orchestrator
from firmware.derivation import derive_config


class TestMCUBuilds(unittest.TestCase):
    def setUp(self):
        # We need a real Klipper clone to compile firmware.
        self.klipper_path = os.path.expanduser("~/klipper")
        if not os.path.exists(self.klipper_path):
            print("Cloning Klipper for compilation tests...", flush=True)
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "https://github.com/Klipper3d/klipper.git",
                    self.klipper_path,
                ],
                check=True,
            )

        self.output_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.output_dir.cleanup()

    def _run_build_test(self, mcu, hint, expected_filename, compiler_binary):
        # Check if compiler is available in the environment
        if not shutil.which(compiler_binary) or not shutil.which("make"):
            self.skipTest(f"Compiler {compiler_binary} or make not found")

        # 1. Derive configuration
        config_dict = derive_config(mcu, hint=hint)

        # 2. Activate real build mode via env var so the builder uses the
        #    real system toolchain instead of the Docker mock make.
        #    Using an env var is safer than the old shutil.move rename approach:
        #    if the test crashes the container's /usr/local/bin/make is never lost.
        prev = os.environ.get("KACE_REAL_BUILD")
        os.environ["KACE_REAL_BUILD"] = "1"
        try:
            # 3. Call build_firmware_orchestrator
            result = build_firmware_orchestrator(
                mcu_path=f"/dev/serial/by-id/usb-Klipper_{mcu}_test-if00",
                derived_mcu=mcu,
                hint=hint,
                klipper_path=self.klipper_path,
                output_dir=self.output_dir.name,
                config_dict=config_dict,
            )

            # 4. Assert success and verify output artifact
            self.assertEqual(
                result.get("status"),
                "success",
                f"Build failed for {mcu}: {result.get('message')}",
            )
            self.assertEqual(result.get("firmware"), expected_filename)

            dest_path = result.get("path")
            self.assertIsNotNone(dest_path)
            self.assertTrue(os.path.exists(dest_path))

            # Real firmware must exceed the mock-detection threshold
            from firmware.build_mode import FIRMWARE_MINIMUM_SIZE_BYTES
            self.assertGreater(
                os.path.getsize(dest_path),
                FIRMWARE_MINIMUM_SIZE_BYTES,
                f"Generated binary {expected_filename} for {mcu} is smaller than "
                f"{FIRMWARE_MINIMUM_SIZE_BYTES} bytes — likely a mock artifact",
            )

        finally:
            # Always restore the original env var state
            if prev is None:
                os.environ.pop("KACE_REAL_BUILD", None)
            else:
                os.environ["KACE_REAL_BUILD"] = prev

    def test_lpc1769_build(self):
        """Verify LPC1769 builds successfully to klipper.bin."""
        self._run_build_test("lpc1769", "usb", "klipper.bin", "arm-none-eabi-gcc")

    def test_stm32f103_build(self):
        """Verify STM32F103 builds successfully to klipper.bin."""
        self._run_build_test("stm32f103", "usb", "klipper.bin", "arm-none-eabi-gcc")

    def test_stm32f446_build(self):
        """Verify STM32F446 builds successfully to klipper.bin."""
        self._run_build_test("stm32f446", "usb", "klipper.bin", "arm-none-eabi-gcc")

    def test_rp2040_build(self):
        """Verify RP2040 builds successfully to klipper.uf2."""
        self._run_build_test("rp2040", "usb", "klipper.uf2", "arm-none-eabi-gcc")

    def test_atmega2560_build(self):
        """Verify AVR ATmega2560 builds successfully to klipper.elf.hex."""
        self._run_build_test("atmega2560", "uart", "klipper.elf.hex", "avr-gcc")


if __name__ == "__main__":
    unittest.main()
