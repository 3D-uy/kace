"""Domain contracts shared by firmware deployment methods."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Callable, Optional

from firmware.artifacts import BuildArtifact, FirmwareFormat


class DeploymentMethodId(str, Enum):
    MANUAL = "MANUAL"
    USB = "USB"


class DeploymentStatus(str, Enum):
    ACTION_REQUIRED = "ACTION_REQUIRED"
    FLASHED = "FLASHED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class DeploymentInstruction:
    id: str
    text: str
    level: str = "INFO"


@dataclass(frozen=True)
class DeploymentTarget:
    board: str
    mcu: str
    device_path: str = ""
    mcu_name: str = "mcu"


@dataclass(frozen=True)
class DeploymentProfile:
    id: str
    method: DeploymentMethodId
    board_patterns: tuple[str, ...]
    formats: tuple[FirmwareFormat, ...]
    final_filename: str
    instruction_keys: tuple[str, ...]
    mcu_patterns: tuple[str, ...] = ()
    exact_match_required: bool = False
    auto_flash: bool = False
    backend: str = ""
    backend_options: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DeploymentPlan:
    deployment_id: str
    method: DeploymentMethodId
    profile: DeploymentProfile
    target: DeploymentTarget
    artifact: BuildArtifact
    final_filename: str
    instructions: tuple[DeploymentInstruction, ...]
    automation_supported: bool
    automation_eligible: bool
    automation_blockers: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "deployment_id": self.deployment_id,
            "method": self.method.value,
            "profile_id": self.profile.id,
            "target": asdict(self.target),
            "artifact": self.artifact.to_dict(),
            "final_filename": self.final_filename,
            "instructions": [asdict(item) for item in self.instructions],
            "automation": {
                "supported": self.automation_supported,
                "eligible": self.automation_eligible,
                "blockers": list(self.automation_blockers),
            },
        }


@dataclass(frozen=True)
class PreparedDeployment:
    plan: DeploymentPlan
    staged_path: str
    sha256: str

    def to_dict(self) -> dict:
        data = self.plan.to_dict()
        data["staged_path"] = self.staged_path
        data["staged_sha256"] = self.sha256
        return data


@dataclass(frozen=True)
class DeploymentResult:
    status: DeploymentStatus
    detail: str
    prepared: PreparedDeployment
    executed_automatically: bool = False
    error_code: str = ""

    @property
    def ok(self) -> bool:
        return self.status in (DeploymentStatus.ACTION_REQUIRED, DeploymentStatus.FLASHED)


@dataclass
class DeploymentExecutionContext:
    """Runtime capabilities supplied by the CLI, never by profile data."""

    confirm: Optional[Callable[[str], bool]] = None
    media_path_provider: Optional[Callable[[], str]] = None
    command_runner: Optional[Callable[..., object]] = None
