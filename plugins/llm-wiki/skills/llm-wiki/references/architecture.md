# Architecture

## Boundaries

The generated knowledge base has three data layers:

1. `sources/` contains immutable evidence captured with provenance and a SHA-256 digest.
2. `wiki/` contains LLM-maintained synthesis and cross-links.
3. `system/` contains append-only processing events, operation logs, and lint reports.

The plugin is a fourth, external execution layer. Its skill describes judgment and approvals; its scripts perform deterministic bookkeeping. Plugin upgrades must never overwrite a project's `knowledge/` directory.

## Ownership

| Area | Primary owner | Mutation rule |
|---|---|---|
| `sources/` | User or intake script | Register once; never edit in place |
| `wiki/` | LLM with user direction | Update canonical pages; preserve provenance |
| `system/` | Scripts and hooks | Append events; regenerate reports and indexes |
| Skill and scripts | Plugin maintainer | Versioned through the plugin repository |

## Design choices

- Use Markdown and Git as the primary storage and audit model.
- Use `wiki/index.md` as a routing catalog before adding vector search.
- Keep source registration deterministic; keep synthesis semantic.
- Make hooks advisory and non-blocking by default.
- Treat contradictions and deletion as review boundaries, not automation targets.

## Read-only MCP boundary

The MCP server exposes bounded typed reads over the same Markdown files. It reuses frontmatter and hashing helpers, keeps evidence immutable, and records result metadata in a local SQLite database outside the wiki. Search exposure, listing, and body reads are separate measures. Semantic synthesis and wiki mutations stay in the skill and existing scripts. The optional MCP runtime adds the official Python SDK and a timeout-capable regex engine; script-only workflows remain dependency-free.
