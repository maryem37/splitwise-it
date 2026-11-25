"""FastAPI application for Carve-out Copilot."""
from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from carveout.comparison import compare_baseline_and_optimized
from carveout.decision_report import generate_decision_report
from carveout.explain import explain_asset_planning
from carveout.loader import load_portfolio
from carveout.logging_config import configure_logging
from carveout.metrics import calculate_metrics
from carveout.scenarios_manager import WhatIfScenarioConfig, run_what_if_scenario
from carveout.sequencing import compute_waves
from carveout.strategy import assess_strategies
from carveout.workflows.checkpointer import checkpoint_exists, get_default_db_path
from carveout.workflows.graph import get_workflow_state, resume_agent_workflow, run_agent_workflow

from .schemas import (
    HealthResponse,
    PortfolioSummaryItem,
    ScenarioRunRequest,
    WorkflowLaunchRequest,
    WorkflowLaunchResponse,
    WorkflowResumeRequest,
    WorkflowStatusResponse,
)
from .security import (
    ALLOWED_PORTFOLIOS,
    CONSTRAINTS_PATH,
    RULES_PATH,
    get_cors_origins,
    resolve_portfolio_path,
    validate_production_config,
    verify_approval_authorization,
)
from .telemetry import TelemetryTracker
from .ui import WEB_UI_HTML

logger = logging.getLogger("carveout.api")


def create_app(db_path: str | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    configure_logging()
    telemetry = TelemetryTracker()

    def _db() -> str:
        return db_path or str(get_default_db_path())

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        logger.info("Starting Carve-out Copilot API...")
        validate_production_config(_db())
        yield
        logger.info("Shutting down Carve-out Copilot API gracefully.")

    app = FastAPI(
        title="Carve-out Copilot API",
        description="Agentic IT separation planning, CP-SAT optimization, and decision intelligence API.",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _observability_middleware(request: Request, call_next: Any) -> Any:
        t0 = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - t0) * 1000.0
        telemetry.record_request(response.status_code, duration_ms)
        logger.info(f"{request.method} {request.url.path} -> {response.status_code} ({duration_ms:.1f}ms)")
        return response

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(f"Unhandled API error on {request.url.path}: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error. Check server logs for diagnostics."},
        )

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def serve_ui() -> HTMLResponse:
        return HTMLResponse(content=WEB_UI_HTML)

    @app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
    def serve_embedded_dashboard(portfolio_id: str = Query(default="portfolio_v1")) -> HTMLResponse:
        """Serve the self-contained visual dashboard (Graph, Gantt, Risks, TSA Costs)."""
        from pathlib import Path
        import tempfile
        from carveout.dashboard import export_dashboard
        from carveout.generation.documents import build_risk_register

        if portfolio_id == "portfolio_v1":
            static_dash = Path("output/dashboard.html")
            if static_dash.exists():
                return HTMLResponse(content=static_dash.read_text(encoding="utf-8"))

        path = resolve_portfolio_path(portfolio_id)
        p = load_portfolio(path)
        strategies = assess_strategies(p, RULES_PATH)
        seq = compute_waves(p, CONSTRAINTS_PATH, strategies=strategies)
        metrics = calculate_metrics(p, seq)
        risks = build_risk_register(p, seq, strategies)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "dashboard.html"
            export_dashboard(p, strategies, seq, metrics, risks, out_path)
            return HTMLResponse(content=out_path.read_text(encoding="utf-8"))

    @app.get("/graph", response_class=HTMLResponse, include_in_schema=False)
    def serve_embedded_graph() -> HTMLResponse:
        """Serve the force-directed dependency graph if generated."""
        from pathlib import Path

        graph_path = Path("output/graph.html")
        if graph_path.exists():
            return HTMLResponse(content=graph_path.read_text(encoding="utf-8"))
        return HTMLResponse(
            content="<html><body style='font-family:sans-serif;padding:24px'><h2>Graph not generated yet</h2><p>Run <code>carveout run-all</code> first to generate <code>output/graph.html</code>.</p></body></html>"
        )

    @app.get("/api/health", response_model=HealthResponse, tags=["System"])
    def health_check() -> HealthResponse:
        """Liveness probe: confirms the API process is running."""
        return HealthResponse()

    @app.get("/api/ready", tags=["System"])
    def readiness_check() -> dict[str, Any]:
        """Readiness probe: verifies SQLite checkpoint storage and portfolio data availability."""
        from carveout.workflows.checkpointer import get_checkpointer
        try:
            with get_checkpointer(db_path=_db()) as _:
                pass
        except Exception as exc:
            logger.error(f"Readiness check failed: SQLite persistence unavailable: {exc}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Readiness check failed: checkpoint persistence unavailable.",
            ) from exc

        portfolios_ok = any(p.exists() for p in ALLOWED_PORTFOLIOS.values())
        if not portfolios_ok:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Readiness check failed: no portfolio data files available.",
            )
        return {"status": "ready", "persistence": "sqlite", "portfolios_available": True}

    @app.get("/api/metrics", tags=["System"])
    def get_api_metrics() -> dict[str, Any]:
        """Return lightweight in-process API and workflow telemetry."""
        return telemetry.snapshot()

    @app.get("/api/portfolios", response_model=list[PortfolioSummaryItem], tags=["Portfolios"])
    def list_portfolios() -> list[PortfolioSummaryItem]:
        items: list[PortfolioSummaryItem] = []
        for pid, path in ALLOWED_PORTFOLIOS.items():
            if path.exists():
                p = load_portfolio(path)
                items.append(
                    PortfolioSummaryItem(
                        portfolio_id=pid,
                        company=p.planning.company,
                        description=p.planning.carve_out_description,
                        asset_count=len(p.assets),
                        tsa_count=len(p.tsa_services),
                    )
                )
        return items

    @app.get("/api/portfolios/{portfolio_id}", tags=["Portfolios"])
    def get_portfolio_detail(portfolio_id: str) -> dict[str, Any]:
        path = resolve_portfolio_path(portfolio_id)
        p = load_portfolio(path)
        strategies = assess_strategies(p, RULES_PATH)
        seq = compute_waves(p, CONSTRAINTS_PATH, strategies=strategies)
        metrics = calculate_metrics(p, seq)
        return {
            "portfolio_id": portfolio_id,
            "company": p.planning.company,
            "description": p.planning.carve_out_description,
            "day1": p.planning.day1.isoformat(),
            "target_tsa_exit": p.planning.target_tsa_exit.isoformat(),
            "asset_count": len(p.assets),
            "wave_count": metrics["wave_count"],
            "cycle_count": metrics["cycle_count"],
            "cycles": seq.get("cycles", []),
            "conflict_count": len(seq.get("conflicts", [])),
            "conflicts": seq.get("conflicts", []),
            "latest_planned_completion": metrics["latest_planned_completion"],
            "estimated_tsa_cost_total": metrics["estimated_tsa_cost_total"],
            "assets": [
                {
                    "id": a.id,
                    "name": a.name,
                    "type": a.type.value,
                    "owner": a.owner.value,
                    "criticality": a.criticality,
                }
                for a in p.assets
            ],
            "waves": seq["waves"],
        }

    @app.post("/api/workflows", response_model=WorkflowLaunchResponse, tags=["Workflows"])
    def launch_workflow(req: WorkflowLaunchRequest) -> WorkflowLaunchResponse:
        path = resolve_portfolio_path(req.portfolio_id)
        tid = (req.thread_id or f"api-{uuid.uuid4().hex[:10]}").strip()

        if req.thread_id and checkpoint_exists(tid, db_path=_db()):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Workflow thread '{tid}' already exists. Use a new thread_id or inspect/resume the existing thread.",
            )

        res = run_agent_workflow(
            user_request=req.user_request,
            portfolio_path=str(path),
            rules_path=str(RULES_PATH),
            constraints_path=str(CONSTRAINTS_PATH),
            thread_id=tid,
            human_review=req.human_review,
            max_correction_attempts=req.max_correction_attempts,
            db_path=_db(),
        )

        interrupted = "__interrupt__" in res
        wf_status = "interrupted" if interrupted else res.get("workflow_status", "completed")
        telemetry.record_workflow(wf_status)
        return WorkflowLaunchResponse(
            thread_id=tid,
            workflow_status=wf_status,
            approval_status=res.get("approval_status", "pending"),
            interrupted=interrupted,
            evaluation_status=res.get("evaluation_report", {}).get("status"),
            critic_decision=res.get("critic_decision", {}).get("decision"),
            metrics=res.get("metrics", {}),
            final_response=res.get("final_response", ""),
            errors=res.get("errors", []),
        )

    @app.get("/api/workflows/{thread_id}/status", response_model=WorkflowStatusResponse, tags=["Workflows"])
    def get_workflow_status(thread_id: str) -> WorkflowStatusResponse:
        if not checkpoint_exists(thread_id, db_path=_db()):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No checkpoint found for thread_id '{thread_id}'.",
            )
        snap = get_workflow_state(thread_id=thread_id, db_path=_db())
        if not snap or not snap.values:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No checkpoint state found for thread_id '{thread_id}'.",
            )
        vals = snap.values
        interrupted = bool(snap.tasks and hasattr(snap.tasks[0], "interrupts") and snap.tasks[0].interrupts)
        interrupt_payload = None
        if interrupted:
            raw_int = snap.tasks[0].interrupts[0]
            interrupt_payload = raw_int.value if hasattr(raw_int, "value") else None

        wf_status = "interrupted" if interrupted else vals.get("workflow_status", "unknown")
        return WorkflowStatusResponse(
            thread_id=thread_id,
            workflow_status=wf_status,
            approval_status=vals.get("approval_status", "unknown"),
            interrupted=interrupted,
            next_nodes=list(snap.next),
            evaluation_status=vals.get("evaluation_report", {}).get("status"),
            critic_decision=vals.get("critic_decision", {}).get("decision"),
            correction_attempts=int(vals.get("correction_attempts", 0)),
            max_correction_attempts=int(vals.get("max_correction_attempts", 2)),
            metrics=vals.get("metrics", {}),
            interrupt_payload=interrupt_payload,
        )

    @app.get("/api/workflows/{thread_id}", tags=["Workflows"])
    def get_workflow_detail(thread_id: str) -> dict[str, Any]:
        if not checkpoint_exists(thread_id, db_path=_db()):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No checkpoint found for thread_id '{thread_id}'.",
            )
        snap = get_workflow_state(thread_id=thread_id, db_path=_db())
        vals = snap.values if snap else {}
        return {
            "thread_id": thread_id,
            "workflow_status": vals.get("workflow_status", "unknown"),
            "approval_status": vals.get("approval_status", "unknown"),
            "evaluation_report": vals.get("evaluation_report", {}),
            "critic_decision": vals.get("critic_decision", {}),
            "metrics": vals.get("metrics", {}),
            "final_response": vals.get("final_response", ""),
            "errors": vals.get("errors", []),
        }

    @app.post(
        "/api/workflows/{thread_id}/resume",
        response_model=WorkflowLaunchResponse,
        tags=["Workflows"],
        dependencies=[Depends(verify_approval_authorization)],
    )
    def resume_workflow(thread_id: str, req: WorkflowResumeRequest) -> WorkflowLaunchResponse:
        if not checkpoint_exists(thread_id, db_path=_db()):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No checkpoint found for thread_id '{thread_id}'.",
            )
        res = resume_agent_workflow(
            thread_id=thread_id,
            decision={"action": req.action, "reviewer": req.reviewer, "comment": req.comment},
            db_path=_db(),
        )
        interrupted = "__interrupt__" in res
        wf_status = "interrupted" if interrupted else res.get("workflow_status", "completed")
        telemetry.record_workflow(wf_status)
        return WorkflowLaunchResponse(
            thread_id=thread_id,
            workflow_status=wf_status,
            approval_status=res.get("approval_status", "pending"),
            interrupted=interrupted,
            evaluation_status=res.get("evaluation_report", {}).get("status"),
            critic_decision=res.get("critic_decision", {}).get("decision"),
            metrics=res.get("metrics", {}),
            final_response=res.get("final_response", ""),
            errors=res.get("errors", []),
        )

    @app.get("/api/assets/{asset_id}/explanation", tags=["Decision Intelligence"])
    def get_asset_explanation(
        asset_id: str,
        portfolio_id: str = Query(default="portfolio_v1"),
    ) -> dict[str, Any]:
        path = resolve_portfolio_path(portfolio_id)
        try:
            exp = explain_asset_planning(path, asset_id, rules_path=RULES_PATH, constraints_path=CONSTRAINTS_PATH)
        except KeyError as ke:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ke)) from ke
        return exp.model_dump()

    @app.get("/api/comparisons", tags=["Decision Intelligence"])
    def get_plan_comparison(
        portfolio_id: str = Query(default="portfolio_v1"),
        scenario: str = Query(default="minimize_cost"),
        delay_weeks: int = Query(default=12, ge=1, le=52),
    ) -> dict[str, Any]:
        path = resolve_portfolio_path(portfolio_id)
        rep = compare_baseline_and_optimized(
            path,
            rules_path=RULES_PATH,
            constraints_path=CONSTRAINTS_PATH,
            optimized_scenario=scenario,
            delay_weeks=delay_weeks,
        )
        return rep.model_dump()

    @app.post("/api/scenarios", tags=["Scenarios"])
    def execute_scenario(req: ScenarioRunRequest) -> dict[str, Any]:
        path = resolve_portfolio_path(req.portfolio_id)
        cfg = WhatIfScenarioConfig(
            scenario_id=req.scenario_id,
            scenario_name=req.scenario_name,
            description=req.description,
            delay_weeks=req.delay_weeks,
            tsa_rate_multiplier=req.tsa_rate_multiplier,
            objective=req.objective,
            max_waves=req.max_waves,
        )
        res = run_what_if_scenario(path, cfg, rules_path=RULES_PATH, constraints_path=CONSTRAINTS_PATH)
        return res.model_dump()

    @app.get("/api/reports/{portfolio_id}", tags=["Reports"])
    def get_decision_report(
        portfolio_id: str,
        format: str = Query(default="json", pattern="^(json|markdown)$"),
        scenario: str = Query(default="minimize_cost"),
    ) -> Any:
        path = resolve_portfolio_path(portfolio_id)
        rep = generate_decision_report(
            path,
            rules_path=RULES_PATH,
            constraints_path=CONSTRAINTS_PATH,
            scenario=scenario,
        )
        if format == "markdown":
            b = rep.plan_comparison.baseline
            o = rep.plan_comparison.optimized
            md = (
                f"# IT Separation Decision & Planning Report ({rep.report_id})\n"
                f"**Company:** {rep.company} — *{rep.description}*\n\n"
                f"## Baseline vs Optimized ({scenario})\n"
                f"- Baseline Waves: {b.total_waves} | Optimized Waves: {o.total_waves}\n"
                f"- Baseline TSA Cost: ${b.tsa_cost:,.2f} | Optimized TSA Cost: ${o.tsa_cost:,.2f}\n"
                f"- Solver Status: `{o.solver_status}`\n"
            )
            return PlainTextResponse(content=md, media_type="text/markdown")
        return rep.model_dump()

    return app


app = create_app()


def main() -> None:
    import uvicorn
    host = os.environ.get("CARVEOUT_API_HOST", "0.0.0.0")
    port = int(os.environ.get("CARVEOUT_API_PORT", "8000"))
    uvicorn.run("carveout.api.app:app", host=host, port=port, reload=False)
