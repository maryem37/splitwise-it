# Dependency-graph separation planner — final report

## Problem and objective

Explain the IT carve-out planning problem and the need to keep shared services,
licences, dependencies, TSA dates, and business cutovers aligned.

## Data and method

Describe the Nordia Retail portfolio, schema, deliberate edge cases, and the
hand-authored expert reference plan. Explain the deterministic strategy rules,
dependency direction, SCC grouping, capacity limits, and date constraints.

## Architecture

Refer to [architecture.md](architecture.md). The code computes strategies,
waves, dates, metrics, and risks. Optional Groq output only supplies narrative
sections; document tables are rendered from computed values.

## Results

Populate this section from `evaluation/results.csv`, `evaluation/comparison.json`,
`evaluation/robustness.json`, and the generated files under `output/` after running
`carveout run-all`. Report dependency violations, cycle handling, strategy match,
wave order similarity, risk coverage, unknown asset references, and TSA conflicts.

## Failure analysis

Use the strategy mismatches and dependency violation list from
`evaluation/comparison.json`. Explain disagreements with the expert plan and
whether the rule set or reference plan needs revision.

## Limitations

- Effort and calendar dates are estimates from the fictional input.
- Current strategy rules are ordered and portfolio-specific; they need review
  before reuse on another company.
- The sequencing model uses one planned start per wave and does not model
  resource calendars or task-level parallelism.
- AI prose is optional and requires a configured provider; deterministic tables
  and risk entries do not depend on it.

## Conclusion and future work

Summarize whether the graph and sequencing checks met their targets. Possible
extensions include calibrated effort estimates, richer freeze calendars,
resource-constrained scheduling, an MCP server, and a Streamlit demo.
