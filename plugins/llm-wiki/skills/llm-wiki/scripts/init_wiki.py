#!/usr/bin/env python3
"""Initialize a project-local LLM Wiki from the bundled template."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from wiki_common import append_operation_log, iso_now, today


TEXT_SUFFIXES = {".md", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".txt"}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--root", default="knowledge", help="Wiki root to create")
    result.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    return result


def main() -> int:
    args = parser().parse_args()
    root = Path(args.root).expanduser().resolve()
    template = Path(__file__).resolve().parent.parent / "assets" / "template" / "knowledge"
    if not template.exists():
        raise SystemExit(f"template not found: {template}")

    created: list[str] = []
    skipped: list[str] = []
    for source in sorted(template.rglob("*")):
        relative = source.relative_to(template)
        target = root / relative
        if source.is_dir():
            if not args.dry_run:
                target.mkdir(parents=True, exist_ok=True)
            continue
        if target.exists():
            skipped.append(relative.as_posix())
            continue
        if not args.dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.suffix in TEXT_SUFFIXES:
                content = source.read_text(encoding="utf-8")
                content = content.replace("{{DATE}}", today()).replace("{{DATETIME}}", iso_now())
                target.write_text(content, encoding="utf-8")
            else:
                shutil.copy2(source, target)
        created.append(relative.as_posix())

    if not args.dry_run:
        manifest = root / "system" / "manifest.jsonl"
        manifest.touch(exist_ok=True)
        append_operation_log(root, "init", "Initialized LLM Wiki", [f"root: {root}"])

    print(f"wiki root: {root}")
    print(f"created: {len(created)}")
    print(f"skipped: {len(skipped)}")
    if args.dry_run:
        print("dry-run: no files were written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
