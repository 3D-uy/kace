"""Typed, deployment-agnostic firmware build artifacts."""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import asdict, dataclass
from enum import Enum
import re
from typing import Optional

from .identity import FirmwareBuildIdentity, FirmwareBuildInputs


class FirmwareFormat(str, Enum):
    BIN = "BIN"
    UF2 = "UF2"
    IHEX = "IHEX"

    @classmethod
    def from_filename(cls, filename: str) -> "FirmwareFormat":
        lowered = filename.lower()
        if lowered.endswith(".uf2"):
            return cls.UF2
        if lowered.endswith(".hex"):
            return cls.IHEX
        return cls.BIN


class BuildProvenance(str, Enum):
    REAL = "REAL"
    MOCK = "MOCK"


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        # Some unit tests replace the filesystem copy with a mock. An empty
        # digest is explicit and prevents automatic deployment.
        return ""
    return digest.hexdigest()


@dataclass(frozen=True)
class BuildArtifact:
    """Exact output produced by Klipper, before deployment-specific naming."""

    build_id: str
    path: str
    native_filename: str
    format: FirmwareFormat
    sha256: str
    size_bytes: int
    mcu: str
    firmware_fingerprint: str
    provenance: BuildProvenance
    flashable: bool
    firmware_identity: Optional[FirmwareBuildIdentity] = None
    # BoardContract identity is additive and empty for every legacy build.
    # A populated tuple is only produced after a BuildProof has been checked.
    board_id: str = ""
    hardware_variant_id: str = ""
    build_target_id: str = ""
    board_contract_digest: str = ""
    klipper_commit: str = ""
    build_proof_digest: str = ""

    def __post_init__(self) -> None:
        identity = (
            self.board_id,
            self.hardware_variant_id,
            self.build_target_id,
            self.board_contract_digest,
            self.klipper_commit,
            self.build_proof_digest,
        )
        if any(identity) and not all(identity):
            raise ValueError("BoardContract artifact identity must be complete or absent")
        if all(identity):
            if not re.fullmatch(r"[0-9a-f]{64}", self.board_contract_digest):
                raise ValueError("board_contract_digest must be a lowercase SHA-256")
            if not re.fullmatch(r"[0-9a-f]{40}", self.klipper_commit):
                raise ValueError("klipper_commit must be an exact lowercase Git SHA")
            if not re.fullmatch(r"[0-9a-f]{64}", self.build_proof_digest):
                raise ValueError("build_proof_digest must be a lowercase SHA-256")

    @classmethod
    def create(
        cls,
        *,
        path: str,
        native_filename: str,
        size_bytes: int,
        mcu: str,
        firmware_fingerprint: str,
        mock_build: bool,
        size_warning: bool,
        build_identity: Optional[FirmwareBuildInputs] = None,
        board_id: str = "",
        hardware_variant_id: str = "",
        build_target_id: str = "",
        board_contract_digest: str = "",
        klipper_commit: str = "",
        build_proof_digest: str = "",
    ) -> "BuildArtifact":
        provenance = BuildProvenance.MOCK if mock_build else BuildProvenance.REAL
        digest = _sha256(path)
        artifact_format = FirmwareFormat.from_filename(native_filename)
        identity = None
        if build_identity is not None and digest:
            identity = build_identity.complete(
                artifact_sha256=digest,
                artifact_size=int(size_bytes),
                artifact_format=artifact_format.value,
            )
        return cls(
            build_id=str(uuid.uuid4()),
            path=os.path.abspath(os.path.expanduser(path)),
            native_filename=native_filename,
            format=artifact_format,
            sha256=digest,
            size_bytes=int(size_bytes),
            mcu=mcu or "",
            firmware_fingerprint=(
                identity.reported_version if identity is not None else firmware_fingerprint or ""
            ),
            provenance=provenance,
            flashable=bool(not mock_build and not size_warning and digest and identity is not None),
            firmware_identity=identity,
            board_id=board_id,
            hardware_variant_id=hardware_variant_id,
            build_target_id=build_target_id,
            board_contract_digest=board_contract_digest,
            klipper_commit=klipper_commit,
            build_proof_digest=build_proof_digest,
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data["format"] = self.format.value
        data["provenance"] = self.provenance.value
        return data
