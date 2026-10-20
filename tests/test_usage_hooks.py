from __future__ import annotations

import importlib.util
import io
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins/llm-wiki"
sys.path.insert(0, str(PLUGIN / "mcp"))
spec = importlib.util.spec_from_file_location("wiki_usage_hook", PLUGIN / "hooks/wiki_usage.py")
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


class UsageHookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "knowledge"
        (self.root / "wiki/concepts").mkdir(parents=True)
        (self.root / "SCHEMA.md").write_text("# Schema\n")
        self.page = self.root / "wiki/concepts/example.md"
        self.page.write_text("---\nstatus: canonical\n---\n# Example\n")
        self.db = self.base / "access.sqlite3"

    def observe(self, event, **fields):
        payload = {"hook_event_name": event, "session_id": "chat-1", "turn_id": "turn-1", **fields}
        hook.observe(payload, self.root, "codex", self.db)

    def rows(self, table):
        with closing(sqlite3.connect(self.db)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(f"SELECT * FROM {table}")]

    def seed_event(self, event_id=7, session="server-1", purpose="unknown", tool="wiki_read"):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            hook.ensure_schema(db)
            if not db.execute("SELECT root FROM wiki").fetchone():
                db.execute("INSERT INTO wiki VALUES(?)", (str(self.root),))
            db.execute("INSERT INTO events(id,time,session_id,tool,success,truncated,detail,purpose,classification_source) VALUES(?,?,?,?,?,?,?,?,?)",
                       (event_id, "2026-10-21T00:00:00+00:00", session, tool, 1, 0, "{}", purpose,
                        "explicit" if purpose != "unknown" else "unknown"))

    def post(self, audit=None, **fields):
        self.observe("PostToolUse", tool_name="mcp__personal_wiki__wiki_read", tool_use_id="tool-1",
                     tool_response={"structuredContent": {"audit": audit or {"event_id": 7, "session_id": "server-1", "root": str(self.root)}}}, **fields)

    def test_zero_call_turn_is_retained_without_prompt_or_body(self):
        secret = "NEVER_STORE_THIS_SECRET_OR_PROMPT"
        self.observe("UserPromptSubmit", prompt=secret, transcript_path=str(self.base / secret),
                     usage_purpose="maintenance", execution_origin="automation")
        self.observe("Stop", last_assistant_message=f"{secret} [canonical]({self.page}:8) [web](https://example.com/{secret})")
        turns = self.rows("hook_turns")
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["purpose"], "maintenance")
        self.assertEqual(turns[0]["status"], "completed")
        self.assertEqual(self.rows("hook_tools"), [])
        self.assertEqual(self.rows("hook_citations")[0]["path"], "wiki/concepts/example.md")
        with closing(sqlite3.connect(self.db)) as db:
            self.assertNotIn(secret, "\n".join(db.iterdump()))

    def test_exact_audit_links_once_and_keeps_explicit_service_purpose(self):
        self.seed_event(purpose="knowledge_lookup")
        self.post(tool_input={"usage_purpose": "maintenance", "query": "private query", "token": "secret"})
        self.post(tool_input={"usage_purpose": "maintenance"})
        self.assertEqual(len(self.rows("hook_tools")), 1)
        event = self.rows("events")[0]
        self.assertEqual(event["purpose"], "knowledge_lookup")
        self.assertEqual(event["classification_source"], "explicit")
        self.assertEqual(event["chat_id"], "chat-1")
        self.assertEqual(event["tool_use_id"], "tool-1")
        self.assertEqual(self.rows("hook_tools")[0]["link_status"], "linked")
        self.assertEqual(self.rows("hook_turns")[0]["purpose"], "unknown")

    def test_content_wrapper_and_late_event_reconcile_without_losing_stop(self):
        audit = {"event_id": 7, "session_id": "server-1", "root": str(self.root)}
        self.observe("Stop")
        self.observe("PostToolUse", tool_name="mcp__wiki__wiki_read", tool_use_id="tool-1",
                     tool_input={"usage_purpose": "diagnostic"},
                     tool_response={"content": [{"type": "text", "text": json.dumps({"audit": audit})}]})
        self.assertEqual(self.rows("hook_tools")[0]["link_status"], "pending")
        self.seed_event()
        self.observe("UserPromptSubmit", prompt="not retained")
        self.assertEqual(self.rows("hook_tools")[0]["link_status"], "linked")
        self.assertEqual(self.rows("hook_turns")[0]["status"], "completed")
        self.assertEqual(self.rows("events")[0]["purpose"], "diagnostic")

    def test_wrong_root_server_tool_and_preexisting_identity_are_not_linked(self):
        self.seed_event(session="correct-server")
        self.post(audit={"event_id": 7, "session_id": "server-1", "root": str(self.root / "other")})
        self.assertEqual(self.rows("hook_tools"), [])
        self.post()
        self.assertEqual(self.rows("hook_tools")[0]["link_status"], "invalid")
        self.assertIsNone(self.rows("events")[0]["chat_id"])
        self.seed_event(event_id=8, tool="wiki_search")
        self.observe("PostToolUse", tool_name="mcp__wiki__wiki_read", tool_use_id="wrong-tool",
                     tool_response={"audit": {"event_id": 8, "session_id": "server-1", "root": str(self.root)}})
        self.assertEqual(self.rows("hook_tools")[1]["link_status"], "invalid")
        self.seed_event(event_id=9)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE events SET chat_id='other-chat' WHERE id=9")
        self.observe("PostToolUse", tool_name="mcp__wiki__wiki_read", tool_use_id="conflict",
                     tool_response={"audit": {"event_id": 9, "session_id": "server-1", "root": str(self.root)}})
        self.assertEqual(self.rows("hook_tools")[2]["link_status"], "conflict")

    def test_other_wiki_database_is_never_migrated_or_modified(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("CREATE TABLE wiki(root TEXT NOT NULL)")
            db.execute("INSERT INTO wiki VALUES(?)", (str(self.base / "another-wiki"),))
        with self.assertRaises(ValueError):
            self.observe("UserPromptSubmit")
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [("wiki",)])

    def test_no_purpose_inference_from_task_names_and_malformed_context(self):
        self.observe("UserPromptSubmit", task_id="hourly-maintenance-automation", prompt="sync the wiki")
        self.assertEqual(self.rows("hook_turns")[0]["purpose"], "unknown")
        self.observe("Stop", usage_purpose={"bad": "data"}, execution_origin=[], agent_role=3)
        self.assertEqual(self.rows("hook_turns")[0]["classification_source"], "unknown")

    def test_explicit_unknown_call_overrides_inherited_turn_context(self):
        self.seed_event()
        self.observe("UserPromptSubmit", usage_purpose="maintenance", execution_origin="automation")
        self.post(tool_input={"usage_purpose": "unknown", "execution_origin": "unknown"})
        event = self.rows("events")[0]
        self.assertEqual(event["purpose"], "unknown")
        self.assertEqual(event["classification_source"], "unknown")
        self.assertEqual(event["execution_origin"], "unknown")

    def test_call_inherits_declared_turn_context_without_changing_source_to_explicit(self):
        self.seed_event()
        self.observe("UserPromptSubmit", usage_purpose="maintenance")
        self.post()
        self.assertEqual(self.rows("events")[0]["purpose"], "maintenance")
        self.assertEqual(self.rows("events")[0]["classification_source"], "inherited")

    def test_late_agent_parent_context_reaches_already_linked_call_after_child_stop(self):
        self.seed_event()
        self.observe("UserPromptSubmit", usage_purpose="maintenance", execution_origin="automation")
        self.observe("PostToolUse", turn_id="child-turn", agent_id="agent-late", tool_name="mcp__wiki__wiki_read",
                     tool_use_id="tool-late", tool_response={"audit": {"event_id": 7, "session_id": "server-1", "root": str(self.root)}})
        self.assertEqual(self.rows("events")[0]["purpose"], "unknown")
        self.assertEqual(self.rows("hook_tools")[0]["link_status"], "linked")
        self.observe("Stop", turn_id="child-turn", agent_id="agent-late")
        # The parent start hook can be delivered after even the child's stop.
        self.observe("SubagentStart", agent_id="agent-late")
        event = self.rows("events")[0]
        self.assertEqual(event["purpose"], "maintenance")
        self.assertEqual(event["classification_source"], "inherited")
        self.assertEqual(event["execution_origin"], "automation")
        candidate = self.rows("hook_tools")[0]
        self.assertEqual(candidate["purpose"], "maintenance")
        self.assertEqual(candidate["classification_source"], "inherited")
        child = next(t for t in self.rows("hook_turns") if t["turn_id"] == "child-turn")
        self.assertEqual(child["status"], "completed")
        self.assertEqual(child["parent_turn_id"], "turn-1")

    def test_late_parent_context_keeps_explicit_unknown_call_unclassified(self):
        self.seed_event()
        self.observe("UserPromptSubmit", usage_purpose="maintenance", execution_origin="automation")
        self.observe("PostToolUse", turn_id="child-turn", agent_id="agent-late", tool_name="mcp__wiki__wiki_read",
                     tool_use_id="tool-late", tool_input={"usage_purpose": "unknown", "execution_origin": "unknown"},
                     tool_response={"audit": {"event_id": 7, "session_id": "server-1", "root": str(self.root)}})
        self.observe("SubagentStart", agent_id="agent-late")
        self.observe("Stop", turn_id="child-turn", agent_id="agent-late")
        event, candidate = self.rows("events")[0], self.rows("hook_tools")[0]
        for row in (event, candidate):
            self.assertEqual(row["purpose"], "unknown")
            self.assertEqual(row["classification_source"], "unknown")
            self.assertEqual(row["execution_origin"], "unknown")

    def test_hook_candidate_migration_preserves_old_unknown_intent(self):
        self.seed_event()
        self.post()
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("ALTER TABLE hook_tools DROP COLUMN declared_fields")
        self.observe("UserPromptSubmit", usage_purpose="maintenance")
        self.assertEqual(self.rows("hook_tools")[0]["declared_fields"], 7)
        self.assertEqual(self.rows("events")[0]["purpose"], "unknown")

    def test_explicit_subagent_link_inherits_and_unlinked_agent_does_not(self):
        self.observe("UserPromptSubmit", usage_purpose="maintenance", execution_origin="automation")
        self.observe("SubagentStart", agent_id="agent-1")
        self.observe("UserPromptSubmit", turn_id="child-1", agent_id="agent-1")
        self.observe("UserPromptSubmit", turn_id="child-unknown", agent_id="another-agent")
        turns = {r["turn_id"]: r for r in self.rows("hook_turns")}
        self.assertEqual(turns["child-1"]["purpose"], "maintenance")
        self.assertEqual(turns["child-1"]["classification_source"], "inherited")
        self.assertEqual(turns["child-unknown"]["purpose"], "unknown")
        self.observe("SubagentStop", agent_id="agent-1", last_assistant_message=f"[canonical]({self.page})")
        self.assertEqual(self.rows("hook_citations"), [])
        self.assertEqual(turns["turn-1"]["agent_role"], "unknown")

    def test_interrupt_and_session_end_survive_late_prompt_delivery(self):
        self.observe("Interrupt")
        self.observe("Stop")
        self.observe("UserPromptSubmit")
        self.assertEqual(self.rows("hook_turns")[0]["status"], "interrupted")
        self.observe("SessionEnd")
        self.observe("UserPromptSubmit", turn_id="late-turn")
        self.assertEqual(self.rows("hook_turns")[1]["status"], "ended")

    def test_claude_uses_supplied_prompt_id_and_missing_ids_are_skipped(self):
        hook.observe({"hook_event_name": "UserPromptSubmit", "session_id": "claude-session", "prompt_id": "prompt-1"},
                     self.root, "claude", self.db)
        self.assertEqual(self.rows("hook_turns")[0]["turn_id"], "prompt-1")
        hook.observe({"hook_event_name": "Stop", "session_id": "claude-session"}, self.root, "claude", self.db)
        self.assertEqual(len(self.rows("hook_turns")), 1)

    def test_canonical_links_reject_symlinks_noncanonical_and_outside_targets(self):
        noncanonical = self.root / "wiki/concepts/draft.md"
        noncanonical.write_text("---\nstatus: draft\n---\n")
        symlink = self.root / "wiki/concepts/symlink.md"
        symlink.symlink_to(self.page)
        message = f"[ok](<{self.page}:4>) [duplicate]({self.page}) [draft]({noncanonical}) [symlink]({symlink}) [other](/etc/passwd)"
        self.assertEqual(hook.canonical_link_paths(message, self.root), ["wiki/concepts/example.md"])

    def test_global_root_config_precedence_without_project_discovery(self):
        config = self.base / "config/llm-wiki"
        config.mkdir(parents=True)
        (config / "usage.json").write_text(json.dumps({"root": str(self.root)}))
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config.parent)}, clear=True):
            self.assertEqual(hook.configured_root(), self.root)
            self.assertIsNone(hook.configured_root("knowledge"))
            with patch.dict(os.environ, {"LLM_WIKI_ROOT": str(self.base / "missing")}):
                self.assertEqual(hook.configured_root(str(self.root)), self.root)

    def test_custom_audit_database_cli_and_environment(self):
        payload = json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "custom", "turn_id": "custom-turn"})
        for mode in ("cli", "env"):
            audit = self.base / f"{mode}.sqlite3"
            argv = ["--client", "codex", "--root", str(self.root)]
            env = {"LLM_WIKI_AUDIT_DB": str(audit)} if mode == "env" else {}
            if mode == "cli":
                argv.extend(["--audit-db", str(audit)])
            with patch.dict(os.environ, env), patch("sys.stdin", io.StringIO(payload)), redirect_stdout(io.StringIO()):
                self.assertEqual(hook.main(argv), 0)
            with closing(sqlite3.connect(audit)) as db:
                self.assertEqual(db.execute("SELECT turn_id FROM hook_turns").fetchone()[0], "custom-turn")

    def test_main_is_fail_open_on_bad_payload_database_lock_and_missing_root(self):
        for payload in ("not json", "[]", "{}", "x" * (hook.MAX_INPUT + 1)):
            output = io.StringIO()
            with patch("sys.stdin", io.StringIO(payload)), redirect_stdout(output):
                self.assertEqual(hook.main(["--client", "codex", "--root", str(self.root)]), 0)
            self.assertTrue(json.loads(output.getvalue())["continue"])
        self.observe("UserPromptSubmit")
        with closing(sqlite3.connect(self.db)) as lock:
            lock.execute("BEGIN IMMEDIATE")
            output = io.StringIO()
            payload = json.dumps({"hook_event_name": "Stop", "session_id": "chat-1", "turn_id": "turn-1"})
            start = time.monotonic()
            with patch("sys.stdin", io.StringIO(payload)), patch.object(hook, "audit_db_path", return_value=self.db), redirect_stdout(output):
                self.assertEqual(hook.main(["--client", "codex", "--root", str(self.root)]), 0)
            self.assertLess(time.monotonic() - start, 1)
            result = json.loads(output.getvalue())
            self.assertTrue(result["continue"])
            self.assertIn("OperationalError", result["systemMessage"])

    def test_failure_warning_redacts_exception_text_and_unconfigured_is_quiet(self):
        payload = json.dumps({"hook_event_name": "Stop", "session_id": "chat-1", "turn_id": "turn-1"})
        output = io.StringIO()
        with patch("sys.stdin", io.StringIO(payload)), patch.object(hook, "observe", side_effect=OSError("SECRET /private/credential/path")), redirect_stdout(output):
            self.assertEqual(hook.main(["--client", "codex", "--root", str(self.root)]), 0)
        result = json.loads(output.getvalue())
        self.assertTrue(result["continue"])
        self.assertIn("OSError", result["systemMessage"])
        self.assertNotIn("SECRET", output.getvalue())
        self.assertNotIn("/private/credential", output.getvalue())
        output = io.StringIO()
        with patch("sys.stdin", io.StringIO(payload)), patch.object(hook, "configured_root", return_value=None), redirect_stdout(output):
            self.assertEqual(hook.main(["--client", "codex"]), 0)
        self.assertEqual(json.loads(output.getvalue()), {"continue": True})

    def test_hook_maps_preserve_existing_hooks_and_only_register_supported_events(self):
        for filename, client in (("hooks.json", "codex"), ("claude-hooks.json", "claude")):
            hooks = json.loads((PLUGIN / "hooks" / filename).read_text())["hooks"]
            self.assertIn("session_start.py", hooks["SessionStart"][0]["hooks"][0]["command"])
            self.assertIn("stop_validate.py", hooks["Stop"][0]["hooks"][0]["command"])
            self.assertEqual("Interrupt" in hooks, client == "codex")
            for event in hook.EVENTS - ({"Interrupt"} if client == "claude" else set()):
                observation = next(h for entry in hooks[event] for h in entry["hooks"] if "wiki_usage.py" in h["command"])
                self.assertIn(f"--client {client}", observation["command"])
                self.assertNotIn("PreToolUse", hooks)
                self.assertLessEqual(observation["timeout"], 3)


if __name__ == "__main__":
    unittest.main()
