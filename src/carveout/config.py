"""Centralized configuration for carveout agents, models, and environments."""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "groq")
GROQ_API_KEY: str | None = os.getenv("GROQ_API_KEY")
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

AGENT_TEMPERATURE: float = float(os.getenv("AGENT_TEMPERATURE", "0.0"))
AGENT_MAX_TOKENS: int = int(os.getenv("AGENT_MAX_TOKENS", "4096"))

DEFAULT_PORTFOLIO_PATH: Path = PROJECT_ROOT / "data" / "portfolio_v1.yaml"
DEFAULT_RULES_PATH: Path = PROJECT_ROOT / "config" / "strategy_rules.yaml"
DEFAULT_CONSTRAINTS_PATH: Path = PROJECT_ROOT / "config" / "constraints.yaml"
