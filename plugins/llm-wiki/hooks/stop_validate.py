#!/usr/bin/env python3
"""Run non-blocking structural validation before a turn stops."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def find_knowledge(start: Path) -> Path | None:
    current = start.resolve()
    for directory in (current, *current.parents):
        candidate = directory / "knowledge"
        if (candidate / "SCHEMA.md").is_file():
            return candidate
    return None


def emit(message: str | None = None) -> int:
    payload: dict[str, object] = {"continue": True}
    if message:
        payload["systemMessage"] = message
    print(json.dumps(payload))
    return 0


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, TypeError):
        payload = {}
    cwd = Path(payload.get("cwd") or os.getcwd())
    knowledge = find_knowledge(cwd)
    if knowledge is None:
        return emit()

    env_root = os.environ.get("PLUGIN_ROOT") or os.environ.get("CLAUDE_PLUGIN_ROOT")
    plugin_root = Path(env_root or Path(__file__).resolve().parent.parent)
    validator = plugin_root / "skills" / "llm-wiki" / "scripts" / "validate_wiki.py"
    if not validator.is_file():
        return emit(f"LLM Wiki hook could not find validator: {validator}")
    try:
        completed = subprocess.run(
            [sys.executable, str(validator), "--root", str(knowledge), "--json"],
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return emit("LLM Wiki validation timed out after 25 seconds.")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
        return emit(f"LLM Wiki validation could not run: {detail[:500]}")

    errors = result.get("errors", [])
    warnings = result.get("warnings", [])
    if errors:
        summary = "; ".join(str(item) for item in errors[:3])
        return emit(
            f"LLM Wiki structural validation found {len(errors)} error(s). "
            f"Run the llm-wiki skill lint workflow. First issues: {summary}"
        )
    if warnings:
        return emit(
            f"LLM Wiki validation passed with {len(warnings)} warning(s). "
            "Review them during the next lint pass."
        )
    return emit()


if __name__ == "__main__":
    raise SystemExit(main())
