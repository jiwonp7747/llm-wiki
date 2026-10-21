# Hook behavior

The plugin bundles two hook maps over the same Python files. They differ only in
the plugin-root environment variable:

- `hooks/hooks.json` — `${PLUGIN_ROOT}`, discovered automatically by Codex.
- `hooks/claude-hooks.json` — `${CLAUDE_PLUGIN_ROOT}`, named by the `hooks` field
  of `.claude-plugin/plugin.json` for Claude Code.

Both maps register exactly three handlers: `SessionStart` context, `Stop`
validation, and Wiki-only `PostToolUse` correlation. No prompt, completion,
subagent, interruption, or session-end usage observations are registered.

## SessionStart

If an ancestor project contains `knowledge/SCHEMA.md`, the hook adds developer context telling the agent to read the schema, use the `llm-wiki` skill, and preserve immutable sources. It does nothing in projects without an initialized wiki.

## Stop

If a wiki exists, the hook runs `validate_wiki.py --json`. It never edits files and never blocks the turn from ending. Errors or warnings are surfaced as a UI/system message for the next lint pass.

## Optional local usage observation

`hooks/wiki_usage.py --client codex` or `--client claude` observes Wiki tool-call
metadata in the same local SQLite database used by the configured wiki's MCP
server. It is separate from the existing startup context and stop validation.
An unconfigured usage hook exits successfully without recording anything.

Set an absolute initialized wiki root using the first available source:

1. The hook command's `--root /absolute/path/to/knowledge` argument.
2. `LLM_WIKI_ROOT` in the hook process environment.
3. `$XDG_CONFIG_HOME/llm-wiki/usage.json`, or `~/.config/llm-wiki/usage.json` when
   `XDG_CONFIG_HOME` is unset:

   ```json
   {"root":"/absolute/path/to/knowledge"}
   ```

The usage hook does not discover a wiki from the current directory. This keeps
personal-wiki observations attached to the configured root when work runs in a
different project. Configure the MCP server to the same root. The per-user file
does not change the MCP server's own root discovery. The audit database remains
outside the wiki and is bound to exactly one root. Relative root paths are
rejected after expanding `~`.

If the MCP server uses a custom database, pass the same `--audit-db` path to the
hook or provide `LLM_WIKI_AUDIT_DB` in its environment. The CLI argument takes
precedence. Otherwise the hook uses the default root-specific audit database
described in [MCP accounting](mcp.md#accounting).

The sole usage observation runs on `PostToolUse`, asynchronously with a
three-second hook timeout. SQLite lock waits are bounded to 0.1 seconds.
Observation failures never block a prompt, tool, or turn.

Only allowlisted identifiers, timestamps, enum labels, and runtime correlation
states are stored. The script reads at most 1 MiB of the event on stdin and never
opens `transcript_path`. Raw prompts, queries, tool bodies, answer prose, and
transcript contents are not retained. The minimal map does not collect zero-call
turns, turn completion, answer citations, or subagent lifecycle relationships.
It therefore cannot measure the fraction of all questions using the wiki.
Historical observations remain stored; they do not establish current lifecycle
coverage. The observer retains compatibility with older event payloads without
registering those events in the bundled maps.

`PostToolUse` links only the six Wiki MCP tools. It validates the returned
`audit.root`, `audit.event_id`, and `audit.session_id` against the configured root
and the recorded event's tool. It stores `client`, chat/turn IDs, and
`tool_use_id` on that existing event. Repeated hook delivery is deduplicated by
client/chat/tool-use identity; it never creates another MCP usage count.
Conflicting or uncorrelated events remain distinguishable instead of being
attached by task name or approximate timing.

Declare `usage_purpose`, `execution_origin`, and `agent_role` on the MCP call as
described in [MCP accounting](mcp.md#accounting). An explicit MCP label remains
authoritative. Missing purpose stays `unknown`; prompt text and task-name
patterns are not classifiers. Parent-context correlation from older observations
is retained for compatibility, but the minimal map supplies no new parent
lifecycle observations. Claude's
`prompt_id` serves as the turn ID only when a `turn_id` is absent.

## Trust and safety

Keep commands scoped to files bundled in the plugin through the plugin-root
variable. Review the hook commands and use the runtime's normal trust controls.
Installing or enabling a Codex plugin does not trust new or changed hook
definitions. In a new Codex session, open `/hooks` to review and trust them;
until then, Codex skips them. Do not edit trust hashes or installed caches by
hand. [Official OpenAI Hooks documentation](https://learn.chatgpt.com/docs/hooks#review-and-trust-hooks)

Update plugins through `codex plugin add llm-wiki@llm-wiki` or
`claude plugin update llm-wiki@llm-wiki` after updating their marketplace source.
Start a fresh session and confirm the loaded definitions. Claude's hook
execution and workspace trust follow its own runtime rules.
[Claude Hooks reference](https://code.claude.com/docs/en/hooks#workspace-trust)

Validate direct purpose recording and runtime observation separately. A fresh
MCP response must show the expected root and labels; an actual tool call must
then create a correlated hook observation without increasing its MCP count
twice. Include a real nested MCP call for Codex code mode and a real Claude
session before claiming those paths work. Passing synthetic hook payload tests
or installing the updated plugin alone does not establish runtime delivery.
