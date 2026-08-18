"""Load the versioned board catalog and enforce exact global identity."""

from __future__ import annotations

from dataclasses import dataclass
import os
import unicodedata
from typing import Iterable, Optional

import yaml

from .models import BoardContract, BoardContractError


class BoardCatalogError(RuntimeError):
    pass


def default_contract_directory() -> str:
    return os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "data", "board_contracts", "v1")
    )


def normalize_exact_alias(value: object) -> str:
    """Normalize presentation only; deliberately perform no fuzzy matching."""
    return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()


@dataclass(frozen=True)
class CatalogEntry:
    contract: BoardContract
    source_path: str


class BoardCatalog:
    def __init__(self, entries: Iterable[CatalogEntry]):
        self.entries = tuple(entries)
        if not self.entries:
            raise BoardCatalogError("board contract catalog is empty")
        self._by_id: dict[str, CatalogEntry] = {}
        self._by_alias: dict[str, CatalogEntry] = {}
        self._build_indices()

    def _build_indices(self) -> None:
        for entry in self.entries:
            board_id = normalize_exact_alias(entry.contract.board_id)
            if board_id in self._by_id:
                raise BoardCatalogError(f"duplicate board_id: {entry.contract.board_id}")
            self._by_id[board_id] = entry

            candidates = (entry.contract.board_id,) + entry.contract.aliases
            seen_local: set[str] = set()
            for alias in candidates:
                normalized = normalize_exact_alias(alias)
                if not normalized:
                    raise BoardCatalogError(f"{entry.contract.board_id}: empty alias")
                if normalized in seen_local:
                    raise BoardCatalogError(
                        f"{entry.contract.board_id}: duplicate normalized alias {alias!r}"
                    )
                seen_local.add(normalized)
                owner = self._by_alias.get(normalized)
                if owner is not None:
                    raise BoardCatalogError(
                        "ambiguous exact alias "
                        f"{alias!r}: {owner.contract.board_id} and {entry.contract.board_id}"
                    )
                self._by_alias[normalized] = entry

    @classmethod
    def load(cls, directory: Optional[str] = None) -> "BoardCatalog":
        root = os.path.abspath(directory or default_contract_directory())
        if not os.path.isdir(root):
            raise BoardCatalogError(f"board contract directory not found: {root}")
        paths = sorted(
            os.path.join(root, name)
            for name in os.listdir(root)
            if name.endswith((".yaml", ".yml"))
        )
        entries = []
        for path in paths:
            try:
                with open(path, "r", encoding="utf-8") as source:
                    payload = yaml.safe_load(source)
                contract = BoardContract.from_mapping(payload, source=path)
            except (OSError, yaml.YAMLError, BoardContractError) as exc:
                raise BoardCatalogError(f"cannot load board contract {path}: {exc}") from exc
            entries.append(CatalogEntry(contract, path))
        return cls(entries)

    @property
    def contracts(self) -> tuple[BoardContract, ...]:
        return tuple(entry.contract for entry in self.entries)

    def by_id(self, board_id: object) -> Optional[BoardContract]:
        entry = self._by_id.get(normalize_exact_alias(board_id))
        return entry.contract if entry else None

    def resolve_exact(self, alias: object) -> Optional[BoardContract]:
        entry = self._by_alias.get(normalize_exact_alias(alias))
        return entry.contract if entry else None


_DEFAULT_CATALOG: Optional[BoardCatalog] = None


def load_default_catalog(*, refresh: bool = False) -> BoardCatalog:
    global _DEFAULT_CATALOG
    if refresh or _DEFAULT_CATALOG is None:
        _DEFAULT_CATALOG = BoardCatalog.load()
    return _DEFAULT_CATALOG
