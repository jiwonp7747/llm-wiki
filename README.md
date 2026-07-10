# LLM Wiki for Codex

An installable Codex plugin for building persistent, source-backed Markdown knowledge bases.

LLM Wiki turns source material into a maintained, interlinked wiki instead of rediscovering the same knowledge from raw files for every question. The plugin packages a reusable Codex skill, standard-library Python helpers, safe lifecycle hooks, and a Git-backed marketplace entry. MCP is intentionally out of scope for the first release.

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
- Unit tests and GitHub Actions validation.

## Install from GitHub

After this repository is published:

```bash
codex plugin marketplace add jiwonp7747/llm-wiki
codex plugin add llm-wiki@llm-wiki
```

Start a new Codex task after installation so the bundled skill and hooks are loaded. Open `/hooks` and review the two plugin hooks before trusting them.

## Install from a local clone

```bash
git clone https://github.com/jiwonp7747/llm-wiki.git
cd llm-wiki
codex plugin marketplace add "$PWD"
codex plugin add llm-wiki@llm-wiki
```

## Use

Invoke the skill explicitly or describe a matching task:

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

Version `0.1.0` is a file-based local-first implementation. Search uses the generated index and normal repository tools. An MCP server should be considered only after real usage shows a need for typed cross-client tools or remote/shared storage.

## License

MIT
