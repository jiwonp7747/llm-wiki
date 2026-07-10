---
name: llm-wiki
description: Initialize and maintain a persistent, source-backed Markdown wiki using immutable sources, LLM-authored knowledge pages, and append-only operational metadata. Use when Codex needs to create an LLM wiki, ingest a document or user note, update linked concepts and components, answer from the wiki, rebuild its index, record an operation, or lint the knowledge base for schema, link, provenance, contradiction, staleness, and orphan issues.
---

# LLM Wiki

## Overview

Maintain a project-local `knowledge/` directory as a compounding knowledge base. Keep raw evidence immutable, let the LLM own synthesized wiki pages, and use deterministic scripts for bookkeeping and structural checks.

## Locate the wiki

Use `<git-root>/knowledge` when a Git root exists; otherwise use `<cwd>/knowledge`. When the directory exists, read `knowledge/SCHEMA.md` before editing it.

## Select the workflow

- **Initialize**: Run `scripts/init_wiki.py`, inspect the generated schema, then validate.
- **Ingest**: Run `scripts/intake_source.py` first. Read the new source and existing `wiki/index.md`; update the source note and all affected canonical pages; rebuild the index; record the source as ingested; validate.
- **Query**: Route through `wiki/index.md`, verify claims against source notes or immutable originals, answer with page/source references, and save durable synthesis only when requested or clearly useful.
- **Lint**: Run `scripts/validate_wiki.py` and `scripts/build_index.py --check` first, then inspect semantic contradictions, stale claims, duplicate concepts, missing cross-links, and coverage gaps.
- **Log**: Use `scripts/append_log.py` for query, lint, and maintenance events. Intake and source-status scripts log automatically.

Read [references/workflows.md](references/workflows.md) before ingesting or linting. Read [references/schema.md](references/schema.md) when creating or changing page metadata. Read [references/architecture.md](references/architecture.md) when initializing or adapting the directory model. Read [references/hooks.md](references/hooks.md) when changing plugin hooks.

## Preserve trust boundaries

- Never modify files under `knowledge/sources/` after registration. Register a replacement as a new source.
- Treat user notes as attributed, unverified evidence unless another source verifies them.
- Do not treat a question as a factual source; store open questions under `wiki/questions/`.
- Never silently resolve contradictions, delete pages, or archive canonical knowledge. Explain the evidence and request approval.
- Prefer updating one canonical page over copying the same claim into multiple pages.
- Cite source IDs in frontmatter and keep claim-level provenance in page bodies when practical.
- Keep `system/manifest.jsonl` and `system/log.md` append-only.

## Use deterministic helpers

Run scripts with the current Python 3 interpreter; they use only the standard library.

```bash
python3 scripts/init_wiki.py --root knowledge
python3 scripts/intake_source.py path/to/document.pdf --root knowledge
python3 scripts/intake_source.py --text "User-provided note" --kind user-note --root knowledge
python3 scripts/record_source_status.py SRC_ID ingested --root knowledge
python3 scripts/build_index.py --root knowledge
python3 scripts/validate_wiki.py --root knowledge
python3 scripts/append_log.py query "Compared two designs" --root knowledge
```

Resolve script paths relative to this `SKILL.md`, not the user's working directory. Do not reimplement their deterministic behavior in ad hoc shell commands.

## Finish each mutation

After any wiki mutation:

1. Rebuild `wiki/index.md`.
2. Update the relevant source status when an ingest completed.
3. Append an operation log entry.
4. Run structural validation.
5. Summarize changed pages, sources, unresolved contradictions, and validation results.
