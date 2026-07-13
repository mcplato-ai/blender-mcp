from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ReleaseContractTests(unittest.TestCase):
    def test_distribution_and_console_script_names_are_stable(self):
        pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertRegex(pyproject, r'(?m)^name = "blender-mcp-cli"$')
        self.assertRegex(
            pyproject,
            r'(?m)^blender-mcp-cli = "blender_mcp\.cli:main"$',
        )
        self.assertNotRegex(pyproject, r'(?m)^blender-mcp = ')
        self.assertRegex(pyproject, r'(?m)^dependencies = \[\]$')
        self.assertIn("legacy-mcp = [", pyproject)

    def test_publish_workflow_uses_trusted_publishing(self):
        workflow = (PROJECT_ROOT / ".github/workflows/publish.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("release:", workflow)
        self.assertIn("github.event_name == 'release'", workflow)
        self.assertIn("environment:\n      name: pypi", workflow)
        self.assertIn("id-token: write", workflow)
        self.assertIn("pypa/gh-action-pypi-publish@release/v1", workflow)
        self.assertIn("dist/blender_mcp_cli-*.whl", workflow)
        self.assertIn("actions/checkout@v7", workflow)
        self.assertIn("actions/setup-python@v6", workflow)
        self.assertIn("actions/upload-artifact@v7", workflow)
        self.assertIn("actions/download-artifact@v8", workflow)
        self.assertNotIn("actions/checkout@v4", workflow)
        self.assertNotIn("actions/setup-python@v5", workflow)

    def test_skill_and_documentation_use_final_cli_name(self):
        skill = (PROJECT_ROOT / "skills/blender-mcp-cli/SKILL.md").read_text(
            encoding="utf-8"
        )
        metadata = (
            PROJECT_ROOT / "skills/blender-mcp-cli/agents/openai.yaml"
        ).read_text(encoding="utf-8")
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertRegex(skill, r"(?m)^name: blender-mcp-cli$")
        self.assertNotIn("TODO", skill)
        self.assertIn("$blender-mcp-cli", metadata)
        self.assertIn("pipx install blender-mcp-cli", readme)
        self.assertIn("blender-mcp-cli skill path", readme)
        self.assertIn("blender-mcp-cli skill install", readme)
        self.assertIsNone(re.search(r"(?<!-mcp)blender-cli", skill + readme))

    def test_wheel_publishes_the_skill(self):
        pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn('[tool.setuptools.data-files]', pyproject)
        self.assertIn(
            '"share/blender-mcp-cli/skills/blender-mcp-cli"', pyproject
        )
        self.assertIn("skills/blender-mcp-cli/SKILL.md", pyproject)
        self.assertIn("skills/blender-mcp-cli/agents/openai.yaml", pyproject)

    def test_source_distribution_includes_addon_skill_and_tests(self):
        manifest = (PROJECT_ROOT / "MANIFEST.in").read_text(encoding="utf-8")

        self.assertIn("include addon.py", manifest)
        self.assertIn("recursive-include skills/blender-mcp-cli", manifest)
        self.assertIn("recursive-include tests *.py", manifest)


if __name__ == "__main__":
    unittest.main()
