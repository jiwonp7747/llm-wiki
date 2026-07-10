#!/usr/bin/env python3
"""Validate LLM Wiki structure, metadata, provenance, links, and source hashes."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from wiki_common import (
    ALLOWED_PAGE_STATUSES,
    ALLOWED_PAGE_TYPES,
    REQUIRED_PAGE_FIELDS,
    normalize_wikilink,
    parse_frontmatter,
    registered_sources,
    resolve_wikilink,
    sha256_file,
    wiki_markdown_files,
    wiki_targets,
    wikilinks,
)


REQUIRED_PATHS = (
    "AGENTS.md",
    "SCHEMA.md",
    "sources",
    "wiki",
    "wiki/index.md",
    "wiki/overview.md",
    "system",
    "system/log.md",
    "system/manifest.jsonl",
)


def validate(root: Path) -> dict[str, object]:
    errors: list[str] = []
    warnings: list[str] = []
    for relative in REQUIRED_PATHS:
        if not (root / relative).exists():
            errors.append(f"missing required path: {relative}")

    try:
        sources = registered_sources(root)
    except ValueError as exc:
        errors.append(str(exc))
        sources = {}

    page_ids: list[str] = []
    paths, stems = wiki_targets(root)
    inbound: Counter[str] = Counter()
    pages = wiki_markdown_files(root)
    for path in pages:
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        metadata, _ = parse_frontmatter(text)
        if not metadata:
            errors.append(f"{relative}: missing or invalid YAML frontmatter")
            continue
        for field in REQUIRED_PAGE_FIELDS:
            if field not in metadata:
                errors.append(f"{relative}: missing frontmatter field '{field}'")
        page_id = metadata.get("id")
        if isinstance(page_id, str) and page_id:
            page_ids.append(page_id)
        page_type = metadata.get("type")
        if page_type and page_type not in ALLOWED_PAGE_TYPES:
            warnings.append(f"{relative}: custom page type '{page_type}'")
        status = metadata.get("status")
        if status and status not in ALLOWED_PAGE_STATUSES:
            errors.append(f"{relative}: invalid status '{status}'")
        source_ids = metadata.get("sources", [])
        if not isinstance(source_ids, list):
            errors.append(f"{relative}: sources must be a list")
        else:
            for source_id in source_ids:
                if source_id not in sources:
                    errors.append(f"{relative}: unknown source ID '{source_id}'")

        for link in wikilinks(text):
            if not resolve_wikilink(link, paths, stems):
                warnings.append(f"{relative}: unresolved wikilink '[[{link}]]'")
            else:
                normalized = normalize_wikilink(link).lstrip("./")
                if normalized in paths:
                    inbound[normalized] += 1
                else:
                    for target in paths:
                        if Path(target).name == Path(normalized).name:
                            inbound[target] += 1

    for page_id, count in Counter(page_ids).items():
        if count > 1:
            errors.append(f"duplicate page id '{page_id}' appears {count} times")

    for target in sorted(paths):
        if target != "index" and inbound[target] == 0:
            warnings.append(f"wiki/{target}.md: orphan page with no inbound wikilink")

    for source_id, metadata in sources.items():
        stored_path = metadata.get("stored_path")
        expected_hash = metadata.get("sha256")
        if not isinstance(stored_path, str) or not isinstance(expected_hash, str):
            errors.append(f"{source_id}: registration is missing stored_path or sha256")
            continue
        original = root / stored_path
        if not original.is_file():
            errors.append(f"{source_id}: stored original is missing: {stored_path}")
            continue
        actual_hash = sha256_file(original)
        if actual_hash != expected_hash:
            errors.append(f"{source_id}: immutable source hash changed: {stored_path}")
        metadata_path = root / "sources" / source_id / "metadata.json"
        if not metadata_path.is_file():
            errors.append(f"{source_id}: metadata.json is missing")
            continue
        try:
            captured = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{source_id}: invalid metadata.json: {exc}")
            continue
        if captured.get("source_id") != source_id or captured.get("sha256") != expected_hash:
            errors.append(f"{source_id}: metadata.json does not match the manifest")

    return {
        "root": str(root),
        "valid": not errors,
        "page_count": len(pages),
        "source_count": len(sources),
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="knowledge")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    result = validate(root)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        state = "PASS" if result["valid"] else "FAIL"
        print(
            f"{state}: {result['page_count']} pages, {result['source_count']} sources, "
            f"{len(result['errors'])} errors, {len(result['warnings'])} warnings"
        )
        for error in result["errors"]:
            print(f"ERROR: {error}")
        for warning in result["warnings"]:
            print(f"WARN: {warning}")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
