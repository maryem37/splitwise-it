"""Checkpointer factory and helpers for persistent SQLite and in-memory workflows."""
from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger("carveout.checkpointer")

DEFAULT_DB_DIR = Path(".carveout")
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "checkpoints.sqlite"


def get_default_db_path() -> Path:
    """Return default checkpoint SQLite database path, honoring CARVEOUT_CHECKPOINT_DB if set."""
    env_path = os.environ.get("CARVEOUT_CHECKPOINT_DB")
    if env_path:
        return Path(env_path)
    return DEFAULT_DB_PATH


def validate_db_path(db_path: str | Path | None) -> Path:
    """Validate that the database path is usable and parent directory is creatable."""
    path = Path(db_path) if db_path is not None else get_default_db_path()
    try:
        if path.is_dir():
            raise IsADirectoryError(f"Checkpoint path '{path}' is a directory, not a SQLite file.")
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(f"Invalid checkpoint database path '{path}': {e}")
        raise ValueError(f"Cannot initialize checkpoint storage at '{path}': {e}") from e
    return path


@contextmanager
def get_checkpointer(
    db_path: str | Path | None = None,
    in_memory: bool = False,
    timeout: float = 15.0,
) -> Iterator[BaseCheckpointSaver]:
    """
    Context manager providing a BaseCheckpointSaver.
    - If in_memory is True, yields MemorySaver.
    - Otherwise, initializes SqliteSaver using a hardened sqlite3 connection with WAL mode and busy_timeout.
    - Guarantees cleanup: executes commit and closes connection on exit.
    - Never silently falls back to MemorySaver if persistent storage fails.
    """
    if in_memory:
        logger.debug("Using in-memory checkpoint saver.")
        yield MemorySaver()
        return

    path = validate_db_path(db_path)

    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError as e:
        logger.error("langgraph-checkpoint-sqlite is not installed.")
        raise RuntimeError(
            "Persistent SQLite checkpointing requested, but 'langgraph-checkpoint-sqlite' is not installed. "
            "Install it or use in_memory=True."
        ) from e

    logger.debug(f"Connecting to SQLite checkpoint database at {path}")
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(
            str(path),
            timeout=timeout,
            check_same_thread=False,
            isolation_level=None,  # autocommit mode in Python 3.11
        )
        # Configure SQLite for operational resilience: WAL mode and busy timeout
        conn.execute(f"PRAGMA busy_timeout = {int(timeout * 1000)};")
        conn.execute("PRAGMA journal_mode = WAL;")

        saver = SqliteSaver(conn)
        saver.setup()
        yield saver
    except sqlite3.OperationalError as oe:
        logger.error(f"SQLite operational error on '{path}': {oe}")
        raise
    except Exception as exc:
        logger.error(f"Failed to initialize SQLite checkpointer on '{path}': {exc}")
        raise
    finally:
        if conn is not None:
            try:
                conn.close()
                logger.debug(f"Closed connection to SQLite database at {path}")
            except Exception as close_err:
                logger.warning(f"Error closing SQLite connection: {close_err}")


def checkpoint_exists(thread_id: str, db_path: str | Path | None = None, in_memory: bool = False) -> bool:
    """Return True if at least one checkpoint exists for the given thread_id."""
    if in_memory or not thread_id:
        return False
    path = Path(db_path) if db_path is not None else get_default_db_path()
    if not path.exists():
        return False
    try:
        with sqlite3.connect(str(path), timeout=5.0) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM checkpoints WHERE thread_id = ? LIMIT 1;", (thread_id,))
            return cursor.fetchone() is not None
    except Exception as e:
        logger.warning(f"Error querying checkpoint existence for thread '{thread_id}': {e}")
        return False
