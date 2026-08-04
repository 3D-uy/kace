"""Load and validate board-specific firmware deployment profiles."""

from __future__ import annotations

import os
import json
from pathlib import PurePath

try:
    import yaml
except ImportError:  # Minimal/offline validation environments
    yaml = None

_PROFILE_PARSE_ERRORS = (OSError, ValueError)
if yaml is not None:
    _PROFILE_PARSE_ERRORS += (yaml.YAMLError,)

from firmware.artifacts import FirmwareFormat
from .models import DeploymentMethodId, DeploymentProfile, DeploymentTarget


class DeploymentProfileError(ValueError):
    pass


def _default_path() -> str:
    return os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "data", "firmware_deployments.yaml")
    )


def _validate_filename(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DeploymentProfileError("final_filename must be a non-empty string")
    value = value.strip()
    if (
        PurePath(value).name != value
        or value in (".", "..")
        or ".." in value
        or "/" in value
        or "\\" in value
    ):
        raise DeploymentProfileError(f"unsafe final_filename: {value}")
    return value


def load_profiles(path: str | None = None) -> list[DeploymentProfile]:
    source_path = path or _default_path()
    try:
        with open(source_path, "r", encoding="utf-8") as source:
            raw = (yaml.safe_load(source) if yaml is not None else json.load(source)) or {}
    except _PROFILE_PARSE_ERRORS as exc:
        raise DeploymentProfileError(f"cannot load deployment profiles: {exc}") from exc

    profiles = []
    seen = set()
    for index, item in enumerate(raw.get("profiles", [])):
        try:
            profile_id = str(item["id"]).strip()
            if not profile_id or profile_id in seen:
                raise DeploymentProfileError(f"duplicate or empty profile id: {profile_id}")
            seen.add(profile_id)
            method = DeploymentMethodId(str(item["method"]).upper())
            formats = tuple(FirmwareFormat(str(value).upper()) for value in item["formats"])
            profile = DeploymentProfile(
                id=profile_id,
                method=method,
                board_patterns=tuple(str(value).lower() for value in item.get("board_patterns", [])),
                formats=formats,
                final_filename=_validate_filename(item["final_filename"]),
                instruction_keys=tuple(str(value) for value in item.get("instructions", [])),
                mcu_patterns=tuple(str(value).lower() for value in item.get("mcu_patterns", [])),
                exact_match_required=bool(item.get("exact_match_required", False)),
                auto_flash=bool(item.get("auto_flash", False)),
                backend=str(item.get("backend", "")),
                backend_options=dict(item.get("backend_options", {})),
            )
        except (KeyError, TypeError, ValueError, DeploymentProfileError) as exc:
            raise DeploymentProfileError(f"invalid profile at index {index}: {exc}") from exc
        if profile.auto_flash and profile.method is not DeploymentMethodId.USB:
            raise DeploymentProfileError(f"{profile.id}: only USB may enable auto_flash")
        if profile.backend and profile.backend not in {"avrdude"}:
            raise DeploymentProfileError(f"{profile.id}: unsupported backend {profile.backend}")
        profiles.append(profile)
    return profiles


class DeploymentProfileResolver:
    def __init__(self, profiles: list[DeploymentProfile] | None = None):
        self.profiles = profiles if profiles is not None else load_profiles()

    @staticmethod
    def _matches(profile: DeploymentProfile, target: DeploymentTarget) -> bool:
        board = (target.board or "").lower()
        mcu = (target.mcu or "").lower()
        if profile.mcu_patterns and not any(pattern in mcu for pattern in profile.mcu_patterns):
            return False
        if not profile.board_patterns:
            return not profile.exact_match_required
        if profile.exact_match_required:
            return any(board == pattern for pattern in profile.board_patterns)
        return any(pattern in board for pattern in profile.board_patterns)

    def available(self, target: DeploymentTarget, artifact_format: FirmwareFormat) -> list[DeploymentProfile]:
        exact = []
        fallback = []
        for profile in self.profiles:
            if artifact_format not in profile.formats or not self._matches(profile, target):
                continue
            (exact if profile.board_patterns else fallback).append(profile)
        return exact + fallback

    def resolve(
        self,
        target: DeploymentTarget,
        artifact_format: FirmwareFormat,
        method: DeploymentMethodId,
    ) -> DeploymentProfile:
        for profile in self.available(target, artifact_format):
            if profile.method is method:
                return profile
        raise DeploymentProfileError(
            f"no {method.value} deployment profile for board={target.board!r}, format={artifact_format.value}"
        )
