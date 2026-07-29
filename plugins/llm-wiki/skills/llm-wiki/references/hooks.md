# Hook behavior

The plugin bundles two hook maps over the same Python files. They differ only in
the plugin-root environment variable:

- `hooks/hooks.json` — `${PLUGIN_ROOT}`, discovered automatically by Codex.
- `hooks/claude-hooks.json` — `${CLAUDE_PLUGIN_ROOT}`, named by the `hooks` field
  of `.claude-plugin/plugin.json` for Claude Code.

Keep the two files in sync when the hook map changes.

## SessionStart

If an ancestor project contains `knowledge/SCHEMA.md`, the hook adds developer context telling the agent to read the schema, use the `llm-wiki` skill, and preserve immutable sources. It does nothing in projects without an initialized wiki.

## Stop

If a wiki exists, the hook runs `validate_wiki.py --json`. It never edits files and never blocks the turn from ending. Errors or warnings are surfaced as a UI/system message for the next lint pass.

## Trust and safety

Both runtimes require users to review and trust non-managed plugin hooks. Keep commands scoped to files bundled in the plugin through the plugin-root variable. Do not add prompt capture, network calls, automatic commits, deletion, or hidden source ingestion to these hooks.
