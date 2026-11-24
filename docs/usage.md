# Running the pipeline

Install Python 3.11 or newer and the project dependencies from the repository
root:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -e ".[dev]"
```

The commands create reproducible outputs under `output/`; evaluation files are
written under `evaluation/`. No frontend is needed: the CLI runs the pipeline
and writes files you can open directly.

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

To enable Groq narrative sections, install the optional provider and create a
local `.env` file from the example, then set `GROQ_API_KEY` and `GROQ_MODEL`
there:

```powershell
py -m pip install -e ".[ai]"
Copy-Item .env.example .env
# Edit .env with your key and model ID before running the command.
carveout generate --ai
```

The AI writes explanatory prose only. Code supplies the asset lists, decisions,
wave dates, runbook checklists, TSA schedule, and risk register. Inputs and model
responses are logged under `logs/`; keep secrets out of those files.
