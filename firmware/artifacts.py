"""Typed, deployment-agnostic firmware build artifacts."""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import asdict, dataclass
from enum import Enum


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
    ) -> "BuildArtifact":
        provenance = BuildProvenance.MOCK if mock_build else BuildProvenance.REAL
        digest = _sha256(path)
        return cls(
            build_id=str(uuid.uuid4()),
            path=os.path.abspath(os.path.expanduser(path)),
            native_filename=native_filename,
            format=FirmwareFormat.from_filename(native_filename),
            sha256=digest,
            size_bytes=int(size_bytes),
            mcu=mcu or "",
            firmware_fingerprint=firmware_fingerprint or "",
            provenance=provenance,
            flashable=bool(not mock_build and not size_warning and digest),
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data["format"] = self.format.value
        data["provenance"] = self.provenance.value
        return data
