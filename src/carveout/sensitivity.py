"""Scenario sensitivity and Monte Carlo schedule/cost simulation."""
from __future__ import annotations

from collections import Counter
import csv
from datetime import date
import json
import math
from pathlib import Path
import random
from typing import Any

from .metrics import calculate_metrics
from .models import Portfolio
from .sequencing import _add_months, compute_waves


def _clone_portfolio(portfolio: Portfolio) -> Portfolio:
    return Portfolio.model_validate(portfolio.model_dump())


def _evaluate_scenario(
    name: str,
    portfolio: Portfolio,
    constraints_path: str | Path | None,
    strategies: list[dict[str, Any]],
    extra_tsa_cost: float = 0.0,
) -> dict[str, Any]:
    sequencing = compute_waves(portfolio, constraints_path, strategies)
    metrics = calculate_metrics(portfolio, sequencing)
    latest = date.fromisoformat(metrics["latest_planned_completion"])
    margin_days = (portfolio.planning.target_tsa_exit - latest).days
    total_cost = round(metrics["estimated_tsa_cost_total"] + extra_tsa_cost, 2)
    return {
        "scenario": name,
        "wave_count": metrics["wave_count"],
        "latest_planned_completion": metrics["latest_planned_completion"],
        "estimated_tsa_cost_total": total_cost,
        "conflict_count": len(sequencing["conflicts"]),
        "margin_to_target_days": margin_days,
        "details": "",
    }


def _apply_max_parallel_builds(portfolio: Portfolio, max_parallel: int = 3) -> None:
    """Greedy LPT scheduling of build_effort_weeks across `max_parallel` slots."""
    build_assets = sorted(
        (asset for asset in portfolio.assets if asset.build_effort_weeks > 0),
        key=lambda asset: (-asset.build_effort_weeks, asset.id),
    )
    slots = [0] * max_parallel
    for asset in build_assets:
        idx = min(range(max_parallel), key=lambda k: slots[k])
        finish = slots[idx] + asset.build_effort_weeks
        slots[idx] = finish
        asset.build_effort_weeks = finish


def _run_monte_carlo(
    portfolio: Portfolio,
    constraints_path: str | Path | None,
    strategies: list[dict[str, Any]],
    trials: int = 1000,
    seed: int = 42,
) -> tuple[dict[str, Any], dict[str, Any]]:
    rng = random.Random(seed)
    completions: list[date] = []
    costs: list[float] = []
    wave_counts: list[int] = []
    conflict_counts: list[int] = []
    margins: list[int] = []
    meets_target = 0

    for _ in range(trials):
        sim = _clone_portfolio(portfolio)
        for asset in sim.assets:
            if asset.build_effort_weeks > 0:
                asset.build_effort_weeks = max(
                    0, round(asset.build_effort_weeks * rng.triangular(0.8, 1.5, 1.0))
                )
            if asset.effort_weeks > 0:
                asset.effort_weeks = max(
                    1, round(asset.effort_weeks * rng.triangular(0.8, 1.5, 1.0))
                )
        seq = compute_waves(sim, constraints_path, strategies)
        metrics = calculate_metrics(sim, seq)
        latest = date.fromisoformat(metrics["latest_planned_completion"])
        completions.append(latest)
        costs.append(metrics["estimated_tsa_cost_total"])
        wave_counts.append(metrics["wave_count"])
        conflict_counts.append(len(seq["conflicts"]))
        margins.append((sim.planning.target_tsa_exit - latest).days)
        if latest <= sim.planning.target_tsa_exit:
            meets_target += 1

    sorted_dates = sorted(completions)
    p50_date = sorted_dates[int(0.50 * (trials - 1))]
    p80_date = sorted_dates[int(0.80 * (trials - 1))]
    prob_target = round(100.0 * meets_target / trials, 2)
    conflict_dist = {str(k): v for k, v in sorted(Counter(conflict_counts).items())}

    mc_stats = {
        "trials": trials,
        "seed": seed,
        "p50_completion": p50_date.isoformat(),
        "p80_completion": p80_date.isoformat(),
        "target_tsa_exit": portfolio.planning.target_tsa_exit.isoformat(),
        "target_exit_probability_percent": prob_target,
        "conflict_count_distribution": conflict_dist,
        "mean_tsa_cost": round(sum(costs) / trials, 2),
        "mean_wave_count": round(sum(wave_counts) / trials, 2),
        "p50_margin_days": (portfolio.planning.target_tsa_exit - p50_date).days,
    }
    row = {
        "scenario": f"monte_carlo_{trials}",
        "wave_count": round(sum(wave_counts) / trials, 2),
        "latest_planned_completion": f"P50={p50_date.isoformat()} / P80={p80_date.isoformat()}",
        "estimated_tsa_cost_total": mc_stats["mean_tsa_cost"],
        "conflict_count": round(sum(conflict_counts) / trials, 2),
        "margin_to_target_days": mc_stats["p50_margin_days"],
        "details": f"P(on_time)={prob_target}%, conflicts={json.dumps(conflict_dist)}",
    }
    return row, mc_stats


def run_sensitivity(
    portfolio: Portfolio,
    constraints_path: str | Path | None,
    strategies: list[dict[str, Any]],
    output_dir: str | Path,
    trials: int = 1000,
    seed: int = 42,
) -> dict[str, Any]:
    """Run deterministic sensitivity scenarios + Monte Carlo and write CSV/MD reports."""
    rows: list[dict[str, Any]] = []

    # 1. Base
    rows.append(_evaluate_scenario("base", _clone_portfolio(portfolio), constraints_path, strategies))

    # 2. All builds delayed by 4 weeks
    p_delay = _clone_portfolio(portfolio)
    for asset in p_delay.assets:
        if asset.build_effort_weeks > 0:
            asset.build_effort_weeks += 4
    rows.append(_evaluate_scenario("all_builds_delayed_4w", p_delay, constraints_path, strategies))

    # 3. build_effort_weeks +30%
    p_plus30 = _clone_portfolio(portfolio)
    for asset in p_plus30.assets:
        if asset.build_effort_weeks > 0:
            asset.build_effort_weeks = math.ceil(asset.build_effort_weeks * 1.3)
    rows.append(_evaluate_scenario("build_effort_plus_30pct", p_plus30, constraints_path, strategies))

    # 4. At most 3 parallel builds (greedy LPT)
    p_par3 = _clone_portfolio(portfolio)
    _apply_max_parallel_builds(p_par3, max_parallel=3)
    rows.append(_evaluate_scenario("max_3_parallel_builds", p_par3, constraints_path, strategies))

    # 5. TSA-01 extended by 6 months (+6 * monthly_cost, recalculate conflicts)
    p_tsa01 = _clone_portfolio(portfolio)
    extra_cost = 0.0
    for svc in p_tsa01.tsa_services:
        if svc.id == "TSA-01":
            svc.end_date = _add_months(svc.end_date, 6)
            extra_cost = 6 * svc.monthly_cost
            break
    rows.append(_evaluate_scenario("tsa_01_extended_6m", p_tsa01, constraints_path, strategies, extra_tsa_cost=extra_cost))

    # 6. Monte Carlo
    mc_row, mc_stats = _run_monte_carlo(portfolio, constraints_path, strategies, trials=trials, seed=seed)
    rows.append(mc_row)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    columns = [
        "scenario", "wave_count", "latest_planned_completion",
        "estimated_tsa_cost_total", "conflict_count", "margin_to_target_days", "details",
    ]
    with (out / "sensitivity.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    md_lines = [
        "# Sensitivity analysis",
        "",
        f"Target TSA exit: `{portfolio.planning.target_tsa_exit.isoformat()}`",
        "",
        "## Scenarios",
        "",
        "| Scenario | Waves | Latest completion | TSA cost | Conflicts | Margin to target (days) |",
        "|---|---:|---|---:|---:|---:|",
    ]
    for row in rows:
        md_lines.append(
            f"| {row['scenario']} | {row['wave_count']} | {row['latest_planned_completion']} | "
            f"{row['estimated_tsa_cost_total']:,.2f} | {row['conflict_count']} | {row['margin_to_target_days']} |"
        )
    md_lines.extend([
        "",
        f"## Monte Carlo ({mc_stats['trials']} trials, seed={mc_stats['seed']})",
        "",
        f"- **P50 completion date:** `{mc_stats['p50_completion']}` (margin: {mc_stats['p50_margin_days']} days)",
        f"- **P80 completion date:** `{mc_stats['p80_completion']}`",
        f"- **Probability of meeting `target_tsa_exit` (`{mc_stats['target_tsa_exit']}`):** {mc_stats['target_exit_probability_percent']}%",
        "- **Conflict count distribution:**",
    ])
    for count_str, freq in mc_stats["conflict_count_distribution"].items():
        md_lines.append(f"  - `{count_str}` conflicts: {freq} / {mc_stats['trials']} trials")
    (out / "sensitivity.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    return {"scenarios": rows, "monte_carlo": mc_stats}
