# Workflow reference

## Initialize

1. Run `init_wiki.py` against the target project.
2. Read the generated `SCHEMA.md` and adapt only domain-specific page types or conventions.
3. Run `build_index.py` and `validate_wiki.py`.
4. Commit the empty structure before ingesting sources when practical.

## Ingest

1. Register the source with `intake_source.py`. Registration copies bytes, writes metadata, records a manifest event, and creates an unsynthesized source-note page.
2. Read `wiki/index.md`, the new source, and the smallest relevant set of existing pages.
3. Decide whether each claim updates an existing canonical page, creates a distinct page, or remains only in the source note.
4. Preserve contradictions explicitly. Ask before replacing disputed canonical claims.
5. Finish the source note and update affected concept, component, decision, guide, overview, and question pages.
6. Rebuild the index.
7. Record the source as `ingested`; use `reviewed` only after human review.
8. Validate and report changed pages plus unresolved gaps.

## Query

1. Read `wiki/index.md` first.
2. Read relevant canonical pages, then their source notes or originals when verification matters.
3. Answer with wiki page and source references.
4. Save durable new synthesis only when requested or when it materially improves the wiki; log saved queries.
5. If evidence is missing, create or update a question page instead of inventing certainty.

## Lint

Run deterministic checks before semantic review:

```bash
python3 validate_wiki.py --root knowledge
python3 build_index.py --root knowledge --check
```

Then inspect:

- contradictions between canonical pages or sources;
- stale claims relative to newer sources or code;
- near-duplicate concepts;
- weak or missing provenance;
- pages with poor cross-link coverage;
- important referenced concepts without pages;
- questions that now have sufficient evidence.

Write a dated report under `system/lint-reports/`. Fix mechanical issues when unambiguous. Ask before semantic replacements, merges, deletions, or archival.
