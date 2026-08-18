"""Typed and strictly validated board-contract domain model.

The YAML documents are declarative data.  In particular, flash commands select
an allow-listed backend and provide an argv vector; they can never contain a
shell program or a shell command string.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping, Optional


class BoardContractError(ValueError):
    pass


class SupportStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    BUILD_VERIFIED = "BUILD_VERIFIED"
    DEPLOYMENT_VERIFIED = "DEPLOYMENT_VERIFIED"
    RUNTIME_SUPPORTED = "RUNTIME_SUPPORTED"
    CONFIG_ONLY = "CONFIG_ONLY"
    BLOCKED = "BLOCKED"


class TransportKind(str, Enum):
    USB = "USB"
    UART = "UART"
    CAN = "CAN"


class ArtifactFormat(str, Enum):
    BIN = "BIN"
    UF2 = "UF2"
    IHEX = "IHEX"


class FlashStrategy(str, Enum):
    PREPARE_ONLY = "PREPARE_ONLY"
    SD_CARD = "SD_CARD"
    AVRDUDE = "AVRDUDE"
    DFU_UTIL = "DFU_UTIL"
    MAKE_FLASH = "MAKE_FLASH"
    RAW_ADDRESS = "RAW_ADDRESS"
    RP2040_BOOTSEL = "RP2040_BOOTSEL"


class WarningSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    BLOCKING = "BLOCKING"


_ID_RE = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_KCONFIG_RE = re.compile(r"^CONFIG_[A-Za-z0-9_]+$")
_PROCESSOR_RE = re.compile(
    r"^(?:STM32[A-Z0-9]+|LPC[0-9]+|RP[0-9]+|"
    r"ATMEGA[A-Z0-9]+|AT90USB[A-Z0-9]+|SAM[A-Z0-9]+|SAME[A-Z0-9]+)$",
    re.IGNORECASE,
)
_ARCHITECTURES = {"stm32", "lpc176x", "rpxxxx", "avr", "atsam", "atsamd", "linux"}
_ALIAS_META = set("*?[](){}+|\\^$")
_SHELL_MARKERS = ("&&", "||", ";", "|", ">", "<", "`", "$(", "\r", "\n", "\x00")
_ALLOWED_BACKENDS = {"avrdude", "dfu-util", "make-flash", "raw-flash"}
_FORBIDDEN_BACKENDS = {"sh", "bash", "cmd", "cmd.exe", "powershell", "pwsh", "shell"}
_ALLOWED_STEPS = {
    "VALIDATE_ARTIFACT",
    "ASSIGN_FINAL_FILENAME",
    "VERIFY_FILENAME_POLICY",
    "COPY_TO_MEDIA_ROOT",
    "VERIFY_MEDIA_CHECKSUM",
    "SAFE_EJECT",
    "REQUIRE_PRINTER_POWER_OFF",
    "REQUIRE_MEDIA_INSERTED",
    "REQUIRE_PRINTER_POWER_ON",
    "CONNECT_BOOT_JUMPER",
    "PRESS_RESET",
    "ENTER_DFU",
    "ENTER_BOOTSEL",
    "RUN_BACKEND",
    "WAIT_FOR_MCU_REENUMERATION",
    "VERIFY_KLIPPER_BUILD_ID",
    "OPERATOR_ACTION_REQUIRED",
    # Phase-3 non-executing DeploymentPlan vocabulary. Legacy spellings stay
    # accepted until all provisional contracts are migrated.
    "PREPARE_MEDIA",
    "COPY_TO_MEDIA",
    "REQUIRE_POWER_OFF",
    "REQUIRE_MEDIA_INSERTED",
    "REQUIRE_POWER_ON",
}


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BoardContractError(f"{field_name} must be an object")
    return value


def _only_keys(data: Mapping[str, Any], allowed: set[str], field_name: str) -> None:
    unexpected = sorted(set(data) - allowed)
    if unexpected:
        raise BoardContractError(f"{field_name} has unexpected fields: {unexpected}")


def _sequence(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise BoardContractError(f"{field_name} must be a list")
    return value


def _text(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise BoardContractError(f"{field_name} must be a string")
    result = value.strip()
    if not allow_empty and not result:
        raise BoardContractError(f"{field_name} must not be empty")
    return result


def _identifier(value: Any, field_name: str) -> str:
    result = _text(value, field_name).lower()
    if not _ID_RE.fullmatch(result):
        raise BoardContractError(f"{field_name} is not a canonical identifier: {result!r}")
    return result


def _sha256(value: Any, field_name: str) -> str:
    result = _text(value, field_name).lower()
    if not _SHA256_RE.fullmatch(result):
        raise BoardContractError(f"{field_name} must be a lowercase SHA-256")
    return result


def _provenance(value: Any, field_name: str) -> tuple["Provenance", ...]:
    items = tuple(Provenance.from_mapping(item, f"{field_name}[{index}]")
                  for index, item in enumerate(_sequence(value, field_name)))
    if not items:
        raise BoardContractError(f"{field_name} must contain at least one source")
    return items


def _kconfig_values(value: Any, field_name: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in _mapping(value, field_name).items():
        if not isinstance(key, str) or not _KCONFIG_RE.fullmatch(key):
            raise BoardContractError(f"{field_name} has invalid Kconfig symbol {key!r}")
        if not isinstance(item, (bool, int, str)) or isinstance(item, float):
            raise BoardContractError(f"{field_name}.{key} has an unsupported value")
        result[key] = item
    return result


def canonical_contract_bytes(payload: Mapping[str, Any]) -> bytes:
    """Return the stable JSON form used to identify one contract.

    The declared digest is excluded so the digest is not self-referential.
    YAML ordering, comments, anchors and presentation do not affect identity.
    """
    normalized = deepcopy(dict(payload))
    normalized.pop("contract_digest", None)
    try:
        encoded = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise BoardContractError(f"contract is not canonically serializable: {exc}") from exc
    return encoded.encode("utf-8")


def compute_contract_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_contract_bytes(payload)).hexdigest()


@dataclass(frozen=True)
class Provenance:
    source: str
    reference: str
    detail: str = ""

    @classmethod
    def from_mapping(cls, value: Any, field_name: str) -> "Provenance":
        data = _mapping(value, field_name)
        _only_keys(data, {"source", "reference", "detail"}, field_name)
        return cls(
            source=_identifier(data.get("source"), f"{field_name}.source"),
            reference=_text(data.get("reference"), f"{field_name}.reference"),
            detail=_text(data.get("detail", ""), f"{field_name}.detail", allow_empty=True),
        )


@dataclass(frozen=True)
class ProcessorSpec:
    architecture: str
    architecture_kconfig: str
    model: str
    model_kconfig: str
    resolved_mcu: str
    provenance: tuple[Provenance, ...]

    @classmethod
    def from_mapping(cls, value: Any, field_name: str) -> "ProcessorSpec":
        data = _mapping(value, field_name)
        _only_keys(data, {
            "architecture", "architecture_kconfig", "model", "model_kconfig",
            "resolved_mcu", "provenance",
        }, field_name)
        architecture = _text(data.get("architecture"), f"{field_name}.architecture").lower()
        if architecture not in _ARCHITECTURES:
            raise BoardContractError(f"{field_name}.architecture is unsupported: {architecture}")
        model = _text(data.get("model"), f"{field_name}.model")
        if not _PROCESSOR_RE.fullmatch(model):
            raise BoardContractError(
                f"{field_name}.model is not an allow-listed processor model: {model!r}"
            )
        resolved_mcu = _text(data.get("resolved_mcu"), f"{field_name}.resolved_mcu").lower()
        if not _PROCESSOR_RE.fullmatch(resolved_mcu):
            raise BoardContractError(
                f"{field_name}.resolved_mcu is not an allow-listed MCU: {resolved_mcu!r}"
            )
        arch_symbol = _text(data.get("architecture_kconfig"), f"{field_name}.architecture_kconfig")
        model_symbol = _text(data.get("model_kconfig"), f"{field_name}.model_kconfig")
        if not _KCONFIG_RE.fullmatch(arch_symbol) or not _KCONFIG_RE.fullmatch(model_symbol):
            raise BoardContractError(f"{field_name} contains an invalid Kconfig symbol")
        if not model_symbol.startswith("CONFIG_MACH_"):
            raise BoardContractError(f"{field_name}.model_kconfig must select CONFIG_MACH_*")
        return cls(
            architecture=architecture,
            architecture_kconfig=arch_symbol,
            model=model,
            model_kconfig=model_symbol,
            resolved_mcu=resolved_mcu,
            provenance=_provenance(data.get("provenance"), f"{field_name}.provenance"),
        )


@dataclass(frozen=True)
class BootloaderSpec:
    label: str
    selection: dict[str, Any]
    application_address: Optional[str]
    provenance: tuple[Provenance, ...]

    @classmethod
    def from_mapping(cls, value: Any, field_name: str) -> "BootloaderSpec":
        data = _mapping(value, field_name)
        _only_keys(data, {"label", "selection", "application_address", "provenance"}, field_name)
        address = data.get("application_address")
        if address is not None:
            address = _text(address, f"{field_name}.application_address")
            if not re.fullmatch(r"0x[0-9a-fA-F]+", address):
                raise BoardContractError(f"{field_name}.application_address must be hexadecimal")
        return cls(
            label=_text(data.get("label"), f"{field_name}.label"),
            selection=_kconfig_values(data.get("selection", {}), f"{field_name}.selection"),
            application_address=address,
            provenance=_provenance(data.get("provenance"), f"{field_name}.provenance"),
        )


@dataclass(frozen=True)
class ClockSpec:
    label: str
    selection: dict[str, Any]
    reference_hz: int
    provenance: tuple[Provenance, ...]

    @classmethod
    def from_mapping(cls, value: Any, field_name: str) -> "ClockSpec":
        data = _mapping(value, field_name)
        _only_keys(data, {"label", "selection", "reference_hz", "provenance"}, field_name)
        reference_hz = data.get("reference_hz")
        if not isinstance(reference_hz, int) or isinstance(reference_hz, bool) or reference_hz <= 0:
            raise BoardContractError(f"{field_name}.reference_hz must be a positive integer")
        return cls(
            label=_text(data.get("label"), f"{field_name}.label"),
            selection=_kconfig_values(data.get("selection", {}), f"{field_name}.selection"),
            reference_hz=reference_hz,
            provenance=_provenance(data.get("provenance"), f"{field_name}.provenance"),
        )


@dataclass(frozen=True)
class TransportSpec:
    kind: TransportKind
    selection: dict[str, Any]
    endpoint: dict[str, str]
    host_connection: str
    provenance: tuple[Provenance, ...]

    @classmethod
    def from_mapping(cls, value: Any, field_name: str) -> "TransportSpec":
        data = _mapping(value, field_name)
        _only_keys(data, {"kind", "selection", "endpoint", "host_connection", "provenance"}, field_name)
        try:
            kind = TransportKind(_text(data.get("kind"), f"{field_name}.kind").upper())
        except ValueError as exc:
            raise BoardContractError(f"{field_name}.kind is unsupported") from exc
        endpoint = {
            _text(key, f"{field_name}.endpoint key"):
            _text(item, f"{field_name}.endpoint.{key}")
            for key, item in _mapping(data.get("endpoint"), f"{field_name}.endpoint").items()
        }
        if not endpoint:
            raise BoardContractError(f"{field_name}.endpoint must not be empty")
        return cls(
            kind=kind,
            selection=_kconfig_values(data.get("selection"), f"{field_name}.selection"),
            endpoint=endpoint,
            host_connection=_identifier(data.get("host_connection"), f"{field_name}.host_connection"),
            provenance=_provenance(data.get("provenance"), f"{field_name}.provenance"),
        )


@dataclass(frozen=True)
class LowLevelSpec:
    enabled: bool
    startup_gpio: tuple[str, ...]
    provenance: tuple[Provenance, ...]

    @classmethod
    def from_mapping(cls, value: Any, field_name: str) -> "LowLevelSpec":
        data = _mapping(value, field_name)
        _only_keys(data, {"enabled", "startup_gpio", "provenance"}, field_name)
        enabled = data.get("enabled")
        if not isinstance(enabled, bool):
            raise BoardContractError(f"{field_name}.enabled must be boolean")
        pins = tuple(_text(item, f"{field_name}.startup_gpio")
                     for item in _sequence(data.get("startup_gpio", []), f"{field_name}.startup_gpio"))
        if pins and not enabled:
            raise BoardContractError(f"{field_name} cannot set startup GPIO with low-level disabled")
        return cls(enabled, pins, _provenance(data.get("provenance"), f"{field_name}.provenance"))


@dataclass(frozen=True)
class ArtifactPolicy:
    native_path: str
    native_filename: str
    format: ArtifactFormat
    final_filename: dict[str, Any]
    provenance: tuple[Provenance, ...]

    @classmethod
    def from_mapping(cls, value: Any, field_name: str) -> "ArtifactPolicy":
        data = _mapping(value, field_name)
        _only_keys(data, {
            "native_path", "native_filename", "format", "final_filename", "provenance",
        }, field_name)
        native_filename = _text(data.get("native_filename"), f"{field_name}.native_filename")
        if "/" in native_filename or "\\" in native_filename or native_filename in (".", ".."):
            raise BoardContractError(f"{field_name}.native_filename must be a basename")
        final = dict(_mapping(data.get("final_filename"), f"{field_name}.final_filename"))
        _only_keys(final, {
            "strategy", "value", "template", "required_suffix",
            "must_differ_from_last_successful_flash",
        }, f"{field_name}.final_filename")
        strategy = _identifier(final.get("strategy"), f"{field_name}.final_filename.strategy")
        if strategy not in {"fixed", "native", "build-id"}:
            raise BoardContractError(f"{field_name}.final_filename.strategy is unsupported")
        if strategy == "fixed":
            fixed = _text(final.get("value"), f"{field_name}.final_filename.value")
            if "/" in fixed or "\\" in fixed:
                raise BoardContractError(f"{field_name}.final_filename.value must be a basename")
        if strategy == "build-id" and not _text(
            final.get("template"), f"{field_name}.final_filename.template"
        ):
            raise BoardContractError(f"{field_name}.final_filename.template must not be empty")
        return cls(
            native_path=_text(data.get("native_path"), f"{field_name}.native_path"),
            native_filename=native_filename,
            format=ArtifactFormat(_text(data.get("format"), f"{field_name}.format").upper()),
            final_filename=final,
            provenance=_provenance(data.get("provenance"), f"{field_name}.provenance"),
        )


@dataclass(frozen=True)
class FlashCommand:
    backend: str
    argv: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: Any, field_name: str) -> "FlashCommand":
        data = _mapping(value, field_name)
        _only_keys(data, {"backend", "argv"}, field_name)
        backend = _text(data.get("backend"), f"{field_name}.backend").lower()
        if backend in _FORBIDDEN_BACKENDS or backend not in _ALLOWED_BACKENDS:
            raise BoardContractError(f"{field_name}.backend is not allow-listed: {backend!r}")
        argv = tuple(_text(item, f"{field_name}.argv")
                     for item in _sequence(data.get("argv"), f"{field_name}.argv"))
        if not argv:
            raise BoardContractError(f"{field_name}.argv must not be empty")
        for argument in argv:
            if any(marker in argument for marker in _SHELL_MARKERS):
                raise BoardContractError(f"{field_name}.argv contains shell syntax")
        return cls(backend, argv)


@dataclass(frozen=True)
class FlashRecipe:
    strategy: FlashStrategy
    steps: tuple[str, ...]
    command: Optional[FlashCommand]
    options: dict[str, Any]
    provenance: tuple[Provenance, ...]

    @classmethod
    def from_mapping(cls, value: Any, field_name: str) -> "FlashRecipe":
        data = _mapping(value, field_name)
        _only_keys(data, {"strategy", "steps", "command", "options", "provenance"}, field_name)
        try:
            strategy = FlashStrategy(_text(data.get("strategy"), f"{field_name}.strategy").upper())
        except ValueError as exc:
            raise BoardContractError(f"{field_name}.strategy is not allow-listed") from exc
        steps = tuple(_text(item, f"{field_name}.steps").upper()
                      for item in _sequence(data.get("steps"), f"{field_name}.steps"))
        invalid = [step for step in steps if step not in _ALLOWED_STEPS]
        if not steps:
            raise BoardContractError(f"{field_name}.steps must not be empty")
        if invalid:
            raise BoardContractError(f"{field_name}.steps contains unsupported actions: {invalid}")
        command_data = data.get("command")
        command = None if command_data is None else FlashCommand.from_mapping(
            command_data, f"{field_name}.command"
        )
        needs_command = strategy in {
            FlashStrategy.AVRDUDE, FlashStrategy.DFU_UTIL,
            FlashStrategy.MAKE_FLASH, FlashStrategy.RAW_ADDRESS,
        }
        if needs_command != (command is not None):
            raise BoardContractError(f"{field_name} command does not match strategy {strategy.value}")
        if (command is not None) != ("RUN_BACKEND" in steps):
            raise BoardContractError(f"{field_name}.steps must represent backend execution exactly")
        options = dict(_mapping(data.get("options", {}), f"{field_name}.options"))
        if strategy is FlashStrategy.SD_CARD:
            allowed_options = {
                "destination", "make_flash_supported", "restart_board",
                "required_filesystems", "require_removable",
            }
            unknown_options = sorted(set(options) - allowed_options)
            if unknown_options:
                raise BoardContractError(
                    f"{field_name}.options has unsupported SD_CARD fields: {unknown_options}"
                )
            if options.get("destination") != "sd-card-root":
                raise BoardContractError(
                    f"{field_name}.options.destination must be sd-card-root"
                )
            filesystems = options.get("required_filesystems")
            if (
                not isinstance(filesystems, list)
                or not filesystems
                or any(item not in {"vfat"} for item in filesystems)
            ):
                raise BoardContractError(
                    f"{field_name}.options.required_filesystems must be ['vfat']"
                )
            if options.get("require_removable") is not True:
                raise BoardContractError(
                    f"{field_name}.options.require_removable must be true"
                )
        return cls(
            strategy=strategy,
            steps=steps,
            command=command,
            options=options,
            provenance=_provenance(data.get("provenance"), f"{field_name}.provenance"),
        )


@dataclass(frozen=True)
class ContractWarning:
    id: str
    severity: WarningSeverity
    text: str
    incompatible_board_ids: tuple[str, ...]
    provenance: tuple[Provenance, ...]

    @classmethod
    def from_mapping(cls, value: Any, field_name: str) -> "ContractWarning":
        data = _mapping(value, field_name)
        _only_keys(data, {"id", "severity", "text", "incompatible_board_ids", "provenance"}, field_name)
        return cls(
            id=_identifier(data.get("id"), f"{field_name}.id"),
            severity=WarningSeverity(_text(data.get("severity"), f"{field_name}.severity").upper()),
            text=_text(data.get("text"), f"{field_name}.text"),
            incompatible_board_ids=tuple(
                _identifier(item, f"{field_name}.incompatible_board_ids")
                for item in _sequence(data.get("incompatible_board_ids", []),
                                      f"{field_name}.incompatible_board_ids")
            ),
            provenance=_provenance(data.get("provenance"), f"{field_name}.provenance"),
        )


@dataclass(frozen=True)
class BuildTarget:
    id: str
    support_status: SupportStatus
    transport: TransportSpec
    low_level: LowLevelSpec
    requested_kconfig: dict[str, Any]
    resolved_assertions: dict[str, Any]
    kconfig_provenance: tuple[Provenance, ...]
    artifact: ArtifactPolicy
    flash: FlashRecipe

    @classmethod
    def from_mapping(cls, value: Any, field_name: str) -> "BuildTarget":
        data = _mapping(value, field_name)
        _only_keys(data, {
            "id", "support_status", "transport", "low_level", "requested_kconfig",
            "resolved_assertions", "kconfig_provenance", "artifact", "flash",
        }, field_name)
        requested = _kconfig_values(data.get("requested_kconfig"), f"{field_name}.requested_kconfig")
        resolved = _kconfig_values(data.get("resolved_assertions"), f"{field_name}.resolved_assertions")
        if not requested or not resolved:
            raise BoardContractError(f"{field_name} must declare requested and resolved Kconfig")
        return cls(
            id=_identifier(data.get("id"), f"{field_name}.id"),
            support_status=SupportStatus(
                _text(data.get("support_status"), f"{field_name}.support_status").upper()
            ),
            transport=TransportSpec.from_mapping(data.get("transport"), f"{field_name}.transport"),
            low_level=LowLevelSpec.from_mapping(data.get("low_level"), f"{field_name}.low_level"),
            requested_kconfig=requested,
            resolved_assertions=resolved,
            kconfig_provenance=_provenance(
                data.get("kconfig_provenance"), f"{field_name}.kconfig_provenance"
            ),
            artifact=ArtifactPolicy.from_mapping(data.get("artifact"), f"{field_name}.artifact"),
            flash=FlashRecipe.from_mapping(data.get("flash"), f"{field_name}.flash"),
        )


@dataclass(frozen=True)
class HardwareVariant:
    id: str
    processor: ProcessorSpec
    bootloader: BootloaderSpec
    clock: ClockSpec
    build_targets: tuple[BuildTarget, ...]

    @classmethod
    def from_mapping(cls, value: Any, field_name: str) -> "HardwareVariant":
        data = _mapping(value, field_name)
        _only_keys(data, {"id", "processor", "bootloader", "clock", "build_targets"}, field_name)
        targets = tuple(
            BuildTarget.from_mapping(item, f"{field_name}.build_targets[{index}]")
            for index, item in enumerate(
                _sequence(data.get("build_targets"), f"{field_name}.build_targets")
            )
        )
        if not targets:
            raise BoardContractError(f"{field_name}.build_targets must not be empty")
        ids = [item.id for item in targets]
        if len(ids) != len(set(ids)):
            raise BoardContractError(f"{field_name} contains duplicate build target IDs")
        processor = ProcessorSpec.from_mapping(data.get("processor"), f"{field_name}.processor")
        bootloader = BootloaderSpec.from_mapping(data.get("bootloader"), f"{field_name}.bootloader")
        clock = ClockSpec.from_mapping(data.get("clock"), f"{field_name}.clock")
        for target in targets:
            required = {
                processor.architecture_kconfig: True,
                processor.model_kconfig: True,
                "CONFIG_LOW_LEVEL_OPTIONS": target.low_level.enabled,
                **bootloader.selection,
                **clock.selection,
                **target.transport.selection,
            }
            mismatches = {
                symbol: expected for symbol, expected in required.items()
                if target.requested_kconfig.get(symbol) != expected
            }
            if mismatches:
                raise BoardContractError(
                    f"{field_name}.{target.id}.requested_kconfig does not encode {mismatches}"
                )
            if target.resolved_assertions.get("CONFIG_MCU") != processor.resolved_mcu:
                raise BoardContractError(
                    f"{field_name}.{target.id}.resolved_assertions has the wrong CONFIG_MCU"
                )
        return cls(
            id=_identifier(data.get("id"), f"{field_name}.id"),
            processor=processor,
            bootloader=bootloader,
            clock=clock,
            build_targets=targets,
        )

    def target(self, target_id: str) -> Optional[BuildTarget]:
        normalized = str(target_id or "").strip().lower()
        return next((item for item in self.build_targets if item.id == normalized), None)


@dataclass(frozen=True)
class UpstreamMetadata:
    source_contract: str
    repository: str
    validated_commit: str
    config_path: str
    config_sha256_lf: str
    header_sha256_lf: str
    header_text: str

    @classmethod
    def from_mapping(cls, value: Any, field_name: str) -> "UpstreamMetadata":
        data = _mapping(value, field_name)
        _only_keys(data, {
            "source_contract", "repository", "validated_commit", "config_path",
            "config_sha256_lf", "header_sha256_lf", "header_text",
        }, field_name)
        commit = _text(data.get("validated_commit"), f"{field_name}.validated_commit").lower()
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise BoardContractError(f"{field_name}.validated_commit must be a full Git SHA")
        path = _text(data.get("config_path"), f"{field_name}.config_path")
        if not path.startswith("config/") or ".." in path or "\\" in path:
            raise BoardContractError(f"{field_name}.config_path must remain under config/")
        header_text = data.get("header_text")
        if not isinstance(header_text, str) or not header_text.strip():
            raise BoardContractError(f"{field_name}.header_text must not be empty")
        source_contract = _text(data.get("source_contract"), f"{field_name}.source_contract")
        repository = _text(data.get("repository"), f"{field_name}.repository")
        if source_contract != "kace-klipper-source/v1":
            raise BoardContractError(f"{field_name}.source_contract is unsupported")
        if repository != "https://github.com/Klipper3d/klipper.git":
            raise BoardContractError(f"{field_name}.repository must be the official Klipper repository")
        header_hash = _sha256(data.get("header_sha256_lf"), f"{field_name}.header_sha256_lf")
        normalized_header = header_text.replace("\r\n", "\n").replace("\r", "\n")
        if hashlib.sha256(normalized_header.encode("utf-8")).hexdigest() != header_hash:
            raise BoardContractError(f"{field_name}.header_text does not match header_sha256_lf")
        return cls(
            source_contract=source_contract,
            repository=repository,
            validated_commit=commit,
            config_path=path,
            config_sha256_lf=_sha256(data.get("config_sha256_lf"), f"{field_name}.config_sha256_lf"),
            header_sha256_lf=header_hash,
            # This is upstream evidence, not presentation text. Preserve its
            # whitespace so the reviewed header hash remains reproducible.
            header_text=header_text,
        )


@dataclass(frozen=True)
class BoardContract:
    schema: str
    board_id: str
    display_name: str
    manufacturer: str
    family_id: str
    revision: str
    official_config_filenames: tuple[str, ...]
    legacy_aliases: tuple[str, ...]
    upstream: UpstreamMetadata
    hardware_variants: tuple[HardwareVariant, ...]
    warnings: tuple[ContractWarning, ...]
    declared_digest: str
    _payload: dict[str, Any] = field(repr=False, compare=False)

    @classmethod
    def from_mapping(cls, value: Any, *, source: str = "<memory>") -> "BoardContract":
        data = dict(_mapping(value, source))
        _only_keys(data, {
            "schema", "board_id", "display_name", "manufacturer", "family_id",
            "revision", "aliases", "upstream", "hardware_variants", "warnings",
            "contract_digest",
        }, source)
        if data.get("schema") != "kace-board-contract/v1":
            raise BoardContractError(f"{source}: unsupported board contract schema")
        aliases = _mapping(data.get("aliases"), f"{source}.aliases")
        _only_keys(aliases, {"official_config_filenames", "legacy_exact"}, f"{source}.aliases")
        official = tuple(
            _text(item, f"{source}.aliases.official_config_filenames")
            for item in _sequence(aliases.get("official_config_filenames"),
                                  f"{source}.aliases.official_config_filenames")
        )
        legacy = tuple(
            _text(item, f"{source}.aliases.legacy_exact")
            for item in _sequence(aliases.get("legacy_exact", []), f"{source}.aliases.legacy_exact")
        )
        if not official:
            raise BoardContractError(f"{source}: at least one official config filename is required")
        for alias in official + legacy:
            if any(char in _ALIAS_META for char in alias):
                raise BoardContractError(f"{source}: aliases must be exact literals: {alias!r}")

        variants = tuple(
            HardwareVariant.from_mapping(item, f"{source}.hardware_variants[{index}]")
            for index, item in enumerate(
                _sequence(data.get("hardware_variants"), f"{source}.hardware_variants")
            )
        )
        if not variants:
            raise BoardContractError(f"{source}: hardware_variants must not be empty")
        variant_ids = [item.id for item in variants]
        if len(variant_ids) != len(set(variant_ids)):
            raise BoardContractError(f"{source}: duplicate hardware variant IDs")

        warnings = tuple(
            ContractWarning.from_mapping(item, f"{source}.warnings[{index}]")
            for index, item in enumerate(_sequence(data.get("warnings", []), f"{source}.warnings"))
        )
        warning_ids = [item.id for item in warnings]
        if len(warning_ids) != len(set(warning_ids)):
            raise BoardContractError(f"{source}: duplicate warning IDs")

        declared = _sha256(data.get("contract_digest"), f"{source}.contract_digest")
        computed = compute_contract_digest(data)
        if declared != computed:
            raise BoardContractError(
                f"{source}: contract_digest mismatch: declared {declared}, computed {computed}"
            )
        return cls(
            schema=data["schema"],
            board_id=_identifier(data.get("board_id"), f"{source}.board_id"),
            display_name=_text(data.get("display_name"), f"{source}.display_name"),
            manufacturer=_text(data.get("manufacturer"), f"{source}.manufacturer"),
            family_id=_identifier(data.get("family_id"), f"{source}.family_id"),
            revision=_text(data.get("revision"), f"{source}.revision"),
            official_config_filenames=official,
            legacy_aliases=legacy,
            upstream=UpstreamMetadata.from_mapping(data.get("upstream"), f"{source}.upstream"),
            hardware_variants=variants,
            warnings=warnings,
            declared_digest=declared,
            _payload=deepcopy(data),
        )

    @property
    def contract_digest(self) -> str:
        return compute_contract_digest(self._payload)

    @property
    def aliases(self) -> tuple[str, ...]:
        return self.official_config_filenames + self.legacy_aliases

    def canonical_bytes(self) -> bytes:
        return canonical_contract_bytes(self._payload)

    def to_mapping(self, *, include_digest: bool = True) -> dict[str, Any]:
        result = deepcopy(self._payload)
        if include_digest:
            result["contract_digest"] = self.contract_digest
        else:
            result.pop("contract_digest", None)
        return result

    def variant(self, variant_id: str) -> Optional[HardwareVariant]:
        normalized = str(variant_id or "").strip().lower()
        return next((item for item in self.hardware_variants if item.id == normalized), None)
