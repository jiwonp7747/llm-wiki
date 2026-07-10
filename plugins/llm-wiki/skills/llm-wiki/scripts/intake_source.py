#!/usr/bin/env python3
"""Register an immutable source and create its unsynthesized source-note page."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from wiki_common import (
    append_jsonl,
    append_operation_log,
    iso_now,
    load_jsonl,
    sha256_bytes,
    slugify,
    today,
)


KINDS = ("external-document", "user-note", "code-snapshot", "conversation-excerpt", "other")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("source", nargs="?", help="Local source file")
    result.add_argument("--text", help="Register text instead of a file")
    result.add_argument("--title", help="Human-readable source title")
    result.add_argument("--kind", choices=KINDS, default="external-document")
    result.add_argument("--root", default="knowledge", help="Wiki root")
    result.add_argument("--author", default="unknown", help="Source author or origin")
    return result


def main() -> int:
    args = parser().parse_args()
    if bool(args.source) == bool(args.text):
        raise SystemExit("provide exactly one of SOURCE or --text")

    root = Path(args.root).expanduser().resolve()
    manifest = root / "system" / "manifest.jsonl"
    if not (root / "SCHEMA.md").exists():
        raise SystemExit(f"not an initialized LLM Wiki: {root}")

    original_path: str | None = None
    if args.source:
        source = Path(args.source).expanduser().resolve()
        if not source.is_file():
            raise SystemExit(f"source file not found: {source}")
        data = source.read_bytes()
        filename = source.name
        title = args.title or source.stem
        original_path = str(source)
    else:
        data = args.text.encode("utf-8")
        filename = "note.md"
        title = args.title or "User note"
    title = " ".join(title.splitlines()).strip()
    if not title:
        raise SystemExit("source title must not be empty")

    digest = sha256_bytes(data)
    for event in load_jsonl(manifest):
        if event.get("event") == "source_registered" and event.get("sha256") == digest:
            print(json.dumps({"status": "duplicate", "source_id": event["source_id"]}))
            return 0

    source_id = f"src-{today().replace('-', '')}-{slugify(title)}-{digest[:8]}"
    source_dir = root / "sources" / source_id
    if source_dir.exists():
        raise SystemExit(f"source directory already exists: {source_dir}")

    original_dir = source_dir / "original"
    original_dir.mkdir(parents=True)
    stored = original_dir / filename
    if args.source:
        shutil.copy2(Path(args.source).expanduser().resolve(), stored)
    else:
        stored.write_bytes(data)

    metadata = {
        "source_id": source_id,
        "title": title,
        "kind": args.kind,
        "author": args.author,
        "verification": "unverified" if args.kind == "user-note" else "source-provided",
        "captured_at": iso_now(),
        "sha256": digest,
        "original_path": original_path,
        "stored_path": stored.relative_to(root).as_posix(),
    }
    (source_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    event = {"event": "source_registered", "status": "registered", **metadata}
    append_jsonl(manifest, event)

    note = root / "wiki" / "source-notes" / f"{source_id}.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "\n".join(
            [
                "---",
                f"id: note-{source_id}",
                "type: source-note",
                "status: draft",
                "sources:",
                f"  - {source_id}",
                f"updated: {today()}",
                f"description: Unsynthesized note for {title}",
                "---",
                "",
                f"# {title}",
                "",
                "> Pending LLM synthesis. Registration does not validate the source's claims.",
                "",
                "## Summary",
                "",
                "<!-- Replace with a concise source summary. -->",
                "",
                "## Key claims",
                "",
                "<!-- Record claims with page links and precise provenance. -->",
                "",
                "## Relationships",
                "",
                "<!-- Link affected concepts, components, decisions, and questions. -->",
                "",
                "## Provenance",
                "",
                f"- Source ID: `{source_id}`",
                f"- Stored original: `{stored.relative_to(root).as_posix()}`",
                f"- SHA-256: `{digest}`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    append_operation_log(
        root,
        "ingest",
        f"Registered source: {title}",
        [f"source_id: {source_id}", f"kind: {args.kind}", f"sha256: {digest}"],
    )
    print(json.dumps({"status": "registered", "source_id": source_id, "note": str(note)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
