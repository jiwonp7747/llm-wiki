# Schema

## Source ID

Source IDs use this form:

```text
src-YYYYMMDD-title-slug-hash8
```

The hash suffix makes same-title sources distinct and supports duplicate detection.

## Manifest events

`system/manifest.jsonl` is append-only. Current event types:

- `wiki_initialized`
- `source_registered`
- `source_status_changed`

Consumers should fold events by `source_id` rather than rewriting old records.

## Page identity

Every page has a stable `id` independent of its filename. The filename and path optimize navigation; the ID supports validation and future migrations.

Required fields are `id`, `type`, `status`, `sources`, and `updated`. `description` is strongly recommended because `build_index.py` uses it as routing text.

## Tags

`tags` is an optional list of strings. The MCP `wiki_list` tool filters on one exact tag per call (combined with `page_type` and `path_prefix` by AND). A wiki can restrict tags to a dictionary in `knowledge/tags.json` (`{"tags": {"name": "definition"}}`); `validate_wiki.py` then rejects unknown tags, and always rejects duplicate, empty, or non-list values. Wikis without `tags.json` accept any well-formed tag.

See the generated `knowledge/SCHEMA.md` and the skill's `references/schema.md` for the complete page-type and status rules.
