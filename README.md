# Splitwise IT

A deterministic dependency-graph planner for separating a fictional business unit's IT portfolio. It validates portfolio data and, in later phases, computes explainable strategies and migration waves before generating human-readable planning documents.

## Project rule

The code owns asset strategies, dependencies, sequencing and dates. An optional language model may explain computed results in documents, but it must not change those decisions.

## Current status

- Phase 1: Pydantic portfolio model in `src/carveout/models.py`.
- Phase 2: YAML loading and integrity validation in `src/carveout/loader.py`.
- Phase 3: fictional Nordia Retail portfolio, edge-case notes and a manually authored expert reference plan.
- Next: dependency graph and impact queries (Phase 4).

## Requirements

- Python 3.11 or newer

Install the current dependencies:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Load and validate the sample portfolio from Python:

```python
from carveout.loader import load_portfolio, validate_portfolio

portfolio = load_portfolio("data/portfolio_v1.yaml")
report = validate_portfolio(portfolio)
print(report)
```

The `src` layout is not packaged yet; set `PYTHONPATH=src` when running this snippet from the repository root, or install the project after packaging is added.

## Repository map

```text
config/       strategy and sequencing rules (planned)
data/         sample portfolio and expert reference
docs/         architecture and final report (planned)
evaluation/   comparison results (planned)
prompts/      versioned document-generation prompts (planned)
src/carveout/ portfolio model, validation and planning modules
templates/    document templates (planned)
tests/        loader checks
```

## Data conventions

- Relationships are directed from a dependent asset to the asset it depends on: `source -> target` means the target must be ready before the source can cut over.
- The sample portfolio is fictional and its deliberate edge cases are documented in `data/README.md`.
- `data/expert_plan_v1.yaml` is the human reference for later evaluation; algorithm output should be compared with it rather than used to rewrite it.
- Generated outputs and logs are excluded from Git. Never commit API keys or `.env` files.

## Planned phases

1. Data model and JSON schema.
2. Loader and validation report.
3. Fictional portfolio and expert reference plan.
4. Dependency graph, queries and visualization.
5. Configurable strategy assessment.
6. Cycle-aware sequencing and constraints.
7. Metrics.
8. Guarded document generation and rendering.
9. CLI and end-to-end evaluation.
10. Report and demo; optional MCP/Streamlit extras if time permits.
