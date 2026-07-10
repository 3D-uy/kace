import os
os.environ["KACE_TESTING"] = "1"
import shutil
import subprocess
import tempfile
import unittest

from firmware.builder import build_firmware_orchestrator, BuildContext
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
        # Check if compiler is available in the environment, excluding the wrapper directory
        from tests.fixtures.mocks import get_compiler_wrapper_path
        wrapper_dir = get_compiler_wrapper_path()
        clean_paths = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p and os.path.abspath(p) != os.path.abspath(wrapper_dir)]
        real_compiler_path = shutil.which(compiler_binary, path=os.pathsep.join(clean_paths))
        if not real_compiler_path or not shutil.which("make"):
            self.skipTest(f"Compiler {compiler_binary} or make not found")

        # 1. Derive configuration
        config_dict = derive_config(mcu, hint=hint)

        # 2. Configure build context to use the real system make
        make_cmd = "make"
        if os.path.exists("/usr/bin/make"):
            make_cmd = "/usr/bin/make"
        ctx = BuildContext(make_command=make_cmd)
        
        # 3. Call build_firmware_orchestrator
        result = build_firmware_orchestrator(
            mcu_path=f"/dev/serial/by-id/usb-Klipper_{mcu}_test-if00",
            derived_mcu=mcu,
            hint=hint,
            klipper_path=self.klipper_path,
            output_dir=self.output_dir.name,
            config_dict=config_dict,
            build_context=ctx,
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
