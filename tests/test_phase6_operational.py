"""Tests for Phase 6 operational readiness, liveness/readiness probes, and API telemetry."""
from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from carveout.api.app import create_app
from carveout.api.security import validate_production_config


def test_liveness_and_readiness_probes(tmp_path: Path):
    db_file = str(tmp_path / "ready_test.sqlite")
    app = create_app(db_path=db_file)
    with TestClient(app) as client:
        live = client.get("/api/health")
        assert live.status_code == 200
        assert live.json()["status"] == "ok"

        ready = client.get("/api/ready")
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready"
        assert ready.json()["persistence"] == "sqlite"


def test_readiness_fails_when_db_path_is_directory(tmp_path: Path):
    bad_dir = tmp_path / "not_a_file"
    bad_dir.mkdir()
    app = create_app(db_path=str(bad_dir))
    client = TestClient(app)

    ready = client.get("/api/ready")
    assert ready.status_code == 503
    assert "checkpoint persistence unavailable" in ready.json()["detail"]


def test_api_telemetry_metrics_recorded(tmp_path: Path):
    app = create_app(db_path=str(tmp_path / "metrics_test.sqlite"))
    client = TestClient(app)

    client.get("/api/health")
    client.get("/api/portfolios/nonexistent_id")

    metrics = client.get("/api/metrics")
    assert metrics.status_code == 200
    data = metrics.json()
    assert data["total_requests"] >= 2
    assert data["status_counts"].get("200", 0) >= 1
    assert data["status_counts"].get("404", 0) >= 1
    assert data["avg_request_duration_ms"] >= 0.0


def test_production_config_validation_warnings(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("CARVEOUT_APPROVAL_TOKEN", raising=False)
    monkeypatch.setenv("CARVEOUT_CORS_ORIGINS", "*")
    warnings = validate_production_config(db_path=str(tmp_path / "cfg.sqlite"))
    assert len(warnings) == 2
