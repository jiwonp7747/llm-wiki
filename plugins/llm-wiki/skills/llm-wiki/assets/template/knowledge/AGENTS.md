# LLM Wiki Instructions

- Read `SCHEMA.md` before changing this directory.
- Treat `sources/` as immutable evidence. Register replacements as new sources.
- Let scripts own hashes, manifest events, logs, indexes, and structural validation.
- Let the LLM own synthesis under `wiki/`, with source IDs and cross-links.
- Do not silently resolve contradictions, delete pages, or archive canonical content.
- Rebuild `wiki/index.md` and validate after wiki mutations.
- Prefer the LLM Wiki MCP tools for search and reads when available; keep a consistent `task_id` for access accounting.
- Declare `usage_purpose` on every MCP call: `knowledge_lookup` for answering or decision support, `maintenance` for wiki upkeep, or `diagnostic` for tool checks. Use `unknown` when unclear. A task name does not determine purpose; mixed tasks keep each call's actual purpose.
- Declare `execution_origin` (`interactive`, `automation`, `background`, or `unknown`) and `agent_role` (`root`, `subagent`, or `unknown`) independently of purpose. Subagents declare their own role.
- In `wiki_usage`, use `filter_purpose`, `filter_execution_origin`, and `filter_agent_role` to select recorded events; the unprefixed classification arguments label the report call itself.
- Shell fallback reads are not included in MCP usage. Hook installation, hook trust, and fresh-session observation are separate verification steps; usage records do not prove model understanding or answer usefulness.
