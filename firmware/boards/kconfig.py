"""Experimental, isolated BoardContract Kconfig and firmware builds.

This module is intentionally not called by the normal wizard or firmware
builder.  It turns one explicit BuildTarget into a fresh Klipper ``.config``,
checks the result of ``olddefconfig``, compiles it, and emits immutable build
evidence.  Commands are always argv vectors and never pass through a shell.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import uuid
import zlib
from typing import Any, Callable, Mapping, Optional, Sequence

from firmware.identity import ToolchainIdentity

from .catalog import BoardCatalog, load_default_catalog
from .models import ArtifactFormat, BoardContract, BuildTarget, HardwareVariant, TransportKind
from .resolver import BoardResolver, ResolutionStatus
from .upstream import KlipperSourceContract, load_klipper_source_contract


KconfigScalar = bool | int | str
CommandRunner = Callable[[Sequence[str], Path, Mapping[str, str]], subprocess.CompletedProcess]


class BoardContractBuildError(RuntimeError):
    """Base error for the experimental BoardContract build path."""


class CheckoutError(BoardContractBuildError):
    pass


class CheckoutCommitMismatch(CheckoutError):
    pass


class KconfigError(BoardContractBuildError):
    pass


class UnknownKconfigSymbol(KconfigError):
    pass


class DiscardedKconfigSelection(KconfigError):
    pass


class ResolvedAssertionMismatch(KconfigError):
    pass


class IncompatibleBuildTarget(KconfigError):
    pass


class ArtifactValidationError(BoardContractBuildError):
    pass


class BuildCommandError(BoardContractBuildError):
    def __init__(self, phase: str, result: "CommandProof"):
        detail = result.stderr_tail or result.stdout_tail
        message = f"{phase} failed with exit code {result.returncode}"
        if detail:
            message += f": {detail}"
        super().__init__(message)
        self.phase = phase
        self.result = result


@dataclass(frozen=True)
class CommandProof:
    argv: tuple[str, ...]
    returncode: int
    stdout_sha256: str
    stderr_sha256: str
    stdout_tail: str = ""
    stderr_tail: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True)
class VerificationProof:
    ok: bool
    checked_symbols: tuple[str, ...]
    failures: tuple[str, ...] = ()


@dataclass(frozen=True)
class BuildProof:
    """Immutable proof of one successful BoardContract firmware build."""

    schema: str
    board_id: str
    hardware_variant_id: str
    build_target_id: str
    contract_digest: str
    klipper_commit: str
    requested_config_path: str
    requested_config_sha256: str
    resolved_config_path: str
    resolved_config_sha256: str
    artifact_path: str
    artifact_sha256: str
    artifact_size: int
    olddefconfig: CommandProof
    requested_selections: VerificationProof
    resolved_assertions: VerificationProof
    build: CommandProof
    build_attempts: tuple[CommandProof, ...]
    lto_retry_used: bool
    toolchain: ToolchainIdentity
    requested_flags: tuple[str, ...]
    effective_flags: tuple[str, ...]
    lto_requested: bool
    lto_effective: bool
    fallback_used: bool
    fallback_reason: str
    build_id: str
    firmware_fingerprint: str
    embedded_fingerprint_verified: bool

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.to_mapping(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

    @property
    def digest(self) -> str:
        return _sha256(self.canonical_bytes())


@dataclass(frozen=True)
class BoardContractBuildContext:
    """Constrained tools and paths for an experimental build."""

    output_directory: str
    staging_parent: Optional[str] = None
    source_checkout: Optional[str] = None
    git_command: tuple[str, ...] = ("git",)
    make_command: tuple[str, ...] = ("make",)
    concurrency: Optional[int] = None
    environment_path: Optional[str] = None
    allow_lto_retry: bool = True

    def __post_init__(self) -> None:
        if not self.output_directory:
            raise ValueError("output_directory is required")
        for name, command in (("git_command", self.git_command), ("make_command", self.make_command)):
            if not command or any(not isinstance(item, str) or not item for item in command):
                raise ValueError(f"{name} must be a non-empty argv prefix")
            if any(_contains_shell_syntax(item) for item in command):
                raise ValueError(f"{name} may not contain shell syntax")
        if self.concurrency is not None and self.concurrency < 1:
            raise ValueError("concurrency must be positive")


_NOT_SET_RE = re.compile(r"^# (CONFIG_[A-Za-z0-9_]+) is not set$")
_ASSIGNMENT_RE = re.compile(r"^(CONFIG_[A-Za-z0-9_]+)=(.*)$")
_HEX_RE = re.compile(r"^[+-]?0[xX][0-9a-fA-F]+$")
_INTEGER_RE = re.compile(r"^[+-]?[0-9]+$")
_SHELL_MARKERS = ("&&", "||", ";", "|", ">", "<", "`", "$(", "\r", "\n", "\x00")
_TRANSPORT_PREFIXES = {
    TransportKind.USB: (
        "CONFIG_STM32_USB_", "CONFIG_RPXXXX_USB", "CONFIG_AVR_USB",
        "CONFIG_LPC_USB",
    ),
    TransportKind.UART: (
        "CONFIG_STM32_SERIAL_", "CONFIG_RPXXXX_SERIAL_", "CONFIG_AVR_SERIAL_",
        "CONFIG_LPC_SERIAL_",
    ),
    TransportKind.CAN: (
        "CONFIG_STM32_CANBUS_", "CONFIG_RPXXXX_CANBUS",
        "CONFIG_LPC_MMENU_CANBUS_",
    ),
}
_ALL_TRANSPORT_PREFIXES = tuple(
    prefix for prefixes in _TRANSPORT_PREFIXES.values() for prefix in prefixes
)
_BOOTLOADER_PREFIXES = (
    "CONFIG_STM32_FLASH_START_",
    "CONFIG_RPXXXX_FLASH_START_",
    "CONFIG_LPC_FLASH_START_",
)
_ARTIFACT_SUFFIXES = {
    ArtifactFormat.BIN: ".bin",
    ArtifactFormat.UF2: ".uf2",
    ArtifactFormat.IHEX: ".hex",
}
_COMPILERS = {
    "stm32": "arm-none-eabi-gcc",
    "lpc176x": "arm-none-eabi-gcc",
    "rpxxxx": "arm-none-eabi-gcc",
    "atsam": "arm-none-eabi-gcc",
    "atsamd": "arm-none-eabi-gcc",
    "avr": "avr-gcc",
    "linux": "gcc",
}


def _contains_shell_syntax(value: str) -> bool:
    return any(marker in value for marker in _SHELL_MARKERS)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def artifact_contains_firmware_fingerprint(
    content: bytes,
    firmware_fingerprint: str,
) -> bool:
    """Verify a Klipper identity in either plain or compressed MCU metadata.

    Klipper stores its identify dictionary as a zlib stream in the native
    firmware image.  The version therefore is normally not a plain-text byte
    sequence.  Scanning and decoding candidate zlib streams lets deployment
    revalidate the staged binary itself without trusting a sidecar dictionary.
    """
    expected = firmware_fingerprint.encode("ascii")
    payloads = (content, _decode_uf2_payload(content))
    for payload in payloads:
        if payload is None:
            continue
        if expected in payload:
            # Retain compatibility with deterministic unit fixtures and any
            # target that emits an uncompressed version string.
            return True
        start = 0
        while True:
            offset = payload.find(b"\x78", start)
            if offset < 0:
                break
            try:
                decoded = zlib.decompress(payload[offset:])
            except zlib.error:
                start = offset + 1
                continue
            if expected in decoded:
                try:
                    dictionary = json.loads(decoded.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    start = offset + 1
                    continue
                if firmware_fingerprint in str(dictionary.get("version", "")):
                    return True
            start = offset + 1
    return False


def _decode_uf2_payload(content: bytes) -> Optional[bytes]:
    """Reconstruct the contiguous binary payload of a validated UF2 image."""
    if len(content) < 512 or len(content) % 512:
        return None
    chunks: list[tuple[int, bytes]] = []
    declared_blocks: Optional[int] = None
    for offset in range(0, len(content), 512):
        block = content[offset:offset + 512]
        magic0, magic1 = struct.unpack_from("<II", block, 0)
        end_magic = struct.unpack_from("<I", block, 508)[0]
        if (magic0, magic1, end_magic) != (
            0x0A324655, 0x9E5D5157, 0x0AB16F30,
        ):
            return None
        target_address, payload_size, block_number, block_count = struct.unpack_from(
            "<IIII", block, 12
        )
        if payload_size < 1 or payload_size > 476:
            return None
        if declared_blocks is None:
            declared_blocks = block_count
        if block_count != declared_blocks or block_number >= block_count:
            return None
        chunks.append((target_address, block[32:32 + payload_size]))
    if declared_blocks != len(chunks):
        return None
    chunks.sort(key=lambda item: item[0])
    base = chunks[0][0]
    end = max(address + len(chunk) for address, chunk in chunks)
    if end - base > 32 * 1024 * 1024:
        return None
    payload = bytearray(b"\x00" * (end - base))
    previous_end = base
    for address, chunk in chunks:
        if address < previous_end:
            return None
        payload[address - base:address - base + len(chunk)] = chunk
        previous_end = address + len(chunk)
    return bytes(payload)


def _normalize_lf(content: bytes | str) -> bytes:
    if isinstance(content, bytes):
        text = content.decode("utf-8")
    else:
        text = content
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def serialize_requested_config(values: Mapping[str, KconfigScalar]) -> bytes:
    """Serialize a deterministic seed ``.config`` accepted by Kconfig."""
    lines: list[str] = []
    for symbol in sorted(values):
        if not re.fullmatch(r"CONFIG_[A-Za-z0-9_]+", symbol):
            raise UnknownKconfigSymbol(f"invalid Kconfig symbol name: {symbol!r}")
        value = values[symbol]
        if value is True:
            lines.append(f"{symbol}=y")
        elif value is False:
            lines.append(f"# {symbol} is not set")
        elif isinstance(value, int) and not isinstance(value, bool):
            lines.append(f"{symbol}={value}")
        elif isinstance(value, str):
            if "\x00" in value or "\r" in value or "\n" in value:
                raise KconfigError(f"{symbol} contains unsupported control characters")
            lines.append(f"{symbol}={json.dumps(value, ensure_ascii=False)}")
        else:
            raise KconfigError(f"{symbol} has unsupported value {value!r}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def parse_kconfig(content: bytes | str) -> dict[str, KconfigScalar]:
    """Parse bool, integer, hex, and string values from a Klipper ``.config``."""
    text = _normalize_lf(content).decode("utf-8")
    parsed: dict[str, KconfigScalar] = {}
    for line in text.splitlines():
        not_set = _NOT_SET_RE.fullmatch(line)
        if not_set:
            parsed[not_set.group(1)] = False
            continue
        assignment = _ASSIGNMENT_RE.fullmatch(line)
        if not assignment:
            continue
        symbol, raw = assignment.groups()
        if raw == "y":
            value: KconfigScalar = True
        elif raw == "n":
            value = False
        elif raw.startswith('"') and raw.endswith('"'):
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise KconfigError(f"invalid quoted value for {symbol}") from exc
        elif _HEX_RE.fullmatch(raw):
            value = int(raw, 16)
        elif _INTEGER_RE.fullmatch(raw):
            value = int(raw, 10)
        else:
            value = raw
        parsed[symbol] = value
    return parsed


def _normalize_expected(value: KconfigScalar) -> KconfigScalar:
    if isinstance(value, str) and _HEX_RE.fullmatch(value):
        return int(value, 16)
    return value


def verify_requested_selections(
    requested: Mapping[str, KconfigScalar],
    resolved: Mapping[str, KconfigScalar],
) -> VerificationProof:
    discarded: list[str] = []
    for symbol, expected in sorted(requested.items()):
        if symbol not in resolved:
            discarded.append(f"{symbol}: requested {expected!r}, removed by olddefconfig")
            continue
        actual = resolved[symbol]
        if _normalize_expected(expected) != actual:
            discarded.append(
                f"{symbol}: requested {expected!r}, resolved {actual!r}"
            )
    if discarded:
        raise DiscardedKconfigSelection("; ".join(discarded))
    return VerificationProof(True, tuple(sorted(requested)))


def collect_declared_kconfig_symbols(checkout: Path | str) -> frozenset[str]:
    root = Path(checkout)
    declared: set[str] = set()
    pattern = re.compile(r"^\s*(?:menu)?config\s+([A-Za-z0-9_]+)\s*$", re.MULTILINE)
    for path in sorted((root / "src").rglob("Kconfig")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise KconfigError(f"cannot read Kconfig source {path}: {exc}") from exc
        declared.update("CONFIG_" + item for item in pattern.findall(text))
    if not declared:
        raise KconfigError("checkout contains no readable Klipper Kconfig symbols")
    return frozenset(declared)


def verify_declared_symbols(
    values: Mapping[str, KconfigScalar], declared: frozenset[str]
) -> None:
    missing = sorted(set(values) - declared)
    if missing:
        raise UnknownKconfigSymbol("symbols not declared by Klipper: " + ", ".join(missing))


def verify_resolved_assertions(
    assertions: Mapping[str, KconfigScalar],
    resolved: Mapping[str, KconfigScalar],
) -> VerificationProof:
    failures: list[str] = []
    for symbol, expected in sorted(assertions.items()):
        actual = resolved.get(symbol, None)
        if symbol not in resolved or _normalize_expected(expected) != actual:
            failures.append(
                f"{symbol}: expected {expected!r}, resolved {actual!r}"
            )
    if failures:
        raise ResolvedAssertionMismatch("; ".join(failures))
    return VerificationProof(True, tuple(sorted(assertions)))


def validate_target_contract(variant: HardwareVariant, target: BuildTarget) -> None:
    """Reject contradictions that Kconfig might otherwise silently normalize."""
    requested = target.requested_kconfig
    if requested.get(variant.processor.architecture_kconfig) is not True:
        raise IncompatibleBuildTarget("target does not select its declared architecture")
    if requested.get(variant.processor.model_kconfig) is not True:
        raise IncompatibleBuildTarget("target does not select its declared processor")
    selected_processors = {
        symbol for symbol, value in requested.items()
        if value is True and symbol.startswith("CONFIG_MACH_")
    }
    expected_processors = {
        variant.processor.architecture_kconfig,
        variant.processor.model_kconfig,
    }
    if selected_processors != expected_processors:
        raise IncompatibleBuildTarget(
            "target selects processors outside its declared architecture/model: "
            f"{sorted(selected_processors - expected_processors)}"
        )
    if requested.get("CONFIG_LOW_LEVEL_OPTIONS") is not target.low_level.enabled:
        raise IncompatibleBuildTarget("target low-level selection is inconsistent")
    transport_symbols = tuple(target.transport.selection)
    prefixes = _TRANSPORT_PREFIXES[target.transport.kind]
    if not transport_symbols or any(
        not symbol.startswith(prefixes) for symbol in transport_symbols
    ):
        raise IncompatibleBuildTarget(
            f"{target.transport.kind.value} target has incompatible transport selectors"
        )
    selected_transports = {
        symbol for symbol, value in requested.items()
        if value is True and symbol.startswith(_ALL_TRANSPORT_PREFIXES)
    }
    if selected_transports != set(transport_symbols):
        raise IncompatibleBuildTarget(
            "target requests incompatible or multiple communication interfaces"
        )
    selected_bootloaders = {
        symbol for symbol, value in requested.items()
        if value is True and symbol.startswith(_BOOTLOADER_PREFIXES)
    }
    declared_bootloaders = {
        symbol for symbol, value in variant.bootloader.selection.items() if value is True
    }
    if selected_bootloaders != declared_bootloaders:
        raise IncompatibleBuildTarget(
            "target requests incompatible or multiple bootloader/flash starts"
        )
    for expected in (
        variant.bootloader.selection,
        variant.clock.selection,
        target.transport.selection,
    ):
        for symbol, value in expected.items():
            if requested.get(symbol) != value:
                raise IncompatibleBuildTarget(
                    f"target does not request declared selector {symbol}={value!r}"
                )


def verify_checkout_commit(checkout: Path | str, expected_commit: str) -> str:
    """Read and validate HEAD without mutating the checkout."""
    path = Path(checkout).resolve()
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise CheckoutError(f"cannot read checkout commit: {result.stderr.strip()}")
    observed = result.stdout.strip().lower()
    if observed != expected_commit.lower():
        raise CheckoutCommitMismatch(
            f"checkout commit {observed} does not match validated {expected_commit}"
        )
    return observed


def _default_command_runner(
    argv: Sequence[str], cwd: Path, environment: Mapping[str, str]
) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(argv),
        cwd=cwd,
        env=dict(environment),
        check=False,
        capture_output=True,
        text=True,
    )


class BoardContractKconfigBuilder:
    """Build one exact target in a fresh, disposable Klipper checkout."""

    def __init__(
        self,
        *,
        catalog: Optional[BoardCatalog] = None,
        source_contract: Optional[KlipperSourceContract] = None,
        command_runner: Optional[CommandRunner] = None,
    ):
        self.catalog = catalog or load_default_catalog()
        self.source_contract = source_contract or load_klipper_source_contract()
        self.command_runner = command_runner or _default_command_runner

    def build(
        self,
        board_alias: str,
        hardware_variant_id: str,
        build_target_id: str,
        *,
        context: BoardContractBuildContext,
    ) -> BuildProof:
        resolution = BoardResolver(self.catalog).resolve(
            board_alias,
            hardware_variant_id=hardware_variant_id,
            build_target_id=build_target_id,
        )
        if resolution.status is not ResolutionStatus.RESOLVED:
            raise IncompatibleBuildTarget(
                f"target resolution failed: {resolution.status.value} {resolution.candidates}"
            )
        contract = resolution.contract
        variant = resolution.variant
        target = resolution.target
        assert contract is not None and variant is not None and target is not None
        self._validate_pinned_source(contract)
        validate_target_contract(variant, target)

        output_root = Path(context.output_directory).expanduser().resolve()
        self._reject_legacy_path(output_root, "output_directory")
        output_root.mkdir(parents=True, exist_ok=True)
        staging_parent = None
        if context.staging_parent:
            staging_parent = Path(context.staging_parent).expanduser().resolve()
            self._reject_legacy_path(staging_parent, "staging_parent")
            staging_parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(
            prefix="kace-board-contract-", dir=str(staging_parent) if staging_parent else None
        ) as temporary:
            staging_root = Path(temporary).resolve()
            checkout = staging_root / "klipper"
            self._prepare_checkout(checkout, contract, context)
            self._reject_legacy_checkout(checkout)
            commit = self._read_checkout_commit(checkout, context)
            if commit != contract.upstream.validated_commit:
                raise CheckoutCommitMismatch(
                    f"checkout commit {commit} does not match validated "
                    f"{contract.upstream.validated_commit}"
                )
            return self._build_in_checkout(
                checkout, contract, variant, target, context, output_root, commit
            )

    def _validate_pinned_source(self, contract: BoardContract) -> None:
        if contract.upstream.validated_commit != self.source_contract.validated_commit:
            raise CheckoutCommitMismatch("board contract and global Klipper commit differ")
        if contract.upstream.repository != self.source_contract.repository:
            raise CheckoutError("board contract and global Klipper repositories differ")

    def _prepare_checkout(
        self,
        checkout: Path,
        contract: BoardContract,
        context: BoardContractBuildContext,
    ) -> None:
        source = context.source_checkout or contract.upstream.repository
        if context.source_checkout:
            self._reject_legacy_path(
                Path(context.source_checkout).expanduser().resolve(), "source_checkout"
            )
        environment = self._environment(context)
        clone = self._run(
            (*context.git_command, "clone", "--no-checkout", "--no-hardlinks", source, str(checkout)),
            checkout.parent,
            environment,
        )
        if not clone.ok:
            raise BuildCommandError("git clone", clone)
        checkout_result = self._run(
            (*context.git_command, "checkout", "--detach", contract.upstream.validated_commit),
            checkout,
            environment,
        )
        if not checkout_result.ok:
            raise BuildCommandError("git checkout", checkout_result)

    def _read_checkout_commit(
        self, checkout: Path, context: BoardContractBuildContext
    ) -> str:
        result, completed = self._execute(
            (*context.git_command, "rev-parse", "HEAD"),
            checkout,
            self._environment(context),
        )
        if not result.ok:
            raise BuildCommandError("git rev-parse", result)
        commit = str(completed.stdout or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise CheckoutError(f"git returned invalid commit identity: {commit!r}")
        return commit

    def _reject_legacy_checkout(self, checkout: Path) -> None:
        self._reject_legacy_path(checkout, "isolated checkout")

    @staticmethod
    def _reject_legacy_path(path: Path, field_name: str) -> None:
        legacy = (Path.home() / "klipper").resolve()
        try:
            path.resolve().relative_to(legacy)
        except ValueError:
            return
        raise CheckoutError(f"{field_name} may not use or write under ~/klipper")

    def _build_in_checkout(
        self,
        checkout: Path,
        contract: BoardContract,
        variant: HardwareVariant,
        target: BuildTarget,
        context: BoardContractBuildContext,
        output_root: Path,
        commit: str,
    ) -> BuildProof:
        environment = self._environment(context)
        requested_bytes = serialize_requested_config(target.requested_kconfig)
        declared_symbols = collect_declared_kconfig_symbols(checkout)
        verify_declared_symbols(target.requested_kconfig, declared_symbols)
        verify_declared_symbols(target.resolved_assertions, declared_symbols)
        config_path = checkout / ".config"
        config_path.write_bytes(requested_bytes)

        olddefconfig = self._run(
            (*context.make_command, "olddefconfig"), checkout, environment
        )
        if not olddefconfig.ok:
            raise BuildCommandError("olddefconfig", olddefconfig)
        if not config_path.is_file():
            raise KconfigError("olddefconfig removed .config")
        resolved_bytes = _normalize_lf(config_path.read_bytes())
        resolved = parse_kconfig(resolved_bytes)
        selection_proof = verify_requested_selections(target.requested_kconfig, resolved)
        assertion_proof = verify_resolved_assertions(target.resolved_assertions, resolved)

        toolchain = self._identify_toolchain(checkout, variant, context, environment)
        wrapper_directory, flags_log = self._prepare_compiler_audit(checkout)
        build_environment = dict(environment)
        build_environment["PATH"] = (
            str(wrapper_directory) + os.pathsep + build_environment.get("PATH", "")
        )
        build_environment["KACE_CC_FLAGS_LOG"] = str(flags_log)
        build_environment["KACE_CC_DISABLE_LTO"] = "0"

        # The identity later observed through Moonraker must be compiled into
        # the firmware.  Choosing it after the build would produce an identity
        # that the MCU can never report.
        build_id = uuid.uuid4().hex
        firmware_fingerprint = f"kace-b1-{build_id}"
        self._inject_firmware_fingerprint(checkout, firmware_fingerprint)
        build_argv: tuple[str, ...] = context.make_command + (
            f"KLIPPER_VERSION={firmware_fingerprint}",
        )
        if context.concurrency and context.concurrency > 1:
            build_argv += (f"-j{context.concurrency}",)
        build_attempts: list[CommandProof] = []
        build = self._run(build_argv, checkout, build_environment)
        build_attempts.append(build)
        lto_retry_used = False
        fallback_reason = ""
        if not build.ok and context.allow_lto_retry and self._is_lto_failure(build):
            lto_retry_used = True
            fallback_reason = "LTO linker failure: compiler ltrans objects were unavailable"
            retry_environment = dict(build_environment)
            retry_environment["KACE_CC_DISABLE_LTO"] = "1"
            flags_log.write_bytes(b"")
            clean = self._run((*context.make_command, "clean"), checkout, retry_environment)
            if not clean.ok:
                raise BuildCommandError("LTO retry clean", clean)
            build = self._run(build_argv, checkout, retry_environment)
            build_attempts.append(build)
        if not build.ok:
            raise BuildCommandError("build", build)
        requested_flags, effective_flags = self._read_compiler_flags(flags_log)
        lto_requested = any(self._is_lto_flag(item) for item in requested_flags)
        lto_effective = any(self._is_lto_flag(item) for item in effective_flags)

        native_path = (checkout / target.artifact.native_path).resolve()
        try:
            native_path.relative_to(checkout)
        except ValueError as exc:
            raise ArtifactValidationError("artifact path escapes checkout") from exc
        if native_path.name != target.artifact.native_filename:
            raise ArtifactValidationError("ArtifactPolicy native path/name disagree")
        expected_suffix = _ARTIFACT_SUFFIXES[target.artifact.format]
        if not native_path.name.lower().endswith(expected_suffix):
            raise ArtifactValidationError(
                f"artifact extension does not match {target.artifact.format.value}"
            )
        if not native_path.is_file():
            raise ArtifactValidationError(
                f"expected native artifact is absent: {target.artifact.native_path}"
            )
        artifact_bytes = native_path.read_bytes()
        if not artifact_bytes:
            raise ArtifactValidationError("native artifact is empty")
        if not artifact_contains_firmware_fingerprint(
            artifact_bytes, firmware_fingerprint
        ):
            raise ArtifactValidationError(
                "native artifact identify metadata does not contain the requested fingerprint"
            )

        evidence_dir = Path(tempfile.mkdtemp(
            prefix=(
                f"{contract.board_id}-{variant.id}-{target.id}-"
                f"{contract.contract_digest[:12]}-"
            ),
            dir=output_root,
        ))
        requested_evidence = evidence_dir / "requested.config"
        resolved_evidence = evidence_dir / "resolved.config"
        artifact_evidence = evidence_dir / target.artifact.native_filename
        requested_evidence.write_bytes(requested_bytes)
        resolved_evidence.write_bytes(resolved_bytes)
        shutil.copyfile(native_path, artifact_evidence)

        proof = BuildProof(
            schema="kace-board-build-proof/v3",
            board_id=contract.board_id,
            hardware_variant_id=variant.id,
            build_target_id=target.id,
            contract_digest=contract.contract_digest,
            klipper_commit=commit,
            requested_config_path=str(requested_evidence),
            requested_config_sha256=_sha256(requested_bytes),
            resolved_config_path=str(resolved_evidence),
            resolved_config_sha256=_sha256(resolved_bytes),
            artifact_path=str(artifact_evidence),
            artifact_sha256=_sha256(artifact_bytes),
            artifact_size=len(artifact_bytes),
            olddefconfig=olddefconfig,
            requested_selections=selection_proof,
            resolved_assertions=assertion_proof,
            build=build,
            build_attempts=tuple(build_attempts),
            lto_retry_used=lto_retry_used,
            toolchain=toolchain,
            requested_flags=requested_flags,
            effective_flags=effective_flags,
            lto_requested=lto_requested,
            lto_effective=lto_effective,
            fallback_used=lto_retry_used,
            fallback_reason=fallback_reason,
            build_id=build_id,
            firmware_fingerprint=firmware_fingerprint,
            embedded_fingerprint_verified=True,
        )
        proof_path = evidence_dir / "build-proof.json"
        temporary_proof = evidence_dir / ".build-proof.json.tmp"
        temporary_proof.write_bytes(
            json.dumps(proof.to_mapping(), ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
            + b"\n"
        )
        os.replace(temporary_proof, proof_path)
        return proof

    @staticmethod
    def _inject_firmware_fingerprint(checkout: Path, fingerprint: str) -> None:
        """Request a version suffix through Klipper's own buildcommands API.

        The validated Klipper commit exposes ``buildcommands.py --extra`` but
        its Makefile has no public variable for that option.  The isolated
        checkout is therefore patched at one exact reviewed line.  Any drift
        in that line fails closed instead of applying a broad text rewrite.
        """
        if not re.fullmatch(r"kace-b1-[0-9a-f]{32}", fingerprint):
            raise ArtifactValidationError("invalid firmware fingerprint format")
        makefile = checkout / "Makefile"
        if not makefile.is_file():
            raise ArtifactValidationError("Klipper Makefile is absent")
        content = makefile.read_text(encoding="utf-8")
        needle = "$(PYTHON) ./scripts/buildcommands.py -d $(OUT)klipper.dict"
        replacement = (
            "$(PYTHON) ./scripts/buildcommands.py "
            f"--extra=-{fingerprint} -d $(OUT)klipper.dict"
        )
        if content.count(needle) != 1:
            raise ArtifactValidationError(
                "validated Klipper buildcommands invocation drifted"
            )
        makefile.write_text(content.replace(needle, replacement), encoding="utf-8")

    def _environment(self, context: BoardContractBuildContext) -> dict[str, str]:
        environment = dict(os.environ)
        environment.pop("KCONFIG_CONFIG", None)
        if context.environment_path:
            environment["PATH"] = context.environment_path
        environment["LC_ALL"] = "C"
        return environment

    @staticmethod
    def _is_lto_failure(result: CommandProof) -> bool:
        text = (result.stdout_tail + "\n" + result.stderr_tail).lower()
        return any(marker in text for marker in ("ltrans", "lto-wrapper", "cannot find /tmp/cc"))

    @staticmethod
    def _prepare_compiler_audit(checkout: Path) -> tuple[Path, Path]:
        source = (
            Path(__file__).resolve().parents[2]
            / "scripts"
            / "board_contract_cc_wrapper.py"
        )
        if not source.is_file():
            raise BoardContractBuildError(f"trusted compiler wrapper is absent: {source}")
        wrapper_directory = checkout.parent / "trusted-board-contract-wrappers"
        wrapper_directory.mkdir(mode=0o700)
        for compiler in sorted(set(_COMPILERS.values())):
            destination = wrapper_directory / compiler
            shutil.copyfile(source, destination)
            destination.chmod(0o700)
        flags_log = checkout.parent / "compiler-flags.jsonl"
        flags_log.write_bytes(b"")
        return wrapper_directory, flags_log

    def _identify_toolchain(
        self,
        checkout: Path,
        variant: HardwareVariant,
        context: BoardContractBuildContext,
        environment: Mapping[str, str],
    ) -> ToolchainIdentity:
        compiler = _COMPILERS.get(variant.processor.architecture)
        if compiler is None:
            raise BoardContractBuildError(
                f"no compiler identity mapping for {variant.processor.architecture}"
            )
        make_proof, make_result = self._execute(
            (*context.make_command, "--version"), checkout, environment
        )
        if not make_proof.ok:
            raise BuildCommandError("make toolchain identity", make_proof)
        compiler_proof, compiler_result = self._execute(
            (compiler, "--version"), checkout, environment
        )
        if not compiler_proof.ok:
            raise BuildCommandError("compiler toolchain identity", compiler_proof)
        make_version = self._first_output_line(make_result)
        compiler_version = self._first_output_line(compiler_result)
        if not make_version or not compiler_version:
            raise BoardContractBuildError("toolchain identity returned an empty version")
        return ToolchainIdentity(
            make_command=" ".join(context.make_command),
            make_version=make_version,
            compiler=compiler,
            compiler_version=compiler_version,
        )

    @staticmethod
    def _first_output_line(result: subprocess.CompletedProcess) -> str:
        output = str(result.stdout or result.stderr or "").strip().splitlines()
        return output[0].strip() if output else ""

    @staticmethod
    def _is_lto_flag(argument: str) -> bool:
        return (
            argument.startswith("-flto")
            or argument in {"-fwhole-program", "-fno-use-linker-plugin"}
        )

    @classmethod
    def _read_compiler_flags(cls, path: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
        requested: set[str] = set()
        effective: set[str] = set()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise BoardContractBuildError(f"cannot read compiler flag audit: {exc}") from exc
        for line_number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BoardContractBuildError(
                    f"invalid compiler flag audit at line {line_number}"
                ) from exc
            for destination, key in ((requested, "requested"), (effective, "effective")):
                values = entry.get(key)
                if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
                    raise BoardContractBuildError("compiler flag audit has an invalid argv")
                destination.update(item for item in values if item.startswith("-"))
        return tuple(sorted(requested)), tuple(sorted(effective))

    def _run(
        self,
        argv: Sequence[str],
        cwd: Path,
        environment: Mapping[str, str],
    ) -> CommandProof:
        proof, _completed = self._execute(argv, cwd, environment)
        return proof

    def _execute(
        self,
        argv: Sequence[str],
        cwd: Path,
        environment: Mapping[str, str],
    ) -> tuple[CommandProof, subprocess.CompletedProcess]:
        command = tuple(str(item) for item in argv)
        if any(_contains_shell_syntax(item) for item in command):
            raise BoardContractBuildError("command argv contains shell syntax")
        completed = self.command_runner(command, cwd, environment)
        stdout = str(completed.stdout or "").encode("utf-8", errors="replace")
        stderr = str(completed.stderr or "").encode("utf-8", errors="replace")
        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")
        proof = CommandProof(
            command,
            int(completed.returncode),
            _sha256(stdout),
            _sha256(stderr),
            stdout_text[-4000:],
            stderr_text[-4000:],
        )
        return proof, completed


def build_board_contract_shadow(
    board_alias: str,
    hardware_variant_id: str,
    build_target_id: str,
    *,
    context: BoardContractBuildContext,
    catalog: Optional[BoardCatalog] = None,
) -> BuildProof:
    """Explicit experimental entry point; normal runtime never calls it."""
    return BoardContractKconfigBuilder(catalog=catalog).build(
        board_alias,
        hardware_variant_id,
        build_target_id,
        context=context,
    )
