#!/usr/bin/env python3
"""Run release QA for the cross-agent Hello Interview card skill.

This is stricter than the visual smoke test. It validates the renderer against
multiple Hello Interview chapter styles, short/medium/long content, Chinese and
English output, plus cross-agent plugin packaging invariants.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import run_hello_interview_visual_smoke as smoke
from build_curriculum import publication_config


ROOT = Path(__file__).resolve().parents[1]
SMOKE_CASE_DIR = ROOT / "examples" / "hello_interview_smoke_cases"
RELEASE_CASE_DIR = ROOT / "examples" / "hello_interview_release_cases"
DEFAULT_OUT_DIR = Path("/tmp/hello-interview-release-qa")

REQUIRED_LAYOUTS = {"architecture", "comparison", "concept-map", "decision", "modular-composite", "pipeline"}
REQUIRED_CATEGORIES = {
    "advanced-topic",
    "api-design",
    "core-concept",
    "framework",
    "key-technology",
    "pattern",
    "problem-breakdown",
}
REQUIRED_SIZES = {"short", "medium", "long"}
REQUIRED_LANGUAGES = {"Chinese", "English"}
REQUIRED_SOURCE_COMPLETENESS = {"complete", "thin"}
VALID_SOURCE_COMPLETENESS = {"complete", "partial", "thin"}
VALID_COMPLETION_MODES = {"none", "model_background", "researched"}
SEMANTIC_KIND_FILLS = {
    "client": "#ffffff",
    "actor": "#ffffff",
    "user": "#ffffff",
    "frontend": "#ffffff",
    "api": "#d0ebff",
    "gateway": "#d0ebff",
    "edge": "#d0ebff",
    "cdn": "#d0ebff",
    "database": "#d8f5a2",
    "db": "#d8f5a2",
    "cache": "#c3fae8",
    "redis": "#c3fae8",
    "queue": "#e5dbff",
    "stream": "#e5dbff",
    "kafka": "#e5dbff",
    "storage": "#d3f9d8",
    "store": "#d3f9d8",
    "data": "#d3f9d8",
    "s3": "#d3f9d8",
    "blob": "#d3f9d8",
    "file": "#d3f9d8",
    "note": "#f8f9fa",
    "callout": "#f8f9fa",
    "example": "#f8f9fa",
    "question": "#fcc2d7",
    "followup": "#fcc2d7",
    "follow-up": "#fcc2d7",
    "interviewer": "#fcc2d7",
    "caveat": "#fffbe6",
    "risk": "#fffbe6",
    "tradeoff": "#fffbe6",
    "trade-off": "#fffbe6",
    "warning": "#fffbe6",
    "answer": "#f1fcf3",
    "principle": "#f1fcf3",
    "takeaway": "#f1fcf3",
    "conclusion": "#f1fcf3",
    "annotation": "#eef8ff",
    "hint": "#eef8ff",
}
DEFAULT_SEMANTIC_FILL = "#a5d8ff"

SMOKE_METADATA: dict[str, dict[str, str]] = {
    "api-design-concept-map.zh.json": {
        "chapter_category": "api-design",
        "content_size": "medium",
        "source_kind": "Hello Interview API design",
    },
    "caching-architecture.zh.json": {
        "chapter_category": "core-concept",
        "content_size": "medium",
        "source_kind": "Hello Interview core concept",
    },
    "cap-comparison.zh.json": {
        "chapter_category": "core-concept",
        "content_size": "medium",
        "source_kind": "Hello Interview core concept",
    },
    "consistent-hashing-map.zh.json": {
        "chapter_category": "core-concept",
        "content_size": "medium",
        "source_kind": "Hello Interview core concept",
    },
    "google-docs-realtime.zh.json": {
        "chapter_category": "problem-breakdown",
        "content_size": "long",
        "source_kind": "Hello Interview problem breakdown",
    },
    "kafka-pipeline.zh.json": {
        "chapter_category": "key-technology",
        "content_size": "medium",
        "source_kind": "Hello Interview key technology",
    },
    "rate-limiter-decision.zh.json": {
        "chapter_category": "problem-breakdown",
        "content_size": "short",
        "source_kind": "Hello Interview problem breakdown",
    },
    "redis-deep-dive-long.zh.json": {
        "chapter_category": "key-technology",
        "content_size": "long",
        "source_kind": "Hello Interview key technology",
    },
    "sharding-pipeline.zh.json": {
        "chapter_category": "core-concept",
        "content_size": "medium",
        "source_kind": "Hello Interview core concept",
    },
    "ticketmaster-architecture.zh.json": {
        "chapter_category": "problem-breakdown",
        "content_size": "long",
        "source_kind": "Hello Interview problem breakdown",
    },
    "ticketmaster-modular-composite.zh.json": {
        "chapter_category": "problem-breakdown",
        "content_size": "long",
        "source_kind": "Hello Interview problem breakdown",
    },
}

REQUIRED_JSON_FILES = [
    ".agents/plugins/marketplace.json",
    ".cursor-plugin/marketplace.json",
    ".claude-plugin/marketplace.json",
    "plugins/crack-system-interview-skill/.codex-plugin/plugin.json",
    "plugins/crack-system-interview-skill/.cursor-plugin/plugin.json",
    "plugins/crack-system-interview-skill/.claude-plugin/plugin.json",
    "plugins/crack-system-interview-skill/.mcp.json",
    "plugins/crack-system-interview-skill/mcp.json",
]

REQUIRED_PATHS = [
    "interview-coach/SKILL.md",
    "plugins/crack-system-interview-skill/skills/interview-coach/SKILL.md",
    "card/SKILL.md",
    "senior-sde-interview-script/SKILL.md",
    "system-design-study-coach/SKILL.md",
    "plugins/crack-system-interview-skill/commands/card.md",
    "plugins/crack-system-interview-skill/skills/card/SKILL.md",
    "plugins/crack-system-interview-skill/skills/senior-sde-interview-script/SKILL.md",
    "plugins/crack-system-interview-skill/skills/system-design-study-coach/SKILL.md",
    "plugins/crack-system-interview-skill/skills/system-design-study-coach/scripts/plan_lookup.py",
    "docs/index.html",
    "cases/schema/interview-case.schema.json",
    "cases/week-01/bitly-core.case.json",
    "curriculum/week-01.json",
    "scripts/sync_plugin_content.py",
    "scripts/fetch_url_text.py",
    "scripts/render_interview_card.py",
    "scripts/run_hello_interview_visual_smoke.py",
    "scripts/share_excalidraw.mjs",
]

SKILL_COPIES = [
    ("interview-coach/SKILL.md", "plugins/crack-system-interview-skill/skills/interview-coach/SKILL.md"),
    ("card/SKILL.md", "plugins/crack-system-interview-skill/skills/card/SKILL.md"),
    (
        "senior-sde-interview-script/SKILL.md",
        "plugins/crack-system-interview-skill/skills/senior-sde-interview-script/SKILL.md",
    ),
    (
        "system-design-study-coach/SKILL.md",
        "plugins/crack-system-interview-skill/skills/system-design-study-coach/SKILL.md",
    ),
]

STUDY_COACH_SCRIPTS = [
    "system-design-study-coach/scripts/plan_lookup.py",
    "plugins/crack-system-interview-skill/skills/system-design-study-coach/scripts/plan_lookup.py",
]

URL_FETCH_COPIES = [
    "card/scripts/fetch_url_text.py",
    "plugins/crack-system-interview-skill/skills/card/scripts/fetch_url_text.py",
]

RENDERER_COPIES = [
    "card/scripts/render_interview_card.py",
    "senior-sde-interview-script/scripts/render_interview_card.py",
    "plugins/crack-system-interview-skill/skills/card/scripts/render_interview_card.py",
    "plugins/crack-system-interview-skill/skills/senior-sde-interview-script/scripts/render_interview_card.py",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run release QA for the SDE interview card skill.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="Rendered output directory.")
    parser.add_argument(
        "--renderer",
        type=Path,
        default=ROOT / "scripts" / "render_interview_card.py",
        help="Renderer script to test.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def expected_fill_for_kind(kind: str) -> str:
    return SEMANTIC_KIND_FILLS.get(kind.lower(), DEFAULT_SEMANTIC_FILL)


def metadata_for(case_path: Path, fixture: dict[str, Any]) -> dict[str, str]:
    metadata = fixture.get("qa")
    if isinstance(metadata, dict):
        return {str(key): str(value) for key, value in metadata.items()}
    if case_path.name in SMOKE_METADATA:
        return SMOKE_METADATA[case_path.name]
    raise AssertionError(f"{case_path.name}: missing release QA metadata")


def validate_case_metadata(case_path: Path, fixture: dict[str, Any], metadata: dict[str, str]) -> None:
    for key in ("chapter_category", "content_size", "source_kind"):
        if not metadata.get(key):
            raise AssertionError(f"{case_path.name}: metadata missing {key}")
    if metadata["content_size"] not in REQUIRED_SIZES:
        raise AssertionError(f"{case_path.name}: invalid content_size {metadata['content_size']!r}")
    if metadata["chapter_category"] not in REQUIRED_CATEGORIES:
        raise AssertionError(f"{case_path.name}: invalid chapter_category {metadata['chapter_category']!r}")

    layout = str(fixture.get("layout") or "")
    expected_layout = metadata.get("expected_layout")
    if expected_layout and expected_layout != layout:
        raise AssertionError(f"{case_path.name}: expected layout {expected_layout}, got {layout}")

    if not fixture.get("summary") or not fixture.get("task") or not fixture.get("constraints"):
        raise AssertionError(f"{case_path.name}: summary, task, and constraints are required")
    if len(fixture.get("blocks") or []) < 4:
        raise AssertionError(f"{case_path.name}: release fixtures need at least four board blocks")

    qa = fixture.get("qa") if isinstance(fixture.get("qa"), dict) else {}
    required_terms = qa.get("required_terms")
    if isinstance(required_terms, list):
        haystack_parts = [
            str(fixture.get("title") or ""),
            str(fixture.get("summary") or ""),
            str(fixture.get("task") or ""),
            coerce_release_text(fixture.get("constraints")),
            str(fixture.get("talk_track") or ""),
        ]
        for block in fixture.get("blocks") or []:
            if isinstance(block, dict):
                haystack_parts.append(str(block.get("title") or ""))
                haystack_parts.append(str(block.get("body") or block.get("text") or ""))
        for callout in fixture.get("callouts") or []:
            if isinstance(callout, dict):
                haystack_parts.append(str(callout.get("title") or ""))
                haystack_parts.append(str(callout.get("body") or callout.get("text") or ""))
        haystack = "\n".join(haystack_parts)
        missing_terms = [str(term) for term in required_terms if str(term) not in haystack]
        if missing_terms:
            raise AssertionError(f"{case_path.name}: missing required coherence terms: {missing_terms}")

    block_count = len(fixture.get("blocks") or [])
    size = metadata["content_size"]
    if size == "short" and block_count > 5:
        raise AssertionError(f"{case_path.name}: short case has too many blocks: {block_count}")
    if size == "long" and block_count < 6:
        raise AssertionError(f"{case_path.name}: long case is too small: {block_count} blocks")

    source_notes = fixture.get("source_notes")
    completeness = metadata.get("source_completeness", "complete")
    completion_mode = metadata.get("completion_mode", "none")
    if completeness not in VALID_SOURCE_COMPLETENESS:
        raise AssertionError(f"{case_path.name}: invalid source_completeness {completeness!r}")
    if completion_mode not in VALID_COMPLETION_MODES:
        raise AssertionError(f"{case_path.name}: invalid completion_mode {completion_mode!r}")

    if completeness == "complete":
        return
    if not isinstance(source_notes, dict):
        raise AssertionError(f"{case_path.name}: partial/thin cases must include source_notes")
    if str(source_notes.get("completeness") or "") != completeness:
        raise AssertionError(f"{case_path.name}: source_notes completeness does not match QA metadata")
    if str(source_notes.get("completion_mode") or "") != completion_mode:
        raise AssertionError(f"{case_path.name}: source_notes completion_mode does not match QA metadata")
    added_points = source_notes.get("added_points")
    if not isinstance(added_points, list) or len(added_points) < 2:
        raise AssertionError(f"{case_path.name}: partial/thin cases need at least two added_points")


def absolute_points(element: dict[str, Any]) -> list[list[float]]:
    x = float(element.get("x", 0))
    y = float(element.get("y", 0))
    points = element.get("points") or [[0, 0], [element.get("width", 0), element.get("height", 0)]]
    return [[x + float(point[0]), y + float(point[1])] for point in points]


def coerce_release_text(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(f"{key}: {item}" for key, item in value.items())
    return str(value or "")


def rect_to_axis_segment_distance(
    rect: tuple[float, float, float, float],
    p1: list[float],
    p2: list[float],
) -> float:
    left, top, right, bottom = rect
    x1, y1 = p1
    x2, y2 = p2
    if abs(y1 - y2) < 0.001:
        seg_left, seg_right = sorted((x1, x2))
        dx = 0.0 if max(left, seg_left) <= min(right, seg_right) else min(abs(left - seg_right), abs(right - seg_left))
        dy = 0.0 if top <= y1 <= bottom else min(abs(top - y1), abs(bottom - y1))
        return math.hypot(dx, dy)
    if abs(x1 - x2) < 0.001:
        seg_top, seg_bottom = sorted((y1, y2))
        dx = 0.0 if left <= x1 <= right else min(abs(left - x1), abs(right - x1))
        dy = 0.0 if max(top, seg_top) <= min(bottom, seg_bottom) else min(abs(top - seg_bottom), abs(bottom - seg_top))
        return math.hypot(dx, dy)
    center_x = (left + right) / 2
    center_y = (top + bottom) / 2
    return min(math.hypot(center_x - x1, center_y - y1), math.hypot(center_x - x2, center_y - y2))


def bounds_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    padding: float = 0.0,
) -> bool:
    a_left, a_top, a_right, a_bottom = a
    b_left, b_top, b_right, b_bottom = b
    return (
        max(a_left, b_left - padding) < min(a_right, b_right + padding)
        and max(a_top, b_top - padding) < min(a_bottom, b_bottom + padding)
    )


def validate_connector_label_words(label_text: str, label_lines: list[Any], case_name: str, key: tuple[str, str]) -> None:
    lines = [str(line) for line in label_lines if str(line).strip()]
    if not lines:
        return
    for token in re.findall(r"[A-Za-z0-9_]+", label_text):
        if len(token) <= 1:
            continue
        if not any(token in line for line in lines):
            raise AssertionError(
                f"{case_name}: connector label {key[0]}->{key[1]} splits word {token!r} across lines",
            )
    for token in re.findall(r"[\u3400-\u9fff]+", label_text):
        if len(token) <= 1:
            continue
        if not any(token in line for line in lines):
            raise AssertionError(
                f"{case_name}: connector label {key[0]}->{key[1]} splits phrase {token!r} across lines",
            )


def validate_release_scene(case_path: Path, fixture: dict[str, Any], excalidraw_path: Path, preview_path: Path) -> None:
    scene = load_json(excalidraw_path)
    _, canvas_height = smoke.svg_size(preview_path)
    max_bottom = 0.0
    connectors: dict[tuple[str, str], dict[str, Any]] = {}
    labels: list[dict[str, Any]] = []
    block_bounds: list[tuple[float, float, float, float]] = []
    kind_by_block_id: dict[str, str] = {}
    explicit_fill_ids: set[str] = set()
    seen_kind_fills: dict[str, str] = {}

    for block in fixture.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        block_id = str(block.get("id") or "")
        if not block_id:
            continue
        kind_by_block_id[block_id] = str(block.get("kind") or block.get("type") or block.get("shape") or "concept").lower()
        if block.get("fill") is not None or block.get("background") is not None:
            explicit_fill_ids.add(block_id)
    for index, callout in enumerate(fixture.get("callouts") or []):
        if not isinstance(callout, dict):
            continue
        block_id = str(callout.get("id") or f"callout{index}")
        kind_by_block_id[block_id] = str(callout.get("kind") or callout.get("type") or "note").lower()
        if callout.get("fill") is not None or callout.get("background") is not None:
            explicit_fill_ids.add(block_id)

    for element in scene.get("elements", []):
        bounds = smoke.element_bounds(element)
        if bounds:
            max_bottom = max(max_bottom, bounds[3])
        custom = element.get("customData") or {}
        if custom.get("role") == "block":
            if bounds:
                block_bounds.append(bounds)
            block_id = str(custom.get("blockId") or "")
            kind = kind_by_block_id.get(block_id)
            if kind and block_id not in explicit_fill_ids:
                fill = str(element.get("backgroundColor") or "transparent")
                expected_fill = expected_fill_for_kind(kind)
                if fill != expected_fill:
                    raise AssertionError(
                        f"{case_path.name}: block {block_id} kind {kind!r} expected fill {expected_fill}, got {fill}",
                    )
                previous_fill = seen_kind_fills.setdefault(kind, fill)
                if previous_fill != fill:
                    raise AssertionError(
                        f"{case_path.name}: kind {kind!r} uses inconsistent fills: {previous_fill} and {fill}",
                    )
        if custom.get("role") == "connector":
            connectors[(str(custom.get("from") or ""), str(custom.get("to") or ""))] = element
        if custom.get("role") == "connector_label":
            labels.append(element)

    if canvas_height - max_bottom < 58:
        raise AssertionError(
            f"{case_path.name}: bottom padding too small: canvas={canvas_height}, max_bottom={max_bottom:.1f}",
        )

    for label in labels:
        custom = label.get("customData") or {}
        key = (str(custom.get("from") or ""), str(custom.get("to") or ""))
        validate_connector_label_words(str(custom.get("label") or ""), list(custom.get("labelLines") or []), case_path.name, key)
        connector = connectors.get(key)
        if not connector:
            continue
        bounds = smoke.element_bounds(label)
        if not bounds:
            continue
        points = absolute_points(connector)
        distance = min(
            rect_to_axis_segment_distance(bounds, points[index], points[index + 1])
            for index in range(len(points) - 1)
        )
        if distance > 52:
            raise AssertionError(
                f"{case_path.name}: connector label {key[0]}->{key[1]} is too far from its line: {distance:.1f}px",
            )
        for block_bound in block_bounds:
            if bounds_overlap(bounds, block_bound, padding=1):
                raise AssertionError(
                    f"{case_path.name}: connector label {key[0]}->{key[1]} overlaps a block",
                )


def validate_packaging() -> None:
    public_route = "docs/index.html"
    for path_text in [*REQUIRED_PATHS, public_route]:
        path = ROOT / path_text
        if not path.exists():
            raise AssertionError(f"Missing required release path: {path_text}")
    for path_text in REQUIRED_JSON_FILES:
        path = ROOT / path_text
        load_json(path)

    canonical = (ROOT / "scripts/render_interview_card.py").read_bytes()
    for copy_text in RENDERER_COPIES:
        copy_path = ROOT / copy_text
        if copy_path.read_bytes() != canonical:
            raise AssertionError(f"Renderer copy is out of sync: {copy_text}")

    canonical_fetch = (ROOT / "scripts/fetch_url_text.py").read_bytes()
    for copy_text in URL_FETCH_COPIES:
        copy_path = ROOT / copy_text
        if copy_path.read_bytes() != canonical_fetch:
            raise AssertionError(f"URL fetcher copy is out of sync: {copy_text}")

    for canonical_text, copy_text in SKILL_COPIES:
        canonical_skill = ROOT / canonical_text
        copy_path = ROOT / copy_text
        if copy_path.read_bytes() != canonical_skill.read_bytes():
            raise AssertionError(f"Skill copy is out of sync: {copy_text}")

    canonical_lookup = (ROOT / STUDY_COACH_SCRIPTS[0]).read_bytes()
    for copy_text in STUDY_COACH_SCRIPTS[1:]:
        copy_path = ROOT / copy_text
        if copy_path.read_bytes() != canonical_lookup:
            raise AssertionError(f"Study coach lookup copy is out of sync: {copy_text}")

    curriculum = ROOT / "curriculum"
    packaged_curriculum = ROOT / "plugins/crack-system-interview-skill/curriculum"
    source_files = sorted(
        path.relative_to(curriculum)
        for path in curriculum.rglob("*")
        if path.is_file()
    )
    packaged_files = sorted(
        path.relative_to(packaged_curriculum)
        for path in packaged_curriculum.rglob("*")
        if path.is_file()
    )
    if source_files != packaged_files:
        raise AssertionError("Plugin curriculum files are out of sync")
    for relative_path in source_files:
        if (packaged_curriculum / relative_path).read_bytes() != (curriculum / relative_path).read_bytes():
            raise AssertionError(f"Plugin curriculum is out of sync: {relative_path}")

    for name in ("cases", "sources"):
        canonical_root = ROOT / name
        packaged_root = ROOT / "plugins/crack-system-interview-skill" / name
        canonical_files = sorted(
            path.relative_to(canonical_root)
            for path in canonical_root.rglob("*")
            if path.is_file()
        )
        packaged_files = sorted(
            path.relative_to(packaged_root)
            for path in packaged_root.rglob("*")
            if path.is_file()
        )
        if canonical_files != packaged_files:
            raise AssertionError(f"Plugin {name} files are out of sync")
        for relative_path in canonical_files:
            if (canonical_root / relative_path).read_bytes() != (
                packaged_root / relative_path
            ).read_bytes():
                raise AssertionError(
                    f"Plugin {name} is out of sync: {relative_path}"
                )


def compile_python() -> None:
    paths = [
        ROOT / "scripts/render_interview_card.py",
        ROOT / "scripts/fetch_url_text.py",
        ROOT / "scripts/run_hello_interview_visual_smoke.py",
        ROOT / "scripts/run_release_qa.py",
        ROOT / "scripts/build_curriculum.py",
        ROOT / "scripts/curriculum_model.py",
        ROOT / "scripts/qa_curriculum.py",
        ROOT / "scripts/verify_sources.py",
        ROOT / "scripts/sync_plugin_content.py",
        *(ROOT / copy for copy in RENDERER_COPIES),
        *(ROOT / copy for copy in URL_FETCH_COPIES),
        *(ROOT / copy for copy in STUDY_COACH_SCRIPTS),
    ]
    env = dict(os.environ)
    env.setdefault("PYTHONPYCACHEPREFIX", "/tmp/sde-skill-pycache")
    subprocess.run([sys.executable, "-m", "py_compile", *(str(path) for path in paths)], check=True, env=env)


def validate_text_wrapping(renderer: Path) -> None:
    spec = importlib.util.spec_from_file_location("card_renderer_for_qa", renderer)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Cannot import renderer for text wrapping QA: {renderer}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    title_lines = module.wrap_text("Geohash: encode grid path", 28, 356)
    if title_lines != ["Geohash: encode grid path"]:
        raise AssertionError(f"Premature block title wrapping: {title_lines}")

    body_lines = module.wrap_text("Store each restaurant's location as a geohash like dr5ru.", 20, 356)
    if body_lines != ["Store each restaurant's location as a", "geohash like dr5ru."]:
        raise AssertionError(f"Unexpected block body wrapping: {body_lines}")

    label_block = module.text_block_svg(
        "loses 2D meaning",
        17,
        54,
        "#111",
        10,
        14,
        module.DIAGRAM_FONT,
        break_long_words=False,
    )
    if label_block.get("lines") != ["loses", "2D", "meaning"]:
        raise AssertionError(f"Connector label split a word: {label_block.get('lines')}")


def validate_url_fetch_outline() -> None:
    fetcher_path = ROOT / "scripts/fetch_url_text.py"
    spec = importlib.util.spec_from_file_location("card_fetcher_for_qa", fetcher_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Cannot import URL fetcher for QA: {fetcher_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    html_doc = """
    <html>
      <body>
        <nav>Subscribe Sign in</nav>
        <main>
          <h1>Caching for System Design Interviews</h1>
          <p>In system design interviews, caching comes up almost every time high read traffic would otherwise make the database the bottleneck.</p>
          <h2>Where to Cache</h2>
          <p>Most systems use a cache between the application and database, but caching can also live in browsers, CDNs, applications, and databases.</p>
          <h2>CDN (Content Delivery Network)</h2>
          <p>A CDN keeps public content near users so images and other cacheable responses do not always travel back to the origin server.</p>
          <h2>Cache Invalidation</h2>
          <p>Invalidation is the hard part because the system must decide when stale data is acceptable and when correctness requires a fresh read.</p>
          <h2>Test Your Knowledge</h2>
          <p>This footer content should be trimmed before outline extraction.</p>
        </main>
      </body>
    </html>
    """
    parser = module.ArticleTextParser()
    parser.feed(html_doc)
    text, method = parser.best_text(24000)
    outline, sections = module.build_outline_and_sections(text, parser.structured_blocks)
    titles = [item["title"] for item in outline]
    expected = ["Where to Cache", "CDN (Content Delivery Network)", "Cache Invalidation"]
    if titles != expected:
        raise AssertionError(f"URL outline extraction drifted: {titles!r}")
    if method != "html-main":
        raise AssertionError(f"Unexpected URL extraction method: {method}")
    if len(sections) != 4:
        raise AssertionError(f"Expected intro plus 3 titled sections, got {len(sections)}")
    if any("Test Your Knowledge" in section.get("text", "") for section in sections):
        raise AssertionError("URL sections include trimmed footer content")


def validate_study_coach_lookup() -> None:
    expected_days = [(1, 1), (12, 7)]
    for script_text in STUDY_COACH_SCRIPTS:
        script = ROOT / script_text
        for week, day in expected_days:
            result = subprocess.run(
                [sys.executable, str(script), "--week", str(week), "--day", str(day), "--format", "json"],
                check=True,
                capture_output=True,
                text=True,
            )
            item = json.loads(result.stdout)
            if item["week"] != week or item["day"] != day:
                raise AssertionError(f"{script_text}: Week {week} Day {day} lookup returned the wrong item")
            if not item["title"] or not item.get("time_blocks"):
                raise AssertionError(f"{script_text}: Week {week} Day {day} is missing title or duration blocks")
            if any(type(block.get("minutes")) is not int for block in item["time_blocks"]):
                raise AssertionError(f"{script_text}: Week {week} Day {day} has invalid duration blocks")

    plugin_root = ROOT / "plugins/crack-system-interview-skill"
    with tempfile.TemporaryDirectory(prefix="crack-system-interview-plugin-") as temp_dir:
        isolated_plugin = Path(temp_dir) / "plugin"
        shutil.copytree(plugin_root, isolated_plugin)
        result = subprocess.run(
            [
                sys.executable,
                str(isolated_plugin / "skills/system-design-study-coach/scripts/plan_lookup.py"),
                "--week",
                "12",
                "--day",
                "7",
                "--format",
                "json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        item = json.loads(result.stdout)
        if item.get("week") != 12 or item.get("day") != 7:
            raise AssertionError("Isolated plugin study coach did not return the requested position")


def validate_case_library() -> None:
    schema = load_json(ROOT / "cases/schema/interview-case.schema.json")
    required_fields = schema["required"]
    cases: dict[str, dict] = {}
    for case_path in sorted((ROOT / "cases").glob("week-*/*.case.json")):
        case = load_json(case_path)
        missing = [field for field in required_fields if field not in case]
        if missing:
            raise AssertionError(f"{case_path.name}: missing case fields {missing}")
        if case["schema_version"] != "1.0":
            raise AssertionError(f"{case_path.name}: unsupported schema version")
        if sum(item["weight"] for item in case["rubric"]["dimensions"]) != 100:
            raise AssertionError(f"{case_path.name}: rubric weights must total 100")
        cases[case["id"]] = case

    curriculum_files = sorted((ROOT / "curriculum").glob("week-*.json"))
    expected_weeks = list(range(1, 13))
    actual_weeks = [int(path.stem.removeprefix("week-")) for path in curriculum_files]
    if actual_weeks != expected_weeks:
        raise AssertionError(f"Curriculum weeks must be 1-12, got {actual_weeks}")
    for week_path in curriculum_files:
        week = load_json(week_path)
        days = week.get("days", [])
        if [item.get("day") for item in days] != list(range(1, 8)):
            raise AssertionError(f"{week_path.name}: days must be 1-7 in order")
        for day in days:
            if len(day.get("algorithms", {}).get("problems", [])) != 3:
                raise AssertionError(f"{week_path.name}: Day {day.get('day')} needs exactly 3 algorithms")
            case_id = day.get("case_id")
            if case_id and case_id not in cases:
                raise AssertionError(f"{week_path.name}: unknown case_id {case_id}")


def validate_curriculum_page_alignment() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/qa_curriculum.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            "Curriculum QA failed:\n" + (result.stdout or result.stderr)
        )
    report = json.loads(result.stdout)
    unverified = report["checks"]["pages"].get("unverified_editorial_external_links", 0)
    print(f"Curriculum QA: {report['publication_mode']}; {report['verification_scope']}; "
          f"{unverified} editorial external link occurrences remain unverified; "
          "independent calendar pages are not certified as canonical assignments.")


def run_release_cases(out_dir: Path, renderer: Path) -> None:
    case_paths = sorted(SMOKE_CASE_DIR.glob("*.json")) + sorted(RELEASE_CASE_DIR.glob("*.json"))
    if not case_paths:
        raise AssertionError("No release QA fixtures found")

    layouts: set[str] = set()
    categories: set[str] = set()
    sizes: set[str] = set()
    languages: set[str] = set()
    source_completeness: set[str] = set()
    print(f"Release QA rendering {len(case_paths)} fixtures into {out_dir}")

    for case_path in case_paths:
        fixture = load_json(case_path)
        metadata = metadata_for(case_path, fixture)
        validate_case_metadata(case_path, fixture, metadata)

        layout, counts, preview = smoke.run_case(case_path, out_dir, renderer)
        slug = case_path.stem.replace(".", "-")
        case_out = out_dir / slug
        validate_release_scene(case_path, fixture, case_out / f"{slug}.excalidraw", Path(preview))

        layouts.add(layout)
        categories.add(metadata["chapter_category"])
        sizes.add(metadata["content_size"])
        languages.add(str(fixture.get("language") or ""))
        source_completeness.add(metadata.get("source_completeness", "complete"))
        compact_counts = ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
        print(
            f"PASS {case_path.name} "
            f"[{metadata['chapter_category']}/{metadata['content_size']}/{layout}] "
            f"{compact_counts}",
        )

    missing_layouts = REQUIRED_LAYOUTS - layouts
    missing_categories = REQUIRED_CATEGORIES - categories
    missing_sizes = REQUIRED_SIZES - sizes
    missing_languages = REQUIRED_LANGUAGES - languages
    missing_source_completeness = REQUIRED_SOURCE_COMPLETENESS - source_completeness
    if missing_layouts:
        raise AssertionError(f"Missing release layout coverage: {sorted(missing_layouts)}")
    if missing_categories:
        raise AssertionError(f"Missing Hello Interview category coverage: {sorted(missing_categories)}")
    if missing_sizes:
        raise AssertionError(f"Missing content size coverage: {sorted(missing_sizes)}")
    if missing_languages:
        raise AssertionError(f"Missing language coverage: {sorted(missing_languages)}")
    if missing_source_completeness:
        raise AssertionError(f"Missing source-completeness coverage: {sorted(missing_source_completeness)}")

    print("Release matrix:")
    print(f"  layouts: {', '.join(sorted(layouts))}")
    print(f"  categories: {', '.join(sorted(categories))}")
    print(f"  sizes: {', '.join(sorted(sizes))}")
    print(f"  languages: {', '.join(sorted(languages))}")
    print(f"  source completeness: {', '.join(sorted(source_completeness))}")


def main() -> None:
    args = parse_args()
    validate_packaging()
    compile_python()
    validate_text_wrapping(args.renderer)
    validate_url_fetch_outline()
    validate_case_library()
    validate_curriculum_page_alignment()
    validate_study_coach_lookup()
    run_release_cases(args.out, args.renderer)
    print("RELEASE_QA_PASS")


if __name__ == "__main__":
    main()
