"""Manual firmware delivery: stage/copy the exact file and instruct the user."""

from __future__ import annotations

import os
import shutil
import hashlib
import tempfile

from .models import (
    DeploymentExecutionContext,
    DeploymentInstruction,
    DeploymentPlan,
    DeploymentResult,
    DeploymentStatus,
    PreparedDeployment,
)


class ManualDeploymentMethod:
    @staticmethod
    def _sha256(path: str) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def plan(self, *, deployment_id, artifact, target, profile, translate) -> DeploymentPlan:
        instructions = tuple(
            DeploymentInstruction(
                key,
                translate(key, filename=profile.final_filename),
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
            automation_supported=False,
            automation_eligible=False,
            automation_blockers=("manual deployment requires user action",),
        )

    def execute(
        self,
        prepared: PreparedDeployment,
        context: DeploymentExecutionContext,
    ) -> DeploymentResult:
        if context.media_path_provider is not None:
            destination = context.media_path_provider()
            if not destination:
                return DeploymentResult(
                    DeploymentStatus.CANCELLED,
                    "manual destination selection cancelled",
                    prepared,
                    error_code="DESTINATION_CANCELLED",
                )
            destination = os.path.abspath(os.path.expanduser(destination))
            if not os.path.isdir(destination):
                return DeploymentResult(
                    DeploymentStatus.FAILED,
                    f"manual destination is not a directory: {destination}",
                    prepared,
                    error_code="INVALID_DESTINATION",
                )
            target_path = os.path.join(destination, prepared.plan.final_filename)
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(dir=destination, delete=False) as temporary:
                    tmp_path = temporary.name
                shutil.copy2(prepared.staged_path, tmp_path)
                if self._sha256(tmp_path) != prepared.sha256:
                    raise OSError("destination checksum mismatch")
                os.replace(tmp_path, target_path)
            except OSError as exc:
                return DeploymentResult(
                    DeploymentStatus.FAILED,
                    f"could not copy firmware to manual destination: {exc}",
                    prepared,
                    error_code="COPY_FAILED",
                )
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
            detail = f"{prepared.plan.final_filename} copied to {destination}"
        else:
            detail = f"{prepared.plan.final_filename} is ready for manual installation"
        return DeploymentResult(DeploymentStatus.ACTION_REQUIRED, detail, prepared)
