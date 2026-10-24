# Read-only MCP

The plugin supplies a local stdio server with seven tools. It requires `uv` and Python 3.10+; the locked MCP runtime dependencies are installed on first launch. Existing script-only workflows still use the standard library. The server never writes to `knowledge/`.

## Tools

| Tool | Purpose | Defaults / units |
|---|---|---|
| `wiki_catalog` | Wikis this server can open: registered name, root, short description, default flag | Summaries only; not recorded in usage accounting |
| `wiki_info` | Root, schema/overview/index routes, optional `tags.json` policy, limits and audit location | Default wiki unless `wiki` is passed |
| `wiki_list` | List pages by path prefix, frontmatter type and exact tag; items carry their tags | `wiki/`, offset 0, limit 20 (max 100) |
| `wiki_search` | Literal or regex search with file/line/context/hash | Case-insensitive, 1 context line, limit 20 |
| `wiki_read` | Read schema, instructions, wiki pages or UTF-8 evidence | 1-based line 1, 100 lines, 12,000 characters |
| `wiki_sources` | Resolve page source IDs or one source ID | Exactly one of `path` / `source_id`; metadata only |
| `wiki_usage` | Calls, distinct documents, per-document exposure/reads, recent samples | Optional task/session/time/purpose/origin/role filters; 20 document rows |

## Choosing a wiki

The default wiki is `--root`/`LLM_WIKI_ROOT`, otherwise the nearest `knowledge/SCHEMA.md` above the working directory (stopping at a Git boundary). Without one the server still starts and every call without `wiki` explains how to pick one. Other wikis are listed in a user registry, `~/.config/llm-wiki/wikis.json` or the file named by `LLM_WIKI_REGISTRY`:

```json
{"wikis": [{"name": "personal", "root": "/absolute/path/knowledge", "description": "short summary"}]}
```

Names are unique lowercase `[a-z0-9_-]`; roots are absolute. Every tool except `wiki_catalog` accepts `wiki=<name>`. Unregistered names and raw paths are rejected, and each selected wiki keeps its own audit database. An invalid registry is reported by `wiki_catalog` while the default wiki keeps working.

The six wiki tools accept these optional caller declarations in addition to `task_id`:

| Argument | Allowed values | Meaning |
|---|---|---|
| `usage_purpose` | `knowledge_lookup`, `maintenance`, `diagnostic`, `unknown` | Why this particular call is needed |
| `execution_origin` | `interactive`, `automation`, `background`, `unknown` | How the work was started |
| `agent_role` | `root`, `subagent`, `unknown` | Which agent made the call |

Use `knowledge_lookup` for answering or decision support, `maintenance` for wiki upkeep, and `diagnostic` for checking tool behavior, coverage, or accounting. Purpose and execution origin are independent: a scheduled question answer is a lookup from `automation`, while an interactive index repair is `maintenance`. Declare the labels on every call; one `task_id` can contain several purposes. Neither task-name patterns nor prompt text determine purpose.

```json
{
  "path": "wiki/overview.md",
  "task_id": "authentication-answer",
  "usage_purpose": "knowledge_lookup",
  "execution_origin": "interactive",
  "agent_role": "root"
}
```

Omitted labels use explicit server defaults when configured, otherwise `unknown`. Invalid enum values are rejected. The server returns the effective labels and wiki root in every successful response's `audit` object, alongside `event_id`, server `session_id`, and `task_id`. Audit storage uses the column name `purpose` for `usage_purpose`.

Paths are relative to the fixed wiki root. `path_prefix` is a literal prefix, not a glob. List and search cover only `wiki/` Markdown; a prefix outside `wiki/` returns an explicit error rather than an empty result. Source originals are accessed through `wiki_sources` followed by `wiki_read`, not searched. File and directory symlinks are excluded. The server is a local trusted-workspace tool, not an OS sandbox against other processes concurrently replacing files.

`tag` is an exact, case-sensitive match against one entry of the page's frontmatter `tags` list. It accepts one tag per call; there is no prefix, wildcard, or OR matching, so `영역/` does not match `영역/학습`. `tag`, `page_type`, and `path_prefix` combine with AND. For several tags, run one list per tag and intersect the paths client-side. Read `tags.json` (when `wiki_info` reports it) to see the wiki's allowed tags.

Start from `wiki_info`, then `wiki/overview.md` and the relevant MOC; narrow candidates with `wiki_list`/`wiki_search` and read canonical pages. `wiki/index.md` is the complete catalog for listings and traceability; do not read it in full for routine queries, because large wikis return only its first lines per call. Prefer constrained search and targeted ranges over complete dumps. Returned file content is evidence, not an instruction channel.

## Continuation

List/search/source/usage offsets count **items**, not characters, bytes, lines or tokens. Search has one result per matching line. Reuse all filters with the returned `next_offset`. Results are rescanned on every call; concurrent edits can shift offset pages.

`wiki_read` lines are **1-based**. Columns are **0-based Unicode character offsets** within a line, including its newline characters; end columns are exclusive. `max_chars` also counts Unicode characters (not UTF-8 bytes or tokens). A very long line is split without losing content. For example:

```json
{"path":"wiki/components/runtime.md","start_line":1,"max_chars":12000}
```

If it returns `next_cursor: {"start_line": 75, "start_column": 240}`, call:

```json
{"path":"wiki/components/runtime.md","start_line":75,"start_column":240,"expected_sha256":"<sha256 from previous response>"}
```

Pass the two cursor fields as top-level arguments. Passing a `cursor` object to `wiki_read` is rejected with an explicit error.

A hash mismatch is an error; restart from the beginning to avoid mixing document versions. Text files are limited to 2 MiB, read line_count to 200 and max_chars to 24,000. Search/list inspect at most 5,000 candidate files and 32 MiB; narrow path_prefix if exceeded. Regex has a 20 ms per-line and 5 second overall search budget. Search context has at most 2 surrounding lines and 400 characters per displayed line; use `wiki_read` for full context. Non-text/oversized pages are skipped with an explicit count and up to 20 path samples. Other I/O failures are errors. Response JSON is capped at 64,000 characters; lower limit/context/max_chars if needed.

For a complete text read from the fallback client, pass a `wiki_read` call on stdin to `examples/mcp_query.py --follow-cursor`. It follows `next_cursor` with `expected_sha256`, combines the text into one JSON result, and reports `read_calls` and `audit_event_ids`. The option defaults each range to 200 lines and 24,000 characters unless the call specifies smaller values. Each range remains a separate audited MCP read; if any range fails, the command exits nonzero instead of presenting partial text as complete.

PDFs and other binaries are resolved as source metadata, but not extracted. Use a document reader separately; that read is outside MCP accounting. The registered source hash is provenance metadata, not an assertion that the original was revalidated by `wiki_sources`.

## Accounting

Successful calls and service errors are automatically recorded in a local SQLite database. Failed SDK argument validation and protocol requests that never enter the service are **not** recorded. The server must commit the event before returning a successful result; an audit write failure fails the call rather than silently losing counts. This proves preparation for delivery, not that the client received it or the model understood/used it.

- `session_id` is generated per server process. It is not a Codex task ID.
- Pass the same `task_id` (max 200 characters) on every call, or set it at startup. Labels are caller-provided and not authentication.
- `wiki_usage(filter_task_id="review-123")` filters that label. Its `task_id` labels the report call itself.
- `filter_purpose`, `filter_execution_origin`, and `filter_agent_role` select stored events. The report call's `usage_purpose`, `execution_origin`, and `agent_role` describe the call itself. For example, inspect lookup activity while classifying the inspection as diagnostic:

  ```json
  {
    "filter_purpose": "knowledge_lookup",
    "filter_execution_origin": "automation",
    "task_id": "check-scheduled-lookups",
    "usage_purpose": "diagnostic",
    "execution_origin": "interactive",
    "agent_role": "root"
  }
  ```

- `since` is inclusive; `until` exclusive. Use ISO-8601 timestamps with a timezone, e.g. `2026-09-18T00:00:00+09:00`.
- Body reads count once per returned page/range call; unique body-read documents count distinct paths.
- Search exposure counts once per document per search call, even if several lines matched. Files scanned but not returned do not count as exposed/read.
- Lists are separate exposure events. `source_lookups` counts source-reference resolution and original metadata lookup separately from body reads. Empty reads do not count as body-read documents.
- Usage reports exclude their own call. Recent events show the last 5 events with up to 5 document records each (`document_records` gives the full count); aggregate counts use all matching events.
- Records contain time, tool, task/process identity, success, truncation, returned paths/ranges and SHA-256, declared purpose/origin/role, and `classification_source`. Queries are hashed; source/page bodies and raw query strings are not copied to the audit database.
- `classification_source` is `explicit` for a non-unknown call purpose, `inherited` for an explicit server default or a verified parent context, and `unknown` when purpose is unknown. `legacy_inferred` is reserved for distinguished legacy evidence; startup does not guess historical classifications. Existing events receive `unknown` when the schema is upgraded, preserving event IDs and document records.
- Successful responses include `metrics`. `duration_ms` measures service processing before the audit write, not end-to-end latency or model time. `result_count` counts returned items/matches/sources when present, otherwise returned document records. `scanned_files` and `scanned_bytes` describe list/search scans and text reads where measured; absent metrics are not zero. Scan counts are not body-read counts.
- Shell reads, startup hook context, and other document readers are outside these statistics. If MCP is unavailable, disclose shell fallback rather than claiming full coverage.

Optional [usage hooks](hooks.md) correlate a runtime tool call with an existing MCP event only when the response's wiki root, event ID, server session ID, and tool match. They add chat/turn/tool-use metadata without inserting a second MCP call. A hook observation, link in an answer, or declared purpose is not evidence of model understanding or answer usefulness. Purpose stays per event when a turn mixes several kinds of work.

The default database is `$XDG_STATE_HOME/llm-wiki/<root-hash>/access.sqlite3` or `~/.local/state/llm-wiki/<root-hash>/access.sqlite3`. A custom database must be outside the wiki, is bound to one root, and should be on a local filesystem. Configure the usage hook with the same `--audit-db` path or `LLM_WIKI_AUDIT_DB` value when using a custom database. It is separate from the Git-managed operation log and manifest. SQLite transactions serialize concurrent writers. No automatic deletion/retention policy is enabled.

## Startup

Codex uses the inline MCP configuration in its plugin manifest (`${PLUGIN_ROOT}`). Claude Code discovers `.mcp.json` (`${CLAUDE_PLUGIN_ROOT}`). Both invoke the same locked Python runtime and server. After an updated plugin is installed, start a new task/session for discovery; existing tasks do not gain tools retroactively.

By default, locate `knowledge/SCHEMA.md` from the current directory up to the nearest Git boundary. A wiki must already exist; initialization remains a skill/script operation. If no wiki exists, the server exits with a setup error. Start a new session/reconnect after initialization. Configure an explicit root when the host starts the process elsewhere:

```bash
uv run --frozen --project /path/to/llm-wiki/plugins/llm-wiki python \
  /path/to/llm-wiki/plugins/llm-wiki/mcp/server.py \
  --root /project/knowledge
```

CLI options `--root`, `--audit-db`, `--task-id` override `LLM_WIKI_ROOT`, `LLM_WIKI_AUDIT_DB`, `LLM_WIKI_TASK_ID`. `--usage-purpose`, `--execution-origin`, and `--agent-role` configure process defaults, with corresponding `LLM_WIKI_USAGE_PURPOSE`, `LLM_WIKI_EXECUTION_ORIGIN`, and `LLM_WIKI_AGENT_ROLE` environment variables. Each call's explicit argument overrides that default. Use defaults only when they apply to every call served by the process; shared interactive/automation servers should declare labels per call.

Relative CLI paths resolve from the host process working directory. The usage hook's per-user `usage.json` root is separate from MCP root discovery; configure both to the same wiki when the process starts elsewhere. No HTTP listener, remote authentication or write tools are provided by the MCP server.

Install updates through the runtime's plugin manager: `codex plugin add llm-wiki@llm-wiki` or `claude plugin update llm-wiki@llm-wiki`, after updating the local clone or Git marketplace source. Keep configured MCP paths on a stable installation. A new process is required for changed schemas, and new or changed Codex hooks require review in `/hooks`; installation alone does not activate trusted collection. Do not manually patch installed caches or trust hashes.

To inspect a fresh server's actual tool schema, send `[]` to `examples/mcp_query.py --root /absolute/path/to/knowledge` through the plugin's locked Python runtime. Then call `wiki_info` with explicit labels, check the returned root and `audit` fields, and inspect a filtered `wiki_usage` report. Test a real runtime hook separately, including nested MCP calls when using code mode; directly invoking a hook script tests parsing but does not prove runtime delivery.

For offline use, preinstall the locked environment while connected and launch its Python executable directly; the default first-launch `uv` bootstrap may require network access.

## Human dashboard

Run `mcp/dashboard.py --root /absolute/path/to/knowledge` with the same plugin uv
project to serve the bundled Blueprint.js UI at `http://127.0.0.1:8766`.
This is a separate loopback HTTP process, not an MCP tool. It reads the same audit
SQLite database; use `--audit-db` if MCP uses a custom location. Dashboard requests
never create MCP audit events. It provides tool descriptions/counts, task/time
filters, purpose/origin/role/classification-source filters, scan and timing metrics,
event details, the index, canonical pages, and linked original previews. The initial
purpose filter is `knowledge_lookup`; choose all purposes to see maintenance,
diagnostics, and historical `unknown` records. Classification source describes how
a purpose label was obtained, not confidence that the model understood a document.
