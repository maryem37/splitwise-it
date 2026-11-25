"""Compare computed outputs with an independent hand-authored expert plan."""
from __future__ import annotations

import csv
from itertools import combinations
import json
from pathlib import Path
import re
from typing import Any

import yaml

from .graph import build_graph, cycles
from .models import Portfolio


_THEME_KEYWORDS = (
    "erp", "tsa-01", "payment", "lic-04", "inventory", "warehouse", "cyclic",
    "identity", "inf-03", "sensitive", "data", "payroll", "hr", "tsa-02",
    "capacity", "freeze", "crm", "tsa", "licence", "tsa-04",
)
_ID_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]*(?:-\d+)+\b")


def _themes(text: str) -> set[str]:
    low = text.lower()
    return {kw for kw in _THEME_KEYWORDS if kw in low}


def _risk_match_details(
    expert_risk: dict[str, Any], generated_risk: dict[str, Any], known_assets: set[str]
) -> tuple[bool, set[str], set[str]]:
    exp_text = f"{expert_risk.get('risk', '')} {expert_risk.get('cause', '')}"
    gen_text = f"{generated_risk.get('risk', '')} {generated_risk.get('cause', '')}"
    exp_assets = set(expert_risk.get("asset_ids", [])) | (set(_ID_PATTERN.findall(exp_text)) & known_assets)
    gen_assets = set(generated_risk.get("asset_ids", []))
    shared_assets = exp_assets & gen_assets
    shared_themes = _themes(exp_text) & _themes(gen_text)
    matched = (bool(exp_assets) and bool(shared_assets) and bool(shared_themes)) or len(shared_themes) >= 2
    return matched, shared_themes, shared_assets


def _risk_matches(expert_risk: dict[str, Any], generated_risk: dict[str, Any], known_assets: set[str]) -> bool:
    matched, _, _ = _risk_match_details(expert_risk, generated_risk, known_assets)
    return matched


def _explain_risk_match(
    expert_risk: dict[str, Any],
    generated_risks: list[dict[str, Any]],
    known_assets: set[str],
) -> dict[str, Any]:
    exp_text = f"{expert_risk.get('risk', '')} {expert_risk.get('cause', '')}"
    exp_assets = sorted(set(expert_risk.get("asset_ids", [])) | (set(_ID_PATTERN.findall(exp_text)) & known_assets))
    exp_themes = sorted(_themes(exp_text))
    matches: list[tuple[int, int, dict[str, Any], set[str], set[str]]] = []
    candidates: list[tuple[int, int, dict[str, Any], set[str], set[str]]] = []
    for gen in generated_risks:
        matched, shared_themes, shared_assets = _risk_match_details(expert_risk, gen, known_assets)
        entry = (len(shared_assets), len(shared_themes), gen, shared_themes, shared_assets)
        if matched:
            matches.append(entry)
        else:
            candidates.append(entry)

    if matches:
        matches.sort(key=lambda item: (item[0], item[1], item[2].get("id", "")), reverse=True)
        _, _, best, s_themes, s_assets = matches[0]
        return {
            "expert_id": expert_risk.get("id", ""),
            "expert_risk": expert_risk.get("risk", ""),
            "matched": True,
            "generated_id": best.get("id", ""),
            "shared_themes": sorted(s_themes),
            "shared_assets": sorted(s_assets),
            "reason": "matched",
        }

    if not exp_themes:
        reason = "No theme keywords detected in expert risk."
    elif candidates:
        candidates.sort(key=lambda item: (item[0] + item[1], item[1], item[0]), reverse=True)
        _, _, best, s_themes, s_assets = candidates[0]
        if s_themes or s_assets:
            reason = (
                f"Below threshold (needs asset+>=1 theme or >=2 themes); closest {best.get('id', '')} "
                f"shares themes={sorted(s_themes)} and assets={sorted(s_assets)} "
                f"(expert themes={exp_themes}, expert assets={exp_assets})."
            )
        else:
            reason = f"No generated risk shares any theme or asset (expert themes={exp_themes}, expert assets={exp_assets})."
    else:
        reason = "No generated risks to compare against."

    return {
        "expert_id": expert_risk.get("id", ""),
        "expert_risk": expert_risk.get("risk", ""),
        "matched": False,
        "generated_id": None,
        "shared_themes": [],
        "shared_assets": [],
        "reason": reason,
    }


def format_evaluation_explanation(comparison_data: dict[str, Any]) -> str:
    """Format per-asset strategy and per-risk matching explanations for CLI output."""
    lines = ["=== Strategy Comparison by Asset ==="]
    lines.append(f"{'Asset':<8} | {'Expected':<16} | {'Computed':<16} | {'Exit':<10} | Verdict")
    lines.append("-" * 72)
    for row in comparison_data.get("strategy_comparison", []):
        verdict = "MATCH" if row["match"] else "MISMATCH"
        lines.append(
            f"{row['asset_id']:<8} | {str(row.get('expected_strategy') or ''):<16} | "
            f"{str(row.get('actual_strategy') or ''):<16} | "
            f"{str(row.get('exit_strategy') or '-'):<10} | {verdict}"
        )
    lines.append("")
    lines.append("=== Expert Risk Matching ===")
    for item in comparison_data.get("risk_explanations", []):
        if item["matched"]:
            lines.append(
                f"{item['expert_id']} -> {item['generated_id']} | "
                f"themes={item['shared_themes']} | assets={item['shared_assets']}"
            )
        else:
            lines.append(f"{item['expert_id']} -> UNMATCHED | {item['reason']}")
    return "\n".join(lines)


def evaluate_results(
    portfolio: Portfolio,
    expert_path: str | Path,
    strategies: list[dict[str, Any]],
    sequencing: dict[str, Any],
    generated_risks: list[dict[str, Any]],
    output_dir: str | Path,
    docs_dir: str | Path | None = None,
) -> dict[str, Any]:
    expert = yaml.safe_load(Path(expert_path).read_text(encoding="utf-8"))
    expected_strategies = expert.get("strategies", {})
    actual_strategies = {item["asset_id"]: item["strategy"] for item in strategies}
    exit_strategies = {item["asset_id"]: item.get("exit_strategy") for item in strategies}
    strategy_rows = []
    for asset in portfolio.assets:
        expected = expected_strategies.get(asset.id, {}).get("strategy")
        actual = actual_strategies.get(asset.id)
        exit_strategy = exit_strategies.get(asset.id)
        compared = exit_strategy if actual == "retain_under_tsa" and exit_strategy else actual
        strategy_rows.append({
            "asset_id": asset.id,
            "expected_strategy": expected,
            "actual_strategy": actual,
            "exit_strategy": exit_strategy,
            "compared_strategy": compared,
            "match": expected == compared,
        })

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
    known_assets = {asset.id for asset in portfolio.assets}
    expert_risks = expert.get("top_risks", [])
    risk_explanations = [
        _explain_risk_match(exp, generated_risks, known_assets)
        for exp in expert_risks
    ]
    covered_risks = sum(1 for item in risk_explanations if item["matched"])
    risk_coverage = covered_risks / max(1, len(expert_risks))

    references = set(actual_strategies)
    references.update(actual_wave)
    for risk in generated_risks:
        references.update(risk.get("asset_ids", []))
    known_non_assets = (
        {lic.id for lic in portfolio.licences}
        | {tsa.id for tsa in portfolio.tsa_services}
        | {risk.get("id", "") for risk in generated_risks}
    )
    if docs_dir is not None and Path(docs_dir).exists():
        for md_path in Path(docs_dir).rglob("*.md"):
            text = md_path.read_text(encoding="utf-8")
            references.update(set(_ID_PATTERN.findall(text)) - known_non_assets)
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
        and (
            (relation.target not in retained_under_tsa and actual_wave[relation.source] < actual_wave[relation.target])
            or (relation.target in retained_under_tsa and actual_wave[relation.source] > actual_wave[relation.target])
        )
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
        "risk_explanations": risk_explanations,
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
