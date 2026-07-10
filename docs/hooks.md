# Codex hooks

The plugin uses the default plugin hook location at `plugins/llm-wiki/hooks/hooks.json`; the plugin manifest does not need to name it.

## SessionStart

The command receives the Codex hook payload on standard input. It searches the current directory and its parents for `knowledge/SCHEMA.md`. When present, it returns `hookSpecificOutput.additionalContext` with the schema path and the core source immutability rule.

## Stop

The command locates the same wiki and invokes the bundled validator with `--json`. It returns `continue: true` in all cases. Validation problems are surfaced in `systemMessage`, so the hook is advisory and cannot create a continuation loop.

## Trust

Codex requires review when a non-managed hook is installed or changed. Use `/hooks` in a new task to inspect the exact commands. Both commands run local Python files through `PLUGIN_ROOT`, make no network calls, and do not modify the wiki.

## Why not auto-ingest

Hook events are too broad for deciding whether a prompt, file, or tool result is durable knowledge. Automatic ingestion would mix low-value chat with evidence and could silently change canonical pages. Ingest remains an explicit skill workflow.
