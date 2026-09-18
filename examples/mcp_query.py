#!/usr/bin/env python3
"""A real stdio MCP client for smoke tests and clients without hot-loaded tools.

Send {"name":"wiki_info","arguments":{}} or a list of such calls on stdin.
Run with: uv run --project plugins/llm-wiki python examples/mcp_query.py --root /project/knowledge
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--audit-db")
    parser.add_argument("--task-id")
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
                result = await session.call_tool(call["name"], call.get("arguments", {}))
                print(json.dumps({"name": call["name"], "isError": result.isError,
                                  "result": result.structuredContent or [c.model_dump() for c in result.content]},
                                 ensure_ascii=False))
                failed |= bool(result.isError)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
