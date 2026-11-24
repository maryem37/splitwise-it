"""Compare computed outputs with an independent hand-authored expert plan."""
from __future__ import annotations

import csv
from itertools import combinations
import json
from pathlib import Path
from typing import Any

import yaml

from .graph import build_graph, cycles
from .models import Portfolio


def evaluate_results(
    portfolio: Portfolio,
    expert_path: str | Path,
    strategies: list[dict[str, Any]],
    sequencing: dict[str, Any],
    generated_risks: list[dict[str, Any]],
    output_dir: str | Path,
) -> dict[str, Any]:
    expert = yaml.safe_load(Path(expert_path).read_text(encoding="utf-8"))
    expected_strategies = expert.get("strategies", {})
    actual_strategies = {item["asset_id"]: item["strategy"] for item in strategies}
    strategy_rows = []
    for asset in portfolio.assets:
        expected = expected_strategies.get(asset.id, {}).get("strategy")
        actual = actual_strategies.get(asset.id)
        strategy_rows.append({"asset_id": asset.id, "expected_strategy": expected,
                              "actual_strategy": actual, "match": expected == actual})

    expected_wave = {
        asset_id: item["wave"]
        for item in expert.get("expected_waves", [])
        for asset_id in item.get("assets", [])
    }
    actual_wave = {
        asset_id: item["wave"]
        for item in sequencing["waves"]
        for asset_id in item["assets"]
    }
    wave_matches = sum(expected_wave.get(asset_id) == actual_wave.get(asset_id)
                       for asset_id in expected_wave)
    wave_exact_percent = 100 * wave_matches / max(1, len(expected_wave))
    order_pairs = [
        (left, right) for left, right in combinations(sorted(expected_wave), 2)
        if expected_wave[left] != expected_wave[right]
    ]
    order_matches = sum(
        (expected_wave[left] < expected_wave[right]) == (actual_wave.get(left, 0) < actual_wave.get(right, 0))
        for left, right in order_pairs
    )
    expected_risk_ids = {item["id"] for item in expert.get("top_risks", [])}
    actual_risk_ids = {item.get("id") for item in generated_risks}
    risk_coverage = len(expected_risk_ids & actual_risk_ids) / max(1, len(expected_risk_ids))

    known_assets = {asset.id for asset in portfolio.assets}
    references = set(actual_strategies)
    references.update(actual_wave)
    for risk in generated_risks:
        references.update(risk.get("asset_ids", []))
    unknown_references = sorted(references - known_assets)
    retained_under_tsa = {
        item["asset_id"] for item in strategies
        if item.get("strategy") == "retain_under_tsa"
    }
    dependency_violations = [
        {"source": relation.source, "dependency": relation.target,
         "source_wave": actual_wave.get(relation.source),
         "dependency_wave": actual_wave.get(relation.target)}
        for relation in portfolio.relationships
        if relation.source in actual_wave and relation.target in actual_wave
        and relation.target not in retained_under_tsa
        and actual_wave[relation.source] < actual_wave[relation.target]
    ]
    cycles_grouped = all(
        len({actual_wave.get(asset_id) for asset_id in group}) == 1
        for group in sequencing.get("cycles", [])
    )
    summary = {
        "dependency_violations": len(dependency_violations),
        "strategy_match_percent": round(
            100 * sum(row["match"] for row in strategy_rows) / max(1, len(strategy_rows)), 2
        ),
        "wave_exact_match_percent": round(wave_exact_percent, 2),
        "wave_order_similarity_percent": round(100 * order_matches / max(1, len(order_pairs)), 2),
        "risk_coverage_percent": round(100 * risk_coverage, 2),
        "hallucination_count": len(unknown_references),
        "hallucination_assets": unknown_references,
        "cycles_grouped": cycles_grouped,
        "expert_asset_count": len(expected_wave),
        "computed_asset_count": len(actual_wave),
    }

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "results.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=["metric", "value"])
        writer.writeheader()
        writer.writerows({"metric": key, "value": value} for key, value in summary.items())
    (out / "comparison.json").write_text(json.dumps({
        "summary": summary,
        "strategy_comparison": strategy_rows,
        "dependency_violations": dependency_violations,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "comparison.md").write_text(
        "# Evaluation comparison\n\n| Metric | Result |\n|---|---:|\n" +
        "\n".join(f"| {key.replace('_', ' ')} | {value} |" for key, value in summary.items()) +
        "\n\n## Strategy mismatches\n\n" +
        ("\n".join(f"- `{row['asset_id']}`: expected {row['expected_strategy']}, got {row['actual_strategy']}"
                    for row in strategy_rows if not row["match"]) or "No strategy mismatches.") + "\n",
        encoding="utf-8")
    mismatches = [row for row in strategy_rows if not row["match"]]
    (out / "analysis.md").write_text(
        "# Evaluation analysis\n\n"
        f"- Dependency violations: {summary['dependency_violations']} (target: 0).\n"
        f"- Strategy match: {summary['strategy_match_percent']}%.\n"
        f"- Exact expert wave match: {summary['wave_exact_match_percent']}%.\n"
        f"- Pairwise wave order similarity: {summary['wave_order_similarity_percent']}%.\n"
        f"- Expert risk coverage: {summary['risk_coverage_percent']}%.\n"
        f"- Unknown asset references: {summary['hallucination_count']}.\n\n"
        "Wave exact match compares wave numbers asset by asset. A low score can "
        "reflect different grouping or capacity assumptions even when dependency "
        "violations are zero. Review strategy mismatches and wave differences "
        "against the expert assumptions before changing rules.\n\n"
        "## Strategy mismatches\n\n" +
        ("\n".join(
            f"- `{row['asset_id']}`: expected `{row['expected_strategy']}`, "
            f"computed `{row['actual_strategy']}`."
            for row in mismatches
        ) or "No strategy mismatches.") + "\n",
        encoding="utf-8",
    )
    return summary


def evaluate_robustness(portfolio: Portfolio, sequencing: dict[str, Any]) -> dict[str, Any]:
    """Check pipeline invariants on a second portfolio without tuning to its answers."""
    graph = build_graph(portfolio)
    wave_for = {asset_id: wave["wave"] for wave in sequencing["waves"] for asset_id in wave["assets"]}
    violations = [
        {"source": source, "dependency": target}
        for source, target in graph.edges
        if wave_for.get(source, 0) < wave_for.get(target, 0)
    ]
    cycle_list = cycles(graph)
    result = {
        "assets": graph.number_of_nodes(),
        "dependency_violations": len(violations),
        "cycles_detected": len(cycle_list),
        "cycles_grouped": all(len({wave_for.get(asset_id) for asset_id in group}) == 1 for group in cycle_list),
        "all_assets_scheduled": set(wave_for) == set(graph.nodes),
    }
    return result
