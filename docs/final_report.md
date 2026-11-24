# Dependency-graph separation planner

**Project report — 25 November 2026**

## Summary

This project implements a deterministic planner for a fictional IT carve-out.
It validates a portfolio, builds an application dependency graph, assigns
explainable strategies, groups assets into cutover waves, flags TSA and licence
date conflicts, and produces separation documents. The algorithm decides
strategies and order; optional Claude calls can add explanatory prose only.

The 30-asset Nordia Retail portfolio produced seven waves, one detected cycle,
zero dependency-order violations, and zero unknown IDs in structured output
references. The latest estimated completion is 18 December 2028, one year after
the portfolio's target TSA exit. This exposes material schedule risk rather
than a plan that is ready to execute.

## Problem and objective

An IT separation must coordinate applications, data stores, infrastructure,
contracts, shared services and business cutovers. Moving a dependent system
before its prerequisite is ready can interrupt operations. Shared parent
services also need to remain available while the buyer builds replacements, but
their TSA dates and costs can constrain the programme.

The objective is to produce an auditable, repeatable baseline from structured
portfolio data. Computed decisions must be explainable and stable; generated
documents may describe those decisions but cannot change them.

## Data and method

The Pydantic model and JSON schema describe assets, relationships, licences,
TSA services and planning dates. The fictional portfolio has 30 assets, 61
relationships, seven licences and four TSA services. It deliberately includes
shared ERP, shared identity, sensitive data, a non-transferable licence, an
expiring payment licence, an unused application, duplicate CRM functionality,
an inventory/WMS cycle, TSA end-date conflicts and wave capacity pressure.

Each relationship is directed from consumer to prerequisite: `source -> target`
means the source depends on the target. NetworkX supplies graph queries and
strongly connected components. The scheduler condenses cycles, places
prerequisites first, respects wave capacity and freeze periods, and computes
dates from the effort estimates and gap after each completed wave. Assets
retained under a TSA remain available to consumers and are scheduled to exit
after those consumers.

Ordered YAML rules assign one of five strategies: clone, migrate, rebuild,
retire, or retain under TSA. Every result contains a reason, confidence and
matched rule. TSA and licence conflicts are calculated from scheduled asset
completion dates. Metrics summarize waves, dependency depth, cycles and TSA
cost exposure.

The expert plan was written separately from the sequencing implementation. A
second, four-asset portfolio checks whether the core scheduling invariants
hold outside the main example.

## Architecture and outputs

See [architecture.md](architecture.md). The CLI runs validation, graph export,
strategy assessment, sequencing, document rendering and evaluation. The
default deterministic pipeline writes:

- Validation report, dependency graph JSON and interactive HTML.
- Strategy assessment, `waves.json` and metrics.
- Separation plan and one cutover runbook per wave.
- TSA exit schedule, risk register and dependency summary.
- Expert comparison and second-portfolio robustness report.

Generated files are written under the ignored `output/` and `logs/`
directories. Evaluation artifacts are versioned under `evaluation/`.

## Results

| Measure | Result | Interpretation |
|---|---:|---|
| Assets scheduled | 30 / 30 | Every main-portfolio asset is assigned a wave. |
| Planned waves | 7 | Wave capacity is at most 8 assets. |
| Longest dependency chain | 5 components | Based on the condensed dependency graph. |
| Dependency violations | 0 | Target is zero. |
| Cycles | 1, grouped | APP-06 and APP-07 remain together. |
| Strategy match to expert plan | 83.33% | 25 of 30 strategy labels match. |
| Exact expert wave match | 20.00% | Same wave number for 6 of 30 assets. |
| Pairwise wave-order similarity | 67.86% | Preserves the relative order of about two thirds of compared asset pairs. |
| Expert risk coverage | 80.00% | 8 of 10 reference risk IDs are represented. |
| Unknown structured asset references | 0 | No unknown asset IDs were found. |

The robustness portfolio schedules all four assets, detects no cycles and has
zero dependency violations. These checks establish basic pipeline behavior;
they do not prove operational readiness for a real carve-out.

## Schedule and cost findings

The current effort inputs produce a latest completion of 18 December 2028,
against a target TSA exit of 31 December 2027. The estimated TSA exposure is
$3.415 million across the four services:

| TSA | Estimated months | Estimated cost |
|---|---:|---:|
| TSA-01 | 24 | $2,040,000 |
| TSA-02 | 8 | $240,000 |
| TSA-03 | 7 | $175,000 |
| TSA-04 | 16 | $960,000 |

The scheduler flags seven date conflicts: APP-08 completes after LIC-04 expires;
APP-09, DB-05 and INF-02 need extendable TSA coverage; APP-14, APP-19 and APP-01
complete after their TSA end dates, including the non-extendable TSA-01. These
figures are scenario estimates from fictional effort data, not vendor quotes or
approved extension costs. TSA-01 and the overall target date need an explicit
contingency decision.

## Evaluation and failure analysis

The largest strategy differences are INF-04, APP-13 and APP-18: the expert
plan describes validating existing target-owned components as migrations,
while the ordered rules classify them as clones. APP-14 and APP-19 are expected
as rebuilds by the expert but retained under TSA by the current shared-service
rule. The rule configuration and expert definitions should be reconciled by
reviewing the intended destination and ownership for each asset, not by tuning
the engine blindly to increase its score.

Exact wave matching is low because it compares numeric wave assignments asset
by asset. Pairwise order similarity is more informative for grouping
differences, while the zero dependency violations and grouped cycle show that
the dependency invariants held. Risk coverage is short by two reference risks;
the risk rules should add explicit contract-transfer and TSA-extension risks.

No AI provider was called for these results. The reported unknown-reference
count checks structured strategy, wave and risk asset IDs; prose hallucination
rates require running the optional AI generation path with a configured model.

## Limitations

- The portfolio, effort and dates are fictional and hand-estimated.
- Rules are currently portfolio-specific and require owner review before reuse.
- One effort duration per asset is used; workstreams and staff capacity are not
  modeled at task level.
- Dates use a simple gap between completed waves, not a resource-constrained
  project schedule or full business calendar.
- Risk generation covers selected known patterns, not a complete risk method.
- Optional AI narrative generation has not been exercised against a live
  provider; core documents are deterministic templates and tables.

## Conclusion and next work

The prototype meets its core safety checks: all assets are scheduled, the cycle
is grouped, dependency violations are zero, and the modified portfolio passes
the robustness invariants. Its date analysis also reveals that the present
portfolio assumptions miss the target exit by a year and outlive key TSA and
licence dates. Before using the plan operationally, owners should resolve the
strategy mismatches, validate the effort estimates, and approve a TSA
contingency. A richer calendar/resource scheduler, reviewed risk rules, live
AI validation, and a polished interactive demo are the next extensions.
