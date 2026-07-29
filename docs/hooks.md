# Hooks

The plugin ships two hook maps over the same Python files. They differ only in the plugin-root environment variable, so a change to one must be mirrored in the other.

| Runtime | File | Variable | Discovery |
|---|---|---|---|
| Codex | `plugins/llm-wiki/hooks/hooks.json` | `${PLUGIN_ROOT}` | default location; the manifest does not name it |
| Claude Code | `plugins/llm-wiki/hooks/claude-hooks.json` | `${CLAUDE_PLUGIN_ROOT}` | named by the `hooks` field of `.claude-plugin/plugin.json` |

Claude Code would otherwise auto-load `hooks/hooks.json`, where `${PLUGIN_ROOT}` is unset. The explicit `hooks` field points it at the correct map.

## SessionStart

The command receives the hook payload on standard input. It searches the current directory and its parents for `knowledge/SCHEMA.md`. When present, it returns `hookSpecificOutput.additionalContext` with the schema path and the core source immutability rule. Both runtimes use the same payload and response shape.

## Stop

The command locates the same wiki and invokes the bundled validator with `--json`. It returns `continue: true` in all cases. Validation problems are surfaced in `systemMessage`, so the hook is advisory and cannot create a continuation loop.

`stop_validate.py` resolves the plugin root from `PLUGIN_ROOT`, then `CLAUDE_PLUGIN_ROOT`, then the script's own location, so it works under either runtime and when run directly.

## Trust

Both runtimes require review when a non-managed hook is installed or changed. Use `/hooks` in a new session to inspect the exact commands. Both commands run local Python files under the plugin root, make no network calls, and do not modify the wiki.

## Why not auto-ingest

Hook events are too broad for deciding whether a prompt, file, or tool result is durable knowledge. Automatic ingestion would mix low-value chat with evidence and could silently change canonical pages. Ingest remains an explicit skill workflow.
