"""Read-only wiki operations and local, transactional access accounting."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import regex

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/llm-wiki/scripts"))
from wiki_common import parse_frontmatter, page_title, sha256_bytes  # noqa: E402

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_FILES = 5000
MAX_SCAN_BYTES = 32 * 1024 * 1024


def discover_root(start: Path) -> Path:
    """Stop at the nearest Git boundary; never borrow another project's wiki."""
    start = start.resolve()
    for directory in (start, *start.parents):
        if (directory / "knowledge/SCHEMA.md").is_file():
            return directory / "knowledge"
        if (directory / ".git").exists():
            break
    raise ValueError("No initialized knowledge/ found; set LLM_WIKI_ROOT or --root")


class WikiService:
    def __init__(self, root: Path, audit_db: Path | None = None, task_id: str | None = None):
        self.root = root.expanduser().resolve(strict=True)
        self.session_id = str(uuid.uuid4())
        self.task_id = task_id
        self._path("SCHEMA.md")
        if audit_db is None:
            state = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
            key = hashlib.sha256(str(self.root).encode()).hexdigest()[:24]
            audit_db = state / "llm-wiki" / key / "access.sqlite3"
        self.audit_db = audit_db.expanduser().resolve()
        if self.audit_db.is_relative_to(self.root):
            raise ValueError("Audit database must be outside the wiki root")
        self.audit_db.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(self._connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS wiki (root TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, time TEXT NOT NULL, session_id TEXT NOT NULL,
                    task_id TEXT, tool TEXT NOT NULL, success INTEGER NOT NULL,
                    truncated INTEGER NOT NULL, detail TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS documents (
                    event_id INTEGER NOT NULL REFERENCES events(id), path TEXT NOT NULL,
                    kind TEXT NOT NULL, sha256 TEXT, start_line INTEGER, end_line INTEGER,
                    start_column INTEGER, end_column INTEGER);
                CREATE INDEX IF NOT EXISTS events_filter ON events(time, task_id, session_id);
                CREATE INDEX IF NOT EXISTS documents_event ON documents(event_id);
            """)
            db.execute("BEGIN IMMEDIATE")
            registered = db.execute("SELECT root FROM wiki").fetchone()
            if registered and registered[0] != str(self.root):
                raise ValueError("Audit database belongs to another wiki root")
            if not registered:
                db.execute("INSERT INTO wiki VALUES(?)", (str(self.root),))
        self.audit_db.chmod(0o600)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.audit_db, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _path(self, relative: str) -> Path:
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or "\\" in relative:
            raise ValueError("Use a wiki-root-relative path without '..' or backslashes")
        if not path.parts or path.parts[0] not in {"wiki", "sources", "SCHEMA.md", "AGENTS.md", "system"}:
            raise ValueError("Path is outside the wiki content areas")
        if path.parts[0] == "system" and relative != "system/manifest.jsonl":
            raise ValueError("Only the source manifest is readable under system/")
        current = self.root
        for part in path.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("Symlinks are not readable through the wiki MCP")
        resolved = current.resolve(strict=True)
        if not resolved.is_relative_to(self.root) or not resolved.is_file():
            raise ValueError("Path must be a regular file within the wiki root")
        return resolved

    def _text(self, relative: str) -> tuple[str, str, int]:
        path = self._path(relative)
        # 크기를 확인한 뒤에도 읽기 상한을 적용한다.
        with path.open("rb") as handle:
            data = handle.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise ValueError("File exceeds the 2 MiB text limit")
        if b"\x00" in data:
            raise ValueError("Binary source: only UTF-8 text can be read")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Binary/non-UTF-8 source: use an appropriate document reader") from exc
        return text, sha256_bytes(data), len(data)

    def _pages(self, path_prefix: str) -> list[str]:
        prefix = path_prefix.removeprefix("./")
        if ".." in Path(prefix).parts or Path(prefix).is_absolute() or "\\" in prefix:
            raise ValueError("Invalid path_prefix")
        wiki = self.root / "wiki"
        if wiki.is_symlink():
            raise ValueError("wiki/ must not be a symlink")
        paths = []
        for directory, dirs, files in os.walk(wiki, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not (Path(directory) / d).is_symlink())
            for name in sorted(files):
                path = Path(directory) / name
                relative = path.relative_to(self.root).as_posix()
                if name.endswith(".md") and relative.startswith(prefix) and not path.is_symlink():
                    paths.append(relative)
                    if len(paths) > MAX_FILES:
                        raise ValueError("Too many pages; narrow path_prefix (maximum 5000)")
        return sorted(paths)

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        args = dict(arguments)
        task_id = args.pop("task_id", None) or self.task_id
        if task_id is not None and (not isinstance(task_id, str) or len(task_id) > 200):
            raise ValueError("task_id must be at most 200 characters")
        if tool not in {"wiki_info", "wiki_list", "wiki_search", "wiki_read", "wiki_sources", "wiki_usage"}:
            raise ValueError("Unknown wiki tool")
        documents: list[dict[str, Any]] = []
        try:
            result = getattr(self, tool)(**args)
            documents = result.pop("_documents", [])
            if len(json.dumps(result, ensure_ascii=False)) > 64000:
                raise ValueError("Result exceeds 64000 characters; reduce limit, context_lines or max_chars")
        except Exception as exc:
            self._record(tool, task_id, False, False, {"error_type": type(exc).__name__}, [])
            raise
        detail = {key: result[key] for key in ("next_offset", "next_cursor", "skipped_count") if key in result}
        if "query" in args:
            detail["query_sha256"] = sha256_bytes(args["query"].encode())
        event_id = self._record(tool, task_id, True, bool(result.get("truncated")), detail, documents)
        return {**result, "audit": {"event_id": event_id, "session_id": self.session_id, "task_id": task_id}}

    def _record(self, tool, task_id, success, truncated, detail, documents) -> int:
        with closing(self._connect()) as db, db:
            cursor = db.execute(
                "INSERT INTO events(time,session_id,task_id,tool,success,truncated,detail) VALUES(?,?,?,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(), self.session_id, task_id, tool,
                 success, truncated, json.dumps(detail, ensure_ascii=False)),
            )
            event_id = cursor.lastrowid
            for doc in documents:
                db.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?,?)", (
                    event_id, doc["path"], doc["kind"], doc.get("sha256"), doc.get("start_line"),
                    doc.get("end_line"), doc.get("start_column"), doc.get("end_column"),
                ))
            return event_id

    def wiki_info(self) -> dict:
        return {
            "root": str(self.root), "schema": "SCHEMA.md", "index": "wiki/index.md",
            "categories": sorted(p.name for p in (self.root / "wiki").iterdir()
                                 if p.is_dir() and not p.is_symlink()),
            "read_only": True, "audit_db": str(self.audit_db),
            "limits": {"file_bytes": MAX_FILE_BYTES, "scan_bytes": MAX_SCAN_BYTES, "pages": MAX_FILES,
                       "read_characters": 12000, "max_read_characters": 24000},
            "accounting": "MCP results prepared for delivery; not proof of model understanding. Shell reads are excluded.",
            "identity": "session_id identifies this server process; task_id is a caller-provided label, not authentication.",
        }

    @staticmethod
    def _pagination(offset: int, limit: int) -> None:
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a nonnegative item index")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be 1..100 items")

    def wiki_list(self, path_prefix="wiki/", page_type=None, tag=None, offset=0, limit=20) -> dict:
        self._pagination(offset, limit)
        items, skipped, scanned = [], [], 0
        for path in self._pages(path_prefix):
            try:
                text, digest, size = self._text(path)
            except ValueError:
                skipped.append(path)
                continue
            scanned += size
            if scanned > MAX_SCAN_BYTES:
                raise ValueError("Scan exceeds 32 MiB; narrow path_prefix")
            metadata, body = parse_frontmatter(text)
            if page_type is not None and metadata.get("type") != page_type:
                continue
            tags = metadata.get("tags", [])
            if not isinstance(tags, list):
                tags = [tags]
            if tag is not None and tag not in tags:
                continue
            items.append({"path": path, "title": page_title(body, Path(path).stem)[:160],
                          "type": str(metadata.get("type", ""))[:40],
                          "status": str(metadata.get("status", ""))[:40], "sha256": digest})
        page = items[offset:offset + limit]
        next_offset = offset + len(page) if offset + len(page) < len(items) else None
        return {"items": page, "total": len(items), "next_offset": next_offset,
                "truncated": next_offset is not None, "skipped": skipped[:20], "skipped_count": len(skipped),
                "_documents": [{**item, "kind": "listed"} for item in page]}

    def wiki_search(self, query: str, path_prefix="wiki/", use_regex=False, case_sensitive=False,
                    context_lines=1, offset=0, limit=20) -> dict:
        self._pagination(offset, limit)
        if not isinstance(query, str) or not query or len(query) > 500:
            raise ValueError("query must contain 1..500 characters")
        if not 0 <= context_lines <= 2:
            raise ValueError("context_lines must be 0..2")
        pattern = regex.compile(query if use_regex else regex.escape(query),
                                0 if case_sensitive else regex.IGNORECASE)
        matches, skipped, seen, scanned = [], [], 0, 0
        deadline = time.monotonic() + 5
        more = False
        for path in self._pages(path_prefix):
            try:
                text, digest, size = self._text(path)
            except ValueError:
                skipped.append(path)
                continue
            scanned += size
            if scanned > MAX_SCAN_BYTES:
                raise ValueError("Scan exceeds 32 MiB; narrow path_prefix")
            lines = text.splitlines()
            for index, line in enumerate(lines):
                if time.monotonic() > deadline:
                    raise ValueError("Search exceeded 5 seconds; narrow path_prefix or simplify query")
                try:
                    match = pattern.search(line, timeout=0.02)
                except TimeoutError as exc:
                    raise ValueError("Regex timed out; simplify query") from exc
                if not match:
                    continue
                seen += 1
                if seen <= offset:
                    continue
                if len(matches) == limit:
                    more = True
                    break
                start, end = max(0, index - context_lines), min(len(lines), index + context_lines + 1)
                column = max(0, match.start() - 120)
                matches.append({"path": path, "line": index + 1, "sha256": digest,
                                "start_line": start + 1, "end_line": end,
                                "match_column": match.start(),
                                "context": [{"line": n + 1,
                                             "start_column": column if n == index else 0,
                                             "text": lines[n][column:column + 400] if n == index else lines[n][:400],
                                             "clipped": len(lines[n]) > 400} for n in range(start, end)]})
            if more:
                break
        return {"matches": matches, "next_offset": offset + len(matches) if more else None,
                "truncated": more, "skipped": skipped[:20], "skipped_count": len(skipped),
                "_documents": [{**item, "kind": "search_hit"} for item in matches]}

    def wiki_read(self, path: str, start_line=1, line_count=100, start_column=0,
                  max_chars=12000, expected_sha256=None) -> dict:
        if not 1 <= start_line or not 1 <= line_count <= 200 or start_column < 0 or not 1 <= max_chars <= 24000:
            raise ValueError("Invalid read bounds: lines 1-based, count 1..200, column >=0, chars 1..24000")
        text, digest, _ = self._text(path)
        if expected_sha256 is not None and expected_sha256 != digest:
            raise ValueError("Document changed; restart reading without the old expected_sha256")
        lines = text.splitlines(keepends=True)
        if start_line > len(lines) + 1 or (start_line == len(lines) + 1 and start_column):
            raise ValueError("start_line is past end of file")
        if start_line <= len(lines) and start_column > len(lines[start_line - 1]):
            raise ValueError("start_column is past end of line")
        remaining, parts = max_chars, []
        index, column = start_line - 1, start_column
        last_line, last_column = None, None
        while index < len(lines) and index < start_line - 1 + line_count and remaining > 0:
            segment = lines[index][column:column + remaining]
            parts.append(segment)
            remaining -= len(segment)
            column += len(segment)
            last_line, last_column = index + 1, column
            if column == len(lines[index]):
                index, column = index + 1, 0
            else:
                break
        cursor = {"start_line": index + 1, "start_column": column} if index < len(lines) else None
        doc = {"path": path, "kind": "body_read", "sha256": digest, "start_line": start_line,
               "end_line": last_line, "start_column": start_column, "end_column": last_column}
        return {"path": path, "sha256": digest, "text": "".join(parts), "total_lines": len(lines),
                "start_line": start_line, "start_column": start_column,
                "end_line": last_line, "end_column": last_column,
                "next_cursor": cursor, "truncated": cursor is not None,
                "_documents": [doc] if parts else []}

    def wiki_sources(self, path=None, source_id=None, offset=0, limit=20) -> dict:
        self._pagination(offset, limit)
        documents = []
        if (path is None) == (source_id is None):
            raise ValueError("Provide exactly one of path or source_id")
        if path:
            text, digest, _ = self._text(path)
            documents.append({"path": path, "sha256": digest, "kind": "source_reference"})
            ids = parse_frontmatter(text)[0].get("sources", [])
            if not isinstance(ids, list) or any(not isinstance(value, str) for value in ids):
                raise ValueError("Page sources must be a list of source IDs")
        else:
            ids = [source_id]
        manifest, _, _ = self._text("system/manifest.jsonl")
        records = {}
        for line in manifest.splitlines():
            if line.strip():
                event = json.loads(line)
                if isinstance(event, dict) and isinstance(event.get("source_id"), str):
                    records.setdefault(event["source_id"], {}).update(event)
        items = []
        for key in ids[offset:offset + limit]:
            record = records.get(key)
            if record is None:
                items.append({"source_id": key, "missing": True})
                continue
            stored = record.get("stored_path", "")
            try:
                original = self._path(stored)
                accessible = stored.startswith("sources/")
                size = original.stat().st_size if accessible else None
            except (ValueError, OSError):
                accessible, size = False, None
            item = {field: str(record.get(field, ""))[:300] for field in
                    ("source_id", "title", "kind", "author", "verification", "status", "sha256", "captured_at")}
            item.update({"stored_path": stored if accessible else None, "accessible": accessible, "bytes": size,
                         "read_hint": "wiki_read supports UTF-8 text up to 2 MiB; binary documents need a document reader"})
            items.append(item)
            if accessible:
                documents.append({"path": stored, "sha256": record.get("sha256"), "kind": "source_metadata"})
        more = offset + len(items) < len(ids)
        return {"sources": items, "total": len(ids), "next_offset": offset + len(items) if more else None,
                "truncated": more, "_documents": documents}

    def wiki_usage(self, filter_task_id=None, session_id=None, since=None, until=None, offset=0, limit=20) -> dict:
        self._pagination(offset, limit)
        clauses, parameters = [], []
        for field, value in (("task_id", filter_task_id), ("session_id", session_id)):
            if value is not None:
                clauses.append(f"e.{field}=?")
                parameters.append(value)
        for operator, value in ((">=", since), ("<", until)):
            if value is not None:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError("since/until require an ISO-8601 timezone")
                clauses.append(f"e.time {operator} ?")
                parameters.append(parsed.astimezone(timezone.utc).isoformat())
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            counts = [dict(row) for row in db.execute(
                "SELECT tool, success, count(*) AS calls FROM events e" + where + " GROUP BY tool, success", parameters)]
            docs_query = " FROM documents d JOIN events e ON e.id=d.event_id" + where
            total = db.execute("SELECT count(DISTINCT path)" + docs_query, parameters).fetchone()[0]
            docs = [dict(row) for row in db.execute(
                "SELECT path, count(DISTINCT CASE WHEN kind='body_read' THEN event_id END) AS body_reads, "
                "count(DISTINCT CASE WHEN kind='search_hit' THEN event_id END) AS search_exposures, "
                "count(DISTINCT CASE WHEN kind='listed' THEN event_id END) AS list_exposures, "
                "count(DISTINCT CASE WHEN kind IN ('source_reference','source_metadata') THEN event_id END) AS source_lookups" + docs_query +
                " GROUP BY path ORDER BY path LIMIT ? OFFSET ?", [*parameters, limit, offset])]
            unique_reads = db.execute("SELECT count(DISTINCT CASE WHEN kind='body_read' THEN path END)" + docs_query,
                                      parameters).fetchone()[0]
            recent = []
            for row in db.execute("SELECT e.* FROM events e" + where + " ORDER BY e.id DESC LIMIT 5", parameters):
                event = dict(row)
                event["detail"] = json.loads(event["detail"])
                event["documents"] = [dict(doc) for doc in db.execute(
                    "SELECT path,kind,sha256,start_line,end_line,start_column,end_column FROM documents WHERE event_id=? LIMIT 5",
                    (event["id"],))]
                event["document_records"] = db.execute("SELECT count(*) FROM documents WHERE event_id=?", (event["id"],)).fetchone()[0]
                recent.append(event)
        more = offset + len(docs) < total
        return {"scope": "MCP results prepared for delivery only; excludes shell reads and this usage call",
                "calls": counts, "unique_body_read_documents": unique_reads, "documents": docs,
                "total_documents": total, "recent_events": recent,
                "next_offset": offset + len(docs) if more else None, "truncated": more}
