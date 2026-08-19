"""Phase 2 BoardContract Kconfig/build proof tests."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from firmware.boards.catalog import load_default_catalog
from firmware.boards.kconfig import (
    ArtifactValidationError,
    BoardContractBuildContext,
    BoardContractKconfigBuilder,
    BuildCommandError,
    CommandProof,
    CheckoutError,
    CheckoutCommitMismatch,
    DiscardedKconfigSelection,
    IncompatibleBuildTarget,
    ResolvedAssertionMismatch,
    UnknownKconfigSymbol,
    collect_declared_kconfig_symbols,
    parse_kconfig,
    serialize_requested_config,
    validate_target_contract,
    verify_declared_symbols,
    verify_requested_selections,
    verify_resolved_assertions,
    artifact_contains_firmware_fingerprint,
)
from core.workspace import WorkspaceSpaceError


TARGETS = (
    ("creality.v4.2.7", "stm32f103-ret6", "uart-usart1-pa10-pa9"),
    ("btt.skr-mini-e3.v3.0", "stm32g0b1", "usb-pa11-pa12"),
    ("mks.robin-nano.v3", "stm32f407", "usb-pa11-pa12"),
    ("btt.skr-pico.v1.0", "rp2040", "usb-native"),
    ("btt.skr-v1.4", "lpc1768", "usb-native"),
    ("btt.skr-v1.4", "lpc1769-turbo", "usb-native"),
)


def _resolved_config(values):
    lines = []
    for symbol, value in sorted(values.items()):
        if value is True:
            lines.append(f"{symbol}=y")
        elif value is False:
            lines.append(f"# {symbol} is not set")
        elif isinstance(value, int):
            lines.append(f"{symbol}={value}")
        elif isinstance(value, str) and value.lower().startswith("0x"):
            lines.append(f"{symbol}={value}")
        else:
            lines.append(f"{symbol}={json.dumps(value)}")
    return ("\n".join(lines) + "\n").encode("utf-8")


class _FixtureBuilder(BoardContractKconfigBuilder):
    """Exercises the complete pipeline with deterministic fake make output."""

    def __init__(self, contract, variant, target, *, create_artifact=True, wrong_commit=False):
        self.fixture_contract = contract
        self.fixture_variant = variant
        self.fixture_target = target
        self.create_artifact = create_artifact
        self.wrong_commit = wrong_commit
        self.checkouts = []
        super().__init__(command_runner=self._command)

    def _prepare_checkout(self, checkout, contract, context):
        self.checkouts.append(checkout)
        (checkout / "src").mkdir(parents=True)
        symbols = set(self.fixture_target.requested_kconfig)
        symbols.update(self.fixture_target.resolved_assertions)
        (checkout / "src" / "Kconfig").write_text(
            "\n".join(f"config {symbol.removeprefix('CONFIG_')}" for symbol in sorted(symbols))
            + "\n",
            encoding="utf-8",
        )
        (checkout / "Makefile").write_text(
            "\t$(PYTHON) ./scripts/buildcommands.py -d $(OUT)klipper.dict "
            "-t tools input output\n",
            encoding="utf-8",
        )

    def _read_checkout_commit(self, checkout, context):
        if self.wrong_commit:
            return "0" * 40
        return self.fixture_contract.upstream.validated_commit

    def _command(self, argv, cwd, environment):
        if "olddefconfig" in argv:
            requested = parse_kconfig((cwd / ".config").read_bytes())
            requested.update(self.fixture_target.resolved_assertions)
            (cwd / ".config").write_bytes(_resolved_config(requested))
        elif (
            argv and Path(argv[0]).name == "make"
            and any(item.startswith("KLIPPER_VERSION=") for item in argv)
        ):
            if self.create_artifact:
                artifact = cwd / self.fixture_target.artifact.native_path
                artifact.parent.mkdir(parents=True, exist_ok=True)
                fingerprint = next(
                    item.split("=", 1)[1]
                    for item in argv
                    if item.startswith("KLIPPER_VERSION=")
                )
                artifact.write_bytes(
                    (
                        self.fixture_contract.contract_digest
                        + self.fixture_target.id
                        + fingerprint
                    ).encode("ascii")
                )
        return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")


class KconfigCodecTests(unittest.TestCase):
    def test_fingerprint_is_verified_inside_a_uf2_wrapped_identify_dictionary(self):
        fingerprint = "kace-b1-" + "a" * 32
        dictionary = json.dumps(
            {"app": "Klipper", "version": f"v-test-{fingerprint}"},
            separators=(",", ":"), sort_keys=True,
        ).encode()
        binary = b"prefix" + zlib.compress(dictionary, 9) + b"suffix"
        blocks = []
        payload_size = 256
        count = (len(binary) + payload_size - 1) // payload_size
        for number in range(count):
            chunk = binary[number * payload_size:(number + 1) * payload_size]
            block = bytearray(512)
            struct.pack_into(
                "<IIIIIIII", block, 0,
                0x0A324655, 0x9E5D5157, 0,
                0x10000000 + number * payload_size,
                len(chunk), number, count, 0,
            )
            block[32:32 + len(chunk)] = chunk
            struct.pack_into("<I", block, 508, 0x0AB16F30)
            blocks.append(block)
        self.assertTrue(artifact_contains_firmware_fingerprint(
            b"".join(blocks), fingerprint
        ))

    def test_requested_config_is_sorted_and_round_trips(self):
        values = {
            "CONFIG_Z_STRING": "stm32f103xe",
            "CONFIG_A_BOOL": True,
            "CONFIG_B_DISABLED": False,
            "CONFIG_C_INT": 8000000,
        }
        encoded = serialize_requested_config(values)
        self.assertEqual(values, parse_kconfig(encoded))
        self.assertTrue(encoded.startswith(b"CONFIG_A_BOOL=y\n"))

    def test_unknown_symbol_is_rejected_before_olddefconfig(self):
        with self.assertRaisesRegex(UnknownKconfigSymbol, "not declared"):
            verify_declared_symbols(
                {"CONFIG_DOES_NOT_EXIST": True}, frozenset({"CONFIG_MACH_STM32"})
            )

    def test_existing_symbol_removed_by_olddefconfig_is_rejected(self):
        with self.assertRaisesRegex(DiscardedKconfigSelection, "removed by olddefconfig"):
            verify_requested_selections(
                {"CONFIG_STM32_SERIAL_USART6": True},
                {"CONFIG_MACH_STM32F103": True},
            )

    def test_changed_requested_value_is_rejected(self):
        with self.assertRaisesRegex(DiscardedKconfigSelection, "resolved False"):
            verify_requested_selections(
                {"CONFIG_STM32_USB_PA11_PA12": True},
                {"CONFIG_STM32_USB_PA11_PA12": False},
            )

    def test_resolved_assertion_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ResolvedAssertionMismatch, "CONFIG_CLOCK_REF_FREQ"):
            verify_resolved_assertions(
                {"CONFIG_CLOCK_REF_FREQ": 12000000},
                {"CONFIG_CLOCK_REF_FREQ": 8000000},
            )


class TargetCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        catalog = load_default_catalog(refresh=True)
        contract = catalog.by_id("btt.skr-mini-e3.v3.0")
        cls.variant = contract.variant("stm32g0b1")
        cls.target = cls.variant.target("usb-pa11-pa12")

    def test_processor_incompatible_with_target_is_rejected(self):
        target = deepcopy(self.target)
        target.requested_kconfig["CONFIG_MACH_STM32F103"] = True
        with self.assertRaisesRegex(IncompatibleBuildTarget, "processors outside"):
            validate_target_contract(self.variant, target)

    def test_transport_incompatible_with_target_is_rejected(self):
        target = deepcopy(self.target)
        target.transport.selection.clear()
        target.transport.selection["CONFIG_STM32_SERIAL_USART1"] = True
        target.requested_kconfig.pop("CONFIG_STM32_USB_PA11_PA12")
        target.requested_kconfig["CONFIG_STM32_SERIAL_USART1"] = True
        with self.assertRaisesRegex(IncompatibleBuildTarget, "USB target"):
            validate_target_contract(self.variant, target)

    def test_multiple_bootloader_selections_are_rejected(self):
        target = deepcopy(self.target)
        target.requested_kconfig["CONFIG_STM32_FLASH_START_C000"] = True
        with self.assertRaisesRegex(IncompatibleBuildTarget, "bootloader/flash"):
            validate_target_contract(self.variant, target)


class BuildProofPipelineTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_default_catalog(refresh=True)
        self.output = tempfile.TemporaryDirectory()
        self.staging = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.output.cleanup()
        self.staging.cleanup()

    def _parts(self, board_id, variant_id, target_id):
        contract = self.catalog.by_id(board_id)
        variant = contract.variant(variant_id)
        target = variant.target(target_id)
        return contract, variant, target

    def _context(self):
        return BoardContractBuildContext(
            output_directory=self.output.name,
            staging_parent=self.staging.name,
            make_command=("make",),
        )

    def test_build_targets_generate_immutable_proofs(self):
        for board_id, variant_id, target_id in TARGETS:
            with self.subTest(board=board_id):
                contract, variant, target = self._parts(board_id, variant_id, target_id)
                builder = _FixtureBuilder(contract, variant, target)
                proof = builder.build(board_id, variant_id, target_id, context=self._context())
                self.assertEqual(contract.contract_digest, proof.contract_digest)
                self.assertEqual(contract.upstream.validated_commit, proof.klipper_commit)
                self.assertTrue(proof.olddefconfig.ok)
                self.assertTrue(proof.requested_selections.ok)
                self.assertTrue(proof.resolved_assertions.ok)
                self.assertTrue(proof.build.ok)
                self.assertEqual("kace-board-build-proof/v3", proof.schema)
                self.assertTrue(proof.toolchain.make_version)
                self.assertTrue(proof.toolchain.compiler_version)
                self.assertEqual(proof.lto_retry_used, proof.fallback_used)
                self.assertEqual(bool(proof.fallback_reason), proof.fallback_used)
                self.assertRegex(proof.build_id, r"^[0-9a-f]{32}$")
                self.assertEqual(f"kace-b1-{proof.build_id}", proof.firmware_fingerprint)
                self.assertIn(
                    f"KLIPPER_VERSION={proof.firmware_fingerprint}", proof.build.argv
                )
                self.assertTrue(proof.embedded_fingerprint_verified)
                self.assertEqual(64, len(proof.digest))
                self.assertGreater(proof.artifact_size, 0)
                for path, expected_hash in (
                    (proof.requested_config_path, proof.requested_config_sha256),
                    (proof.resolved_config_path, proof.resolved_config_sha256),
                    (proof.artifact_path, proof.artifact_sha256),
                ):
                    content = Path(path).read_bytes()
                    self.assertEqual(expected_hash, hashlib.sha256(content).hexdigest())
                self.assertTrue((Path(proof.artifact_path).parent / "build-proof.json").is_file())
                with self.assertRaises(FrozenInstanceError):
                    proof.artifact_size = 0
                self.assertTrue(all(checkout != Path.home() / "klipper" for checkout in builder.checkouts))

    def test_default_workspace_uses_kace_cache_not_a_small_system_temp(self):
        contract, variant, target = self._parts(*TARGETS[0])
        builder = _FixtureBuilder(contract, variant, target)
        cache_home = Path(self.staging.name) / "cache-home"
        small_tmp = Path(self.staging.name) / "small-tmp"
        small_tmp.mkdir()

        def disk_usage(path):
            path = Path(path).resolve()
            free = 128 * 1024 ** 2 if path.is_relative_to(small_tmp.resolve()) else 10 * 1024 ** 3
            return shutil._ntuple_diskusage(20 * 1024 ** 3, 10 * 1024 ** 3, free)

        with patch.dict(os.environ, {"KACE_CACHE_HOME": str(cache_home)}), \
             patch("tempfile.gettempdir", return_value=str(small_tmp)), \
             patch("core.workspace.shutil.disk_usage", side_effect=disk_usage):
            proof = builder.build(
                *TARGETS[0],
                context=BoardContractBuildContext(output_directory=self.output.name),
            )

        self.assertTrue(Path(proof.artifact_path).is_file())
        self.assertEqual(
            cache_home / "kace" / "workspaces",
            builder.checkouts[0].parent.parent,
        )

    def test_insufficient_workspace_space_fails_before_checkout(self):
        contract, variant, target = self._parts(*TARGETS[0])
        builder = _FixtureBuilder(contract, variant, target)
        with patch("core.workspace.shutil.disk_usage") as disk_usage:
            disk_usage.return_value = shutil._ntuple_diskusage(
                1024 ** 3, 900 * 1024 ** 2, 124 * 1024 ** 2,
            )
            with self.assertRaisesRegex(WorkspaceSpaceError, "Klipper clone"):
                builder.build(*TARGETS[0], context=self._context())
        self.assertEqual([], builder.checkouts)

    def test_enospc_command_error_hides_repeated_git_output(self):
        repeated = "unable to write file: No space left on device\n" * 300
        result = CommandProof(("git", "checkout"), 128, "", "", "", repeated)
        error = BuildCommandError("git checkout", result)
        self.assertIn("ran out of disk space", str(error))
        self.assertNotIn("unable to write file", str(error))

    def test_missing_expected_artifact_is_rejected(self):
        contract, variant, target = self._parts(*TARGETS[0])
        builder = _FixtureBuilder(contract, variant, target, create_artifact=False)
        with self.assertRaisesRegex(ArtifactValidationError, "artifact is absent"):
            builder.build(*TARGETS[0], context=self._context())

    def test_wrong_checkout_commit_is_rejected_before_kconfig(self):
        contract, variant, target = self._parts(*TARGETS[0])
        builder = _FixtureBuilder(contract, variant, target, wrong_commit=True)
        with self.assertRaisesRegex(CheckoutCommitMismatch, "does not match validated"):
            builder.build(*TARGETS[0], context=self._context())

    def test_legacy_klipper_tree_is_rejected_for_every_build_path(self):
        legacy = (Path.home() / "klipper").resolve()
        with self.assertRaisesRegex(CheckoutError, "may not use or write"):
            BoardContractKconfigBuilder._reject_legacy_path(
                legacy / "shadow-output", "output_directory"
            )

    def test_declared_symbol_scan_reads_all_kconfig_files(self):
        root = Path(self.staging.name)
        (root / "src" / "stm32").mkdir(parents=True)
        (root / "src" / "Kconfig").write_text("config MACH_STM32\n", encoding="utf-8")
        (root / "src" / "stm32" / "Kconfig").write_text(
            "menuconfig MACH_STM32F103\n", encoding="utf-8"
        )
        self.assertEqual(
            {"CONFIG_MACH_STM32", "CONFIG_MACH_STM32F103"},
            set(collect_declared_kconfig_symbols(root)),
        )


if __name__ == "__main__":
    unittest.main()
