import hashlib
import unittest

from firmware.identity import (
    FirmwareBuildInputs,
    ToolchainIdentity,
    canonicalize_dot_config,
)


TOOLCHAIN = ToolchainIdentity(
    make_command="make",
    make_version="GNU Make 4.4",
    compiler="arm-none-eabi-gcc",
    compiler_version="arm-none-eabi-gcc 13.2.1",
)
CONFIG = 'CONFIG_MCU="stm32"\nCONFIG_CLOCK_REF_8M=y\n# CONFIG_USB is not set\n'


class FirmwareIdentityTests(unittest.TestCase):
    def test_canonical_config_ignores_order_line_endings_and_comments(self):
        left = canonicalize_dot_config(CONFIG)
        right = canonicalize_dot_config(
            "# generated\r\n# CONFIG_USB is not set\r\n"
            "CONFIG_CLOCK_REF_8M=y\r\nCONFIG_MCU=\"stm32\"\r\n"
        )
        self.assertEqual(left, right)

    def test_same_config_with_different_klipper_commit_changes_input_identity(self):
        first = FirmwareBuildInputs.create(
            klipper_commit="1" * 40,
            canonical_config=CONFIG,
            toolchain=TOOLCHAIN,
            build_id="a" * 32,
        )
        second = FirmwareBuildInputs.create(
            klipper_commit="2" * 40,
            canonical_config=CONFIG,
            toolchain=TOOLCHAIN,
            build_id="b" * 32,
        )
        self.assertEqual(first.config_sha256, second.config_sha256)
        self.assertNotEqual(first.input_sha256, second.input_sha256)
        self.assertNotEqual(first.reported_version, second.reported_version)

    def test_repeated_builds_have_unique_reported_versions(self):
        first = FirmwareBuildInputs.create(
            klipper_commit="1" * 40,
            canonical_config=CONFIG,
            toolchain=TOOLCHAIN,
            build_id="a" * 32,
        )
        second = FirmwareBuildInputs.create(
            klipper_commit="1" * 40,
            canonical_config=CONFIG,
            toolchain=TOOLCHAIN,
            build_id="b" * 32,
        )
        self.assertEqual(first.input_sha256, second.input_sha256)
        self.assertNotEqual(first.reported_version, second.reported_version)

    def test_completed_identity_binds_artifact_hash_and_build_id(self):
        inputs = FirmwareBuildInputs.create(
            klipper_commit="1" * 40,
            canonical_config=CONFIG,
            toolchain=TOOLCHAIN,
            build_id="a" * 32,
        )
        artifact_sha = hashlib.sha256(b"firmware").hexdigest()
        identity = inputs.complete(
            artifact_sha256=artifact_sha,
            artifact_size=8,
            artifact_format="BIN",
        )
        self.assertEqual(identity.klipper_commit, "1" * 40)
        self.assertEqual(identity.canonical_config, canonicalize_dot_config(CONFIG))
        self.assertEqual(identity.toolchain.compiler, "arm-none-eabi-gcc")
        self.assertEqual(identity.artifact_sha256, artifact_sha)
        self.assertEqual(identity.build_id, "a" * 32)
        self.assertRegex(identity.artifact_build_id, r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
