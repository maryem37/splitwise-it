"""Reject generated document structures that reference unknown portfolio data."""
from __future__ import annotations

import re
from typing import Any

_FORBIDDEN_GUARANTEE_RE = re.compile(r"\b(guarantee\w*|uninterrupted)\b", re.IGNORECASE)
_INDEPENDENT_WAVES_RE = re.compile(
    r"\b(independent\s+waves?|waves?\s+(?:is|are)\s+independent|each\s+wave\s+is\s+independent)\b",
    re.IGNORECASE,
)
_RENAMED_TSA_RE = re.compile(
    r"(?<!transitional\s)\b(security|service|technical\s+support|support)\s+agreement\b",
    re.IGNORECASE,
)
_REHOST_RE = re.compile(r"\bre-?host\w*\b", re.IGNORECASE)
_FINAL_RE = re.compile(r"\bfinal\b", re.IGNORECASE)
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def validate_document_references(
    document: dict[str, Any], known_asset_ids: set[str], known_waves: set[int]
) -> None:
    unknown_assets = sorted(set(document.get("asset_ids", [])) - known_asset_ids)
    if unknown_assets:
        raise ValueError(f"Document references unknown assets: {unknown_assets}")
    unknown_waves = sorted(set(document.get("wave_numbers", [])) - known_waves)
    if unknown_waves:
        raise ValueError(f"Document references unknown waves: {unknown_waves}")


def validate_narrative_content(
    narrative: str,
    known_dates: set[str] | None = None,
    has_retired_assets: bool = False,
    is_final_wave: bool = True,
) -> None:
    """Reject ungrounded claims, forbidden terms, and invented dates in LLM prose."""
    if match := _FORBIDDEN_GUARANTEE_RE.search(narrative):
        raise ValueError(f"Narrative uses forbidden guarantee term: {match.group(0)!r}")
    if match := _INDEPENDENT_WAVES_RE.search(narrative):
        raise ValueError(f"Narrative falsely claims independent waves: {match.group(0)!r}")
    if match := _RENAMED_TSA_RE.search(narrative):
        raise ValueError(f"Narrative misnames TSA as: {match.group(0)!r}")
    if has_retired_assets and (match := _REHOST_RE.search(narrative)):
        raise ValueError(f"Narrative mentions re-hosting in a wave with retired assets: {match.group(0)!r}")
    if not is_final_wave and (match := _FINAL_RE.search(narrative)):
        raise ValueError(f"Narrative uses 'final' for a non-final wave: {match.group(0)!r}")
    if known_dates is not None:
        invented_dates = sorted(set(_ISO_DATE_RE.findall(narrative)) - known_dates)
        if invented_dates:
            raise ValueError(f"Narrative invents unknown dates: {invented_dates}")
