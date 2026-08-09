# tests/unit/test_builder.py
#
# Unit tests for firmware/builder.py (build_firmware_orchestrator).
# Verifies target binary format selection logic for AVR, RP2040, STM32, and fallback.

import os
import unittest
from unittest.mock import patch, MagicMock
import time

from firmware.builder import build_firmware_orchestrator
from firmware.identity import FirmwareBuildInputs, ToolchainIdentity

class TestFirmwareBuilder(unittest.TestCase):

    def test_real_artifact_embeds_and_returns_complete_build_identity(self):
        import tempfile

        inputs = FirmwareBuildInputs.create(
            klipper_commit="1" * 40,
            canonical_config='CONFIG_MCU="stm32"\nCONFIG_USB=y\n',
            toolchain=ToolchainIdentity("make", "GNU Make 4.4", "gcc", "gcc 13"),
            build_id="2" * 32,
        )
        compile_commands = []

        with tempfile.TemporaryDirectory() as tmp_klipper, tempfile.TemporaryDirectory() as tmp_output:
            config_path = os.path.join(tmp_klipper, ".config")
            with open(config_path, "w", encoding="utf-8") as config_file:
                config_file.write('CONFIG_MCU="stm32"\nCONFIG_USB=y\n')
            out_dir = os.path.join(tmp_klipper, "out")

            def run_make(command, **_kwargs):
                if "olddefconfig" not in command and "clean" not in command:
                    compile_commands.append(list(command))
                    os.makedirs(out_dir, exist_ok=True)
                    with open(os.path.join(out_dir, "klipper.bin"), "wb") as artifact:
                        artifact.write(b"firmware" * 2048)
                return MagicMock(stdout="", stderr="", returncode=0)

            with patch('firmware.builder.generate_firmware_config', return_value=(True, "")), \
                 patch('firmware.builder.validate_config', return_value=(True, "")), \
                 patch('firmware.builder.create_build_inputs', return_value=inputs), \
                 patch('firmware.builder.is_mock_build', return_value=False), \
                 patch('firmware.builder.subprocess.run', side_effect=run_make), \
                 patch('firmware.builder.subprocess.check_output', return_value=b"1"):
                result = build_firmware_orchestrator(
                    derived_mcu="stm32f446",
                    klipper_path=tmp_klipper,
                    output_dir=tmp_output,
                    config_dict={"CONFIG_MCU": '"stm32"'},
                )

        self.assertEqual(result["status"], "success")
        identity = result["artifact"].firmware_identity
        self.assertIsNotNone(identity)
        self.assertEqual(identity.klipper_commit, "1" * 40)
        self.assertEqual(identity.artifact_sha256, result["artifact"].sha256)
        self.assertEqual(result["klipper_version"], inputs.reported_version)
        self.assertEqual(len(compile_commands), 1)
        self.assertIn(
            f"KLIPPER_VERSION={inputs.reported_version}", compile_commands[0]
        )

    @patch('firmware.builder.generate_firmware_config', return_value=(True, ""))
    @patch('firmware.builder.validate_config', return_value=(True, ""))
    @patch('firmware.builder.subprocess.run')
    @patch('firmware.builder.subprocess.check_output')
    @patch('firmware.builder.os.makedirs')
    @patch('firmware.builder.shutil.copy2')
    @patch('firmware.builder.os.path.exists')
    @patch('firmware.builder.os.path.getmtime')
    @patch('firmware.builder.os.path.getsize', return_value=100 * 1024)
    def test_build_avr_mcu(self, mock_getsize, mock_getmtime, mock_exists, mock_copy, mock_makedirs, mock_check_output, mock_run, mock_val, mock_gen):
        """Verify AVR target correctly selects klipper.elf.hex."""
        mock_check_output.return_value = b"4"
        mock_getmtime.return_value = time.time() + 10.0
        
        # Simulate that BOTH klipper.bin and klipper.elf.hex exist (as in mock/test envs)
        # We want to be sure it selects ONLY klipper.elf.hex for AVR
        mock_exists.side_effect = lambda path: True if any(x in path for x in ["klipper.bin", "klipper.elf.hex", "klipper.uf2"]) else False
        
        config_dict = {"CONFIG_MCU": '"avr"'}
        result = build_firmware_orchestrator(
            derived_mcu="atmega2560",
            klipper_path="/fake/klipper",
            output_dir="/fake/kace",
            config_dict=config_dict
        )
        
        self.assertEqual(result.get("status"), "success")
        self.assertEqual(result.get("firmware"), "klipper.elf.hex")
        self.assertIn("klipper.elf.hex", result.get("path"))
        
        # Verify that only klipper.elf.hex was copied
        copied_dest = mock_copy.call_args[0][0]
        self.assertTrue(copied_dest.endswith("klipper.elf.hex"))

    @patch('firmware.builder.generate_firmware_config', return_value=(True, ""))
    @patch('firmware.builder.validate_config', return_value=(True, ""))
    @patch('firmware.builder.subprocess.run')
    @patch('firmware.builder.subprocess.check_output')
    @patch('firmware.builder.os.makedirs')
    @patch('firmware.builder.shutil.copy2')
    @patch('firmware.builder.os.path.exists')
    @patch('firmware.builder.os.path.getmtime')
    @patch('firmware.builder.os.path.getsize', return_value=200 * 1024)
    def test_build_rp2040_mcu(self, mock_getsize, mock_getmtime, mock_exists, mock_copy, mock_makedirs, mock_check_output, mock_run, mock_val, mock_gen):
        """Verify RP2040 target correctly selects klipper.uf2."""
        mock_check_output.return_value = b"4"
        mock_getmtime.return_value = time.time() + 10.0
        mock_exists.side_effect = lambda path: True if any(x in path for x in ["klipper.bin", "klipper.elf.hex", "klipper.uf2"]) else False
        
        config_dict = {"CONFIG_MCU": '"rp2040"'}
        result = build_firmware_orchestrator(
            derived_mcu="rp2040",
            klipper_path="/fake/klipper",
            output_dir="/fake/kace",
            config_dict=config_dict
        )
        
        self.assertEqual(result.get("status"), "success")
        self.assertEqual(result.get("firmware"), "klipper.uf2")
        self.assertIn("klipper.uf2", result.get("path"))
        
        copied_dest = mock_copy.call_args[0][0]
        self.assertTrue(copied_dest.endswith("klipper.uf2"))

    @patch('firmware.builder.generate_firmware_config', return_value=(True, ""))
    @patch('firmware.builder.validate_config', return_value=(True, ""))
    @patch('firmware.builder.subprocess.run')
    @patch('firmware.builder.subprocess.check_output')
    @patch('firmware.builder.os.makedirs')
    @patch('firmware.builder.shutil.copy2')
    @patch('firmware.builder.os.path.exists')
    @patch('firmware.builder.os.path.getmtime')
    @patch('firmware.builder.os.path.getsize', return_value=80 * 1024)
    def test_build_stm32_mcu(self, mock_getsize, mock_getmtime, mock_exists, mock_copy, mock_makedirs, mock_check_output, mock_run, mock_val, mock_gen):
        """Verify STM32 target correctly selects klipper.bin."""
        mock_check_output.return_value = b"4"
        mock_getmtime.return_value = time.time() + 10.0
        mock_exists.side_effect = lambda path: True if any(x in path for x in ["klipper.bin", "klipper.elf.hex", "klipper.uf2"]) else False
        
        config_dict = {"CONFIG_MCU": '"stm32"'}
        result = build_firmware_orchestrator(
            derived_mcu="stm32f446",
            klipper_path="/fake/klipper",
            output_dir="/fake/kace",
            config_dict=config_dict
        )
        
        self.assertEqual(result.get("status"), "success")
        self.assertEqual(result.get("firmware"), "klipper.bin")
        self.assertIn("klipper.bin", result.get("path"))
        
        copied_dest = mock_copy.call_args[0][0]
        self.assertTrue(copied_dest.endswith("klipper.bin"))

    @patch('firmware.builder.generate_firmware_config', return_value=(True, ""))
    @patch('firmware.builder.validate_config', return_value=(True, ""))
    @patch('firmware.builder.subprocess.run')
    @patch('firmware.builder.subprocess.check_output')
    @patch('firmware.builder.os.makedirs')
    @patch('firmware.builder.shutil.copy2')
    @patch('firmware.builder.os.path.exists')
    @patch('firmware.builder.os.path.getmtime')
    @patch('firmware.builder.os.path.getsize', return_value=50 * 1024)
    def test_build_fallback_unknown_mcu(self, mock_getsize, mock_getmtime, mock_exists, mock_copy, mock_makedirs, mock_check_output, mock_run, mock_val, mock_gen):
        """Verify fallback checks klipper.bin first if CONFIG_MCU is unrecognized."""
        mock_check_output.return_value = b"4"
        mock_getmtime.return_value = time.time() + 10.0
        
        # When checking exists, simulate that both exist. The fallback should pick klipper.bin
        # because it is checked first in expected_outputs.
        mock_exists.side_effect = lambda path: True if any(x in path for x in ["klipper.bin", "klipper.elf.hex"]) else False
        
        config_dict = {"CONFIG_MCU": '"unknown_arch"'}
        result = build_firmware_orchestrator(
            derived_mcu="unknown_mcu",
            klipper_path="/fake/klipper",
            output_dir="/fake/kace",
            config_dict=config_dict
        )
        
        self.assertEqual(result.get("status"), "success")
        self.assertEqual(result.get("firmware"), "klipper.bin")
        
        copied_dest = mock_copy.call_args[0][0]
        self.assertTrue(copied_dest.endswith("klipper.bin"))

    def test_build_avr_mcu_from_dot_config(self):
        """Verify dynamic detection reads CONFIG_MCU directly from .config file on disk and selects the correct artifact when all exist."""
        import tempfile
        import shutil
        
        inputs = FirmwareBuildInputs.create(
            klipper_commit="1" * 40,
            canonical_config='CONFIG_MCU="avr"\nCONFIG_USB=y\n',
            toolchain=ToolchainIdentity("make", "GNU Make 4.4", "avr-gcc", "avr-gcc 13"),
            build_id="3" * 32,
        )
        with tempfile.TemporaryDirectory() as tmp_klipper:
            # Create a mock .config with CONFIG_MCU="avr"
            with open(os.path.join(tmp_klipper, ".config"), "w") as f:
                f.write('CONFIG_MCU="avr"\nCONFIG_USB=y\n')

            # Touch a minimal Makefile so _ensure_klipper_source() sees a valid source tree
            open(os.path.join(tmp_klipper, "Makefile"), "w").close()

            mock_out = os.path.join(tmp_klipper, "out")
            os.makedirs(mock_out, exist_ok=True)
            
            def mock_compile(*args, **kwargs):
                # Simulate make creating the outputs after clean
                os.makedirs(mock_out, exist_ok=True)
                for f_name in ["klipper.bin", "klipper.uf2", "klipper.elf.hex"]:
                    with open(os.path.join(mock_out, f_name), "w") as f:
                        f.write("MOCK CONTENT")
                    
            with tempfile.TemporaryDirectory() as tmp_output:
                # Patch validator, compile subprocess calls, and getmtime to return future timestamp
                with patch('firmware.builder.validate_config', return_value=(True, "")), \
                     patch('firmware.builder.create_build_inputs', return_value=inputs), \
                     patch('firmware.builder.subprocess.run', side_effect=mock_compile), \
                     patch('firmware.builder.subprocess.check_output', return_value=b"4"), \
                     patch('firmware.builder.os.path.getmtime', return_value=time.time() + 10.0):
                     
                     result = build_firmware_orchestrator(
                         derived_mcu="atmega2560",
                         klipper_path=tmp_klipper,
                         output_dir=tmp_output,
                         config_dict={"CONFIG_MCU": '"avr"'}
                     )
                     
                     self.assertEqual(result.get("status"), "success")
                     self.assertEqual(result.get("firmware"), "klipper.elf.hex")
                     self.assertTrue(os.path.exists(os.path.join(tmp_output, "klipper.elf.hex")))
                     # Verify other mock files were NOT copied
                     self.assertFalse(os.path.exists(os.path.join(tmp_output, "klipper.bin")))
                     self.assertFalse(os.path.exists(os.path.join(tmp_output, "klipper.uf2")))

if __name__ == '__main__':
    unittest.main()
