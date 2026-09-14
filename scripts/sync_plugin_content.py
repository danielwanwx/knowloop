#!/usr/bin/env python3
"""Synchronize canonical skills and curriculum into the installable plugin."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "crack-system-interview-skill"

SKILLS = ("coach", "interview-coach", "card", "senior-sde-interview-script", "system-design-study-coach")


def sync_targets(root: Path = ROOT, plugin: Path = PLUGIN) -> list[tuple[Path, Path]]:
    targets = [
        (root / name, plugin / "skills" / name)
        for name in SKILLS
    ]
    targets.extend(
        (root / name, plugin / name)
        for name in ("curriculum", "cases", "sources")
    )
    return targets


def sync_all(root: Path = ROOT, plugin: Path = PLUGIN) -> None:
    """Stage every managed tree, then swap all targets with rollback support."""

    targets = sync_targets(root, plugin)
    for source, destination in targets:
        if not source.is_dir() or source.is_symlink():
            raise RuntimeError(f"sync source is missing or unsafe: {source}")
        if destination.is_symlink():
            raise RuntimeError(f"refusing to replace plugin symlink: {destination}")

    plugin.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".crack-system-sync-", dir=plugin.parent
    ) as temporary_name:
        temporary = Path(temporary_name)
        stage_root = temporary / "stage"
        backup_root = temporary / "backup"
        failed_root = temporary / "failed"
        prepared: list[tuple[Path, Path, Path]] = []
        for index, (source, destination) in enumerate(targets):
            staged = stage_root / str(index)
            shutil.copytree(source, staged, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            if not any(path.is_file() for path in staged.rglob("*")):
                raise RuntimeError(f"staged plugin tree is empty: {source}")
            prepared.append((staged, destination, backup_root / str(index)))

        swapped: list[tuple[Path, Path, bool, int]] = []
        try:
            for index, (staged, destination, backup) in enumerate(prepared):
                destination.parent.mkdir(parents=True, exist_ok=True)
                existed = destination.exists()
                if existed:
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(destination, backup)
                try:
                    os.replace(staged, destination)
                except Exception:
                    if existed:
                        os.replace(backup, destination)
                    raise
                swapped.append((destination, backup, existed, index))
        except Exception:
            for destination, backup, existed, index in reversed(swapped):
                displaced = failed_root / str(index)
                displaced.parent.mkdir(parents=True, exist_ok=True)
                os.replace(destination, displaced)
                if existed:
                    os.replace(backup, destination)
            raise


def main() -> None:
    sync_all()
    print("Synced canonical skills, cases, sources, and curriculum into plugin package.")


if __name__ == "__main__":
    main()
