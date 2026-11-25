"""Command-line entry point for the deterministic planning pipeline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .graph import build_graph, export_graph, export_html
from .dashboard import export_dashboard
from .generation.documents import generate_documents
from .generation.documents import build_risk_register
from .evaluate import evaluate_results, evaluate_robustness, format_evaluation_explanation
from .loader import load_portfolio, validate_portfolio, write_report
from .metrics import calculate_metrics
from .models import Portfolio
from .sensitivity import run_sensitivity
from .sequencing import compute_waves
from .strategy import assess_strategies
from .cypher_queries import QUERIES


ROOT = Path(__file__).resolve().parents[2]

_NEO4J_COMMANDS = ("neo4j-load", "neo4j-query", "neo4j-export")
_PLAN_COMMANDS  = ("validate", "schema", "graph", "strategy", "waves",
                   "generate", "evaluate", "sensitivity", "run-all", "agent", "agent-resume", "agent-status", "optimize",
                   "explain", "compare", "scenario", "report")


def _write_json(value: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _paths(args: argparse.Namespace) -> tuple[Path, Path, Path, Path, Path, Path]:
    portfolio_path = Path(args.portfolio)
    rules_path = Path(args.rules)
    output_dir = Path(args.output)
    constraints_path = Path(args.constraints)
    expert_path = Path(args.expert)
    robustness_path = Path(args.robustness_portfolio)
    if not portfolio_path.is_absolute():
        portfolio_path = ROOT / portfolio_path
    if not rules_path.is_absolute():
        rules_path = ROOT / rules_path
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    if not constraints_path.is_absolute():
        constraints_path = ROOT / constraints_path
    if not expert_path.is_absolute():
        expert_path = ROOT / expert_path
    if not robustness_path.is_absolute():
        robustness_path = ROOT / robustness_path
    return portfolio_path, rules_path, output_dir, constraints_path, expert_path, robustness_path


def run(args: argparse.Namespace) -> int:
    portfolio_path, rules_path, output_dir, constraints_path, expert_path, robustness_path = _paths(args)
    try:
        portfolio = load_portfolio(portfolio_path)
        report = validate_portfolio(portfolio)
        output_dir.mkdir(parents=True, exist_ok=True)
        write_report(report, output_dir / "validation_report.json")
        if not report["valid"]:
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 2

        if args.command == "agent":
            from .logging_config import configure_logging
            from .workflows.graph import get_workflow_state, resume_agent_workflow, run_agent_workflow

            log_level = getattr(args, "log_level", None)
            json_logs = bool(getattr(args, "json_logs", False))
            configure_logging(level=log_level, json_format=json_logs)

            query = getattr(args, "query_text", None) or "Investigate dependencies and TSA risks for the portfolio."
            human_review = bool(getattr(args, "human_review", False))
            thread_id = getattr(args, "thread_id", "cli-thread")
            db_path = getattr(args, "db_path", None)
            in_memory = bool(getattr(args, "in_memory", False))

            try:
                result = run_agent_workflow(
                    user_request=query,
                    portfolio_path=portfolio_path,
                    rules_path=rules_path,
                    constraints_path=constraints_path,
                    thread_id=thread_id,
                    human_review=human_review,
                    db_path=db_path,
                    in_memory=in_memory,
                )
            except Exception as e:
                print(f"Error executing agent workflow: {e}", file=sys.stderr)
                return 1

            while "__interrupt__" in result:
                interrupts = result["__interrupt__"]
                payload = interrupts[0].value if hasattr(interrupts[0], "value") else interrupts[0]
                print("\n" + "=" * 70)
                print("HUMAN APPROVAL REQUIRED (LangGraph interrupt)")
                print("=" * 70)
                print(f"Thread ID   : {thread_id}")
                print(f"Scenario    : {payload.get('scenario')}")
                print(f"Eval Status : {payload.get('evaluation_report', {}).get('status')}")
                print(f"Critic      : {payload.get('critic_decision', {}).get('decision')}")
                print(f"TSA Cost    : ${payload.get('tsa_cost', 0):,.2f} (Delta: ${payload.get('tsa_delta', 0):+,.2f})")
                choice = input("Enter decision [APPROVE / REJECT / REQUEST_REVISION]: ").strip().upper() or "REJECT"
                comment = input("Optional comment: ").strip()
                try:
                    result = resume_agent_workflow(
                        thread_id=thread_id,
                        decision={"action": choice, "reviewer": "cli_user", "comment": comment},
                        db_path=db_path,
                        in_memory=in_memory,
                    )
                except Exception as e:
                    print(f"Error resuming workflow: {e}", file=sys.stderr)
                    return 1

            print("\n" + "=" * 70)
            print("CARVEOUT COPILOT AGENTIC INVESTIGATION")
            print("=" * 70 + "\n")
            print(result.get("final_response", "No response generated."))
            print("\n" + "-" * 70)
            print(f"Approval status: {result.get('approval_status')}")
            print(f"Eval status    : {result.get('evaluation_report', {}).get('status')}")
            print(f"Critic decision: {result.get('critic_decision', {}).get('decision')}")
            print(f"Agent handoffs : {len(result.get('agent_messages', []))}")
            metrics_data = result.get("metrics")
            if metrics_data:
                print(f"Execution time : {metrics_data.get('total_duration_seconds', 0.0):.2f}s")
            print("-" * 70)
            return 0 if result.get("workflow_status") not in ("failed", "blocked") else 1

        if args.command == "agent-resume":
            from .logging_config import configure_logging
            from .workflows.graph import resume_agent_workflow

            log_level = getattr(args, "log_level", None)
            json_logs = bool(getattr(args, "json_logs", False))
            configure_logging(level=log_level, json_format=json_logs)

            thread_id = getattr(args, "thread_id", "cli-thread")
            decision_action = str(getattr(args, "action", "APPROVE")).strip().upper()
            if decision_action not in ("APPROVE", "REJECT", "REQUEST_REVISION"):
                print(f"Error: Invalid action '{decision_action}'. Must be one of APPROVE, REJECT, REQUEST_REVISION.", file=sys.stderr)
                return 2

            comment = getattr(args, "comment", "") or ""
            reviewer = getattr(args, "reviewer", "cli_user") or "cli_user"
            db_path = getattr(args, "db_path", None)
            in_memory = bool(getattr(args, "in_memory", False))

            try:
                result = resume_agent_workflow(
                    thread_id=thread_id,
                    decision={"action": decision_action, "reviewer": reviewer, "comment": comment},
                    db_path=db_path,
                    in_memory=in_memory,
                )
            except FileNotFoundError as fnf:
                print(f"Error: {fnf}", file=sys.stderr)
                return 1
            except Exception as e:
                print(f"Error resuming workflow for thread '{thread_id}': {e}", file=sys.stderr)
                return 1

            print("\n" + "=" * 70)
            print(f"CARVEOUT COPILOT RESUMED WORKFLOW: {thread_id}")
            print("=" * 70 + "\n")
            print(result.get("final_response", "No response generated."))
            print("\n" + "-" * 70)
            print(f"Approval status: {result.get('approval_status')}")
            print(f"Workflow status: {result.get('workflow_status')}")
            print(f"Agent handoffs : {len(result.get('agent_messages', []))}")
            print("-" * 70)
            return 0 if result.get("workflow_status") not in ("failed", "blocked") else 1

        if args.command == "agent-status":
            from .logging_config import configure_logging
            from .workflows.graph import get_workflow_state

            log_level = getattr(args, "log_level", None)
            json_logs = bool(getattr(args, "json_logs", False))
            configure_logging(level=log_level, json_format=json_logs)

            thread_id = getattr(args, "thread_id", "cli-thread")
            db_path = getattr(args, "db_path", None)
            in_memory = bool(getattr(args, "in_memory", False))

            try:
                snapshot = get_workflow_state(
                    thread_id=thread_id,
                    db_path=db_path,
                    in_memory=in_memory,
                )
            except Exception as e:
                print(f"Error reading workflow state: {e}", file=sys.stderr)
                return 1

            print("\n" + "=" * 70)
            print(f"CARVEOUT COPILOT WORKFLOW STATUS: {thread_id}")
            print("=" * 70)
            if not snapshot or not snapshot.values:
                print(f"No checkpoint found for thread ID: {thread_id}")
                print("-" * 70)
                return 1

            vals = snapshot.values
            print(f"Workflow Status : {vals.get('workflow_status', 'unknown')}")
            print(f"Approval Status : {vals.get('approval_status', 'unknown')}")
            print(f"Next Node(s)    : {list(snapshot.next)}")
            print(f"Tasks           : {len(snapshot.tasks)}")
            if snapshot.tasks and hasattr(snapshot.tasks[0], "interrupts") and snapshot.tasks[0].interrupts:
                print("Interrupted     : True (waiting for human decision)")
            else:
                print("Interrupted     : False")
            print(f"Eval Status     : {vals.get('evaluation_report', {}).get('status')}")
            print(f"Critic Decision : {vals.get('critic_decision', {}).get('decision')}")
            print(f"Corrections     : {vals.get('correction_attempts', 0)} / {vals.get('max_correction_attempts', 0)}")
            metrics_data = vals.get("metrics")
            if metrics_data:
                print(f"Duration        : {metrics_data.get('total_duration_seconds', 0.0):.2f}s")
            print("-" * 70)
            return 0

        if args.command == "optimize":
            try:
                from .optimization.scenarios import run_scenario
            except ImportError as exc:
                print(f"Error: OR-Tools optimization requires the optional extra. Run: pip install -e \".[optimization]\" ({exc})")
                return 2

            scenario = getattr(args, "scenario", "baseline")
            delay_w = int(getattr(args, "delay_weeks", 12))
            objective = getattr(args, "objective", "minimize_cost")

            res, comp = run_scenario(
                portfolio_path=str(portfolio_path),
                rules_path=str(rules_path),
                scenario_type=scenario,
                delay_weeks=delay_w,
                objective=objective,
                constraints_path=str(constraints_path),
            )

            print("\n" + "=" * 70)
            print(f"CARVEOUT COPILOT OPTIMIZATION: {comp.scenario_name.upper()}")
            print("=" * 70 + "\n")
            print(f"Solver Status     : {res.status} (solved in {res.solve_duration_seconds:.2f}s)")
            print(f"Feasible          : {comp.is_feasible}")
            print(f"Baseline TSA Cost : ${comp.baseline_tsa_cost:,.2f}")
            print(f"Scenario TSA Cost : ${comp.scenario_tsa_cost:,.2f} (Delta: ${comp.additional_tsa_cost:+,.2f})")
            print(f"Latest Completion : {comp.scenario_completion} (Baseline: {comp.baseline_completion})")
            print(f"Total Waves       : {comp.scenario_waves} (Baseline: {comp.baseline_waves})")
            print(f"Schedule Conflicts: {comp.scenario_conflicts}")
            if comp.affected_assets:
                print(f"Affected Unit     : {', '.join(comp.affected_assets)}")
            print("\nTradeoff Summary  :")
            print(comp.tradeoff_summary)
            print("-" * 70)
            return 0

        # ── Phase 4 Decision Intelligence commands ─────────────────────────
        if args.command == "explain":
            from .explain import explain_asset_planning
            aid = getattr(args, "asset_id", None)
            if not aid:
                print("Error: An asset_id is required (e.g. carveout explain APP-06)", file=sys.stderr)
                return 2

            try:
                exp = explain_asset_planning(portfolio, aid, rules_path=rules_path, constraints_path=constraints_path)
            except KeyError as ke:
                print(f"Error: {ke}", file=sys.stderr)
                return 1

            print("\n" + "=" * 70)
            print(f"ASSET PLANNING EXPLANATION: {exp.asset_id} ({exp.asset_name})")
            print("=" * 70)
            print(f"Strategy           : {exp.strategy}")
            print(f"Assigned Wave      : Wave {exp.assigned_wave} ({exp.planned_start} → {exp.planned_completion})")
            print(f"Earliest Feasible  : Wave {exp.min_possible_wave}")
            print(f"Prerequisites ({len(exp.direct_prerequisites)})   : {', '.join(exp.direct_prerequisites) or 'None'}")
            print(f"Dependants ({len(exp.direct_dependants)})      : {', '.join(exp.direct_dependants) or 'None'}")
            if exp.scc_members:
                print(f"Participating SCC  : {', '.join(exp.scc_members)} (co-located)")
            if exp.identified_conflicts:
                print(f"Identified Conflicts: {', '.join(exp.identified_conflicts)}")
            print("\nRationale:")
            print(f"  {exp.placement_rationale}")
            print("\nConsequences of Movement:")
            print(f"  - Move earlier : {exp.move_consequences.get('move_earlier')}")
            print(f"  - Move later   : {exp.move_consequences.get('move_later')}")
            print("-" * 70)
            return 0

        if args.command == "compare":
            from .comparison import compare_baseline_and_optimized
            scenario = getattr(args, "scenario", "minimize_cost")
            delay_w = int(getattr(args, "delay_weeks", 12))

            rep = compare_baseline_and_optimized(
                portfolio,
                rules_path=rules_path,
                constraints_path=constraints_path,
                optimized_scenario=scenario,
                delay_weeks=delay_w,
            )

            print("\n" + "=" * 70)
            print(f"PLAN COMPARISON: BASELINE vs OPTIMIZED ({scenario.upper()})")
            print("=" * 70)
            print(f"{'Metric':<25} | {'Baseline':<20} | {'Optimized':<20} | Delta")
            print("-" * 70)
            print(f"{'Total Waves':<25} | {rep.baseline.total_waves:<20} | {rep.optimized.total_waves:<20} | {rep.wave_count_delta:+d}")
            print(f"{'Latest Completion':<25} | {rep.baseline.completion_date:<20} | {rep.optimized.completion_date:<20} | -")
            print(f"{'TSA Cost':<25} | ${rep.baseline.tsa_cost:<19,.2f} | ${rep.optimized.tsa_cost:<19,.2f} | ${rep.tsa_cost_delta:+,.2f}")
            print(f"{'Conflicts':<25} | {rep.baseline.conflicts_count:<20} | {rep.optimized.conflicts_count:<20} | {rep.optimized.conflicts_count - rep.baseline.conflicts_count:+d}")
            print(f"{'Solver Status':<25} | {rep.baseline.solver_status:<20} | {rep.optimized.solver_status:<20} | -")
            print("\nTradeoff Analysis:")
            print(f"  {rep.tradeoff_analysis}")
            print(f"\n*{rep.objective_vs_financial_note}*")
            if rep.moved_assets:
                print(f"\nAsset Wave Reallocations ({len(rep.moved_assets)}):")
                for m in rep.moved_assets[:5]:
                    print(f"  - {m.asset_id} ({m.asset_name}): Wave {m.baseline_wave} -> Wave {m.optimized_wave} ({m.wave_delta:+d})")
            print("-" * 70)
            return 0

        if args.command == "scenario":
            from .scenarios_manager import WhatIfScenarioConfig, run_what_if_scenario
            scen_file = getattr(args, "scenario_config", None)
            delay_aid = getattr(args, "delay_asset", None)
            delay_w = int(getattr(args, "delay_weeks", 12))
            rate_mult = float(getattr(args, "rate_multiplier", 1.0))

            if scen_file:
                p = Path(scen_file)
                if not p.exists():
                    print(f"Error: Scenario config file not found: {scen_file}", file=sys.stderr)
                    return 1
                raw_cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
                cfg = WhatIfScenarioConfig.model_validate(raw_cfg)
            else:
                delay_dict = {delay_aid: delay_w} if delay_aid else {}
                cfg = WhatIfScenarioConfig(
                    scenario_id=f"whatif_{delay_aid or 'scenario'}",
                    scenario_name=f"What-If: {delay_aid or 'Rate/Delay'}",
                    description="CLI what-if scenario run",
                    delay_weeks=delay_dict,
                    tsa_rate_multiplier=rate_mult,
                    objective=getattr(args, "objective", "minimize_cost"),
                )

            res = run_what_if_scenario(portfolio, cfg, rules_path=rules_path, constraints_path=constraints_path)

            print("\n" + "=" * 70)
            print(f"WHAT-IF SCENARIO: {res.scenario_name.upper()}")
            print("=" * 70)
            print(f"Solver Status     : {res.solver_status}")
            print(f"Feasible          : {res.is_feasible}")
            print(f"Baseline TSA Cost : ${res.baseline_tsa_cost:,.2f}")
            print(f"Scenario TSA Cost : ${res.scenario_tsa_cost:,.2f} (Delta: ${res.tsa_cost_delta:+,.2f})")
            print(f"Latest Completion : {res.scenario_completion} (Baseline: {res.baseline_completion})")
            print(f"Total Waves       : {res.total_waves}")
            print("\nImpact Summary:")
            print(f"  {res.impact_summary}")
            print("-" * 70)
            return 0

        if args.command == "report":
            from .decision_report import export_report_json, export_report_markdown, generate_decision_report
            fmt = str(getattr(args, "format", "markdown")).lower()
            out_file = getattr(args, "report_output", None)
            scenario = getattr(args, "scenario", "minimize_cost")

            rep = generate_decision_report(
                portfolio,
                rules_path=rules_path,
                constraints_path=constraints_path,
                scenario=scenario,
            )

            if fmt == "json":
                target = Path(out_file) if out_file else output_dir / "decision_report.json"
                export_report_json(rep, target)
                print(f"Wrote decision report JSON: {target}")
            else:
                target = Path(out_file) if out_file else output_dir / "decision_report.md"
                export_report_markdown(rep, target)
                print(f"Wrote decision report Markdown: {target}")
            return 0

        # ── Planning pipeline ──────────────────────────────────────────────
        if args.command == "validate":
            print(f"Valid portfolio: {report['counts']['assets']} assets")
            return 0

        if args.command == "schema":
            schema_path = Path(args.schema_output)
            if not schema_path.is_absolute():
                schema_path = ROOT / schema_path
            schema_path.parent.mkdir(parents=True, exist_ok=True)
            schema_path.write_text(json.dumps(Portfolio.model_json_schema(), indent=2), encoding="utf-8")
            print(f"Wrote schema: {schema_path}")
            return 0

        if args.command in ("graph", "run-all"):
            graph = build_graph(portfolio)
            export_graph(graph, output_dir / "dependency_graph.json")
            export_html(graph, output_dir / "graph.html")

        decisions = None
        sequencing = None
        metrics = None

        if args.command in ("strategy", "waves", "generate", "evaluate", "sensitivity", "run-all"):
            decisions = assess_strategies(portfolio, rules_path)
        if args.command in ("strategy", "run-all"):
            _write_json(decisions, output_dir / "strategy_assessment.json")
        if args.command in ("waves", "generate", "evaluate", "run-all"):
            sequencing = compute_waves(portfolio, constraints_path, strategies=decisions)
            _write_json(sequencing, output_dir / "waves.json")
            metrics = calculate_metrics(portfolio, sequencing)
            _write_json(metrics, output_dir / "metrics.json")
        if args.command == "sensitivity":
            run_sensitivity(portfolio, constraints_path, decisions, output_dir)
        if args.command in ("generate", "run-all"):
            generate_documents(portfolio, decisions, sequencing, metrics, output_dir, use_ai=args.ai)
            risks_for_ui = build_risk_register(portfolio, sequencing)
            export_dashboard(portfolio, decisions, sequencing, metrics, risks_for_ui, output_dir / "dashboard.html")
        if args.command in ("evaluate", "run-all"):
            risks = build_risk_register(portfolio, sequencing)
            evaluate_results(portfolio, expert_path, decisions, sequencing, risks, ROOT / "evaluation", docs_dir=output_dir)
            if args.command == "evaluate" and getattr(args, "explain", False):
                comparison = json.loads((ROOT / "evaluation" / "comparison.json").read_text(encoding="utf-8"))
                print(format_evaluation_explanation(comparison))
            robustness_portfolio = load_portfolio(robustness_path)
            robustness_report = validate_portfolio(robustness_portfolio)
            if not robustness_report["valid"]:
                raise ValueError(f"Robustness portfolio is invalid: {robustness_report['errors']}")
            robustness_waves = compute_waves(robustness_portfolio, constraints_path)
            _write_json(evaluate_robustness(robustness_portfolio, robustness_waves),
                        ROOT / "evaluation" / "robustness.json")

        # ── Neo4j commands ─────────────────────────────────────────────────
        if args.command in ("neo4j-load", "neo4j-export"):
            from .neo4j_store import load_portfolio as neo4j_load, export_cypher
            # Try to enrich with previously computed sequencing
            waves_path = output_dir / "waves.json"
            if sequencing is None and waves_path.exists():
                sequencing = json.loads(waves_path.read_text(encoding="utf-8"))

            # Always write the standalone Cypher script (no DB needed)
            export_cypher(portfolio, sequencing, output_dir / "graph.cypher")
            print(f"Wrote Cypher script: {output_dir / 'graph.cypher'}")

            if args.command == "neo4j-load":
                counts = neo4j_load(
                    portfolio, sequencing,
                    uri=args.neo4j_uri,
                    user=args.neo4j_user,
                    password=args.neo4j_password,
                    clear=not args.no_clear,
                )
                print(f"Neo4j load complete: {counts}")
            return 0

        if args.command == "neo4j-query":
            from .neo4j_store import run_query
            params: dict[str, Any] = {}
            if getattr(args, "asset", None):
                params["asset_id"] = args.asset
            if getattr(args, "wave", None) is not None:
                params["wave"] = int(args.wave)
            rows = run_query(
                args.query, params,
                uri=args.neo4j_uri,
                user=args.neo4j_user,
                password=args.neo4j_password,
            )
            print(json.dumps(rows, indent=2, ensure_ascii=False, default=str))
            return 0

        if args.command == "cypher-list":
            for name, cql in QUERIES.items():
                print(f"\n── {name} ─────────────────────────")
                print(cql.strip())
            return 0

        if args.command not in _NEO4J_COMMANDS:
            print(f"Wrote {args.command} outputs to {output_dir}")
        return 0

    except (OSError, ValueError, KeyError) as exc:
        print(f"Error: {exc}")
        return 2


def _add_common(subparser: argparse.ArgumentParser) -> None:
    """Add portfolio/output args shared by all subcommands."""
    subparser.add_argument("--portfolio",           default="data/portfolio_v1.yaml")
    subparser.add_argument("--rules",               default="config/strategy_rules.yaml")
    subparser.add_argument("--constraints",         default="config/constraints.yaml")
    subparser.add_argument("--expert",              default="data/expert_plan_v1.yaml")
    subparser.add_argument("--robustness-portfolio",default="data/portfolio_v2.yaml")
    subparser.add_argument("--output",              default="output")


def _add_neo4j_conn(subparser: argparse.ArgumentParser) -> None:
    """Add Neo4j connection args."""
    subparser.add_argument("--neo4j-uri",      default="bolt://localhost:7687")
    subparser.add_argument("--neo4j-user",     default="neo4j")
    subparser.add_argument("--neo4j-password", default="password")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="carveout",
        description="IT separation dependency-graph planner with Neo4j support",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── Planning pipeline subcommands ──────────────────────────────────────
    for command in _PLAN_COMMANDS:
        sub = subparsers.add_parser(command)
        _add_common(sub)
        sub.add_argument("--ai", action="store_true",
                         help="Generate narrative using the Groq API")
        if command == "schema":
            sub.add_argument("--schema-output", default="schema/portfolio.schema.json")
        if command == "evaluate":
            sub.add_argument("--explain", action="store_true",
                             help="Print per-asset strategy and per-risk matching explanations")
        if command == "agent":
            sub.add_argument("query_text", nargs="?", default="",
                             help="Natural language request or question for the Agentic Copilot")
            sub.add_argument("--human-review", action="store_true",
                             help="Enable interactive LangGraph interrupt() human approval gate")
            sub.add_argument("--thread-id", default="cli-thread",
                             help="Stable checkpoint thread ID for human review / resume")
            sub.add_argument("--db-path", default=None,
                             help="Custom SQLite database path for checkpoint persistence")
            sub.add_argument("--in-memory", action="store_true",
                             help="Use in-memory checkpointing instead of SQLite persistence")
            sub.add_argument("--log-level", default=None,
                             choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                             help="Configure logging level (default: CARVEOUT_LOG_LEVEL or INFO)")
            sub.add_argument("--json-logs", action="store_true",
                             help="Format logs as structured JSON")
        if command == "agent-resume":
            sub.add_argument("--thread-id", default="cli-thread",
                             help="Checkpoint thread ID to resume")
            sub.add_argument("--action", default="APPROVE",
                             choices=["APPROVE", "REJECT", "REQUEST_REVISION"],
                             help="Approval action to submit")
            sub.add_argument("--comment", default="",
                             help="Optional reviewer comment")
            sub.add_argument("--reviewer", default="cli_user",
                             help="Reviewer identifier")
            sub.add_argument("--db-path", default=None,
                             help="Custom SQLite database path for checkpoint persistence")
            sub.add_argument("--in-memory", action="store_true",
                             help="Use in-memory checkpointing")
            sub.add_argument("--log-level", default=None,
                             choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                             help="Configure logging level")
            sub.add_argument("--json-logs", action="store_true",
                             help="Format logs as structured JSON")
        if command == "agent-status":
            sub.add_argument("--thread-id", default="cli-thread",
                             help="Checkpoint thread ID to inspect")
            sub.add_argument("--db-path", default=None,
                             help="Custom SQLite database path for checkpoint persistence")
            sub.add_argument("--in-memory", action="store_true",
                             help="Use in-memory checkpointing")
            sub.add_argument("--log-level", default=None,
                             choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                             help="Configure logging level")
            sub.add_argument("--json-logs", action="store_true",
                             help="Format logs as structured JSON")
        if command == "optimize":
            sub.add_argument("--scenario", default="baseline",
                             choices=["baseline", "app_06_delay", "minimize_cost", "minimize_duration", "balanced"],
                             help="Scenario identifier to optimize")
            sub.add_argument("--delay-weeks", type=int, default=12,
                             help="Delay in weeks for delay scenarios (default: 12)")
            sub.add_argument("--objective", default="minimize_cost",
                             choices=["minimize_cost", "minimize_duration", "balanced"],
                             help="Primary optimization objective (default: minimize_cost)")
        if command == "explain":
            sub.add_argument("asset_id", help="Asset ID to explain (e.g. APP-06)")
        if command == "compare":
            sub.add_argument("--scenario", default="minimize_cost",
                             choices=["baseline", "app_06_delay", "minimize_cost", "minimize_duration", "balanced"],
                             help="Scenario identifier to compare against baseline")
            sub.add_argument("--delay-weeks", type=int, default=12,
                             help="Delay in weeks if delay scenario chosen (default: 12)")
        if command == "scenario":
            sub.add_argument("--config", dest="scenario_config", default=None,
                             help="Path to YAML/JSON scenario configuration file")
            sub.add_argument("--delay-asset", default=None,
                             help="Asset ID to delay")
            sub.add_argument("--delay-weeks", type=int, default=12,
                             help="Weeks to delay specified asset")
            sub.add_argument("--rate-multiplier", type=float, default=1.0,
                             help="Multiplier for TSA rates (e.g. 1.2 for 20% increase)")
            sub.add_argument("--objective", default="minimize_cost",
                             choices=["minimize_cost", "minimize_duration", "balanced"],
                             help="Optimization objective")
        if command == "report":
            sub.add_argument("--format", default="markdown", choices=["markdown", "json"],
                             help="Report output format (default: markdown)")
            sub.add_argument("--report-output", default=None,
                             help="Custom path to output report file")
            sub.add_argument("--scenario", default="minimize_cost",
                             help="Scenario plan to evaluate in report")

    # ── neo4j-load ─────────────────────────────────────────────────────────
    sub_load = subparsers.add_parser(
        "neo4j-load",
        help="Load portfolio graph into a running Neo4j instance",
    )
    _add_common(sub_load)
    _add_neo4j_conn(sub_load)
    sub_load.add_argument("--no-clear", action="store_true",
                          help="Do not wipe the graph before loading")
    sub_load.add_argument("--ai", action="store_true")

    # ── neo4j-export ───────────────────────────────────────────────────────
    sub_exp = subparsers.add_parser(
        "neo4j-export",
        help="Write output/graph.cypher (no DB required)",
    )
    _add_common(sub_exp)
    sub_exp.add_argument("--ai", action="store_true")
    _add_neo4j_conn(sub_exp)  # kept for signature parity (unused)

    # ── neo4j-query ────────────────────────────────────────────────────────
    sub_q = subparsers.add_parser(
        "neo4j-query",
        help="Run a named Cypher analytics query against Neo4j",
    )
    _add_common(sub_q)
    _add_neo4j_conn(sub_q)
    sub_q.add_argument("--query", required=True,
                       choices=list(QUERIES.keys()),
                       help="Named query from cypher_queries.QUERIES")
    sub_q.add_argument("--asset", default=None, help="Asset ID parameter (e.g. INF-01)")
    sub_q.add_argument("--wave",  default=None, help="Wave number parameter (e.g. 3)")
    sub_q.add_argument("--ai", action="store_true")

    # ── cypher-list ────────────────────────────────────────────────────────
    sub_cl = subparsers.add_parser(
        "cypher-list",
        help="Print all named Cypher queries to stdout",
    )
    _add_common(sub_cl)
    sub_cl.add_argument("--ai", action="store_true")

    parser.set_defaults(_handler=run)
    args = parser.parse_args()
    return args._handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
