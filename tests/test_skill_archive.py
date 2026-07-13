from __future__ import annotations

import importlib.util
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts/build_skill_archive.py"
SKILL_ROOT = PROJECT_ROOT / "skills/blender-mcp-cli"
ARCHIVE_NAME = "blender-mcp-cli-skill-9.8.7.zip"
ARCHIVE_FILES = (
    "blender-mcp-cli/SKILL.md",
    "blender-mcp-cli/LICENSE",
    "blender-mcp-cli/agents/openai.yaml",
)


def build_archive(output_dir: Path) -> Path:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--output-dir",
            str(output_dir),
            "--version",
            "9.8.7",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    archive = Path(completed.stdout.strip())
    if archive.name != ARCHIVE_NAME:
        raise AssertionError(f"unexpected archive name: {archive}")
    return archive


class SkillArchiveTests(unittest.TestCase):
    def test_archive_contains_only_the_installable_skill(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = build_archive(Path(directory))

            with zipfile.ZipFile(archive) as bundle:
                self.assertTupleEqual(tuple(bundle.namelist()), ARCHIVE_FILES)
                for relative_name in ("SKILL.md", "LICENSE", "agents/openai.yaml"):
                    self.assertEqual(
                        bundle.read(f"blender-mcp-cli/{relative_name}"),
                        (SKILL_ROOT / relative_name).read_bytes(),
                    )
                for info in bundle.infolist():
                    self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                    self.assertEqual(
                        stat.S_IMODE(info.external_attr >> 16), 0o644
                    )

    def test_archive_extracts_directly_into_a_skills_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = build_archive(root / "dist")
            skills_dir = root / "codex/skills"

            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(skills_dir)

            installed = skills_dir / "blender-mcp-cli"
            self.assertTrue((installed / "SKILL.md").is_file())
            self.assertTrue((installed / "LICENSE").is_file())
            self.assertTrue((installed / "agents/openai.yaml").is_file())

    def test_archive_is_reproducible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = build_archive(root / "first")
            second = build_archive(root / "second")

            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_archive_rejects_symlinked_skill_sources(self):
        spec = importlib.util.spec_from_file_location("skill_archive_builder", SCRIPT)
        if spec is None or spec.loader is None:
            self.fail("could not load Skill archive builder")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "skills/blender-mcp-cli"
            (skill / "agents").mkdir(parents=True)
            outside = root / "outside.md"
            outside.write_text("outside", encoding="utf-8")
            try:
                (skill / "SKILL.md").symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symbolic links are not available: {exc}")
            (skill / "LICENSE").write_text("license", encoding="utf-8")
            (skill / "agents/openai.yaml").write_text(
                "interface: {}", encoding="utf-8"
            )

            with mock.patch.object(module, "PROJECT_ROOT", root):
                with self.assertRaisesRegex(ValueError, "regular in-tree file"):
                    module.build_archive(root / "dist", "1.0.0")


if __name__ == "__main__":
    unittest.main()
