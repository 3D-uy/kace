"""Preflight fixture for tests exercising unrelated deployment boundaries."""
from core.klipper_preflight import PreflightResult, plan_digest


def valid_preflight(plan):
    return PreflightResult("valid", "isolated test fixture", plan_digest(plan))
