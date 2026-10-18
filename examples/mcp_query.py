#!/usr/bin/env python3
"""A real stdio MCP client for smoke tests and clients without hot-loaded tools.

Send {"name":"wiki_info","arguments":{}} or a list of such calls on stdin.
Run with: uv run --project plugins/llm-wiki python examples/mcp_query.py --root /project/knowledge
Add --follow-cursor to read a complete text file with one wiki_read input call.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def call_with_follow_cursor(session, call):
    name = call["name"]
    arguments = dict(call.get("arguments", {}))
    if name != "wiki_read":
        return await session.call_tool(name, arguments), None

    arguments.setdefault("line_count", 200)
    arguments.setdefault("max_chars", 24000)
    chunks = []
    audit_event_ids = []
    first = None
    while True:
        response = await session.call_tool(name, arguments)
        if response.isError:
            return response, None
        page = response.structuredContent
        if not isinstance(page, dict):
            raise RuntimeError("wiki_read returned no structured content")
        if first is None:
            first = page
        elif page["sha256"] != first["sha256"]:
            raise RuntimeError("wiki_read content changed during continuation")
        chunks.append(page["text"])
        audit_event_ids.append(page["audit"]["event_id"])
        cursor = page.get("next_cursor")
        if cursor is None:
            combined = dict(first)
            combined.update(text="".join(chunks), end_line=page["end_line"],
                            end_column=page["end_column"], next_cursor=None,
                            truncated=False, read_calls=len(chunks), audit_event_ids=audit_event_ids)
            return response, combined
        position = (arguments.get("start_line", 1), arguments.get("start_column", 0))
        next_position = (cursor["start_line"], cursor["start_column"])
        if next_position <= position:
            raise RuntimeError("wiki_read continuation cursor did not advance")
        arguments.update(cursor)
        arguments["expected_sha256"] = first["sha256"]


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--audit-db")
    parser.add_argument("--task-id")
    parser.add_argument("--follow-cursor", action="store_true",
                        help="Follow wiki_read next_cursor and print one combined result")
    args = parser.parse_args()
    calls = json.load(sys.stdin)
    if isinstance(calls, dict):
        calls = [calls]
    server = Path(__file__).resolve().parents[1] / "plugins/llm-wiki/mcp/server.py"
    command = [str(server), "--root", args.root]
    if args.audit_db:
        command += ["--audit-db", args.audit_db]
    if args.task_id:
        command += ["--task-id", args.task_id]
    async with stdio_client(StdioServerParameters(command=sys.executable, args=command)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            if not calls:
                print((await session.list_tools()).model_dump_json())
            failed = False
            for call in calls:
                if args.follow_cursor:
                    result, combined = await call_with_follow_cursor(session, call)
                else:
                    result = await session.call_tool(call["name"], call.get("arguments", {}))
                    combined = None
                print(json.dumps({"name": call["name"], "isError": result.isError,
                                  "result": combined if combined is not None else
                                            result.structuredContent or [c.model_dump() for c in result.content]},
                                 ensure_ascii=False))
                failed |= bool(result.isError)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
