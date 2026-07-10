# Repository Instructions

## Purpose

This repository distributes the `llm-wiki` Codex plugin. Plugin code and templates live under `plugins/llm-wiki/`; generated user knowledge bases must never be committed here.

## Design boundaries

- Keep runtime scripts dependency-free unless a measured requirement justifies a dependency.
- Keep semantic judgment in `SKILL.md` and deterministic bookkeeping in Python scripts.
- Keep bundled hooks local, transparent, non-destructive, and non-blocking.
- Do not add MCP configuration until a concrete cross-client or remote-tool requirement exists.
- Never make plugin upgrades overwrite an initialized `knowledge/` directory.

## Required verification

Run these after changing the plugin:

```bash
python3 -m unittest discover -s tests -v
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py plugins/llm-wiki/skills/llm-wiki
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py plugins/llm-wiki
git diff --check
```

Update the skill references, human documentation, templates, and tests together when their shared contract changes.
