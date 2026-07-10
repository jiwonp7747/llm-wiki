# Workflows

## Initialize

The initialization script copies the bundled template without overwriting existing files. It records an initialization log entry and creates an append-only manifest stream.

After initialization, adapt `knowledge/SCHEMA.md` to the domain before the first ingest. Keep the three-layer boundary intact.

## Ingest

Registration and synthesis are deliberately separate.

1. `intake_source.py` captures bytes or text, calculates SHA-256, prevents duplicate registration, writes `metadata.json`, appends a manifest event, and creates a draft source note.
2. Codex reads the source, source note, index, and related canonical pages.
3. Codex completes the source note and updates the smallest sufficient set of canonical pages.
4. `build_index.py` refreshes the routing catalog.
5. `record_source_status.py` appends `ingested` or `reviewed` status.
6. `validate_wiki.py` verifies structural integrity.

Registration does not imply that claims are true. A source can be inaccurate, disputed, or superseded.

## Query

Queries route through `wiki/index.md`. The LLM reads canonical pages first and checks source notes or originals for high-stakes or disputed claims. Answers should reference page paths and source IDs. Durable comparisons or conclusions can be written back; routine chat should not become wiki noise.

## Lint

Structural lint checks required files, frontmatter, page IDs, status values, source IDs, wiki links, and immutable source hashes. Index freshness is checked separately with `build_index.py --check`.

Semantic lint is performed by the LLM and covers contradictions, staleness, duplicates, provenance quality, missing pages, and knowledge gaps. Semantic changes that alter canonical meaning require review.

## Failure recovery

- Duplicate source: reuse the reported source ID.
- Mutated source: restore the captured bytes or register the new version separately.
- Stale index: rebuild it; do not edit the generated list by hand.
- Broken link: correct the target or explicitly preserve it as an open coverage gap.
- Contradiction: keep both claims and their provenance until a human approves resolution.
