# Architecture

## Goals

LLM Wiki is designed to make synthesized knowledge persistent, reviewable, and cumulative. It separates evidence from interpretation and interpretation from operational bookkeeping.

## Runtime model

```text
source file or note
        │
        ▼
deterministic registration ──► sources/ + manifest event
        │
        ▼
LLM synthesis ───────────────► wiki/source-notes + canonical pages
        │
        ▼
deterministic maintenance ───► index + log + validation report
        │
        ▼
human review ────────────────► accepted Git change
```

## Data planes

### Sources

Sources are captured evidence. Registration creates a stable source ID, copies the original bytes, records provenance, and stores a digest. Changed material becomes a new source rather than mutating old evidence.

### Wiki

The wiki is compiled knowledge. Source notes preserve source-level summaries; canonical pages merge knowledge by concept, component, decision, or procedure. The same fact should have one canonical owner and be linked elsewhere.

### System

System files describe processing, not domain knowledge. The manifest is an append-only source lifecycle event stream. The log is a chronological human-readable operation history. Lint reports are dated observations and can be regenerated.

## Execution planes

The skill contains semantic workflow: what to read, how to decide whether to update or create a page, when to ask for approval, and how to finish a mutation. Python scripts contain deterministic operations that should not be rewritten by the model each time.

Hooks connect the plugin to Codex lifecycle points. They intentionally avoid mutation because lifecycle automation should not silently change knowledge.

## Scale path

Start with `wiki/index.md`, file search, and links. The read-only MCP server supplies typed navigation and access accounting across clients, while preserving Markdown/Git storage and the existing mutation scripts. Add vector search only when retrieval measurements justify it. See the [MCP contract](../plugins/llm-wiki/skills/llm-wiki/references/mcp.md) for bounds and accounting limits.
