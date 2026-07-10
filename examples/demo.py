#!/usr/bin/env python3
"""Create and validate a small LLM Wiki using the plugin's deterministic scripts."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "plugins" / "llm-wiki" / "skills" / "llm-wiki" / "scripts"


def run(script: str, *args: str) -> None:
    command = [sys.executable, str(SCRIPTS / script), *args]
    print("+", " ".join(command))
    subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", default="demo-output")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    root = target / "knowledge"
    target.mkdir(parents=True, exist_ok=True)
    run("init_wiki.py", "--root", str(root))
    run(
        "intake_source.py",
        "--text",
        "The demo project stores durable knowledge as Markdown.",
        "--kind",
        "user-note",
        "--title",
        "Demo project note",
        "--author",
        "demo-user",
        "--root",
        str(root),
    )
    run("build_index.py", "--root", str(root))
    run("validate_wiki.py", "--root", str(root))
    print(f"demo created at {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
