#!/usr/bin/env python3
"""Rebuild the catalog-only public pages from canonical course inputs."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from curriculum_model import ROOT, CurriculumError, CurriculumModel, validate_model


PUBLIC_FILES = frozenset({
    "docs/.nojekyll",
    "docs/index.html",
    "docs/courses.json",
    "docs/dashboard-demo.html",
})
GENERATED_INDEX = Path("docs/.curriculum-generated-files.json")


def publication_config(root: Path | None = None) -> dict[str, Any]:
    path = (root or ROOT) / "curriculum" / "publication.json"
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CurriculumError(f"Cannot read publication contract: {exc}") from exc
    if not isinstance(config, dict) or config.get("schema_version") != 1 or config.get("mode") != "catalog-only":
        raise CurriculumError("Invalid catalog-only publication contract")
    if config.get("coach_catalog") != "courses.json":
        raise CurriculumError("Catalog-only publication must name courses.json")
    return config


def build(model: CurriculumModel, live_report: dict[str, Any] | None = None) -> None:
    del live_report
    errors = validate_model(model)
    if errors:
        raise CurriculumError("curriculum validation failed: " + "; ".join(errors))
    publication_config()
    from build_coach_pages import outputs
    for relative, body in outputs().items():
        (ROOT / "docs" / relative).write_text(body, encoding="utf-8")


def _copy_atomically(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".catalog-", dir=destination.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def _publish_staged(stage_root: Path, target_root: Path, generated: set[Path]) -> None:
    """Atomically copy catalog outputs and prune only retired daily pages."""
    with tempfile.TemporaryDirectory(prefix="catalog-backup-") as backup_name:
        backup_root = Path(backup_name)
        existed: dict[Path, bool] = {}
        for relative in generated:
            destination = target_root / relative
            existed[relative] = destination.exists()
            if destination.exists():
                backup = backup_root / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(destination, backup)
        try:
            for relative in sorted(generated):
                _copy_atomically(stage_root / relative, target_root / relative)
        except Exception:
            for relative, was_present in existed.items():
                destination = target_root / relative
                backup = backup_root / relative
                if was_present:
                    _copy_atomically(backup, destination)
                elif destination.exists():
                    destination.unlink()
            raise
    for page in (target_root / "docs").glob("week*/day-*.html"):
        page.unlink()


def verify_live(workers: int) -> dict[str, Any]:
    command = [sys.executable, str(ROOT / "scripts" / "verify_sources.py"), "--workers", str(workers)]
    try:
        result = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise CurriculumError("live source verification failed" + (f":\n{detail}" if detail else "")) from exc
    try:
        return json.loads(result.stdout.splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        raise CurriculumError("source verifier did not return a JSON report") from exc


def parse_args() -> argparse.Namespace:
    return argparse.ArgumentParser(description=__doc__).parse_args()


def main() -> int:
    parse_args()
    from curriculum_model import load_model
    try:
        build(load_model(ROOT))
    except CurriculumError as exc:
        print(f"build blocked: {exc}")
        return 1
    print("Rebuilt catalog-only public pages from canonical inputs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
