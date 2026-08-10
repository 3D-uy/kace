"""Load and validate exact board-specific firmware deployment profiles."""

from __future__ import annotations

import json
import os
import re
from pathlib import PurePath

try:
    import yaml
except ImportError:  # Minimal/offline validation environments
    yaml = None

_PROFILE_PARSE_ERRORS = (OSError, ValueError)
if yaml is not None:
    _PROFILE_PARSE_ERRORS += (yaml.YAMLError,)

from firmware.artifacts import FirmwareFormat
from firmware.configuration import BootloaderOffset, BootloaderOffsetKind
from .models import (
    DeploymentMethodId,
    DeploymentProfile,
    DeploymentStrategyId,
    DeploymentTarget,
    PostFlashVerification,
    UsbIdentityExpectation,
    UsbTopology,
)


_VID_PID_RE = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{4}$")


class DeploymentProfileError(ValueError):
    pass


def _default_path() -> str:
    return os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "data", "firmware_deployments.yaml")
    )


def _validate_filename(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DeploymentProfileError("firmware filename must be a non-empty string")
    value = value.strip()
    if (
        PurePath(value).name != value
        or value in (".", "..")
        or ".." in value
        or "/" in value
        or "\\" in value
    ):
        raise DeploymentProfileError(f"unsafe firmware filename: {value}")
    return value


def _parse_bootloader_offset(value: object) -> BootloaderOffset:
    text = str(value or "").strip().upper()
    if text == BootloaderOffsetKind.NOT_APPLICABLE.value:
        return BootloaderOffset.not_applicable()
    try:
        return BootloaderOffset.from_value(value)
    except ValueError as exc:
        raise DeploymentProfileError(f"invalid bootloader_offset: {value!r}") from exc


def _vid_pids(values: object, *, field_name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if not isinstance(values, list):
        raise DeploymentProfileError(f"{field_name} must be a list")
    normalized = tuple(str(value).strip().lower() for value in values)
    invalid = [value for value in normalized if not _VID_PID_RE.fullmatch(value)]
    if invalid:
        raise DeploymentProfileError(
            f"{field_name} contains invalid VID:PID values: {', '.join(invalid)}"
        )
    if len(set(normalized)) != len(normalized):
        raise DeploymentProfileError(f"{field_name} contains duplicates")
    return normalized


def _parse_usb_expectation(value: object) -> UsbIdentityExpectation:
    if not isinstance(value, dict):
        raise DeploymentProfileError("usb must be an object")
    try:
        topology = UsbTopology(str(value["topology"]).strip().upper())
    except (KeyError, ValueError) as exc:
        raise DeploymentProfileError("usb.topology is missing or unsupported") from exc
    application = _vid_pids(
        value.get("application_vid_pids"), field_name="usb.application_vid_pids"
    )
    bootloader = _vid_pids(
        value.get("bootloader_vid_pids"), field_name="usb.bootloader_vid_pids"
    )
    if topology is UsbTopology.NOT_APPLICABLE and (application or bootloader):
        raise DeploymentProfileError("NOT_APPLICABLE USB topology cannot declare VID/PID values")
    if topology is not UsbTopology.NOT_APPLICABLE and not (application or bootloader):
        raise DeploymentProfileError("USB topology must declare an expected VID/PID")
    return UsbIdentityExpectation(topology, application, bootloader)


def _validate_profile(profile: DeploymentProfile) -> None:
    if not profile.board_patterns:
        raise DeploymentProfileError(f"{profile.id}: board_ids must not be empty")
    if any(not board_id for board_id in profile.board_patterns):
        raise DeploymentProfileError(f"{profile.id}: board_ids must not contain empty values")
    if len(set(profile.board_patterns)) != len(profile.board_patterns):
        raise DeploymentProfileError(f"{profile.id}: board_ids must not contain duplicates")
    if not profile.exact_match_required:
        raise DeploymentProfileError(f"{profile.id}: exact_match_required must be true")
    if len(profile.formats) != 1:
        raise DeploymentProfileError(f"{profile.id}: exactly one artifact format is required")
    if not profile.config_mcu:
        raise DeploymentProfileError(f"{profile.id}: config_mcu is required")
    if not profile.native_filenames:
        raise DeploymentProfileError(f"{profile.id}: native_filenames must not be empty")
    if not profile.mcu_patterns:
        raise DeploymentProfileError(f"{profile.id}: mcu_patterns must not be empty")
    if profile.post_flash_verification is PostFlashVerification.NOT_APPLICABLE:
        raise DeploymentProfileError(
            f"{profile.id}: board-specific profiles require post-flash verification"
        )

    if profile.strategy is DeploymentStrategyId.AVRDUDE:
        if profile.method is not DeploymentMethodId.USB:
            raise DeploymentProfileError(f"{profile.id}: AVRDUDE requires the USB method")
        if not profile.auto_flash or profile.backend != "avrdude":
            raise DeploymentProfileError(
                f"{profile.id}: AVRDUDE requires auto_flash and the avrdude backend"
            )
        if profile.usb.topology is not UsbTopology.USB_SERIAL_BRIDGE:
            raise DeploymentProfileError(
                f"{profile.id}: AVRDUDE requires a USB_SERIAL_BRIDGE topology"
            )
        if not profile.usb.application_vid_pids:
            raise DeploymentProfileError(
                f"{profile.id}: AVRDUDE requires an application VID:PID allow-list"
            )
    elif profile.strategy is DeploymentStrategyId.SD_CARD:
        if profile.method is not DeploymentMethodId.MANUAL:
            raise DeploymentProfileError(f"{profile.id}: SD_CARD requires the MANUAL method")
        if profile.auto_flash or profile.backend:
            raise DeploymentProfileError(f"{profile.id}: SD_CARD cannot enable a USB backend")
    elif profile.strategy is DeploymentStrategyId.PREPARE_ONLY:
        if profile.method is not DeploymentMethodId.MANUAL:
            raise DeploymentProfileError(
                f"{profile.id}: PREPARE_ONLY requires the MANUAL method"
            )
        if profile.auto_flash or profile.backend:
            raise DeploymentProfileError(
                f"{profile.id}: PREPARE_ONLY cannot enable a USB backend"
            )


def load_profiles(path: str | None = None) -> list[DeploymentProfile]:
    source_path = path or _default_path()
    try:
        with open(source_path, "r", encoding="utf-8") as source:
            raw = (yaml.safe_load(source) if yaml is not None else json.load(source)) or {}
    except _PROFILE_PARSE_ERRORS as exc:
        raise DeploymentProfileError(f"cannot load deployment profiles: {exc}") from exc

    profiles = []
    seen = set()
    claimed_board_methods: set[tuple[str, DeploymentMethodId]] = set()
    for index, item in enumerate(raw.get("profiles", [])):
        try:
            profile_id = str(item["id"]).strip()
            if not profile_id or profile_id in seen:
                raise DeploymentProfileError(f"duplicate or empty profile id: {profile_id}")
            seen.add(profile_id)
            method = DeploymentMethodId(str(item["method"]).upper())
            formats = tuple(FirmwareFormat(str(value).upper()) for value in item["formats"])
            board_ids = tuple(str(value).strip().lower() for value in item.get("board_ids", []))
            native_filenames = tuple(
                _validate_filename(value) for value in item.get("native_filenames", [])
            )
            profile = DeploymentProfile(
                id=profile_id,
                method=method,
                board_patterns=board_ids,
                formats=formats,
                config_mcu=str(item.get("config_mcu", "")).strip().lower(),
                native_filenames=native_filenames,
                final_filename=_validate_filename(item["final_filename"]),
                instruction_keys=tuple(str(value) for value in item.get("instructions", [])),
                strategy=DeploymentStrategyId(str(item["strategy"]).upper()),
                bootloader_offset=_parse_bootloader_offset(item.get("bootloader_offset")),
                usb=_parse_usb_expectation(item.get("usb")),
                post_flash_verification=PostFlashVerification(
                    str(item["post_flash_verification"]).upper()
                ),
                mcu_patterns=tuple(str(value).lower() for value in item.get("mcu_patterns", [])),
                exact_match_required=bool(item.get("exact_match_required", False)),
                auto_flash=bool(item.get("auto_flash", False)),
                backend=str(item.get("backend", "")),
                backend_options=dict(item.get("backend_options", {})),
            )
            _validate_profile(profile)
            for board_id in profile.board_patterns:
                key = (board_id, profile.method)
                if key in claimed_board_methods:
                    raise DeploymentProfileError(
                        f"duplicate {profile.method.value} strategy for board {board_id}"
                    )
                claimed_board_methods.add(key)
        except (KeyError, TypeError, ValueError, DeploymentProfileError) as exc:
            raise DeploymentProfileError(f"invalid profile at index {index}: {exc}") from exc
        profiles.append(profile)
    if not profiles:
        raise DeploymentProfileError("deployment profile set is empty")
    return profiles


def _config_values(canonical_config: str) -> dict[str, str]:
    values = {}
    for line in str(canonical_config or "").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.startswith("CONFIG_"):
            values[key] = value.strip().strip('"').lower()
    return values


def profile_artifact_blockers(
    profile: DeploymentProfile, target: DeploymentTarget, artifact
) -> tuple[str, ...]:
    """Return exact profile/build mismatches before any staging or flashing."""
    blockers = []
    if artifact.format not in profile.formats:
        blockers.append(
            f"artifact format {artifact.format.value} does not match {profile.formats[0].value}"
        )
    if artifact.native_filename not in profile.native_filenames:
        blockers.append(
            f"native artifact {artifact.native_filename!r} is not allowed by the board profile"
        )
    artifact_mcu = str(getattr(artifact, "mcu", "") or "").lower()
    target_mcu = str(target.mcu or "").lower()
    if not any(artifact_mcu.startswith(pattern) for pattern in profile.mcu_patterns):
        blockers.append(f"build MCU {artifact_mcu!r} does not match the board profile")
    if not any(target_mcu.startswith(pattern) for pattern in profile.mcu_patterns):
        blockers.append(f"detected MCU {target_mcu!r} does not match the board profile")

    identity = getattr(artifact, "firmware_identity", None)
    values = _config_values(getattr(identity, "canonical_config", ""))
    if values.get("CONFIG_MCU") != profile.config_mcu:
        blockers.append(
            f"build CONFIG_MCU={values.get('CONFIG_MCU')!r} does not match {profile.config_mcu!r}"
        )
    expected_offset = profile.bootloader_offset
    actual_offset = values.get("CONFIG_FLASH_START")
    if expected_offset is not None:
        if expected_offset.kind is BootloaderOffsetKind.NOT_APPLICABLE:
            if actual_offset is not None:
                blockers.append("build unexpectedly defines CONFIG_FLASH_START")
        elif actual_offset != str(expected_offset.kconfig_value).lower():
            blockers.append(
                "build bootloader offset "
                f"{actual_offset!r} does not match {expected_offset.kconfig_value!r}"
            )
    if str(getattr(identity, "artifact_format", "")) != artifact.format.value:
        blockers.append("firmware identity artifact format does not match the build artifact")
    return tuple(blockers)


class DeploymentProfileResolver:
    def __init__(self, profiles: list[DeploymentProfile] | None = None):
        self.profiles = profiles if profiles is not None else load_profiles()

    @staticmethod
    def _board_matches(profile: DeploymentProfile, target: DeploymentTarget) -> bool:
        board = (target.board or "").strip().lower()
        return board in profile.board_patterns

    def _board_profiles(self, target: DeploymentTarget) -> list[DeploymentProfile]:
        return [profile for profile in self.profiles if self._board_matches(profile, target)]

    @staticmethod
    def _fallback_profile(artifact) -> DeploymentProfile:
        native_filename = _validate_filename(artifact.native_filename)
        return DeploymentProfile(
            id="unsupported-board-prepare-only",
            method=DeploymentMethodId.MANUAL,
            board_patterns=(),
            formats=(artifact.format,),
            config_mcu="",
            native_filenames=(native_filename,),
            final_filename=native_filename,
            instruction_keys=("deployment.prepare_only.unsupported",),
            strategy=DeploymentStrategyId.PREPARE_ONLY,
            bootloader_offset=None,
            usb=UsbIdentityExpectation(UsbTopology.NOT_APPLICABLE),
            post_flash_verification=PostFlashVerification.NOT_APPLICABLE,
            fallback=True,
        )

    def available(self, target: DeploymentTarget, artifact) -> list[DeploymentProfile]:
        board_profiles = self._board_profiles(target)
        if not board_profiles:
            return [self._fallback_profile(artifact)]
        return [
            profile
            for profile in board_profiles
            if not profile_artifact_blockers(profile, target, artifact)
        ]

    def blockers(self, target: DeploymentTarget, artifact) -> tuple[str, ...]:
        board_profiles = self._board_profiles(target)
        if not board_profiles:
            return ()
        blockers = []
        for profile in board_profiles:
            blockers.extend(profile_artifact_blockers(profile, target, artifact))
        return tuple(dict.fromkeys(blockers))

    def resolve(
        self,
        target: DeploymentTarget,
        artifact,
        method: DeploymentMethodId,
    ) -> DeploymentProfile:
        method = DeploymentMethodId(method)
        board_profiles = self._board_profiles(target)
        if not board_profiles:
            if method is DeploymentMethodId.MANUAL:
                return self._fallback_profile(artifact)
            raise DeploymentProfileError(
                f"board {target.board!r} has no exact automatic deployment strategy"
            )

        method_profiles = [profile for profile in board_profiles if profile.method is method]
        if not method_profiles:
            raise DeploymentProfileError(
                f"no {method.value} deployment strategy for exact board {target.board!r}"
            )
        errors = []
        for profile in method_profiles:
            blockers = profile_artifact_blockers(profile, target, artifact)
            if not blockers:
                return profile
            errors.extend(blockers)
        raise DeploymentProfileError(
            f"{method.value} strategy rejected the build for {target.board!r}: "
            + "; ".join(dict.fromkeys(errors))
        )
