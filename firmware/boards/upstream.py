"""Pure helpers for pinned Klipper evidence and upstream drift detection."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
import re
from typing import Optional

import yaml

from .models import BoardContract


class UpstreamContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class KlipperSourceContract:
    schema: str
    repository: str
    validated_commit: str
    header_extraction_version: int
    line_endings: str
    upstream_monitor_ref: str
    upstream_monitor_mutation_allowed: bool


@dataclass(frozen=True)
class UpstreamVerification:
    config_hash_matches: bool
    header_hash_matches: bool
    header_text_matches: bool
    observed_config_sha256_lf: str
    observed_header_sha256_lf: str
    observed_header_text: str

    @property
    def ok(self) -> bool:
        return self.config_hash_matches and self.header_hash_matches and self.header_text_matches


def default_source_contract_path() -> str:
    return os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "data", "klipper_contract.yaml")
    )


def load_klipper_source_contract(path: Optional[str] = None) -> KlipperSourceContract:
    source_path = path or default_source_contract_path()
    try:
        with open(source_path, "r", encoding="utf-8") as source:
            data = yaml.safe_load(source) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise UpstreamContractError(f"cannot load Klipper source contract: {exc}") from exc
    if data.get("schema") != "kace-klipper-source/v1":
        raise UpstreamContractError("unsupported Klipper source contract schema")
    commit = str(data.get("validated_commit", "")).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise UpstreamContractError("validated_commit must be a full Git SHA")
    if data.get("line_endings") != "LF":
        raise UpstreamContractError("only canonical LF line endings are supported")
    version = data.get("header_extraction_version")
    if version != 1:
        raise UpstreamContractError("unsupported header extraction version")
    monitor = data.get("upstream_monitor")
    if not isinstance(monitor, dict):
        raise UpstreamContractError("upstream_monitor must be an object")
    monitor_ref = str(monitor.get("ref", "")).strip()
    if not monitor_ref.startswith("refs/heads/"):
        raise UpstreamContractError("upstream_monitor.ref must name a branch ref")
    mutation_allowed = monitor.get("mutation_allowed")
    if mutation_allowed is not False:
        raise UpstreamContractError("upstream monitoring must be read-only")
    return KlipperSourceContract(
        schema=data["schema"],
        repository=str(data.get("repository", "")).strip(),
        validated_commit=commit,
        header_extraction_version=version,
        line_endings="LF",
        upstream_monitor_ref=monitor_ref,
        upstream_monitor_mutation_allowed=False,
    )


def normalize_lf(content: bytes | str) -> str:
    if isinstance(content, bytes):
        content = content.decode("utf-8")
    return str(content).replace("\r\n", "\n").replace("\r", "\n")


def extract_official_header(content: bytes | str, *, version: int = 1) -> str:
    """Extract the reviewed preamble, ending at Klipper's standard reference line."""
    if version != 1:
        raise UpstreamContractError(f"unsupported header extraction version: {version}")
    lines = normalize_lf(content).splitlines(keepends=True)
    end = None
    for index, line in enumerate(lines):
        if line.lstrip().startswith("# See docs/Config_Reference.md"):
            end = index + 1
            while end < len(lines) and not lines[end].strip():
                end += 1
            break
    if end is None:
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped and not line.lstrip().startswith("#"):
                end = index
                break
    if end is None:
        raise UpstreamContractError("could not locate the end of the official header")
    header = "".join(lines[:end])
    if not header.strip():
        raise UpstreamContractError("official header is empty")
    return header


def sha256_lf(content: bytes | str) -> str:
    return hashlib.sha256(normalize_lf(content).encode("utf-8")).hexdigest()


def verify_upstream_content(
    contract: BoardContract,
    content: bytes | str,
    *,
    source_contract: Optional[KlipperSourceContract] = None,
) -> UpstreamVerification:
    source = source_contract or load_klipper_source_contract()
    if contract.upstream.validated_commit != source.validated_commit:
        raise UpstreamContractError(
            f"{contract.board_id}: board and global validated commits differ"
        )
    if contract.upstream.repository != source.repository:
        raise UpstreamContractError(
            f"{contract.board_id}: board and global repositories differ"
        )
    normalized = normalize_lf(content)
    header = extract_official_header(normalized, version=source.header_extraction_version)
    config_hash = sha256_lf(normalized)
    header_hash = sha256_lf(header)
    return UpstreamVerification(
        config_hash_matches=config_hash == contract.upstream.config_sha256_lf,
        header_hash_matches=header_hash == contract.upstream.header_sha256_lf,
        header_text_matches=header == normalize_lf(contract.upstream.header_text),
        observed_config_sha256_lf=config_hash,
        observed_header_sha256_lf=header_hash,
        observed_header_text=header,
    )
