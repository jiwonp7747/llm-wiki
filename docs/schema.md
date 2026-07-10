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

See the generated `knowledge/SCHEMA.md` and the skill's `references/schema.md` for the complete page-type and status rules.
