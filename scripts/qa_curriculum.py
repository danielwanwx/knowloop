#!/usr/bin/env python3
"""QA for the catalog-only public boundary and bundled Week/Day inputs."""

from __future__ import annotations

import json
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from build_curriculum import PUBLIC_FILES, publication_config
from curriculum_model import ROOT, load_model, validate_model


DOCS = ROOT / "docs"


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.links: list[str] = []
        self.assets: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(str(values["id"]))
        if tag == "a" and values.get("href"):
            self.links.append(str(values["href"]))
        if tag == "link" and values.get("href"):
            self.assets.append(("stylesheet", str(values["href"])))
        if tag == "script" and values.get("src"):
            self.assets.append(("script", str(values["src"])))


def generated_html_paths() -> list[Path]:
    return [DOCS / "index.html", DOCS / "dashboard-demo.html"]


def validate_pages(model: Any) -> tuple[list[str], dict[str, int]]:
    del model
    errors: list[str] = []
    pages = generated_html_paths()
    for path in pages:
        if not path.exists():
            errors.append(f"missing page: {path}")
            continue
        parser = _PageParser()
        parser.feed(path.read_text(encoding="utf-8"))
        for href in parser.links:
            if href.startswith("#") and href[1:] not in parser.ids:
                errors.append(f"{path}: missing same-page fragment {href[1:]!r}")
        for kind, reference in parser.assets:
            if "://" not in reference and not (path.parent / reference).is_file():
                errors.append(f"{path}: missing local {kind} asset {reference}")
    return errors, {"pages": len(pages)}


def expected_generated_files() -> set[str]:
    return set(PUBLIC_FILES)


def validate_generated_file_index(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return ["generated-file index root must be an object"]
    if payload.get("schema_version") != 1:
        return ["generated-file index schema_version must be 1"]
    files = payload.get("files")
    if not isinstance(files, list):
        return ["generated-file index files must be a list"]
    if any(not isinstance(value, str) for value in files):
        return ["generated-file index contains non-string entries"]
    if any(count > 1 for count in Counter(files).values()):
        return ["generated-file index contains duplicate entries"]
    return [] if set(files) == expected_generated_files() else ["generated-file index drifted from the catalog-only output set"]


def validate_public_files(root: Path = ROOT) -> list[str]:
    actual = {
        str(path.relative_to(root))
        for path in (root / "docs").rglob("*")
        if path.is_file()
    }
    return [
        f"public file outside catalog-only allowlist: {path}"
        for path in sorted(actual - PUBLIC_FILES)
    ] + [
        f"missing catalog-only public file: {path}"
        for path in sorted(PUBLIC_FILES - actual)
    ]


def validate_plugin_sync() -> tuple[list[str], dict[str, int]]:
    errors: list[str] = []
    count = 0
    plugin = ROOT / "plugins" / "crack-system-interview-skill"
    for name in ("curriculum", "cases", "sources"):
        canonical, packaged = ROOT / name, plugin / name
        source_files = sorted(path.relative_to(canonical) for path in canonical.rglob("*") if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")
        target_files = sorted(path.relative_to(packaged) for path in packaged.rglob("*") if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc") if packaged.exists() else []
        if source_files != target_files:
            errors.append(f"plugin {name} file set is out of sync")
            continue
        for relative in source_files:
            count += 1
            if (canonical / relative).read_bytes() != (packaged / relative).read_bytes():
                errors.append(f"plugin {name} differs: {relative}")
    for name in ("coach", "interview-coach", "system-design-study-coach"):
        canonical, packaged = ROOT / name, plugin / "skills" / name
        source_files = sorted(path.relative_to(canonical) for path in canonical.rglob("*") if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")
        target_files = sorted(path.relative_to(packaged) for path in packaged.rglob("*") if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc") if packaged.exists() else []
        if source_files != target_files:
            errors.append(f"plugin {name} file set is out of sync")
            continue
        for relative in source_files:
            count += 1
            if (canonical / relative).read_bytes() != (packaged / relative).read_bytes():
                errors.append(f"plugin {name} differs: {relative}")
    return errors, {"compared_files": count}


def main() -> int:
    errors = []
    try:
        publication_config()
    except Exception as exc:
        errors.append(str(exc))
    errors.extend(validate_model(load_model(ROOT)))
    errors.extend(validate_public_files())
    plugin_errors, report = validate_plugin_sync()
    errors.extend(plugin_errors)
    print(json.dumps({"status": "failed" if errors else "passed", "errors": errors, **report}, ensure_ascii=False, indent=2))
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
