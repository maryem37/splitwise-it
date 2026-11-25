"""Tests for Phase 5 FastAPI backend, security controls, and E2E restart recovery."""
from __future__ import annotations

import os
from pathlib import Path
from fastapi.testclient import TestClient

from carveout.api.app import create_app


def test_api_health_and_ui(tmp_path: Path):
    app = create_app(db_path=str(tmp_path / "api_test.sqlite"))
    client = TestClient(app)

    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    ui_res = client.get("/")
    assert ui_res.status_code == 200
    assert "Carve-out Copilot" in ui_res.text


def test_portfolio_endpoints_and_path_traversal_protection(tmp_path: Path):
    app = create_app(db_path=str(tmp_path / "api_test.sqlite"))
    client = TestClient(app)

    res = client.get("/api/portfolios")
    assert res.status_code == 200
    ids = [p["portfolio_id"] for p in res.json()]
    assert "portfolio_v1" in ids

    detail = client.get("/api/portfolios/portfolio_v1")
    assert detail.status_code == 200
    assert detail.json()["company"] == "Nordia Retail"
    assert detail.json()["asset_count"] > 0

    # Path traversal / unknown portfolio rejected
    bad = client.get("/api/portfolios/..%2F..%2Fetc%2Fpasswd")
    assert bad.status_code == 404


def test_e2e_user_journey_with_restart_and_auth(tmp_path: Path, monkeypatch):
    db_file = str(tmp_path / "e2e_restart.sqlite")
    thread_id = "e2e-journey-thread-1"

    # 1. Start App Instance 1 & launch workflow with human_review=True
    app1 = create_app(db_path=db_file)
    client1 = TestClient(app1)

    launch = client1.post(
        "/api/workflows",
        json={
            "portfolio_id": "portfolio_v1",
            "user_request": "Investigate APP-06 delay and optimize",
            "thread_id": thread_id,
            "human_review": True,
        },
    )
    assert launch.status_code == 200
    data1 = launch.json()
    assert data1["interrupted"] is True
    assert data1["workflow_status"] == "interrupted"

    # Duplicate thread_id launch is rejected with 409
    dup = client1.post(
        "/api/workflows",
        json={
            "portfolio_id": "portfolio_v1",
            "user_request": "Duplicate",
            "thread_id": thread_id,
        },
    )
    assert dup.status_code == 409

    # 2. Simulate application restart: new FastAPI instance pointing to same SQLite DB
    app2 = create_app(db_path=db_file)
    client2 = TestClient(app2)

    status_res = client2.get(f"/api/workflows/{thread_id}/status")
    assert status_res.status_code == 200
    assert status_res.json()["interrupted"] is True
    assert status_res.json()["interrupt_payload"] is not None

    # 3. Test approval authorization when CARVEOUT_APPROVAL_TOKEN is configured
    monkeypatch.setenv("CARVEOUT_APPROVAL_TOKEN", "secret-approver-token")
    unauth = client2.post(
        f"/api/workflows/{thread_id}/resume",
        json={"action": "APPROVE", "reviewer": "alice", "comment": "ok"},
    )
    assert unauth.status_code == 403

    # 4. Resume with valid token
    auth_res = client2.post(
        f"/api/workflows/{thread_id}/resume",
        headers={"X-Approval-Token": "secret-approver-token"},
        json={"action": "APPROVE", "reviewer": "alice", "comment": "Approved after restart"},
    )
    assert auth_res.status_code == 200
    assert auth_res.json()["approval_status"] == "approved"
    assert auth_res.json()["interrupted"] is False

    # 5. Decision intelligence, comparison, scenario, and reports endpoints
    exp = client2.get("/api/assets/APP-06/explanation?portfolio_id=portfolio_v1")
    assert exp.status_code == 200
    assert exp.json()["asset_id"] == "APP-06"

    comp = client2.get("/api/comparisons?portfolio_id=portfolio_v1&scenario=minimize_cost")
    assert comp.status_code == 200
    assert comp.json()["optimized"]["solver_status"] in ("OPTIMAL", "FEASIBLE")

    scen = client2.post(
        "/api/scenarios",
        json={
            "portfolio_id": "portfolio_v1",
            "scenario_id": "app06_12w",
            "scenario_name": "APP-06 12w Delay",
            "delay_weeks": {"APP-06": 12, "APP-07": 12},
        },
    )
    assert scen.status_code == 200
    assert scen.json()["solver_status"] in ("OPTIMAL", "FEASIBLE")

    rep_md = client2.get("/api/reports/portfolio_v1?format=markdown")
    assert rep_md.status_code == 200
    assert "Nordia Retail" in rep_md.text

    rep_json = client2.get("/api/reports/portfolio_v1?format=json")
    assert rep_json.status_code == 200
    assert rep_json.json()["company"] == "Nordia Retail"
