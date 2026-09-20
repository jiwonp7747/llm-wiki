# LLM Wiki

An installable plugin for building persistent, source-backed Markdown knowledge bases. It installs into both Codex and Claude Code from the same repository.

LLM Wiki turns source material into a maintained, interlinked wiki instead of rediscovering the same knowledge from raw files for every question. The plugin packages a reusable skill, standard-library Python helpers, safe lifecycle hooks, and a Git-backed marketplace entry. A read-only stdio MCP server adds typed wiki navigation and local access accounting.

Both runtimes read `plugins/llm-wiki/` but different manifests, so neither install affects the other:

| | Codex | Claude Code |
|---|---|---|
| marketplace manifest | `.agents/plugins/marketplace.json` | `.claude-plugin/marketplace.json` |
| plugin manifest | `plugins/llm-wiki/.codex-plugin/plugin.json` | `plugins/llm-wiki/.claude-plugin/plugin.json` |
| hook map | `hooks/hooks.json` (`${PLUGIN_ROOT}`) | `hooks/claude-hooks.json` (`${CLAUDE_PLUGIN_ROOT}`) |

The skill, references, scripts, assets, and hook Python are shared verbatim.

[한국어 안내](docs/README.ko.md)

## Core model

| Layer | Purpose | Owner |
|---|---|---|
| `sources/` | Immutable evidence with provenance and SHA-256 | Intake script and user |
| `wiki/` | Current summaries, concepts, components, decisions, guides, and questions | LLM with user direction |
| `system/` | Manifest events, operation log, and lint reports | Deterministic scripts |
| `llm-wiki` skill | Ingest, query, maintenance, and approval workflow | Plugin |

The plugin is separate from the knowledge it manages. Upgrading the plugin never replaces a project's `knowledge/` directory.

## Included

- `llm-wiki` skill with initialize, ingest, query, lint, and logging workflows.
- Python scripts for initialization, source registration, source lifecycle events, index generation, structural validation, and operation logging.
- A project template with `AGENTS.md`, `SCHEMA.md`, wiki folders, and system metadata.
- `SessionStart` context injection when an initialized wiki is present.
- Non-blocking `Stop` validation that reports structural problems without editing files.
- A repo marketplace for installation from GitHub.
- Read-only MCP tools for info, listing, search, text reading, source resolution and usage reports.
- Unit tests and GitHub Actions validation.

## Install in Codex

```bash
codex plugin marketplace add jiwonp7747/llm-wiki
codex plugin add llm-wiki@llm-wiki
```

From a local clone:

```bash
git clone https://github.com/jiwonp7747/llm-wiki.git
cd llm-wiki
codex plugin marketplace add "$PWD"
codex plugin add llm-wiki@llm-wiki
```

Start a new Codex task after installation so the bundled skill and hooks are loaded. Open `/hooks` and review the two plugin hooks before trusting them.

## Install in Claude Code

```bash
claude plugin marketplace add jiwonp7747/llm-wiki
claude plugin install llm-wiki@llm-wiki
```

From a local clone, pass an absolute path or one starting with `./`. A bare `.` is rejected.

```bash
git clone https://github.com/jiwonp7747/llm-wiki.git
claude plugin marketplace add "$PWD/llm-wiki"
claude plugin install llm-wiki@llm-wiki
```

`/plugin` does the same thing in an interactive session. Start a new session afterwards, then confirm with:

```bash
claude plugin details llm-wiki@llm-wiki
```

Validate the manifests before publishing a change:

```bash
claude plugin validate --strict .
claude plugin validate --strict plugins/llm-wiki
```

## Use

Invoke the skill explicitly or describe a matching task. Codex uses `$llm-wiki`; Claude Code uses `/llm-wiki`.

```text
Use $llm-wiki to initialize a knowledge base in this repository.
Use $llm-wiki to ingest architecture.pdf.
Use $llm-wiki to answer how authentication works and cite wiki sources.
Use $llm-wiki to lint the wiki and report contradictions.
```

Initialization creates:

```text
knowledge/
├── AGENTS.md
├── SCHEMA.md
├── sources/
├── wiki/
│   ├── index.md
│   ├── overview.md
│   ├── concepts/
│   ├── components/
│   ├── decisions/
│   ├── guides/
│   ├── questions/
│   └── source-notes/
└── system/
    ├── manifest.jsonl
    ├── log.md
    └── lint-reports/
```

## Python helpers

The skill normally invokes these scripts. During plugin development they can also be run directly:

```bash
SKILL=plugins/llm-wiki/skills/llm-wiki

python3 "$SKILL/scripts/init_wiki.py" --root ./knowledge
python3 "$SKILL/scripts/intake_source.py" ./document.pdf --root ./knowledge
python3 "$SKILL/scripts/intake_source.py" \
  --text "The user says the internal system uses Oracle 11g." \
  --kind user-note --author user --root ./knowledge
python3 "$SKILL/scripts/record_source_status.py" SOURCE_ID ingested --root ./knowledge
python3 "$SKILL/scripts/build_index.py" --root ./knowledge
python3 "$SKILL/scripts/validate_wiki.py" --root ./knowledge
python3 "$SKILL/scripts/append_log.py" query "Compared persistence designs" --root ./knowledge
```

All helpers use the Python standard library. They do not call a model, access the network, commit changes, or delete wiki content.

## Trust and safety

- Registered source bytes are checked against their captured SHA-256.
- User notes are recorded as attributed, unverified evidence.
- Questions are not promoted to factual sources.
- Contradiction resolution, deletion, merges, and archival require human review.
- Hooks are advisory, local, and non-blocking.
- No prompt or transcript content is uploaded.
- Git remains the review and rollback layer.

See [Architecture](docs/architecture.md), [Workflows](docs/workflows.md), [Schema](docs/schema.md), and [Hooks](docs/hooks.md).

## Development

```bash
python3 -m unittest discover -s tests -v
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  plugins/llm-wiki/skills/llm-wiki
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py \
  plugins/llm-wiki
```

## Status

Wiki storage remains local Markdown and Git. The optional MCP server provides consistent read tools across Codex and Claude Code and records MCP usage separately from wiki content. It requires `uv` and Python 3.10+. See [MCP setup, limits and accounting](plugins/llm-wiki/skills/llm-wiki/references/mcp.md). Shell fallback reads are not counted.

## License

MIT

## MCP development checks

```bash
uv sync --frozen --project plugins/llm-wiki
uv run --frozen --project plugins/llm-wiki python -m unittest discover -s tests -v
```

The test suite includes an actual stdio initialize/list/call exchange. For manual use, [examples/mcp_query.py](examples/mcp_query.py) accepts JSON tool calls on stdin and prints MCP results. Pass `[]` to list tools. The existing standard-library-only tests can still run without the MCP environment; MCP tests are explicitly skipped there, so that run alone is not MCP verification.

## Web dashboard

The plugin also serves a read-only HTTP dashboard built with Blueprint.js. It shows
MCP tool counts, last calls, a filterable event timeline, the wiki index, and canonical
pages with source previews. Web browsing does not add MCP usage events.

```bash
uv run --frozen --project plugins/llm-wiki python plugins/llm-wiki/mcp/dashboard.py --root /absolute/path/to/knowledge
```

Open `http://127.0.0.1:8766`. Built assets ship with the plugin; Node.js is only
needed when changing the frontend. See [dashboard operation and API](docs/dashboard.md).
