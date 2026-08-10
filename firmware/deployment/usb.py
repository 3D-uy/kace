"""Conservative direct USB firmware deployment."""

from __future__ import annotations

import hashlib
import shutil
import subprocess

from .models import (
    DeploymentArtifactError,
    DeploymentExecutionContext,
    DeploymentInstruction,
    DeploymentPlan,
    DeploymentResult,
    DeploymentStatus,
    DeploymentStrategyId,
    PreparedDeployment,
    require_deployable_artifact,
)


class UsbDeploymentMethod:
    _SUPPORTED_BACKENDS = frozenset({"avrdude"})

    @staticmethod
    def _sha256(path: str) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _automation_blockers(artifact, target, profile) -> tuple[str, ...]:
        blockers = []
        if profile.strategy is not DeploymentStrategyId.AVRDUDE:
            blockers.append("board profile is not an AVRDUDE strategy")
        if not profile.auto_flash:
            blockers.append("board profile does not allow automatic USB flashing")
        if profile.backend not in UsbDeploymentMethod._SUPPORTED_BACKENDS:
            blockers.append("USB backend is not supported")
        if not artifact.flashable:
            blockers.append("build artifact is not marked flashable")
        if not artifact.sha256:
            blockers.append("build artifact has no checksum")
        device = target.device_path or ""
        if not device.startswith("/dev/serial/by-id/"):
            blockers.append("a unique /dev/serial/by-id device is required")
        expected_vid_pids = profile.usb.application_vid_pids
        observed_vid_pid = target.usb_vid_pid
        if expected_vid_pids and not observed_vid_pid:
            blockers.append("USB VID:PID could not be verified")
        elif expected_vid_pids and observed_vid_pid not in expected_vid_pids:
            blockers.append(
                f"USB VID:PID {observed_vid_pid} is not allowed by the exact board profile"
            )
        return tuple(blockers)

    def plan(self, *, deployment_id, artifact, target, profile, translate) -> DeploymentPlan:
        require_deployable_artifact(artifact)
        blockers = self._automation_blockers(artifact, target, profile)
        instructions = tuple(
            DeploymentInstruction(
                key,
                translate(
                    key,
                    filename=profile.final_filename,
                    device=target.device_path or "USB",
                    board=target.board or "unknown board",
                ),
            )
            for key in profile.instruction_keys
        )
        return DeploymentPlan(
            deployment_id=deployment_id,
            method=profile.method,
            profile=profile,
            target=target,
            artifact=artifact,
            final_filename=profile.final_filename,
            instructions=instructions,
            automation_supported=bool(profile.auto_flash),
            automation_eligible=not blockers,
            automation_blockers=blockers,
        )

    @staticmethod
    def _avrdude_command(prepared: PreparedDeployment) -> list[str]:
        profile = prepared.plan.profile
        if profile.strategy is not DeploymentStrategyId.AVRDUDE:
            raise ValueError("USB profile is not an AVRDUDE strategy")
        options = profile.backend_options
        part = str(options.get("part", "")).strip()
        programmer = str(options.get("programmer", "")).strip()
        baud = int(options.get("baud", 0))
        if not part or not programmer or baud <= 0:
            raise ValueError("incomplete avrdude profile")
        return [
            "avrdude",
            "-p", part,
            "-c", programmer,
            "-P", prepared.plan.target.device_path,
            "-b", str(baud),
            "-U", f"flash:w:{prepared.staged_path}:i",
        ]

    def execute(
        self,
        prepared: PreparedDeployment,
        context: DeploymentExecutionContext,
    ) -> DeploymentResult:
        plan = prepared.plan
        try:
            require_deployable_artifact(plan.artifact)
            staged_digest = self._sha256(prepared.staged_path)
            if staged_digest != prepared.sha256 or staged_digest != plan.artifact.sha256:
                raise DeploymentArtifactError(
                    "prepared firmware checksum no longer matches the immutable artifact"
                )
        except (DeploymentArtifactError, OSError) as exc:
            return DeploymentResult(
                DeploymentStatus.FAILED,
                f"USB deployment rejected unsafe artifact: {exc}",
                prepared,
                error_code="ARTIFACT_UNSAFE",
            )
        if not plan.automation_eligible:
            return DeploymentResult(
                DeploymentStatus.ACTION_REQUIRED,
                "automatic USB flashing is unavailable: " + "; ".join(plan.automation_blockers),
                prepared,
                error_code="AUTOMATION_BLOCKED",
            )
        if context.confirm is None or not context.confirm(
            f"Flash {plan.target.board} via {plan.target.device_path}?"
        ):
            return DeploymentResult(
                DeploymentStatus.CANCELLED,
                "USB flashing cancelled before execution",
                prepared,
                error_code="CONFIRMATION_DECLINED",
            )
        if shutil.which(plan.profile.backend) is None:
            return DeploymentResult(
                DeploymentStatus.FAILED,
                f"required USB backend is not installed: {plan.profile.backend}",
                prepared,
                error_code="BACKEND_MISSING",
            )
        try:
            command = self._avrdude_command(prepared)
            runner = context.command_runner or subprocess.run
            runner(command, check=True, timeout=120)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            return DeploymentResult(
                DeploymentStatus.FAILED,
                f"USB flashing failed: {exc}",
                prepared,
                error_code="FLASH_FAILED",
            )
        return DeploymentResult(
            DeploymentStatus.FLASHED,
            "firmware flashed through the verified USB profile",
            prepared,
            executed_automatically=True,
        )
