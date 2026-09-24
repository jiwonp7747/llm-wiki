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

### Optional tags

Pages may add `tags`, a YAML list of strings (block list or `[a, b]` flow list; a bare scalar is rejected):

```yaml
tags:
  - 영역/학습
  - 주제/인프라
```

- Flow lists accept JSON arrays or simple unquoted tokens beginning with a letter or underscore, followed by letters, digits, underscores, slashes, dots, or hyphens. YAML-only quoting and mixed scalar forms are rejected rather than coerced; use a block list or JSON string array instead. Empty and non-string JSON entries are validated without being dropped.
- Tags are cross-cutting facets for `wiki_list --tag` filtering and lint counts. They do not replace `type`, `status`, or wikilinks to entities, and they do not assert that a claim was verified.
- A wiki may pin its allowed tags in `<root>/tags.json`: `{"tags": {"tag": "one-line definition", ...}}`. When that file exists, `validate_wiki.py` reports any tag outside it as an error; without it, any well-formed tag passes. Duplicate, empty, or non-string tags are always errors.
- Keep tag definitions and application rules for humans in a wiki guide page, and keep `tags.json` as the machine-readable source that the validator enforces.

## Page bodies

Prefer this order when applicable:

1. concise current summary;
2. supported claims with source IDs or links;
3. relationships to other pages;
4. contradictions or uncertainty;
5. open questions.

Use Obsidian-style `[[path/page|Label]]` links. `build_index.py` catalogs every page; `validate_wiki.py` checks metadata, source IDs, tags, links, duplicate IDs, and source hashes.
