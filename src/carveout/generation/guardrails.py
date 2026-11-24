"""Reject generated document structures that reference unknown portfolio data."""
from __future__ import annotations

from typing import Any


def validate_document_references(
    document: dict[str, Any], known_asset_ids: set[str], known_waves: set[int]
) -> None:
    unknown_assets = sorted(set(document.get("asset_ids", [])) - known_asset_ids)
    if unknown_assets:
        raise ValueError(f"Document references unknown assets: {unknown_assets}")
    unknown_waves = sorted(set(document.get("wave_numbers", [])) - known_waves)
    if unknown_waves:
        raise ValueError(f"Document references unknown waves: {unknown_waves}")
