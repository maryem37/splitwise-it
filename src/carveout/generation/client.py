"""Optional Groq JSON-output client for narrative-only sections."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from .guardrails import validate_document_references


class NarrativeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    narrative: str
    referenced_asset_ids: list[str]
    referenced_wave_numbers: list[int]


def generate_narrative(
    prompt_path: str | Path,
    payload: dict[str, Any],
    known_asset_ids: set[str],
    known_wave_numbers: set[int],
    log_name: str,
) -> str:
    """Call Groq for explanatory prose; reject unknown references and retry once."""
    try:
        from groq import Groq
        from dotenv import load_dotenv
    except ImportError as exc:
        raise RuntimeError("Install the optional 'ai' dependency to enable Groq generation.") from exc

    project_root = Path(__file__).resolve().parents[3]
    load_dotenv(project_root / ".env")
    prompt = Path(prompt_path).read_text(encoding="utf-8")
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("Set GROQ_API_KEY in the environment or local .env file.")
    model = os.environ.get("GROQ_MODEL")
    if not model:
        raise RuntimeError("Set GROQ_MODEL to a model ID to enable Groq generation.")
    client = Groq(api_key=api_key)
    logs = project_root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    request_payload = {"prompt": prompt, "input": payload}
    (logs / f"{log_name}.input.json").write_text(
        json.dumps(request_payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    last_error: Exception | None = None
    for attempt in range(2):
        user_text = (
            f"{prompt}\n\n<computed_input>\n{json.dumps(payload, ensure_ascii=False)}\n</computed_input>"
        )
        if attempt and last_error:
            user_text += f"\n\nCorrect your previous output. Validation error: {last_error}"
        response = client.chat.completions.create(
            model=model,
            max_tokens=2500,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Return only one valid JSON object with exactly these keys: "
                        "narrative (string), referenced_asset_ids (array of strings), "
                        "referenced_wave_numbers (array of integers)."
                    ),
                },
                {"role": "user", "content": user_text},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "narrative_output",
                    "strict": True,
                    "schema": NarrativeOutput.model_json_schema(),
                },
            },
        )
        response_text = response.choices[0].message.content or ""
        (logs / f"{log_name}.attempt-{attempt + 1}.json").write_text(
            response_text, encoding="utf-8"
        )
        try:
            result = NarrativeOutput.model_validate_json(response_text)
            validate_document_references(
                {"asset_ids": result.referenced_asset_ids,
                 "wave_numbers": result.referenced_wave_numbers},
                known_asset_ids, known_wave_numbers,
            )
            mention_pattern = re.compile(r"\b[A-Z][A-Z0-9]*(?:-\d+)+\b")
            all_known_ids = set(known_asset_ids)
            all_known_ids.update(payload.get("known_non_asset_ids", []))
            unknown_mentions = sorted(set(mention_pattern.findall(result.narrative)) - all_known_ids)
            if unknown_mentions:
                raise ValueError(f"Narrative mentions unknown identifiers: {unknown_mentions}")
            return result.narrative
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc
    assert last_error is not None
    raise ValueError(f"Narrative generation failed validation after retry: {last_error}")
