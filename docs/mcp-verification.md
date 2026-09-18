# Read-only MCP verification

Verified locally on 2026-09-18 with Python 3.13, the locked MCP 1.30.0 SDK, and a Terra subagent (`gpt-5.6-terra`).

## Implemented scope

Six stdio tools: `wiki_info`, `wiki_list`, `wiki_search`, `wiki_read`, `wiki_sources`, `wiki_usage`. The server reuses wiki frontmatter/title/hash helpers and never edits wiki files. SQLite records MCP result metadata outside the wiki, distinguishing list exposure, search exposure, body reads and source lookups. Existing registration/index/validation scripts remain unchanged.

The MCP SDK owns protocol handling and schema generation. The regex dependency supplies bounded regular-expression execution. Wiki scripts and hooks retain standard-library-only execution. Codex and Claude Code configurations launch the same server; the new session hook and skill prefer MCP reads when available without claiming shell coverage.

## Automated checks

```bash
uv sync --frozen --project plugins/llm-wiki
uv run --frozen --project plugins/llm-wiki python -m unittest discover -s tests -v
```

Result: **20 tests passed** (16 MCP tests plus 4 existing tests). Coverage includes:

- actual stdio initialize/list-tools/call-tool exchange for every tool;
- actual plugin `uv` startup, environment overrides and discovery from project cwd;
- literal/regex search, filters, context and pagination;
- Unicode/long-line continuation, document hash mismatch and EOF;
- source registration resolution and original text retrieval;
- root escape, symlink, binary/oversized file rejection and regex timeout;
- 40 concurrent read events across multiple service instances without lost counts;
- task/time filtering, exposure versus body-read accounting, response limits and audit failure;
- byte-for-byte preservation of all fixture wiki files.

Skill validation, plugin validation, Python compilation and `git diff --check` passed. CI now installs the locked MCP runtime before the existing Python 3.10–3.13 matrix. Local verification does not by itself establish remote CI success or Windows behavior.

## Terra acceptance

One Terra subagent used the real stdio MCP client in [examples/mcp_query.py](../examples/mcp_query.py) to investigate a runtime question against an existing project wiki. It used all six tools, followed list/search/read pagination, resolved source IDs, read original evidence and checked usage. It did not directly read wiki content with shell file-reading commands or change wiki files.

For its main task label, the stored audit records were independently checked:

| Tool | Success | Failure |
|---|---:|---:|
| wiki_info | 2 | 0 |
| wiki_list | 2 | 0 |
| wiki_search | 3 | 0 |
| wiki_read | 10 | 1 |
| wiki_sources | 3 | 0 |
| wiki_usage | 1 | 0 |

There were **8 unique body-read documents**. The one failure was intentional `../AGENTS.md` traversal, followed by a successful normal request. A separate follow-up label verified one source metadata lookup produces `source_lookups=1`, `body_reads=0`, and zero unique body-read documents. No functional issue was reported.

The acceptance client starts a server per invocation (a JSON call list can share one connection). `task_id` combines these process sessions. Normal MCP hosts can keep one connection open; adding a persistent interactive client is not part of this implementation.

## Boundaries

- Verified real MCP protocol through the supplied client, **not native Codex/Claude tool discovery or UI after plugin installation**. The currently installed plugin was not overwritten.
- No remote/shared server, write tools, binary extraction, vector retrieval, or OS-wide file-read tracking.
- Counts describe results prepared for delivery, not proof of model understanding, client receipt, answer correctness or deployment freshness.
- SDK-rejected arguments never enter the service audit; direct shell and document-reader access are outside accounting.
- See the [MCP contract](../plugins/llm-wiki/skills/llm-wiki/references/mcp.md) for limits, log storage and identity semantics.
