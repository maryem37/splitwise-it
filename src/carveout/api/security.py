"""Security, path allowlisting, and approval authorization for the API."""
from __future__ import annotations

import hmac
import os
from pathlib import Path
from fastapi import Header, HTTPException, status

ROOT_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT_DIR / "data"
RULES_PATH = ROOT_DIR / "config" / "strategy_rules.yaml"
CONSTRAINTS_PATH = ROOT_DIR / "config" / "constraints.yaml"

ALLOWED_PORTFOLIOS: dict[str, Path] = {
    "portfolio_v1": DATA_DIR / "portfolio_v1.yaml",
    "portfolio_v2": DATA_DIR / "portfolio_v2.yaml",
    "portfolio_v3": DATA_DIR / "portfolio_v3.yaml",
}


def resolve_portfolio_path(portfolio_id: str) -> Path:
    """Resolve a portfolio_id against an explicit allowlist to prevent path traversal."""
    clean_id = portfolio_id.strip()
    if clean_id not in ALLOWED_PORTFOLIOS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Portfolio '{clean_id}' not found. Available: {list(ALLOWED_PORTFOLIOS.keys())}",
        )
    path = ALLOWED_PORTFOLIOS[clean_id]
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Portfolio file for '{clean_id}' does not exist.",
        )
    return path


def verify_approval_authorization(x_approval_token: str | None = Header(default=None)) -> None:
    """
    Enforce authorization on human approval operations when CARVEOUT_APPROVAL_TOKEN is configured.
    In local development without CARVEOUT_APPROVAL_TOKEN set, requests are permitted.
    """
    expected = os.environ.get("CARVEOUT_APPROVAL_TOKEN", "").strip()
    if not expected:
        return
    if not x_approval_token or not hmac.compare_digest(x_approval_token, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized: valid X-Approval-Token header is required for approval operations.",
        )


def get_cors_origins() -> list[str]:
    raw = os.environ.get("CARVEOUT_CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000")
    return [o.strip() for o in raw.split(",") if o.strip()]


def validate_production_config(db_path: str | None = None) -> list[str]:
    """Validate runtime configuration and return non-fatal warnings."""
    import logging
    from carveout.workflows.checkpointer import validate_db_path

    log = logging.getLogger("carveout.api.config")
    warnings: list[str] = []

    validate_db_path(db_path)

    if not os.environ.get("CARVEOUT_APPROVAL_TOKEN", "").strip():
        msg = "CARVEOUT_APPROVAL_TOKEN is not set; human approval /resume endpoint is running in unauthenticated local mode."
        log.warning(msg)
        warnings.append(msg)

    origins = get_cors_origins()
    if "*" in origins:
        msg = "CARVEOUT_CORS_ORIGINS contains wildcard '*'; restrict origins in production."
        log.warning(msg)
        warnings.append(msg)

    return warnings
