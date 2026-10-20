"""Purpose migration and isolation across real MCP calls."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins/llm-wiki"
sys.path.insert(0, str(PLUGIN / "mcp"))
AVAILABLE = importlib.util.find_spec("mcp") is not None
if AVAILABLE:
    from wiki_service import WikiService
    from server import create_server


@unittest.skipUnless(AVAILABLE, "Install MCP dependencies")
class PurposeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.root = self.project / "knowledge"
        subprocess.run([sys.executable, str(PLUGIN / "skills/llm-wiki/scripts/init_wiki.py"),
                        "--root", str(self.root)], check=True, capture_output=True)
        self.db = self.project / "audit.sqlite3"
        self.service = WikiService(self.root, self.db)

    def test_maintenance_calls_do_not_inflate_lookup(self):
        for _ in range(10):
            self.service.call("wiki_read", {"path": "wiki/overview.md", "usage_purpose": "maintenance",
                                           "execution_origin": "automation", "agent_role": "subagent"})
        self.service.call("wiki_read", {"path": "wiki/overview.md", "usage_purpose": "knowledge_lookup",
                                       "execution_origin": "interactive", "agent_role": "root"})
        report = self.service.call("wiki_usage", {"filter_purpose": "knowledge_lookup",
                                                 "usage_purpose": "diagnostic"})
        self.assertEqual(report["purpose_counts"], [{"purpose": "knowledge_lookup", "calls": 1}])
        self.assertEqual(report["documents"][0]["body_reads"], 1)
        maintenance = self.service.wiki_usage(filter_purpose="maintenance", filter_agent_role="subagent")
        self.assertEqual(maintenance["documents"][0]["body_reads"], 10)
        self.assertEqual(self.service.wiki_usage(filter_purpose="knowledge_lookup",
                                               filter_execution_origin="automation")["documents"], [])

    def test_defaults_overrides_and_failed_reads_keep_classification(self):
        service = WikiService(self.root, self.db, usage_purpose="maintenance", execution_origin="automation")
        inherited = service.call("wiki_info", {})["audit"]
        self.assertEqual((inherited["purpose"], inherited["classification_source"]), ("maintenance", "inherited"))
        explicit = service.call("wiki_info", {"usage_purpose": "knowledge_lookup"})["audit"]
        self.assertEqual((explicit["purpose"], explicit["classification_source"]), ("knowledge_lookup", "explicit"))
        unknown = service.call("wiki_info", {"usage_purpose": "unknown"})["audit"]
        self.assertEqual((unknown["purpose"], unknown["classification_source"]), ("unknown", "unknown"))
        with self.assertRaises(ValueError):
            service.call("wiki_read", {"path": "../secret", "usage_purpose": "diagnostic"})
        event = service.wiki_usage(filter_purpose="diagnostic")["recent_events"][0]
        self.assertEqual(event["success"], 0)
        self.assertGreaterEqual(event["duration_ms"], 0)
        with self.assertRaises(ValueError):
            service.call("wiki_info", {"usage_purpose": "guess-from-task"})

    def test_legacy_schema_and_old_writers_remain_unknown(self):
        old = self.project / "legacy.sqlite3"
        with sqlite3.connect(old) as db:
            db.executescript("CREATE TABLE wiki(root TEXT NOT NULL); CREATE TABLE events("
                "id INTEGER PRIMARY KEY,time TEXT NOT NULL,session_id TEXT NOT NULL,task_id TEXT,"
                "tool TEXT NOT NULL,success INTEGER NOT NULL,truncated INTEGER NOT NULL,detail TEXT NOT NULL);")
            db.execute("INSERT INTO wiki VALUES(?)", (str(self.root.resolve()),))
            db.execute("INSERT INTO events VALUES(7,'2026-10-18T00:00:00Z','old','hourly','wiki_info',1,0,'{}')")
        service = WikiService(self.root, old)
        with sqlite3.connect(old) as db:
            self.assertEqual(db.execute("SELECT id,purpose,classification_source FROM events").fetchone(),
                             (7, "unknown", "unknown"))
            db.execute("INSERT INTO events(time,session_id,tool,success,truncated,detail) "
                       "VALUES('2026-10-18T01:00:00Z','old','wiki_info',1,0,'{}')")
        self.assertEqual(service.wiki_usage(filter_purpose="unknown")["purpose_counts"][0]["calls"], 2)
        # Opening concurrently cannot race ALTER TABLE or change historical IDs.
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: WikiService(self.root, old), range(4)))
        self.assertEqual(service.wiki_usage(filter_purpose="unknown")["purpose_counts"][0]["calls"], 2)

    def test_timing_scan_metrics_and_no_query_body_in_storage(self):
        result = self.service.call("wiki_search", {"query": "Overview", "usage_purpose": "diagnostic"})
        self.assertGreater(result["metrics"]["scanned_files"], 0)
        self.assertGreater(result["metrics"]["scanned_bytes"], 0)
        self.assertEqual(result["metrics"]["result_count"], len(result["matches"]))
        with sqlite3.connect(self.db) as db:
            row = db.execute("SELECT purpose,duration_ms,detail FROM events").fetchone()
        self.assertEqual(row[0], "diagnostic")
        self.assertGreaterEqual(row[1], 0)
        self.assertNotIn("Overview", row[2])

    def test_every_tool_schema_declares_context_without_leaking_usage_filters(self):
        async def check():
            tools = await create_server(self.service).list_tools()
            for tool in tools:
                props = tool.inputSchema["properties"]
                self.assertIn("usage_purpose", props, tool.name)
                self.assertIn("execution_origin", props, tool.name)
                self.assertIn("agent_role", props, tool.name)
                self.assertEqual("filter_purpose" in props, tool.name == "wiki_usage")
        asyncio.run(check())

    def test_fresh_stdio_explicit_purpose_roundtrip(self):
        calls = [{"name": "wiki_info", "arguments": {"usage_purpose": "knowledge_lookup"}},
                 {"name": "wiki_usage", "arguments": {"filter_purpose": "knowledge_lookup",
                    "usage_purpose": "diagnostic"}}]
        process = subprocess.run([sys.executable, str(REPO / "examples/mcp_query.py"),
            "--root", str(self.root), "--audit-db", str(self.db)], input=json.dumps(calls),
            text=True, capture_output=True, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr)
        outputs = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual(outputs[0]["result"]["audit"]["purpose"], "knowledge_lookup")
        self.assertEqual(outputs[1]["result"]["purpose_counts"], [{"purpose": "knowledge_lookup", "calls": 1}])
