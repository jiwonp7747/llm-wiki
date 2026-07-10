# Contributing

Contributions should preserve the boundary between deterministic scripts and semantic LLM judgment.

1. Create a focused branch.
2. Update scripts, skill instructions, templates, and human documentation together when their contract changes.
3. Add or update `unittest` coverage.
4. Run the test suite and both Codex validators.
5. Avoid new runtime dependencies unless they materially improve a measured workflow.
6. Keep hooks local, reviewable, and non-destructive.

Do not commit generated user knowledge bases, private source documents, credentials, or transcripts.
