#!/usr/bin/env python3
"""Build the standalone blender-mcp-cli Codex Skill archive."""

from __future__ import annotations

import argparse
import re
import stat
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_NAME = "blender-mcp-cli"
SKILL_FILES = ("SKILL.md", "LICENSE", "agents/openai.yaml")
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _project_version() -> str:
    try:
        import tomllib
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Python 3.11+ is required when --version is not provided"
        ) from exc

    with (PROJECT_ROOT / "pyproject.toml").open("rb") as file:
        version = tomllib.load(file)["project"]["version"]
    if not isinstance(version, str):
        raise ValueError("project.version must be a string")
    return version


def _validate_version(version: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", version):
        raise ValueError(f"invalid archive version: {version!r}")
    return version


def build_archive(output_dir: Path, version: str) -> Path:
    version = _validate_version(version)
    skill_dir = PROJECT_ROOT / "skills" / SKILL_NAME
    sources = [(relative, skill_dir / relative) for relative in SKILL_FILES]
    missing = [str(path) for _, path in sources if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing Skill files: " + ", ".join(missing))
    for _, source in sources:
        if source.is_symlink() or not source.resolve().is_relative_to(
            skill_dir.resolve()
        ):
            raise ValueError(f"Skill source must be a regular in-tree file: {source}")

    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"{SKILL_NAME}-skill-{version}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as bundle:
        for relative, source in sources:
            info = zipfile.ZipInfo(f"{SKILL_NAME}/{relative}", ZIP_TIMESTAMP)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            bundle.writestr(info, source.read_bytes())
    return archive


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a directly installable blender-mcp-cli Skill ZIP."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("skill-dist"),
        help="archive output directory (default: %(default)s)",
    )
    parser.add_argument(
        "--version",
        help="archive version; defaults to project.version from pyproject.toml",
    )
    args = parser.parse_args(argv)

    try:
        archive = build_archive(args.output_dir, args.version or _project_version())
    except (KeyError, OSError, RuntimeError, ValueError) as exc:
        parser.exit(1, f"error: {exc}\n")
    print(archive.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
