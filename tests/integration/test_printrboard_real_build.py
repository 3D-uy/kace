"""Opt-in AVR regression: real olddefconfig, build and IHEX identity for K15."""
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from firmware.boards.catalog import load_default_catalog
from firmware.boards.kconfig import (
    BoardContractBuildContext, artifact_contains_firmware_fingerprint,
    build_board_contract_shadow,
)
from firmware.boards.models import SupportStatus
from firmware.boards.runtime import FirmwareAuthority, resolve_firmware_authority


@unittest.skipUnless(os.environ.get("KACE_BOARD_CONTRACT_REAL_BUILDS") == "1",
                     "set KACE_BOARD_CONTRACT_REAL_BUILDS=1 for real firmware builds")
class PrintrboardRealBuildTests(unittest.TestCase):
    def test_provisional_target_satisfies_real_kconfig_and_builds_ihex(self):
        if not shutil.which("avr-gcc"):
            self.skipTest("avr-gcc is unavailable")
        source = os.environ.get("KACE_KLIPPER_SOURCE") or None
        git = os.environ.get("KACE_REAL_GIT", "/usr/bin/git")
        git_command = (git, "-c", f"safe.directory={source}") if source else (git,)
        with tempfile.TemporaryDirectory(prefix="kace-printrboard-") as directory:
            proof = build_board_contract_shadow(
                "printrboard.rev-b-d", "at90usb1286", "usb-native",
                context=BoardContractBuildContext(
                    output_directory=str(Path(directory) / "proofs"),
                    staging_parent=directory, source_checkout=source,
                    make_command=(os.environ.get("KACE_REAL_MAKE", "/usr/bin/make"),),
                    git_command=git_command, concurrency=2,
                    environment_path=os.environ.get("KACE_REAL_TOOL_PATH") or None,
                ))
            self.assertTrue(proof.olddefconfig.ok)
            self.assertTrue(proof.requested_selections.ok)
            self.assertTrue(proof.resolved_assertions.ok)
            self.assertTrue(proof.build.ok)
            self.assertEqual(Path(proof.artifact_path).name, "klipper.elf.hex")
            self.assertTrue(proof.embedded_fingerprint_verified)
            self.assertTrue(artifact_contains_firmware_fingerprint(
                Path(proof.artifact_path).read_bytes(), proof.firmware_fingerprint))
        contract = load_default_catalog().by_id("printrboard.rev-b-d")
        self.assertIs(contract.hardware_variants[0].build_targets[0].support_status,
                      SupportStatus.PROVISIONAL)
        self.assertIs(resolve_firmware_authority("printrboard").authority,
                      FirmwareAuthority.LEGACY)
