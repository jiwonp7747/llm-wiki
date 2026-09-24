# LLM Wiki Schema

This directory is a persistent, source-backed knowledge base maintained by an LLM and reviewed through Git.

## 1. Layers

- `sources/`: immutable captured evidence. Every source has metadata and a SHA-256 digest.
- `wiki/`: current LLM-maintained synthesis, organized as linked Markdown pages.
- `system/`: append-only processing metadata, operation logs, and lint reports.

The plugin and its scripts are execution logic; they are not stored knowledge.

## 2. Source policy

- Register external documents, user notes, code snapshots, and intentionally preserved conversation excerpts.
- Do not register every prompt. Questions belong under `wiki/questions/`.
- A user assertion is `unverified` unless corroborated.
- Never edit a registered original. Register changed bytes as a new source ID.
- `system/manifest.jsonl` records lifecycle events; it is append-only.

## 3. Page types

| Type | Purpose |
|---|---|
| `overview` | Entry point and evolving high-level synthesis |
| `moc` | Navigation and routing page |
| `concept` | Reusable idea or rule |
| `component` | Concrete system, person, module, API, table, tool, or other entity |
| `decision` | Choice, rationale, alternatives, and consequences |
| `guide` | Repeatable procedure |
| `source-note` | One source's summary and extracted claims |
| `question` | Open evidence gap or investigation thread |

## 4. Required frontmatter

```yaml
---
id: stable-page-id
type: concept
status: canonical
sources:
  - src-YYYYMMDD-title-hash
updated: YYYY-MM-DD
description: One-line routing summary
---
```

Allowed statuses are `canonical`, `draft`, `stale`, and `archived`. Navigation pages may use `sources: []`; factual pages should cite registered source IDs.

Pages may add an optional `tags` list of strings for cross-cutting facets. If `tags.json` exists in this directory (`{"tags": {"tag": "definition"}}`), only the tags listed there are valid; duplicates and non-string tags are always rejected. Tags never replace `type`, `status`, or wikilinks.

## 5. Linking and canonical ownership

- Use `[[path/page|Label]]` links.
- Maintain one canonical page per concept or component.
- Update the canonical page instead of duplicating claims.
- Record uncertainty and contradictions explicitly.
- Keep claim-level provenance in the body when a page combines several sources.

## 6. Operations

### Ingest

Register the source, synthesize its source note, update affected canonical pages, rebuild the index, append lifecycle/log events, and validate.

### Query

Route through `wiki/index.md`, verify important claims against source notes or originals, answer with references, and save only durable synthesis.

### Lint

Run deterministic validation first. Then inspect contradictions, staleness, duplication, weak provenance, missing links, coverage gaps, and answerable questions. Store dated reports under `system/lint-reports/`.

## 7. Approval boundaries

Request human approval before resolving disputed claims, merging materially different pages, deleting content, or archiving canonical knowledge. Mechanical index, metadata, and unambiguous link repairs may be automated.

## 8. Definition of done

A wiki mutation is complete when affected pages cite sources, links are updated, `wiki/index.md` is current, lifecycle and operation events are recorded, validation passes, and unresolved uncertainty is reported.
