"""Compatibility tests consume the same source contract as BoardContract."""

from firmware.boards.upstream import load_klipper_source_contract

_SOURCE = load_klipper_source_contract()
KLIPPER_REPO_URL = _SOURCE.repository
KLIPPER_REF = _SOURCE.validated_commit
