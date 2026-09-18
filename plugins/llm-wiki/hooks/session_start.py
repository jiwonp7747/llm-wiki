#!/usr/bin/env python3
"""Add LLM Wiki operating context when a session starts in a wiki project."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def find_knowledge(start: Path) -> Path | None:
    current = start.resolve()
    for directory in (current, *current.parents):
        candidate = directory / "knowledge"
        if (candidate / "SCHEMA.md").is_file():
            return candidate
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, TypeError):
        payload = {}
    cwd = Path(payload.get("cwd") or os.getcwd())
    knowledge = find_knowledge(cwd)
    if knowledge is None:
        print(json.dumps({"continue": True}))
        return 0
    context = (
        f"This project has an LLM Wiki at {knowledge}. Read {knowledge / 'SCHEMA.md'} "
        "before changing it. Use the llm-wiki skill for ingest, query, index, log, "
        "and lint operations. Preserve sources as immutable evidence. "
        "When available, prefer wiki_info/wiki_search/wiki_read/wiki_sources MCP tools for "
        "navigation and evidence, with a consistent task_id. MCP usage excludes shell reads."
    )
    print(
        json.dumps(
            {
                "continue": True,
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": context,
                },
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
