#!/usr/bin/env python3
"""Local, fail-open usage observation; never persist prompts or tool bodies."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))
from usage_audit import audit_db_path, ensure_schema  # noqa: E402

MAX_INPUT = 1024 * 1024
TOOLS = {"wiki_info", "wiki_list", "wiki_search", "wiki_read", "wiki_sources", "wiki_usage"}
EVENTS = {"UserPromptSubmit", "PostToolUse", "Stop", "SubagentStart", "SubagentStop", "Interrupt", "SessionEnd"}
PURPOSES = {"knowledge_lookup", "maintenance", "diagnostic", "unknown"}
ORIGINS = {"interactive", "automation", "background", "unknown"}
ROLES = {"root", "subagent", "unknown"}


def identifier(value):
    """Identifiers only, without control characters or arbitrary payload objects."""
    return value if isinstance(value, str) and 0 < len(value) <= 200 and not any(ord(c) < 32 for c in value) else None


def configured_root(argument=None):
    """An explicit personal root works from projects without a project wiki."""
    value = argument or os.environ.get("LLM_WIKI_ROOT")
    if not value:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
        config = config_home / "llm-wiki/usage.json"
        if config.is_file() and config.stat().st_size <= 4096:
            value = json.loads(config.read_text(encoding="utf-8")).get("root")
    if not isinstance(value, str):
        return None
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        return None
    root = candidate.resolve(strict=True)
    return root if (root / "SCHEMA.md").is_file() else None


def ensure_hook_schema(db):
    statements = """
        CREATE TABLE IF NOT EXISTS hook_turns (
            client TEXT NOT NULL, chat_id TEXT NOT NULL, turn_id TEXT NOT NULL,
            started_at TEXT, ended_at TEXT, status TEXT NOT NULL,
            purpose TEXT NOT NULL DEFAULT 'unknown', execution_origin TEXT NOT NULL DEFAULT 'unknown',
            agent_role TEXT NOT NULL DEFAULT 'unknown', classification_source TEXT NOT NULL DEFAULT 'unknown',
            parent_chat_id TEXT, parent_turn_id TEXT, agent_id TEXT,
            PRIMARY KEY(client,chat_id,turn_id));
        CREATE TABLE IF NOT EXISTS hook_tools (
            client TEXT NOT NULL, chat_id TEXT NOT NULL, tool_use_id TEXT NOT NULL, turn_id TEXT,
            event_id INTEGER NOT NULL, server_session_id TEXT NOT NULL, tool TEXT NOT NULL,
            observed_at TEXT NOT NULL, link_status TEXT NOT NULL,
            purpose TEXT NOT NULL DEFAULT 'unknown', execution_origin TEXT NOT NULL DEFAULT 'unknown',
            agent_role TEXT NOT NULL DEFAULT 'unknown', classification_source TEXT NOT NULL DEFAULT 'unknown',
            declared_fields INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(client,chat_id,tool_use_id));
        CREATE TABLE IF NOT EXISTS hook_agents (
            client TEXT NOT NULL, chat_id TEXT NOT NULL, agent_id TEXT NOT NULL,
            parent_chat_id TEXT, parent_turn_id TEXT, child_chat_id TEXT, child_turn_id TEXT,
            started_at TEXT, ended_at TEXT, status TEXT NOT NULL,
            purpose TEXT NOT NULL DEFAULT 'unknown', execution_origin TEXT NOT NULL DEFAULT 'unknown',
            PRIMARY KEY(client,chat_id,agent_id));
        CREATE TABLE IF NOT EXISTS hook_citations (
            client TEXT NOT NULL, chat_id TEXT NOT NULL, turn_id TEXT NOT NULL, path TEXT NOT NULL,
            PRIMARY KEY(client,chat_id,turn_id,path));
        CREATE TABLE IF NOT EXISTS hook_sessions (
            client TEXT NOT NULL, chat_id TEXT NOT NULL, ended_at TEXT NOT NULL,
            PRIMARY KEY(client,chat_id));
        CREATE INDEX IF NOT EXISTS hook_tools_event ON hook_tools(event_id,server_session_id);
    """
    for statement in statements.split(";"):
        if statement.strip():
            db.execute(statement)
    if "declared_fields" not in {row[1] for row in db.execute("PRAGMA table_info(hook_tools)")}:
        # Old candidates did not distinguish omitted labels from explicit unknown.
        # Preserve that uncertainty rather than retrospectively relabeling them.
        db.execute("ALTER TABLE hook_tools ADD COLUMN declared_fields INTEGER NOT NULL DEFAULT 7")


def context(payload):
    purpose = payload.get("usage_purpose")
    purpose = purpose if isinstance(purpose, str) and purpose in PURPOSES else "unknown"
    origin = payload.get("execution_origin")
    origin = origin if isinstance(origin, str) and origin in ORIGINS else "unknown"
    role = payload.get("agent_role")
    role = role if isinstance(role, str) and role in ROLES else "unknown"
    if identifier(payload.get("agent_id")):
        role = "subagent"
    return purpose, origin, role, "explicit" if purpose != "unknown" else "unknown"


def canonical_link_paths(message, root):
    """Extract only existing canonical wiki link targets, discarding all prose."""
    if not isinstance(message, str):
        return []
    paths = set()
    for match in re.finditer(r"\]\((?:<([^>]+)>|([^\s)]+))(?:\s+[^)]*)?\)", message[:MAX_INPUT]):
        target = unquote(match.group(1) or match.group(2))
        if target.startswith("file://"):
            parsed = urlsplit(target)
            if parsed.netloc not in {"", "localhost"}:
                continue
            target = parsed.path
        elif urlsplit(target).scheme:
            continue
        target = re.sub(r":\d+(?::\d+)?$", "", target.split("#", 1)[0])
        path = Path(target)
        if not path.is_absolute() or ".." in path.parts:
            continue
        try:
            relative = path.relative_to(root)
            if relative.parts[0] != "wiki" or path.suffix != ".md":
                continue
            current = root
            for part in relative.parts:
                current = current / part
                if current.is_symlink():
                    raise ValueError("symlink")
            if not path.is_file():
                continue
            with path.open(encoding="utf-8") as handle:
                header = handle.read(8192)
            if not header.startswith("---\n"):
                continue
            parts = header.split("---", 2)
            if len(parts) != 3:
                continue
            metadata = parts[1]
            if re.search(r"^status:\s*[\"']?canonical[\"']?\s*$", metadata, re.MULTILINE):
                paths.add(relative.as_posix())
        except (OSError, UnicodeError, ValueError, IndexError):
            continue
    return sorted(paths)


def response_audits(response, depth=0):
    """Walk only MCP result wrappers, never arbitrary payload/transcript fields."""
    if depth > 4:
        return []
    if isinstance(response, str):
        try:
            return response_audits(json.loads(response), depth + 1)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(response, dict):
        return []
    found = [response["audit"]] if isinstance(response.get("audit"), dict) else []
    for key in ("structuredContent", "result"):
        if key in response:
            found.extend(response_audits(response[key], depth + 1))
    content = response.get("content")
    if isinstance(content, list):
        for item in content[:20]:
            if isinstance(item, dict) and item.get("type") == "text":
                found.extend(response_audits(item.get("text"), depth + 1))
    return found


def record_turn(db, client, chat, turn, event, payload, now):
    values = context(payload)
    parent_chat, parent_turn = identifier(payload.get("parent_chat_id")), identifier(payload.get("parent_turn_id"))
    agent = identifier(payload.get("agent_id"))
    # Only explicit parent identifiers or a recorded agent lifecycle establish inheritance.
    if agent:
        link = db.execute("SELECT parent_chat_id,parent_turn_id FROM hook_agents WHERE client=? AND chat_id=? AND agent_id=?",
                          (client, chat, agent)).fetchone()
        if link:
            parent_chat, parent_turn = parent_chat or link[0], parent_turn or link[1]
    if parent_chat and parent_turn and values[0] == "unknown":
        parent = db.execute("SELECT purpose,execution_origin FROM hook_turns WHERE client=? AND chat_id=? AND turn_id=?",
                            (client, parent_chat, parent_turn)).fetchone()
        if parent and parent[0] != "unknown":
            values = parent[0], values[1] if values[1] != "unknown" else parent[1], values[2], "inherited"
    status = {"UserPromptSubmit": "started", "Stop": "completed", "Interrupt": "interrupted"}.get(event, "observed")
    started = now if event == "UserPromptSubmit" else None
    ended = now if event in {"Stop", "Interrupt"} else None
    session_end = db.execute("SELECT ended_at FROM hook_sessions WHERE client=? AND chat_id=?", (client, chat)).fetchone()
    if session_end and status not in {"completed", "interrupted"}:
        status, ended = "ended", session_end[0]
    db.execute("""INSERT INTO hook_turns VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(client,chat_id,turn_id) DO UPDATE SET
        started_at=COALESCE(hook_turns.started_at,excluded.started_at),
        ended_at=COALESCE(hook_turns.ended_at,excluded.ended_at),
        status=CASE WHEN excluded.status='interrupted' THEN 'interrupted'
                    WHEN hook_turns.status IN ('completed','interrupted','ended') THEN hook_turns.status
                    WHEN excluded.status='observed' THEN hook_turns.status ELSE excluded.status END,
        purpose=CASE WHEN excluded.purpose='unknown' OR
                    (hook_turns.classification_source='explicit' AND excluded.classification_source!='explicit')
                    THEN hook_turns.purpose ELSE excluded.purpose END,
        execution_origin=CASE WHEN excluded.execution_origin='unknown' THEN hook_turns.execution_origin ELSE excluded.execution_origin END,
        agent_role=CASE WHEN excluded.agent_role='unknown' THEN hook_turns.agent_role ELSE excluded.agent_role END,
        classification_source=CASE WHEN excluded.purpose='unknown' OR
                    (hook_turns.classification_source='explicit' AND excluded.classification_source!='explicit')
                    THEN hook_turns.classification_source ELSE excluded.classification_source END,
        parent_chat_id=COALESCE(excluded.parent_chat_id,hook_turns.parent_chat_id),
        parent_turn_id=COALESCE(excluded.parent_turn_id,hook_turns.parent_turn_id),
        agent_id=COALESCE(excluded.agent_id,hook_turns.agent_id)""",
        (client, chat, turn, started, ended, status, *values, parent_chat, parent_turn, agent))


def reconcile_turn_context(db, client, chat, current_turn, current_agent):
    """A lifecycle hook can arrive after all hooks for the child's turn."""
    turns = db.execute("""SELECT * FROM hook_turns AS child WHERE client=? AND
        (chat_id=? OR parent_chat_id=?) AND purpose='unknown' AND
        ((parent_chat_id IS NOT NULL AND parent_turn_id IS NOT NULL) OR EXISTS
            (SELECT 1 FROM hook_agents AS link WHERE link.client=child.client AND link.agent_id=child.agent_id
             AND (link.chat_id=child.chat_id OR (link.child_chat_id=child.chat_id AND link.child_turn_id=child.turn_id))))
        ORDER BY CASE WHEN turn_id=? OR parent_turn_id=? OR agent_id=? THEN 0 ELSE 1 END LIMIT 200""",
        (client, chat, chat, current_turn, current_turn, current_agent)).fetchall()
    for turn in turns:
        parent_chat, parent_turn = turn["parent_chat_id"], turn["parent_turn_id"]
        if turn["agent_id"] and not (parent_chat and parent_turn):
            link = db.execute("""SELECT parent_chat_id,parent_turn_id FROM hook_agents
                WHERE client=? AND agent_id=? AND
                (chat_id=? OR (child_chat_id=? AND child_turn_id=?)) LIMIT 1""",
                (client, turn["agent_id"], turn["chat_id"], turn["chat_id"], turn["turn_id"])).fetchone()
            if link:
                parent_chat, parent_turn = link[0], link[1]
        if not (parent_chat and parent_turn) or (parent_chat, parent_turn) == (turn["chat_id"], turn["turn_id"]):
            continue
        parent = db.execute("SELECT purpose,execution_origin FROM hook_turns WHERE client=? AND chat_id=? AND turn_id=?",
                            (client, parent_chat, parent_turn)).fetchone()
        if parent and parent[0] != "unknown":
            db.execute("""UPDATE hook_turns SET purpose=?,classification_source='inherited',
                execution_origin=CASE WHEN execution_origin='unknown' THEN ? ELSE execution_origin END,
                parent_chat_id=?,parent_turn_id=? WHERE client=? AND chat_id=? AND turn_id=?
                AND purpose='unknown' AND classification_source='unknown'""",
                (parent[0], parent[1], parent_chat, parent_turn, client, turn["chat_id"], turn["turn_id"]))


def reconcile_tools(db, client, chat):
    candidates = db.execute("""SELECT * FROM hook_tools WHERE link_status='pending' OR
        (link_status='linked' AND client=? AND EXISTS
            (SELECT 1 FROM hook_turns AS child WHERE child.client=hook_tools.client
             AND child.chat_id=hook_tools.chat_id AND child.turn_id=hook_tools.turn_id
             AND (child.chat_id=? OR child.parent_chat_id=?) AND
             ((hook_tools.purpose='unknown' AND (declared_fields & 1)=0 AND child.purpose!='unknown') OR
              (hook_tools.execution_origin='unknown' AND (declared_fields & 2)=0 AND child.execution_origin!='unknown') OR
              (hook_tools.agent_role='unknown' AND (declared_fields & 4)=0 AND child.agent_role!='unknown'))))
        ORDER BY CASE WHEN client=? AND chat_id=? AND link_status='pending' THEN 0
                      WHEN client=? AND chat_id=? THEN 1 ELSE 2 END LIMIT 200""",
        (client, chat, chat, client, chat, client, chat)).fetchall()
    for candidate in candidates:
        hook = dict(candidate)
        turn = db.execute("SELECT purpose,execution_origin,agent_role FROM hook_turns WHERE client=? AND chat_id=? AND turn_id=?",
                          (hook["client"], hook["chat_id"], hook["turn_id"])).fetchone()
        if turn:
            for i, key in enumerate(("purpose", "execution_origin", "agent_role")):
                if not (hook["declared_fields"] & (1 << i)) and hook[key] == "unknown" and turn[i] != "unknown":
                    hook[key] = turn[i]
                    if key == "purpose":
                        hook["classification_source"] = "inherited"
            db.execute("""UPDATE hook_tools SET purpose=?,execution_origin=?,agent_role=?,classification_source=?
                WHERE client=? AND chat_id=? AND tool_use_id=?""",
                (hook["purpose"], hook["execution_origin"], hook["agent_role"], hook["classification_source"],
                 hook["client"], hook["chat_id"], hook["tool_use_id"]))
        event = db.execute("SELECT * FROM events WHERE id=?", (hook["event_id"],)).fetchone()
        if event is None:
            continue
        status = "linked"
        if event["session_id"] != hook["server_session_id"] or event["tool"] != hook["tool"]:
            status = "invalid"
        elif any(event[key] is not None and event[key] != hook[key] for key in ("client", "chat_id", "turn_id", "tool_use_id")):
            status = "conflict"
        else:
            db.execute("""UPDATE events SET client=?,chat_id=?,turn_id=?,tool_use_id=?,
                purpose=CASE WHEN purpose='unknown' AND classification_source='unknown' THEN ? ELSE purpose END,
                execution_origin=CASE WHEN execution_origin='unknown' THEN ? ELSE execution_origin END,
                agent_role=CASE WHEN agent_role='unknown' THEN ? ELSE agent_role END,
                classification_source=CASE WHEN purpose='unknown' AND classification_source='unknown' AND ?!='unknown' THEN ? ELSE classification_source END
                WHERE id=? AND session_id=?""",
                (hook["client"], hook["chat_id"], hook["turn_id"], hook["tool_use_id"], hook["purpose"],
                 hook["execution_origin"], hook["agent_role"], hook["purpose"], hook["classification_source"],
                 hook["event_id"], hook["server_session_id"]))
        db.execute("UPDATE hook_tools SET link_status=? WHERE client=? AND chat_id=? AND tool_use_id=?",
                   (status, hook["client"], hook["chat_id"], hook["tool_use_id"]))


def observe(payload, root, client, audit_db=None):
    if not isinstance(payload, dict) or client not in {"codex", "claude"}:
        return
    event = payload.get("hook_event_name")
    chat = identifier(payload.get("session_id"))
    turn = identifier(payload.get("turn_id")) or (identifier(payload.get("prompt_id")) if client == "claude" else None)
    if event not in EVENTS or not chat:
        return
    root = root.expanduser().resolve(strict=True)
    if not (root / "SCHEMA.md").is_file():
        return
    path = Path(audit_db or audit_db_path(root)).expanduser().resolve()
    if path.is_relative_to(root):
        raise ValueError("Audit database must be outside the wiki")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    now = datetime.now(timezone.utc).isoformat()
    with closing(sqlite3.connect(path, timeout=0.1)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        # Check the binding before any migration or writes to an existing database.
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='wiki' AND type='table'").fetchone():
            registered = db.execute("SELECT root FROM wiki").fetchone()
            if registered and registered[0] != str(root):
                raise ValueError("Audit database belongs to another wiki")
        ensure_schema(db)
        registered = db.execute("SELECT root FROM wiki").fetchone()
        if not registered:
            db.execute("INSERT INTO wiki(root) VALUES(?)", (str(root),))
        ensure_hook_schema(db)
        with db:
            if event == "SessionEnd":
                db.execute("INSERT OR IGNORE INTO hook_sessions VALUES(?,?,?)", (client, chat, now))
                db.execute("UPDATE hook_turns SET status='ended',ended_at=? WHERE client=? AND chat_id=? AND status IN ('started','observed')",
                           (now, client, chat))
            elif event in {"SubagentStart", "SubagentStop"}:
                agent = identifier(payload.get("agent_id"))
                if agent:
                    parent_chat = identifier(payload.get("parent_chat_id")) or (chat if event == "SubagentStart" else None)
                    parent_turn = identifier(payload.get("parent_turn_id")) or (turn if event == "SubagentStart" else None)
                    purpose, origin, _, _ = context(payload)
                    db.execute("""INSERT INTO hook_agents VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(client,chat_id,agent_id) DO UPDATE SET
                        started_at=COALESCE(hook_agents.started_at,excluded.started_at),
                        ended_at=COALESCE(hook_agents.ended_at,excluded.ended_at),
                        parent_chat_id=COALESCE(hook_agents.parent_chat_id,excluded.parent_chat_id),
                        parent_turn_id=COALESCE(hook_agents.parent_turn_id,excluded.parent_turn_id),
                        status=CASE WHEN hook_agents.status='completed' THEN 'completed' ELSE excluded.status END""",
                        (client, chat, agent, parent_chat, parent_turn, identifier(payload.get("child_chat_id")),
                         identifier(payload.get("child_turn_id")), now if event == "SubagentStart" else None,
                         now if event == "SubagentStop" else None, "started" if event == "SubagentStart" else "completed", purpose, origin))
                    child_chat, child_turn = identifier(payload.get("child_chat_id")), identifier(payload.get("child_turn_id"))
                    if event == "SubagentStop" and child_chat and child_turn:
                        for relative in canonical_link_paths(payload.get("last_assistant_message"), root):
                            db.execute("INSERT OR IGNORE INTO hook_citations VALUES(?,?,?,?)", (client, child_chat, child_turn, relative))
            elif turn:
                record_turn(db, client, chat, turn, event, payload, now)
                if event == "Stop":
                    for relative in canonical_link_paths(payload.get("last_assistant_message"), root):
                        db.execute("INSERT OR IGNORE INTO hook_citations VALUES(?,?,?,?)", (client, chat, turn, relative))
                if event == "PostToolUse":
                    name, use = payload.get("tool_name"), identifier(payload.get("tool_use_id"))
                    tool = name.rsplit("__", 1)[-1] if isinstance(name, str) and name.startswith("mcp__") else None
                    if tool in TOOLS and use:
                        audits = response_audits(payload.get("tool_response"))
                        unique = {(a.get("event_id"), a.get("session_id"), a.get("root")) for a in audits
                                  if type(a.get("event_id")) is int and a["event_id"] > 0
                                  and identifier(a.get("session_id")) and isinstance(a.get("root"), str)}
                        # Conflicting wrappers cannot silently select a different MCP event.
                        if len(unique) == 1:
                            event_id, server, audit_root = unique.pop()
                            if audit_root == str(root):
                                row = db.execute("SELECT purpose,execution_origin,agent_role,classification_source FROM hook_turns WHERE client=? AND chat_id=? AND turn_id=?",
                                                 (client, chat, turn)).fetchone()
                                values = (row[0], row[1], row[2], "inherited" if row[0] != "unknown" else "unknown")
                                if context(payload)[0] != "unknown":
                                    values = context(payload)
                                args = payload.get("tool_input")
                                declared_fields = 0
                                for i, (key, allowed) in enumerate((("usage_purpose", PURPOSES), ("execution_origin", ORIGINS), ("agent_role", ROLES))):
                                    if isinstance(payload.get(key), str) and payload[key] in allowed:
                                        declared_fields |= 1 << i
                                if isinstance(args, dict):
                                    declared = context(args)
                                    merged = list(values)
                                    for i, (key, allowed) in enumerate((("usage_purpose", PURPOSES), ("execution_origin", ORIGINS), ("agent_role", ROLES))):
                                        if isinstance(args.get(key), str) and args[key] in allowed:
                                            merged[i] = declared[i]
                                            declared_fields |= 1 << i
                                    if isinstance(args.get("usage_purpose"), str) and args["usage_purpose"] in PURPOSES:
                                        merged[3] = declared[3]
                                    values = tuple(merged)
                                db.execute("INSERT OR IGNORE INTO hook_tools VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                           (client, chat, use, turn, event_id, server, tool, now, "pending", *values, declared_fields))
            reconcile_turn_context(db, client, chat, turn, identifier(payload.get("agent_id")))
            reconcile_tools(db, client, chat)
    path.chmod(0o600)


def main(argv=None):
    output = {"continue": True}
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("--root")
        parser.add_argument("--audit-db", default=os.environ.get("LLM_WIKI_AUDIT_DB"))
        parser.add_argument("--client", choices=("codex", "claude"), required=True)
        args = parser.parse_args(argv)
        data = sys.stdin.read(MAX_INPUT + 1)
        if len(data) > MAX_INPUT:
            raise ValueError("Hook input limit exceeded")
        payload = json.loads(data)
        if not isinstance(payload, dict):
            raise ValueError("Hook input must be an object")
        root = configured_root(args.root)
        if root:
            observe(payload, root, args.client, args.audit_db)
    except (Exception, SystemExit) as exc:
        # Observability must never block a prompt, tool call, stop, or interruption.
        output["systemMessage"] = f"LLM Wiki usage observation unavailable ({type(exc).__name__})."
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
