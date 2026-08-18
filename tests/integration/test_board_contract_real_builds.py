"""Opt-in real Klipper builds for BoardContract-verified targets."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
import unittest

from firmware.boards.catalog import load_default_catalog
from firmware.boards.deployment import build_artifact_from_proof, create_deployment_plan
from firmware.boards.kconfig import BoardContractBuildContext, build_board_contract_shadow
from firmware.boards.kconfig import artifact_contains_firmware_fingerprint


TARGETS = (
    ("creality.v4.2.7", "stm32f103-ret6", "uart-usart1-pa10-pa9", "klipper.bin", None),
    ("btt.skr-mini-e3.v3.0", "stm32g0b1", "usb-pa11-pa12", "klipper.bin", "firmware.bin"),
    ("mks.robin-nano.v3", "stm32f407", "usb-pa11-pa12", "klipper.bin", "Robin_nano_v3.bin"),
    ("btt.skr-pico.v1.0", "rp2040", "usb-native", "klipper.uf2", "klipper.uf2"),
    ("btt.skr-v1.4", "lpc1768", "usb-native", "klipper.bin", "firmware.bin"),
    ("btt.skr-v1.4", "lpc1769-turbo", "usb-native", "klipper.bin", "firmware.bin"),
)


@unittest.skipUnless(
    os.environ.get("KACE_BOARD_CONTRACT_REAL_BUILDS") == "1",
    "set KACE_BOARD_CONTRACT_REAL_BUILDS=1 to run isolated real firmware builds",
)
class BoardContractRealBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.make = os.environ.get("KACE_REAL_MAKE", "/usr/bin/make")
        if not Path(cls.make).is_file() and not shutil.which(cls.make):
            raise unittest.SkipTest(f"real make is unavailable: {cls.make}")
        if not shutil.which("arm-none-eabi-gcc"):
            raise unittest.SkipTest("arm-none-eabi-gcc is unavailable")
        cls.source_checkout = os.environ.get("KACE_KLIPPER_SOURCE") or None
        cls.output = tempfile.TemporaryDirectory(prefix="kace-board-proofs-")
        cls.staging = tempfile.TemporaryDirectory(prefix="kace-board-staging-")
        cls.catalog = load_default_catalog(refresh=True)

    @classmethod
    def tearDownClass(cls):
        cls.output.cleanup()
        cls.staging.cleanup()

    def test_real_build_targets(self):
        proofs = []
        for board_id, variant_id, target_id, filename, final_filename in TARGETS:
            with self.subTest(board=board_id):
                proof = build_board_contract_shadow(
                    board_id,
                    variant_id,
                    target_id,
                    context=BoardContractBuildContext(
                        output_directory=self.output.name,
                        staging_parent=self.staging.name,
                        source_checkout=self.source_checkout,
                        make_command=(self.make,),
                        concurrency=2,
                    ),
                )
                self.assertEqual(filename, Path(proof.artifact_path).name)
                self.assertGreater(proof.artifact_size, 0)
                self.assertTrue(proof.olddefconfig.ok)
                self.assertTrue(proof.requested_selections.ok)
                self.assertTrue(proof.resolved_assertions.ok)
                self.assertTrue(proof.build.ok)
                self.assertEqual("kace-board-build-proof/v3", proof.schema)
                self.assertTrue(proof.embedded_fingerprint_verified)
                self.assertTrue(artifact_contains_firmware_fingerprint(
                    Path(proof.artifact_path).read_bytes(), proof.firmware_fingerprint
                ))
                self.assertTrue(proof.toolchain.make_version)
                self.assertTrue(proof.toolchain.compiler_version)
                self.assertTrue(proof.requested_flags)
                self.assertTrue(proof.effective_flags)
                self.assertTrue(proof.lto_requested)
                if proof.fallback_used:
                    self.assertFalse(proof.lto_effective)
                    self.assertTrue(proof.fallback_reason)
                contract = self.catalog.by_id(board_id)
                artifact = build_artifact_from_proof(proof, contract)
                plan = create_deployment_plan(
                    contract,
                    artifact,
                    output_directory=str(Path(self.output.name) / "plans"),
                )
                if final_filename is None:
                    self.assertTrue(plan.transformation.final_filename.startswith("kace-"))
                else:
                    self.assertEqual(final_filename, plan.transformation.final_filename)
                self.assertEqual(artifact.sha256, plan.transformation.final_sha256)
                self.assertFalse(plan.transformation.content_changed)
                proofs.append(proof)
        self.assertEqual(len(TARGETS), len(proofs))


if __name__ == "__main__":
    unittest.main()
