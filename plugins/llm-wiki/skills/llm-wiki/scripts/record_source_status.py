#!/usr/bin/env python3
"""Append a lifecycle status event for a registered source."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from wiki_common import append_jsonl, append_operation_log, iso_now, registered_sources


STATUSES = ("registered", "ingested", "reviewed", "rejected", "archived")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_id")
    parser.add_argument("status", choices=STATUSES)
    parser.add_argument("--root", default="knowledge")
    parser.add_argument("--detail", action="append", default=[])
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    if args.source_id not in registered_sources(root):
        raise SystemExit(f"unknown source_id: {args.source_id}")
    event = {
        "event": "source_status_changed",
        "source_id": args.source_id,
        "status": args.status,
        "changed_at": iso_now(),
        "details": args.detail,
    }
    append_jsonl(root / "system" / "manifest.jsonl", event)
    append_operation_log(
        root,
        "maintenance",
        f"Source status: {args.source_id} -> {args.status}",
        args.detail,
    )
    print(json.dumps(event, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
