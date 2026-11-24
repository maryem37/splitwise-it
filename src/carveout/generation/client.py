"""Optional Anthropic structured-output client for narrative-only sections."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .guardrails import validate_document_references


class NarrativeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    narrative: str
    referenced_asset_ids: list[str] = Field(default_factory=list)
    referenced_wave_numbers: list[int] = Field(default_factory=list)


def generate_narrative(
    prompt_path: str | Path,
    payload: dict[str, Any],
    known_asset_ids: set[str],
    known_wave_numbers: set[int],
    log_name: str,
) -> str:
    """Call Claude for explanatory prose; reject unknown references and retry once."""
    try:
        import anthropic
        from dotenv import load_dotenv
    except ImportError as exc:
        raise RuntimeError("Install the optional 'ai' dependency to enable Claude generation.") from exc

    project_root = Path(__file__).resolve().parents[3]
    load_dotenv(project_root / ".env")
    prompt = Path(prompt_path).read_text(encoding="utf-8")
    model = os.environ.get("CARVEOUT_LLM_MODEL")
    if not model:
        raise RuntimeError("Set CARVEOUT_LLM_MODEL to the Claude model ID to enable AI generation.")
    client = anthropic.Anthropic()
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
        response = client.messages.create(
            model=model,
            max_tokens=2500,
            messages=[{"role": "user", "content": user_text}],
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": NarrativeOutput.model_json_schema(),
                }
            },
        )
        response_text = next((block.text for block in response.content if block.type == "text"), "")
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
