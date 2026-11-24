"""Phase 2: load YAML into a Portfolio and run integrity checks."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import yaml
from pydantic import ValidationError

from .models import Owner, Portfolio


class PortfolioError(Exception):
    pass


def load_portfolio(path: str | Path) -> Portfolio:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return Portfolio.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError) as e:
        raise PortfolioError(f"Schema error in {path}:\n{e}") from e


def validate_portfolio(p: Portfolio) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    ids = [a.id for a in p.assets]
    for dup, n in Counter(ids).items():
        if n > 1:
            errors.append(f"Duplicate asset id: {dup}")
    known = set(ids)
    lic = {l.id for l in p.licences}
    tsa = {t.id for t in p.tsa_services}
    for label, values in (("licence", [l.id for l in p.licences]),
                          ("TSA service", [t.id for t in p.tsa_services])):
        for duplicate, count in Counter(values).items():
            if count > 1:
                errors.append(f"Duplicate {label} id: {duplicate}")

    for r in p.relationships:
        for end in (r.source, r.target):
            if end not in known:
                errors.append(f"Relationship {r.source}->{r.target}: unknown asset {end}")
        if r.source == r.target:
            errors.append(f"Self-dependency on {r.source}")

    for a in p.assets:
        if a.licence_id and a.licence_id not in lic:
            errors.append(f"{a.id}: unknown licence {a.licence_id}")
        if a.tsa_id and a.tsa_id not in tsa:
            errors.append(f"{a.id}: unknown TSA service {a.tsa_id}")
        if a.owner == Owner.SHARED and not a.tsa_id:
            warnings.append(f"{a.id}: shared asset without a TSA service")

    connected = {r.source for r in p.relationships} | {r.target for r in p.relationships}
    for a in p.assets:
        if a.id not in connected:
            warnings.append(f"{a.id}: isolated asset (no relationships)")

    return {"valid": not errors, "errors": errors, "warnings": warnings,
            "counts": {"assets": len(p.assets), "relationships": len(p.relationships),
                       "licences": len(p.licences), "tsa_services": len(p.tsa_services)}}


def write_report(report: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(report, indent=2), encoding="utf-8")
