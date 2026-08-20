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
import time
from types import SimpleNamespace
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
    recommended_build_concurrency,
)
from core.workspace import WorkspaceSpaceError, WorkspaceStorageError


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

    def __init__(
        self,
        contract,
        variant,
        target,
        *,
        create_artifact=True,
        wrong_commit=False,
        lto_fail_first=False,
    ):
        self.fixture_contract = contract
        self.fixture_variant = variant
        self.fixture_target = target
        self.create_artifact = create_artifact
        self.wrong_commit = wrong_commit
        self.lto_fail_first = lto_fail_first
        self.build_calls = 0
        self.commands = []
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

    def _verify_checkout_clean(self, checkout, context):
        return None

    def _command(self, argv, cwd, environment):
        self.commands.append(tuple(argv))
        if "olddefconfig" in argv:
            requested = parse_kconfig((cwd / ".config").read_bytes())
            requested.update(self.fixture_target.resolved_assertions)
            (cwd / ".config").write_bytes(_resolved_config(requested))
        elif (
            argv and Path(argv[0]).name == "make"
            and any(item.startswith("KLIPPER_VERSION=") for item in argv)
        ):
            self.build_calls += 1
            if self.lto_fail_first and self.build_calls == 1:
                return subprocess.CompletedProcess(
                    argv, 1, stdout="", stderr="lto-wrapper failed for ltrans object"
                )
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


class BuildConcurrencyTests(unittest.TestCase):
    def test_raspberry_pi_3_uses_two_jobs(self):
        self.assertEqual(
            2,
            recommended_build_concurrency(
                cpu_count=4,
                model="Raspberry Pi 3 Model B Plus Rev 1.3",
                memory_bytes=1024 ** 3,
            ),
        )

    def test_other_hosts_are_bounded_by_cpu_memory_and_global_cap(self):
        self.assertEqual(
            3,
            recommended_build_concurrency(
                cpu_count=12,
                model="Generic Linux host",
                memory_bytes=3 * 512 * 1024 ** 2,
            ),
        )
        self.assertEqual(
            1,
            recommended_build_concurrency(
                cpu_count=8,
                model="Generic Linux host",
                memory_bytes=256 * 1024 ** 2,
            ),
        )


class ProgressReportingTests(unittest.TestCase):
    def test_long_phase_emits_elapsed_heartbeats_without_command_output(self):
        messages = []
        context = BoardContractBuildContext(
            output_directory="unused",
            progress_reporter=messages.append,
            progress_interval_seconds=0.01,
        )
        builder = BoardContractKconfigBuilder()

        with builder._phase("Compilando firmware", context):
            time.sleep(0.035)

        self.assertTrue(any("en curso" in message for message in messages))
        self.assertTrue(
            messages[-1].startswith("[OK] Compilando firmware completado en")
        )


class PersistentSourceCacheTests(unittest.TestCase):
    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("git is required for source-cache tests")
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self._git("init", "--quiet", cwd=self.source)
        self._git("config", "user.email", "cache-test@example.invalid", cwd=self.source)
        self._git("config", "user.name", "KACE Cache Test", cwd=self.source)
        (self.source / "Makefile").write_text("validated source\n", encoding="utf-8")
        self._git("add", "Makefile", cwd=self.source)
        self._git("commit", "--quiet", "-m", "validated source", cwd=self.source)
        self.commit = self._git("rev-parse", "HEAD", cwd=self.source).stdout.strip()
        self.repository = "https://example.invalid/Klipper3d/klipper.git"
        self.contract = SimpleNamespace(
            upstream=SimpleNamespace(
                repository=self.repository,
                validated_commit=self.commit,
            )
        )
        self.cache_home = self.root / "cache-home"
        self.output = self.root / "output"
        self.output.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def _git(*argv, cwd):
        return subprocess.run(
            ("git", *argv),
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )

    def _context(self, reporter=None):
        return BoardContractBuildContext(
            output_directory=str(self.output),
            source_checkout=str(self.source),
            progress_reporter=reporter,
            progress_interval_seconds=0,
        )

    def _prepare(self, name, *, reporter=None):
        checkout = self.root / name
        builder = BoardContractKconfigBuilder()
        with patch.dict(os.environ, {"KACE_CACHE_HOME": str(self.cache_home)}):
            builder._prepare_checkout(
                checkout, self.contract, self._context(reporter=reporter)
            )
            cache = builder._source_cache_path(self.repository)
        return builder, checkout, cache

    def test_warm_cache_reuses_exact_commit_without_source_or_build_outputs(self):
        _builder, first, cache = self._prepare("checkout-1")
        self.assertTrue(cache.is_dir())
        (first / ".config").write_text("CONFIG_STALE=y\n", encoding="utf-8")
        (first / "out").mkdir()
        (first / "out" / "klipper.bin").write_bytes(b"stale")
        os.replace(self.source, self.root / "source-unavailable")

        _builder, second, reused_cache = self._prepare("checkout-2")

        self.assertEqual(cache, reused_cache)
        self.assertEqual(
            self.commit,
            self._git("rev-parse", "HEAD", cwd=second).stdout.strip(),
        )
        self.assertEqual(
            "", self._git("status", "--porcelain", cwd=second).stdout.strip()
        )
        self.assertFalse((second / ".config").exists())
        self.assertFalse((second / "out").exists())
        self.assertFalse((cache / ".config").exists())
        self.assertFalse((cache / "out").exists())

    def test_corrupt_cache_is_rebuilt_automatically(self):
        _builder, _first, cache = self._prepare("checkout-1")
        shutil.rmtree(cache / "objects")
        messages = []

        _builder, checkout, rebuilt_cache = self._prepare(
            "checkout-2", reporter=messages.append
        )

        self.assertEqual(cache, rebuilt_cache)
        self.assertEqual(
            self.commit,
            self._git("rev-parse", "HEAD", cwd=checkout).stdout.strip(),
        )
        self.assertTrue(any("reconstruyendo" in message for message in messages))

    def test_dirty_isolated_checkout_is_rejected_before_configuration(self):
        builder, checkout, _cache = self._prepare("checkout-1")
        (checkout / ".config").write_text("CONFIG_UNTRUSTED=y\n", encoding="utf-8")

        with self.assertRaisesRegex(CheckoutError, "dirty before configuration"):
            builder._verify_checkout_clean(checkout, self._context())

    def test_missing_validated_commit_is_rejected_without_replacing_good_cache(self):
        builder, _checkout, cache = self._prepare("checkout-1")
        wrong_contract = SimpleNamespace(
            upstream=SimpleNamespace(
                repository=self.repository,
                validated_commit="0" * 40,
            )
        )
        with patch.dict(os.environ, {"KACE_CACHE_HOME": str(self.cache_home)}):
            with self.assertRaisesRegex(CheckoutError, "validated commit"):
                builder._prepare_checkout(
                    self.root / "checkout-wrong", wrong_contract, self._context()
                )
        self.assertTrue(cache.is_dir())
        self.assertEqual(
            self.commit,
            self._git(
                "--git-dir", str(cache), "rev-parse", self.commit, cwd=self.root
            ).stdout.strip(),
        )


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
                self.assertTrue(
                    all(
                        checkout != Path.home() / "klipper"
                        for checkout in builder.checkouts
                    )
                )

    def test_automatic_parallelism_is_recorded_in_the_build_command(self):
        contract, variant, target = self._parts(*TARGETS[0])
        builder = _FixtureBuilder(contract, variant, target)
        with patch(
            "firmware.boards.kconfig.recommended_build_concurrency",
            return_value=2,
        ):
            proof = builder.build(
                *TARGETS[0],
                context=BoardContractBuildContext(
                    output_directory=self.output.name,
                    staging_parent=self.staging.name,
                    progress_interval_seconds=0,
                ),
            )
        self.assertIn("-j2", proof.build.argv)

    def test_explicit_parallelism_overrides_host_detection(self):
        contract, variant, target = self._parts(*TARGETS[0])
        builder = _FixtureBuilder(contract, variant, target)
        with patch(
            "firmware.boards.kconfig.recommended_build_concurrency",
            return_value=4,
        ) as detector:
            proof = builder.build(
                *TARGETS[0],
                context=BoardContractBuildContext(
                    output_directory=self.output.name,
                    staging_parent=self.staging.name,
                    concurrency=1,
                    progress_interval_seconds=0,
                ),
            )
        detector.assert_not_called()
        self.assertNotIn("-j4", proof.build.argv)

    def test_progress_reports_all_phases_durations_and_lto_retry(self):
        contract, variant, target = self._parts(*TARGETS[0])
        builder = _FixtureBuilder(
            contract, variant, target, lto_fail_first=True
        )
        events = []
        fixture_runner = builder.command_runner

        def traced_runner(argv, cwd, environment):
            events.append(("command", tuple(argv)))
            return fixture_runner(argv, cwd, environment)

        builder.command_runner = traced_runner

        proof = builder.build(
            *TARGETS[0],
            context=BoardContractBuildContext(
                output_directory=self.output.name,
                staging_parent=self.staging.name,
                concurrency=2,
                progress_reporter=lambda message: events.append(("report", message)),
                progress_interval_seconds=0,
            ),
        )
        messages = [value for kind, value in events if kind == "report"]

        self.assertTrue(proof.lto_retry_used)
        self.assertEqual(2, len(proof.build_attempts))
        for phase in (
            "Preparando Klipper",
            "Configurando firmware",
            "Compilando firmware",
            "Verificando firmware",
        ):
            self.assertTrue(any(message == f"[....] {phase}..." for message in messages))
            self.assertTrue(
                any(
                    message.startswith(f"[OK] {phase} completado en ")
                    for message in messages
                )
            )
        self.assertTrue(
            any("reintentará explícitamente sin LTO" in message for message in messages)
        )
        notice_index = next(
            index
            for index, event in enumerate(events)
            if event[0] == "report" and "sin LTO" in event[1]
        )
        clean_index = next(
            index
            for index, event in enumerate(events)
            if event[0] == "command" and "clean" in event[1]
        )
        self.assertLess(notice_index, clean_index)

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

    def test_tmpfs_staging_parent_is_rejected_before_clone(self):
        contract, variant, target = self._parts(*TARGETS[0])
        builder = _FixtureBuilder(contract, variant, target)
        with patch("core.workspace._filesystem_type", return_value="tmpfs"):
            with self.assertRaisesRegex(WorkspaceStorageError, "volatile tmpfs"):
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
