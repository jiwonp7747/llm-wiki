# LLM Wiki Instructions

- Read `SCHEMA.md` before changing this directory.
- Treat `sources/` as immutable evidence. Register replacements as new sources.
- Let scripts own hashes, manifest events, logs, indexes, and structural validation.
- Let the LLM own synthesis under `wiki/`, with source IDs and cross-links.
- Do not silently resolve contradictions, delete pages, or archive canonical content.
- Rebuild `wiki/index.md` and validate after wiki mutations.
- Prefer the LLM Wiki MCP tools for search and reads when available; keep a consistent task_id for access accounting. Shell fallback reads are not included in MCP usage.
