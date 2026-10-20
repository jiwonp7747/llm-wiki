"""Shared, dependency-free schema and declared usage classifications."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path

PURPOSES = ("knowledge_lookup", "maintenance", "diagnostic", "unknown")
EXECUTION_ORIGINS = ("interactive", "automation", "background", "unknown")
AGENT_ROLES = ("root", "subagent", "unknown")
CLASSIFICATION_SOURCES = ("explicit", "inherited", "legacy_inferred", "unknown")


def audit_db_path(root: Path) -> Path:
    state = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    key = hashlib.sha256(str(root.expanduser().resolve()).encode()).hexdigest()[:24]
    return state / "llm-wiki" / key / "access.sqlite3"


def ensure_schema(db: sqlite3.Connection) -> None:
    """Run inside the caller's immediate transaction; old event IDs stay intact."""
    for statement in (
        "CREATE TABLE IF NOT EXISTS wiki (root TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, time TEXT NOT NULL, "
        "session_id TEXT NOT NULL, task_id TEXT, tool TEXT NOT NULL, success INTEGER NOT NULL, "
        "truncated INTEGER NOT NULL, detail TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS documents (event_id INTEGER NOT NULL REFERENCES events(id), "
        "path TEXT NOT NULL, kind TEXT NOT NULL, sha256 TEXT, start_line INTEGER, end_line INTEGER, "
        "start_column INTEGER, end_column INTEGER)",
        "CREATE INDEX IF NOT EXISTS events_filter ON events(time,task_id,session_id)",
        "CREATE INDEX IF NOT EXISTS documents_event ON documents(event_id)",
    ):
        db.execute(statement)
    columns = {row[1] for row in db.execute("PRAGMA table_info(events)")}
    additions = {
        "purpose": "TEXT NOT NULL DEFAULT 'unknown'",
        "execution_origin": "TEXT NOT NULL DEFAULT 'unknown'",
        "agent_role": "TEXT NOT NULL DEFAULT 'unknown'",
        "classification_source": "TEXT NOT NULL DEFAULT 'unknown'",
        "duration_ms": "REAL", "result_count": "INTEGER",
        "scanned_files": "INTEGER", "scanned_bytes": "INTEGER",
        "client": "TEXT", "chat_id": "TEXT", "turn_id": "TEXT", "tool_use_id": "TEXT",
    }
    for name, definition in additions.items():
        if name not in columns:
            db.execute(f"ALTER TABLE events ADD COLUMN {name} {definition}")
    db.execute("CREATE INDEX IF NOT EXISTS events_purpose ON events(purpose,time)")


def declared_context(arguments: dict, defaults: dict | None = None) -> dict:
    defaults = defaults or {}
    result = {}
    supplied_purpose = arguments.pop("usage_purpose", None)
    for key, value, allowed in (
        ("purpose", supplied_purpose, PURPOSES),
        ("execution_origin", arguments.pop("execution_origin", None), EXECUTION_ORIGINS),
        ("agent_role", arguments.pop("agent_role", None), AGENT_ROLES),
    ):
        chosen = value if value is not None else defaults.get(key, "unknown")
        if chosen not in allowed:
            raise ValueError(f"{key} must be one of {', '.join(allowed)}")
        result[key] = chosen
    result["classification_source"] = (
        "explicit" if supplied_purpose is not None and supplied_purpose != "unknown" else
        "inherited" if supplied_purpose is None and result["purpose"] != "unknown" else "unknown"
    )
    return result
