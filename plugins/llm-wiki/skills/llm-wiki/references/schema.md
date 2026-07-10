# Schema reference

## Source registration

Each source lives at `sources/<source-id>/` with:

- `original/<filename>`: immutable captured bytes.
- `metadata.json`: title, kind, author, verification state, timestamps, path, and SHA-256.
- a `source_registered` event in `system/manifest.jsonl`.
- a corresponding draft page at `wiki/source-notes/<source-id>.md`.

Valid initial source kinds are `external-document`, `user-note`, `code-snapshot`, `conversation-excerpt`, and `other`. A user note is attributed evidence, not verified truth. A question belongs under `wiki/questions/`, not in the source registry unless a conversation excerpt itself is intentionally preserved.

## Wiki frontmatter

Every Markdown page under `wiki/` must contain:

```yaml
---
id: stable-page-id
type: concept | component | decision | guide | source-note | question | moc | overview
status: canonical | draft | stale | archived
sources:
  - src-20260710-example-deadbeef
updated: 2026-07-10
description: One-line routing summary
---
```

- Keep `id` stable when renaming a file.
- Use an empty list (`sources: []`) only for navigation pages or pages without evidence yet.
- Use `draft` for incomplete synthesis, `stale` for claims that need revalidation, and `archived` for retained history.
- Keep one canonical page per concept or component; link rather than duplicate claims.

## Page bodies

Prefer this order when applicable:

1. concise current summary;
2. supported claims with source IDs or links;
3. relationships to other pages;
4. contradictions or uncertainty;
5. open questions.

Use Obsidian-style `[[path/page|Label]]` links. `build_index.py` catalogs every page; `validate_wiki.py` checks metadata, source IDs, links, duplicate IDs, and source hashes.
