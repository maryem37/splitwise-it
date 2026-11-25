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
from .evaluate import evaluate_results, evaluate_robustness
from .loader import load_portfolio, validate_portfolio, write_report
from .metrics import calculate_metrics
from .models import Portfolio
from .sequencing import compute_waves
from .strategy import assess_strategies
from .cypher_queries import QUERIES


ROOT = Path(__file__).resolve().parents[2]

_NEO4J_COMMANDS = ("neo4j-load", "neo4j-query", "neo4j-export")
_PLAN_COMMANDS  = ("validate", "schema", "graph", "strategy", "waves",
                   "generate", "evaluate", "run-all")


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

        if args.command in ("strategy", "waves", "generate", "evaluate", "run-all"):
            decisions = assess_strategies(portfolio, rules_path)
        if args.command in ("strategy", "run-all"):
            _write_json(decisions, output_dir / "strategy_assessment.json")
        if args.command in ("waves", "generate", "evaluate", "run-all"):
            sequencing = compute_waves(portfolio, constraints_path, strategies=decisions)
            _write_json(sequencing, output_dir / "waves.json")
            metrics = calculate_metrics(portfolio, sequencing)
            _write_json(metrics, output_dir / "metrics.json")
        if args.command in ("generate", "run-all"):
            generate_documents(portfolio, decisions, sequencing, metrics, output_dir, use_ai=args.ai)
            risks_for_ui = build_risk_register(portfolio, sequencing)
            export_dashboard(portfolio, decisions, sequencing, metrics, risks_for_ui, output_dir / "dashboard.html")
        if args.command in ("evaluate", "run-all"):
            risks = build_risk_register(portfolio, sequencing)
            evaluate_results(portfolio, expert_path, decisions, sequencing, risks, ROOT / "evaluation", docs_dir=output_dir)
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
