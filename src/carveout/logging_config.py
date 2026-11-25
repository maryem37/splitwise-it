"""Structured logging, formatting, and thread context for Carve-out Copilot."""
from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

# Context variables for thread-local workflow context
_CURRENT_THREAD_ID: contextvars.ContextVar[str] = contextvars.ContextVar("current_thread_id", default="")
_CURRENT_NODE_NAME: contextvars.ContextVar[str] = contextvars.ContextVar("current_node_name", default="")
_CURRENT_WORKFLOW_STATUS: contextvars.ContextVar[str] = contextvars.ContextVar("current_workflow_status", default="")


def set_workflow_context(thread_id: str = "", node_name: str = "", workflow_status: str = "") -> None:
    """Set the workflow context for the current thread/task."""
    if thread_id:
        _CURRENT_THREAD_ID.set(thread_id)
    if node_name:
        _CURRENT_NODE_NAME.set(node_name)
    if workflow_status:
        _CURRENT_WORKFLOW_STATUS.set(workflow_status)


def get_workflow_context() -> dict[str, str]:
    """Retrieve the current thread ID, node name, and workflow status."""
    return {
        "thread_id": _CURRENT_THREAD_ID.get(),
        "node_name": _CURRENT_NODE_NAME.get(),
        "workflow_status": _CURRENT_WORKFLOW_STATUS.get(),
    }


def clear_workflow_context() -> None:
    """Reset the workflow context."""
    _CURRENT_THREAD_ID.set("")
    _CURRENT_NODE_NAME.set("")
    _CURRENT_WORKFLOW_STATUS.set("")


class WorkflowContextFilter(logging.Filter):
    """Logging filter that injects thread_id, node_name, and workflow_status into records."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = get_workflow_context()
        record.thread_id = getattr(record, "thread_id", None) or ctx["thread_id"] or "-"
        record.node_name = getattr(record, "node_name", None) or ctx["node_name"] or "-"
        record.workflow_status = getattr(record, "workflow_status", None) or ctx["workflow_status"] or "-"
        return True


class JsonFormatter(logging.Formatter):
    """Structured JSON formatter for production observability."""

    def format(self, record: logging.LogRecord) -> str:
        ctx = get_workflow_context()
        log_obj: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "thread_id": getattr(record, "thread_id", None) or ctx["thread_id"] or None,
            "node_name": getattr(record, "node_name", None) or ctx["node_name"] or None,
            "workflow_status": getattr(record, "workflow_status", None) or ctx["workflow_status"] or None,
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj, ensure_ascii=False)


class HumanReadableFormatter(logging.Formatter):
    """Human-readable console formatter displaying thread and node context when present."""

    def format(self, record: logging.LogRecord) -> str:
        t_id = getattr(record, "thread_id", "-")
        node = getattr(record, "node_name", "-")
        ctx_part = ""
        if t_id != "-" or node != "-":
            ctx_part = f" [{t_id} | {node}]"
        prefix = f"{record.levelname:<7} {record.name}{ctx_part}: "
        msg = record.getMessage()
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            return f"{prefix}{msg}\n{exc_text}"
        return f"{prefix}{msg}"


_LOGGING_CONFIGURED = False


def configure_logging(
    level: str | int | None = None,
    json_format: bool = False,
    force: bool = False,
) -> None:
    """
    Configure standard logging for Carve-out Copilot.
    Honors CARVEOUT_LOG_LEVEL and CARVEOUT_LOG_JSON env vars if not explicitly passed.
    """
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED and not force:
        return

    env_level = os.environ.get("CARVEOUT_LOG_LEVEL", "INFO").upper()
    env_json = os.environ.get("CARVEOUT_LOG_JSON", "false").lower() in ("1", "true", "yes")

    chosen_level = level if level is not None else env_level
    chosen_json = json_format or env_json

    root_logger = logging.getLogger("carveout")
    root_logger.setLevel(chosen_level)
    root_logger.propagate = False

    # Remove existing handlers to avoid duplicates
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(chosen_level)
    handler.addFilter(WorkflowContextFilter())

    if chosen_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(HumanReadableFormatter())

    root_logger.addHandler(handler)
    _LOGGING_CONFIGURED = True
