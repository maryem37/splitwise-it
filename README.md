# Carve-out Copilot

Python toolkit for separating an IT portfolio using a dependency graph. The
algorithm owns strategy and sequencing; optional AI generates explanatory
narrative around computed results.

## Setup

Requires Python 3.11 or newer.

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -e ".[dev]"
```

## Commands

```powershell
carveout validate
carveout schema
carveout graph
carveout strategy
carveout waves
carveout generate
carveout evaluate
carveout run-all
```

The portfolio and hand-authored reference plan are in `data/`. Configuration is
in `config/`. Generated documents and computed files go to `output/`; comparison
results go to `evaluation/`. See [docs/usage.md](docs/usage.md) for the AI option.
