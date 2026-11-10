"""Opt-in regression: provision and load pinned Klipper on ARMv7.

Requires Docker with ARM emulation, network for provision, and several minutes.
Set KACE_C3_ARMV7_DOCKER=1 to run the Docker integration explicitly.
"""
import json
import os
import subprocess

import pytest

from core import klipper_preflight as backend
from core.managed_config import build_managed_config_plan
from tests.integration.test_controller_fan_references import EXTRA, SECTION
from tests.integration.test_heater_options_contract import destination
from tests.unit.test_effective_xy_geometry import _context, _generate

pytestmark = pytest.mark.skipif(os.environ.get("KACE_C3_ARMV7_DOCKER") != "1",
                                reason="requires Docker and ARMv7 emulation")


def test_provision_and_validate_armv7(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCKER_DEFAULT_PLATFORM", "linux/arm/v7")
    monkeypatch.setenv("KACE_KLIPPER_PREFLIGHT_RECEIPT", str(tmp_path / "receipt.json"))
    receipt = backend.provision()
    inspect = subprocess.run(["docker", "image", "inspect", "--format", "{{.Os}}/{{.Architecture}}",
                              receipt["image_id"]], check=True, capture_output=True, text=True, timeout=30)
    assert inspect.stdout.strip() == "linux/arm"
    stored = json.loads((tmp_path / "receipt.json").read_text(encoding="utf-8"))
    assert stored == receipt
    base = _generate(tmp_path)
    geometry = _context(tmp_path, base)
    for value, expected in (("Missing", "invalid"), ("extruder, heater_bed", "valid")):
        remote = destination(base + EXTRA.encode(), SECTION, "heater", value, "include")
        plan = build_managed_config_plan(base, None, remote, geometry_context=geometry)
        result = backend.validate_plan(plan)
        assert result.status == expected, result.detail
        assert result.tree_digest == backend.plan_digest(plan)
