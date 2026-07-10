#!/usr/bin/env python3
"""Append a normalized operation entry to system/log.md."""

from __future__ import annotations

import argparse
from pathlib import Path

from wiki_common import append_operation_log


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("init", "ingest", "query", "lint", "maintenance"))
    parser.add_argument("title")
    parser.add_argument("--detail", action="append", default=[])
    parser.add_argument("--root", default="knowledge")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not (root / "system").exists():
        raise SystemExit(f"not an initialized LLM Wiki: {root}")
    append_operation_log(root, args.operation, args.title, args.detail)
    print(f"appended {args.operation} entry to {root / 'system' / 'log.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
