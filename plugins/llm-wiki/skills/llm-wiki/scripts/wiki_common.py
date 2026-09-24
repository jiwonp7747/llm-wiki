#!/usr/bin/env python3
"""Shared helpers for the LLM Wiki scripts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REQUIRED_PAGE_FIELDS = ("id", "type", "status", "sources", "updated")
ALLOWED_PAGE_TYPES = {
    "concept",
    "component",
    "decision",
    "guide",
    "source-note",
    "question",
    "moc",
    "overview",
}
ALLOWED_PAGE_STATUSES = {"canonical", "draft", "stale", "archived"}
TAG_POLICY_FILE = "tags.json"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today() -> str:
    return utc_now().date().isoformat()


def slugify(value: str, fallback: str = "source") -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value).strip("-").lower()
    return slug[:48] or fallback


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{number}: invalid JSONL: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{number}: each JSONL record must be an object")
        records.append(value)
    return records


def registered_sources(root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for event in load_jsonl(root / "system" / "manifest.jsonl"):
        source_id = event.get("source_id")
        if not isinstance(source_id, str):
            continue
        current = result.setdefault(source_id, {})
        current.update(event)
    return result


def append_operation_log(
    root: Path, operation: str, title: str, details: Iterable[str] = ()
) -> None:
    log_path = root / "system" / "log.md"
    if not log_path.exists():
        atomic_write_text(
            log_path,
            "# LLM Wiki Log\n\nAppend-only history of wiki operations.\n",
        )
    lines = [f"\n## [{iso_now()}] {operation} | {title}\n"]
    lines.extend(f"- {detail}\n" for detail in details)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.writelines(lines)


def _decode_scalar(value: str) -> Any:
    value = value.strip()
    if value == "":
        return ""
    if value == "[]":
        return []
    if value in {"true", "false"}:
        return value == "true"
    if value.startswith(("\"", "[", "{")):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            if value.startswith("[") and value.endswith("]"):
                # Only plain string tokens are supported outside JSON arrays.
                # Leave other YAML forms intact so validation rejects them.
                items = [item.strip() for item in value[1:-1].split(",")]
                if all(re.fullmatch(r"[^\W\d][\w/.-]*", item) for item in items):
                    for item in items:
                        if item.lower() in {"true", "false", "null"}:
                            return value
                    return items
                return value
            return value.strip("\"")
    return value


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return {}, text

    metadata: dict[str, Any] = {}
    active_list: str | None = None
    for raw in lines[1:end]:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and active_list:
            metadata.setdefault(active_list, []).append(_decode_scalar(stripped[2:]))
            continue
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        key = key.strip()
        decoded = _decode_scalar(value)
        metadata[key] = decoded
        active_list = key if decoded == "" else None
        if active_list:
            metadata[key] = []
    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    return metadata, body


def page_title(body: str, fallback: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def page_description(metadata: dict[str, Any], body: str) -> str:
    description = metadata.get("description")
    if isinstance(description, str) and description.strip():
        return description.strip()
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "<!--", "```", "- ")):
            continue
        return stripped[:160]
    return "No description yet."


def page_tags(metadata: dict[str, Any]) -> list[str]:
    """Return frontmatter tags as a list. Missing or empty tags yield []; a scalar becomes one item."""
    tags = metadata.get("tags", [])
    if tags is None or tags == "":
        return []
    return tags if isinstance(tags, list) else [tags]


def load_tag_policy(root: Path) -> tuple[dict[str, str] | None, list[str]]:
    """Read the optional per-wiki tag dictionary at `<root>/tags.json`.

    Returns (allowed tags mapped to descriptions, errors). The mapping is None when the
    wiki defines no dictionary, in which case any well-formed tag is accepted.
    """
    path = root / TAG_POLICY_FILE
    if not path.is_file():
        return None, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"{TAG_POLICY_FILE}: invalid JSON: {exc}"]
    tags = data.get("tags") if isinstance(data, dict) else None
    if not isinstance(tags, dict):
        return {}, [f"{TAG_POLICY_FILE}: expected an object with a 'tags' mapping of tag -> description"]
    allowed: dict[str, str] = {}
    errors: list[str] = []
    for tag, description in tags.items():
        if not isinstance(tag, str) or not tag.strip() or tag != tag.strip():
            errors.append(f"{TAG_POLICY_FILE}: tag names must be non-empty strings without surrounding spaces")
            continue
        allowed[tag] = description if isinstance(description, str) else ""
    return allowed, errors


def validate_tags(raw_tags: Any, allowed: dict[str, str] | None) -> list[str]:
    """Check one page's `tags` value: a list of unique non-empty strings, each in `allowed` when given."""
    if raw_tags is None:
        return []
    if not isinstance(raw_tags, list):
        return ["tags must be a YAML list of strings"]
    problems: list[str] = []
    seen: set[str] = set()
    for tag in raw_tags:
        if not isinstance(tag, str) or not tag.strip():
            problems.append("tags must contain non-empty strings")
            continue
        if tag != tag.strip():
            problems.append(f"tag '{tag}' has surrounding whitespace")
        if tag in seen:
            problems.append(f"duplicate tag '{tag}'")
        elif allowed is not None and tag not in allowed:
            problems.append(f"unknown tag '{tag}' (not in {TAG_POLICY_FILE})")
        seen.add(tag)
    return problems


def wiki_markdown_files(root: Path) -> list[Path]:
    wiki = root / "wiki"
    if not wiki.exists():
        return []
    return sorted(path for path in wiki.rglob("*.md") if path.is_file())


def wikilinks(text: str) -> list[str]:
    return re.findall(r"\[\[([^\]]+)\]\]", text)


def normalize_wikilink(value: str) -> str:
    target = value.split("|", 1)[0].split("#", 1)[0].strip().replace("\\|", "|")
    return target[:-3] if target.endswith(".md") else target


def wiki_targets(root: Path) -> tuple[set[str], set[str]]:
    paths: set[str] = set()
    stems: set[str] = set()
    for path in wiki_markdown_files(root):
        relative = path.relative_to(root / "wiki").with_suffix("").as_posix()
        paths.add(relative)
        stems.add(path.stem)
    return paths, stems


def resolve_wikilink(target: str, paths: set[str], stems: set[str]) -> bool:
    normalized = normalize_wikilink(target).lstrip("./")
    return normalized in paths or Path(normalized).name in stems
