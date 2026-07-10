# Hook behavior

The plugin bundles `hooks/hooks.json`, discovered automatically when the plugin is enabled.

## SessionStart

If an ancestor project contains `knowledge/SCHEMA.md`, the hook adds developer context telling Codex to read the schema, use `$llm-wiki`, and preserve immutable sources. It does nothing in projects without an initialized wiki.

## Stop

If a wiki exists, the hook runs `validate_wiki.py --json`. It never edits files and never forces Codex to continue. Errors or warnings are surfaced as a UI/system message for the next lint pass.

## Trust and safety

Codex requires users to review and trust non-managed plugin hooks. Keep commands scoped to files bundled in the plugin through `PLUGIN_ROOT`. Do not add prompt capture, network calls, automatic commits, deletion, or hidden source ingestion to these hooks.
