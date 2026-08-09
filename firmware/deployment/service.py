"""Plan, stage, execute and persist firmware deployments."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import uuid
from typing import Callable, Optional

from core.translations import t

from .models import (
    DeploymentExecutionContext,
    DeploymentMethodId,
    DeploymentResult,
    DeploymentStatus,
    DeploymentTarget,
    PreparedDeployment,
)
from .profiles import DeploymentProfileResolver
from .registry import DeploymentMethodRegistry


EVENT_PREFIX = "=== KACE_WORKFLOW_EVENT: "


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class FirmwareDeploymentService:
    def __init__(
        self,
        *,
        resolver: Optional[DeploymentProfileResolver] = None,
        registry: Optional[DeploymentMethodRegistry] = None,
        output_dir: str = "~/kace",
        translate: Callable[..., str] = t,
        event_sink: Optional[Callable[[dict], None]] = None,
    ):
        self.resolver = resolver or DeploymentProfileResolver()
        self.registry = registry or DeploymentMethodRegistry()
        self.output_dir = os.path.abspath(os.path.expanduser(output_dir))
        self.translate = translate
        self.event_sink = event_sink or self._json_event_sink
        self._sequences: dict[str, int] = {}

    @staticmethod
    def _json_event_sink(event: dict) -> None:
        print(f"{EVENT_PREFIX}{json.dumps(event, sort_keys=True)} ===", file=sys.stdout, flush=True)

    def _emit(self, deployment_id: str, state: str, detail: str, **data) -> None:
        sequence = self._sequences.get(deployment_id, 0) + 1
        self._sequences[deployment_id] = sequence
        event = {
            "schema": 2,
            "workflow_kind": "firmware_deployment",
            "workflow_id": deployment_id,
            "sequence": sequence,
            "state": state,
            "detail": detail,
        }
        if data:
            event["data"] = data
        self.event_sink(event)

    def available_methods(self, target: DeploymentTarget, artifact) -> tuple[DeploymentMethodId, ...]:
        profiles = self.resolver.available(target, artifact.format)
        return tuple(dict.fromkeys(profile.method for profile in profiles))

    def plan(self, artifact, target: DeploymentTarget, method: DeploymentMethodId):
        method = DeploymentMethodId(method)
        profile = self.resolver.resolve(target, artifact.format, method)
        deployment_id = str(uuid.uuid4())
        strategy = self.registry.get(method)
        plan = strategy.plan(
            deployment_id=deployment_id,
            artifact=artifact,
            target=target,
            profile=profile,
            translate=self.translate,
        )
        self._emit(
            deployment_id,
            "DEPLOYMENT_PLANNED",
            f"{method.value} deployment planned",
            method=method.value,
            final_filename=plan.final_filename,
            automation=plan.to_dict()["automation"],
        )
        return plan

    def prepare(self, plan) -> PreparedDeployment:
        self._emit(plan.deployment_id, "PREPARING_ARTIFACT", "preparing deployment artifact")
        deployment_dir = os.path.join(self.output_dir, "deploy", plan.deployment_id)
        os.makedirs(deployment_dir, exist_ok=True)
        staged_path = os.path.join(deployment_dir, plan.final_filename)
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=deployment_dir, delete=False) as temporary:
                tmp_path = temporary.name
            shutil.copy2(plan.artifact.path, tmp_path)
            os.replace(tmp_path, staged_path)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        digest = _sha256(staged_path)
        if plan.artifact.sha256 and digest != plan.artifact.sha256:
            raise RuntimeError("staged firmware checksum does not match build artifact")
        identity = getattr(plan.artifact, "firmware_identity", None)
        if identity is not None and digest != identity.artifact_sha256:
            raise RuntimeError("staged firmware checksum does not match firmware build identity")
        prepared = PreparedDeployment(plan=plan, staged_path=staged_path, sha256=digest)
        self._emit(
            plan.deployment_id,
            "ARTIFACT_READY",
            f"{plan.final_filename} ready",
            method=plan.method.value,
            final_filename=plan.final_filename,
            staged_path=staged_path,
            sha256=digest,
            instructions=[item.__dict__ for item in plan.instructions],
            automation=plan.to_dict()["automation"],
        )
        self._write_manifest(prepared, "ARTIFACT_READY")
        return prepared

    def execute(
        self,
        prepared: PreparedDeployment,
        context: Optional[DeploymentExecutionContext] = None,
    ) -> DeploymentResult:
        context = context or DeploymentExecutionContext()
        plan = prepared.plan
        state = "FLASHING" if plan.automation_eligible else "AWAITING_USER_ACTION"
        self._emit(
            plan.deployment_id,
            state,
            f"executing {plan.method.value} deployment",
            method=plan.method.value,
            instructions=[item.__dict__ for item in plan.instructions],
        )
        result = self.registry.get(plan.method).execute(prepared, context)
        terminal_state = {
            DeploymentStatus.ACTION_REQUIRED: "ACTION_REQUIRED",
            DeploymentStatus.FLASHED: "FLASHED",
            DeploymentStatus.CANCELLED: "CANCELLED",
            DeploymentStatus.FAILED: "FAILED_FLASH",
        }[result.status]
        self._emit(
            plan.deployment_id,
            terminal_state,
            result.detail,
            method=plan.method.value,
            final_filename=plan.final_filename,
            staged_path=prepared.staged_path,
            executed_automatically=result.executed_automatically,
            error_code=result.error_code,
        )
        self._write_manifest(prepared, terminal_state, result=result)
        return result

    def _write_manifest(self, prepared: PreparedDeployment, state: str, result=None) -> None:
        payload = {
            "schema": 1,
            "workflow_kind": "firmware_deployment",
            "workflow_id": prepared.plan.deployment_id,
            "sequence": self._sequences.get(prepared.plan.deployment_id, 0),
            "state": state,
            "deployment": prepared.to_dict(),
        }
        identity = getattr(prepared.plan.artifact, "firmware_identity", None)
        if identity is not None:
            payload["firmware_identity"] = identity.to_dict()
        if result is not None:
            payload["result"] = {
                "status": result.status.value,
                "detail": result.detail,
                "executed_automatically": result.executed_automatically,
                "error_code": result.error_code,
            }
        os.makedirs(self.output_dir, exist_ok=True)
        manifest_path = os.path.join(self.output_dir, "deployment-manifest.json")
        fd, tmp_path = tempfile.mkstemp(prefix="deployment-manifest-", suffix=".json", dir=self.output_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as target:
                json.dump(payload, target, indent=2, sort_keys=True)
                target.write("\n")
            os.replace(tmp_path, manifest_path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
