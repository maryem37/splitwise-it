"""Optional Groq JSON-output client for narrative-only sections."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from .guardrails import validate_document_references, validate_narrative_content


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
        from groq import Groq, RateLimitError
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
    # Keep retries here so rate-limit headers and recovery logs are handled once.
    client = Groq(api_key=api_key, max_retries=0)
    logs = project_root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    request_payload = {"model": model, "prompt": prompt, "input": payload}
    input_path = logs / f"{log_name}.input.json"
    if input_path.exists():
        try:
            cached_input = json.loads(input_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached_input = None
        legacy_cached_input = {"prompt": prompt, "input": payload}
        if cached_input in (request_payload, legacy_cached_input):
            for cached_attempt in range(1, 3):
                response_path = logs / f"{log_name}.attempt-{cached_attempt}.json"
                if not response_path.exists():
                    continue
                try:
                    return _validate_narrative(
                        response_path.read_text(encoding="utf-8"), payload,
                        known_asset_ids, known_wave_numbers,
                    )
                except (ValueError, json.JSONDecodeError):
                    continue
    for cached_attempt in range(1, 3):
        (logs / f"{log_name}.attempt-{cached_attempt}.json").unlink(missing_ok=True)

    input_path.write_text(
        json.dumps(request_payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    last_error: Exception | None = None
    for attempt in range(2):
        user_text = (
            f"{prompt}\n\n<computed_input>\n{json.dumps(payload, ensure_ascii=False)}\n</computed_input>"
        )
        if attempt and last_error:
            user_text += f"\n\nCorrect your previous output. Validation error: {last_error}"
        for rate_attempt in range(5):
            try:
                response = client.chat.completions.create(
                    model=model,
                    temperature=0,
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
                break
            except RateLimitError as exc:
                wait_seconds = _retry_after_seconds(exc, rate_attempt)
                if rate_attempt == 4:
                    raise RuntimeError(
                        "Groq rate limit persisted after five retries; "
                        f"wait about {wait_seconds:.1f}s and rerun."
                    ) from exc
                time.sleep(wait_seconds)
        response_text = response.choices[0].message.content or ""
        (logs / f"{log_name}.attempt-{attempt + 1}.json").write_text(
            response_text, encoding="utf-8"
        )
        try:
            return _validate_narrative(
                response_text, payload, known_asset_ids, known_wave_numbers
            )
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc
    assert last_error is not None
    raise ValueError(f"Narrative generation failed validation after retry: {last_error}")


def _validate_narrative(
    response_text: str,
    payload: dict[str, Any],
    known_asset_ids: set[str],
    known_wave_numbers: set[int],
) -> str:
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
    known_dates = set(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", json.dumps(payload, ensure_ascii=False)))
    validate_narrative_content(
        result.narrative,
        known_dates=known_dates,
        has_retired_assets=bool(payload.get("retired_asset_ids")),
        is_final_wave=payload.get("is_final_wave", True),
    )
    return result.narrative


def _retry_after_seconds(error: Exception, attempt: int) -> float:
    """Prefer Groq's retry/reset headers, then its message, then backoff."""
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", {}) or {}
    candidates = [headers.get("retry-after"), headers.get("x-ratelimit-reset-tokens")]
    match = re.search(
        r"try again in\s+(\d+(?:\.\d+)?)\s*(ms|s|m)", str(error), re.IGNORECASE
    )
    if match:
        candidates.append(match.group(1) + match.group(2))
    for value in candidates:
        if value is None:
            continue
        parsed = re.fullmatch(
            r"\s*(\d+(?:\.\d+)?)\s*(ms|s|m)?\s*", str(value), re.IGNORECASE
        )
        if not parsed:
            continue
        amount = float(parsed.group(1))
        unit = (parsed.group(2) or "s").lower()
        seconds = amount / 1000 if unit == "ms" else amount * 60 if unit == "m" else amount
        return max(0.1, min(seconds, 120.0))
    return min(2.0 ** attempt, 30.0)
