"""Command-line entry point for the deterministic planning pipeline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .graph import build_graph, export_graph, export_html
from .generation.documents import generate_documents
from .generation.documents import build_risk_register
from .evaluate import evaluate_results, evaluate_robustness
from .loader import load_portfolio, validate_portfolio, write_report
from .metrics import calculate_metrics
from .models import Portfolio
from .sequencing import compute_waves
from .strategy import assess_strategies


ROOT = Path(__file__).resolve().parents[2]


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
        if args.command in ("evaluate", "run-all"):
            risks = build_risk_register(portfolio, sequencing)
            evaluate_results(portfolio, expert_path, decisions, sequencing, risks, ROOT / "evaluation")
            robustness_portfolio = load_portfolio(robustness_path)
            robustness_report = validate_portfolio(robustness_portfolio)
            if not robustness_report["valid"]:
                raise ValueError(f"Robustness portfolio is invalid: {robustness_report['errors']}")
            robustness_waves = compute_waves(robustness_portfolio, constraints_path)
            _write_json(evaluate_robustness(robustness_portfolio, robustness_waves),
                        ROOT / "evaluation" / "robustness.json")
        print(f"Wrote {args.command} outputs to {output_dir}")
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"Error: {exc}")
        return 2


def main() -> int:
    parser = argparse.ArgumentParser(prog="carveout", description="Dependency graph separation planner")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "schema", "graph", "strategy", "waves", "generate", "evaluate", "run-all"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--portfolio", default="data/portfolio_v1.yaml")
        subparser.add_argument("--rules", default="config/strategy_rules.yaml")
        subparser.add_argument("--constraints", default="config/constraints.yaml")
        subparser.add_argument("--expert", default="data/expert_plan_v1.yaml")
        subparser.add_argument("--robustness-portfolio", default="data/portfolio_v2.yaml")
        subparser.add_argument("--output", default="output")
        subparser.add_argument("--ai", action="store_true", help="Generate narrative with the configured Claude API")
        if command == "schema":
            subparser.add_argument("--schema-output", default="schema/portfolio.schema.json")
    parser.set_defaults(_handler=run)
    args = parser.parse_args()
    return args._handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
