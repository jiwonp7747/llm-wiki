from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "plugins" / "llm-wiki"
SCRIPTS = PLUGIN / "skills" / "llm-wiki" / "scripts"
HOOKS = PLUGIN / "hooks"


class WikiScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)
        self.root = self.project / "knowledge"

    def run_script(self, name: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPTS / name), *args],
            text=True,
            capture_output=True,
            check=check,
        )

    def initialize(self) -> None:
        self.run_script("init_wiki.py", "--root", str(self.root))

    def test_initialize_build_and_validate(self) -> None:
        self.initialize()
        self.assertTrue((self.root / "SCHEMA.md").is_file())
        schema = self.root / "SCHEMA.md"
        schema.write_text(schema.read_text(encoding="utf-8") + "\nLocal rule.\n", encoding="utf-8")
        self.initialize()
        self.assertTrue(schema.read_text(encoding="utf-8").endswith("Local rule.\n"))
        self.run_script("build_index.py", "--root", str(self.root), "--check")
        completed = self.run_script("validate_wiki.py", "--root", str(self.root), "--json")
        result = json.loads(completed.stdout)
        self.assertTrue(result["valid"])
        self.assertEqual(result["page_count"], 2)
        self.assertEqual(result["source_count"], 0)

    def test_intake_is_deduplicated_and_hash_protected(self) -> None:
        self.initialize()
        source = self.project / "architecture.txt"
        source.write_text("The project uses an append-only manifest.\n", encoding="utf-8")

        registered = self.run_script(
            "intake_source.py",
            str(source),
            "--root",
            str(self.root),
            "--title",
            "Architecture note",
        )
        registration = json.loads(registered.stdout)
        source_id = registration["source_id"]

        duplicate = self.run_script(
            "intake_source.py",
            str(source),
            "--root",
            str(self.root),
            "--title",
            "Architecture note",
        )
        self.assertEqual(json.loads(duplicate.stdout)["status"], "duplicate")

        self.run_script("record_source_status.py", source_id, "ingested", "--root", str(self.root))
        self.run_script("build_index.py", "--root", str(self.root))
        self.run_script("validate_wiki.py", "--root", str(self.root))

        metadata = json.loads(
            (self.root / "sources" / source_id / "metadata.json").read_text(encoding="utf-8")
        )
        original = self.root / metadata["stored_path"]
        original.write_text("mutated\n", encoding="utf-8")
        failed = self.run_script(
            "validate_wiki.py", "--root", str(self.root), "--json", check=False
        )
        self.assertEqual(failed.returncode, 1)
        result = json.loads(failed.stdout)
        self.assertTrue(any("hash changed" in item for item in result["errors"]))

    def write_page(self, relative: str, frontmatter: str) -> Path:
        page = self.root / "wiki" / relative
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(
            f"---\nid: {Path(relative).stem}\ntype: concept\nstatus: canonical\nsources: []\n"
            f"{frontmatter}updated: 2026-01-01\ndescription: Tag fixture\n---\n# {Path(relative).stem}\n"
            "Body. [[overview|Overview]]\n",
            encoding="utf-8",
        )
        return page

    def validate(self) -> dict:
        completed = self.run_script("validate_wiki.py", "--root", str(self.root), "--json", check=False)
        return json.loads(completed.stdout)

    def test_tags_are_optional_and_well_formed_without_a_dictionary(self) -> None:
        self.initialize()
        self.write_page("concepts/untagged.md", "")
        self.write_page("concepts/block.md", "tags:\n  - infra/k8s\n  - 활동/운영\n")
        self.write_page("concepts/flow.md", "tags: [infra/k8s, 활동/운영]\n")
        self.write_page("concepts/empty.md", "tags: []\n")
        result = self.validate()
        self.assertTrue(result["valid"], result["errors"])
        self.assertFalse(result["tag_policy"])
        self.assertEqual(result["tagged_page_count"], 2)

        self.write_page("concepts/duplicate.md", "tags:\n  - infra/k8s\n  - infra/k8s\n")
        self.write_page("concepts/scalar.md", "tags: infra/k8s\n")
        self.write_page("concepts/blank.md", "tags:\n  - \"\"\n")
        result = self.validate()
        self.assertFalse(result["valid"])
        errors = "\n".join(result["errors"])
        self.assertIn("duplicate.md: duplicate tag 'infra/k8s'", errors)
        self.assertIn("scalar.md: tags must be a YAML list of strings", errors)
        self.assertIn("blank.md: tags must contain non-empty strings", errors)
        self.assertNotIn("block.md", errors)

    def test_flow_tags_reject_unsupported_yaml_without_silent_coercion(self) -> None:
        self.initialize()
        invalid = [
            "[영역/학습, '']", "[영역/학습, true]", "[영역/학습, 123]",
            "['a,b', c]", "[영역/학습,, 주제/인프라]",
            '["영역/학습", ""]', '["영역/학습", true]',
            '["영역/학습", 123]', '["영역/학습", null]',
        ]
        for value in invalid:
            with self.subTest(value=value):
                self.write_page("concepts/flow.md", f"tags: {value}\n")
                result = self.validate()
                self.assertFalse(result["valid"])
                self.assertTrue(any("tags" in error for error in result["errors"]))

        # JSON quoting preserves punctuation instead of splitting a tag at its comma.
        (self.root / "tags.json").write_text(
            json.dumps({"tags": {"a,b": "Comma tag", "c": "Plain tag"}}),
            encoding="utf-8",
        )
        self.write_page("concepts/flow.md", 'tags: ["a,b", "c"]\n')
        self.assertTrue(self.validate()["valid"])

    def test_tags_json_restricts_allowed_tags(self) -> None:
        self.initialize()
        self.write_page("concepts/known.md", "tags:\n  - 영역/학습\n")
        self.write_page("concepts/unknown.md", "tags:\n  - 영역/학습\n  - 영역/미정\n")
        (self.root / "tags.json").write_text(
            json.dumps({"tags": {"영역/학습": "학습 목적의 지식", "영역/생활": ""}}, ensure_ascii=False),
            encoding="utf-8",
        )
        result = self.validate()
        self.assertTrue(result["tag_policy"])
        self.assertFalse(result["valid"])
        self.assertEqual(
            [item for item in result["errors"] if "tag" in item],
            ["wiki/concepts/unknown.md: unknown tag '영역/미정' (not in tags.json)"],
        )
        self.assertEqual(result["tagged_page_count"], 1)

        (self.root / "tags.json").write_text('{"tags": ["영역/학습"]}', encoding="utf-8")
        result = self.validate()
        self.assertTrue(any("tags.json: expected an object" in item for item in result["errors"]))
        (self.root / "tags.json").write_text("{not json", encoding="utf-8")
        self.assertTrue(any("tags.json: invalid JSON" in item for item in self.validate()["errors"]))

    def test_append_log(self) -> None:
        self.initialize()
        self.run_script(
            "append_log.py",
            "query",
            "Compared two components",
            "--detail",
            "saved: wiki/components/example.md",
            "--root",
            str(self.root),
        )
        log = (self.root / "system" / "log.md").read_text(encoding="utf-8")
        self.assertIn("query | Compared two components", log)
        self.assertIn("saved: wiki/components/example.md", log)

    def test_hooks_are_contextual_and_non_blocking(self) -> None:
        self.initialize()
        environment = {**os.environ, "PLUGIN_ROOT": str(PLUGIN)}
        payload = json.dumps({"cwd": str(self.project), "hook_event_name": "SessionStart"})
        started = subprocess.run(
            [sys.executable, str(HOOKS / "session_start.py")],
            input=payload,
            text=True,
            capture_output=True,
            check=True,
            env=environment,
        )
        start_result = json.loads(started.stdout)
        context = start_result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("SCHEMA.md", context)

        stopped = subprocess.run(
            [sys.executable, str(HOOKS / "stop_validate.py")],
            input=json.dumps({"cwd": str(self.project), "hook_event_name": "Stop"}),
            text=True,
            capture_output=True,
            check=True,
            env=environment,
        )
        stop_result = json.loads(stopped.stdout)
        self.assertTrue(stop_result["continue"])
        self.assertNotIn("systemMessage", stop_result)


if __name__ == "__main__":
    unittest.main()
