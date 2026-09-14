#!/usr/bin/env python3
"""Run offline visual smoke tests for Hello Interview-style card fixtures.

The tests intentionally avoid network access. They render every curated fixture
into SVG + Excalidraw JSON, then verify that the scene uses native Excalidraw
blocks, covers multiple layouts, embeds image-backed handwritten text, and keeps
visible elements inside the generated canvas.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASE_DIR = ROOT / "examples" / "hello_interview_smoke_cases"
DEFAULT_OUT_DIR = Path("/tmp/hello-interview-visual-smoke")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render and validate visual smoke fixtures.")
    parser.add_argument(
        "--case-dir",
        type=Path,
        default=DEFAULT_CASE_DIR,
        help="Directory containing *.json card fixtures.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="Directory where rendered outputs should be written.",
    )
    parser.add_argument(
        "--renderer",
        type=Path,
        default=ROOT / "scripts" / "render_interview_card.py",
        help="Renderer script to execute.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def svg_size(path: Path) -> tuple[int, int]:
    head = path.read_text(encoding="utf-8")[:240]
    match = re.search(r'width="(\d+)" height="(\d+)"', head)
    if not match:
        raise AssertionError(f"{path}: preview SVG does not expose width/height")
    return int(match.group(1)), int(match.group(2))


def element_bounds(element: dict[str, Any]) -> tuple[float, float, float, float] | None:
    element_type = element.get("type")
    if element_type in {"rectangle", "ellipse", "diamond", "image"}:
        x = float(element.get("x", 0))
        y = float(element.get("y", 0))
        w = float(element.get("width", 0))
        h = float(element.get("height", 0))
        return min(x, x + w), min(y, y + h), max(x, x + w), max(y, y + h)
    if element_type == "arrow":
        x = float(element.get("x", 0))
        y = float(element.get("y", 0))
        points = element.get("points") or [[0, 0], [element.get("width", 0), element.get("height", 0)]]
        xs = [x + float(point[0]) for point in points]
        ys = [y + float(point[1]) for point in points]
        return min(xs), min(ys), max(xs), max(ys)
    return None


def arrow_points(element: dict[str, Any]) -> list[list[float]]:
    x = float(element.get("x", 0))
    y = float(element.get("y", 0))
    points = element.get("points") or [[0, 0], [element.get("width", 0), element.get("height", 0)]]
    return [[x + float(point[0]), y + float(point[1])] for point in points]


def shrink_bounds(
    bounds: tuple[float, float, float, float],
    amount: float,
) -> tuple[float, float, float, float]:
    left, top, right, bottom = bounds
    return left + amount, top + amount, right - amount, bottom - amount


def segment_intersects_bounds(
    p1: list[float],
    p2: list[float],
    bounds: tuple[float, float, float, float],
) -> bool:
    left, top, right, bottom = bounds
    x1, y1 = p1
    x2, y2 = p2
    if right <= left or bottom <= top:
        return False
    if abs(y1 - y2) < 0.001:
        seg_left, seg_right = sorted((x1, x2))
        return top <= y1 <= bottom and max(seg_left, left) <= min(seg_right, right)
    if abs(x1 - x2) < 0.001:
        seg_top, seg_bottom = sorted((y1, y2))
        return left <= x1 <= right and max(seg_top, top) <= min(seg_bottom, bottom)
    return False


def bounds_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    return max(a[0], b[0]) <= min(a[2], b[2]) and max(a[1], b[1]) <= min(a[3], b[3])


def contained_in(
    inner: tuple[float, float, float, float],
    outer: tuple[float, float, float, float],
    tolerance: float = 4,
) -> bool:
    return (
        inner[0] >= outer[0] - tolerance
        and inner[1] >= outer[1] - tolerance
        and inner[2] <= outer[2] + tolerance
        and inner[3] <= outer[3] + tolerance
    )


def non_space_len(value: str) -> int:
    return len(re.sub(r"\s+", "", value))


def validate_interview_sentence_density(case_path: Path, fixture: dict[str, Any]) -> None:
    """Reject flashcard-like fixtures that only contain keywords."""

    for block in fixture.get("blocks", []):
        body = str(block.get("body") or "")
        kind = str(block.get("kind") or block.get("type") or "").lower()
        min_body_len = 24 if kind in {"client", "actor", "user"} else 40
        if non_space_len(body) < min_body_len:
            raise AssertionError(
                f"{case_path.name}: block {block.get('id')} body is too keyword-like: {body!r}",
            )
        if not re.search(r"[。.!?？；;]", body):
            raise AssertionError(
                f"{case_path.name}: block {block.get('id')} body needs speakable sentence punctuation",
            )

    talk_track = str(fixture.get("talk_track") or "")
    if non_space_len(talk_track) < 80:
        raise AssertionError(f"{case_path.name}: talk_track is too short for interview prep")


def validate_board_voice(case_path: Path, fixture: dict[str, Any]) -> None:
    """Keep the rendered board professional; candidate wording belongs in talk_track."""

    banned = re.compile(
        r"我会|我的|面试|面试官|面试可讲|I would|my decision|interview signal|\bcandidate\b|\binterviewer\b",
        re.IGNORECASE,
    )
    board_values: list[tuple[str, str]] = []
    for key in ("title", "summary", "task"):
        board_values.append((key, str(fixture.get(key) or "")))
    for item in fixture.get("constraints", []):
        board_values.append(("constraints", str(item)))
    for block in fixture.get("blocks", []):
        block_id = block.get("id")
        board_values.append((f"block:{block_id}:title", str(block.get("title") or "")))
        board_values.append((f"block:{block_id}:body", str(block.get("body") or "")))
    for callout in fixture.get("callouts", []):
        board_values.append(("callout:title", str(callout.get("title") or "")))
        board_values.append(("callout:body", str(callout.get("body") or "")))
    for connector in fixture.get("connectors", []):
        board_values.append(("connector:label", str(connector.get("label") or "")))

    for field, value in board_values:
        if banned.search(value):
            raise AssertionError(
                f"{case_path.name}: board field {field} contains interview/coaching voice: {value!r}",
            )


def validate_scene(
    case_path: Path,
    fixture: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, int]:
    validate_interview_sentence_density(case_path, fixture)
    validate_board_voice(case_path, fixture)
    preview_path = Path(result["preview"])
    excalidraw_path = Path(result["excalidraw"])
    if not preview_path.exists():
        raise AssertionError(f"{case_path.name}: missing preview {preview_path}")
    if not excalidraw_path.exists():
        raise AssertionError(f"{case_path.name}: missing excalidraw {excalidraw_path}")
    if preview_path.stat().st_size < 2000:
        raise AssertionError(f"{case_path.name}: preview is suspiciously small")
    scene = load_json(excalidraw_path)
    width, height = svg_size(preview_path)
    counts: dict[str, int] = {}
    block_bounds: dict[str, tuple[float, float, float, float]] = {}
    text_images: list[tuple[str, tuple[float, float, float, float], dict[str, Any]]] = []
    connector_arrows: list[dict[str, Any]] = []
    for element in scene.get("elements", []):
        element_type = str(element.get("type"))
        counts[element_type] = counts.get(element_type, 0) + 1
        custom = element.get("customData") or {}
        if custom.get("role") == "block":
            bounds = element_bounds(element)
            if bounds:
                block_bounds[str(custom.get("blockId"))] = bounds
        if custom.get("role") == "connector":
            connector_arrows.append(element)
        if element_type == "image":
            key = str(custom.get("key") or element.get("fileId") or "")
            if key.startswith(("icon", "wb_icon")):
                raise AssertionError(
                    f"{case_path.name}: component icons should not render by default: {key}",
                )
            bounds = element_bounds(element)
            if bounds:
                text_images.append((key, bounds, custom))
        bounds = element_bounds(element)
        if not bounds:
            continue
        left, top, right, bottom = bounds
        if left < -30 or top < -30 or right > width + 30 or bottom > height + 30:
            raise AssertionError(
                f"{case_path.name}: {element_type} element {element.get('id')} "
                f"falls outside canvas {width}x{height}: {bounds}",
            )

    for key, bounds, custom in text_images:
        parent_id = ""
        if key.startswith("wb_block_"):
            parent_id = key.removeprefix("wb_block_")
        elif key.startswith("block"):
            candidate = key.removeprefix("block")
            if candidate in block_bounds:
                parent_id = candidate
        if parent_id and parent_id in block_bounds and not contained_in(bounds, block_bounds[parent_id]):
            raise AssertionError(
                f"{case_path.name}: text image {key} exceeds parent block {parent_id}: "
                f"text={bounds}, block={block_bounds[parent_id]}",
            )
        if key.startswith(("connector", "wb_connector_")):
            src = str(custom.get("from") or "")
            dst = str(custom.get("to") or "")
            for block_id, block in block_bounds.items():
                if block_id in {src, dst}:
                    continue
                if bounds_overlap(shrink_bounds(block, 4), bounds):
                    raise AssertionError(
                        f"{case_path.name}: connector label {key} overlaps block {block_id}: "
                        f"label={bounds}, block={block}",
                    )

    for arrow_element in connector_arrows:
        custom = arrow_element.get("customData") or {}
        src = str(custom.get("from") or "")
        dst = str(custom.get("to") or "")
        points = arrow_points(arrow_element)
        for index in range(len(points) - 1):
            for block_id, bounds in block_bounds.items():
                if block_id in {src, dst}:
                    continue
                if segment_intersects_bounds(points[index], points[index + 1], shrink_bounds(bounds, 6)):
                    raise AssertionError(
                        f"{case_path.name}: connector {src}->{dst} crosses block {block_id}: "
                        f"segment={points[index]}->{points[index + 1]}, block={bounds}",
                    )

    if counts.get("diamond", 0):
        raise AssertionError(f"{case_path.name}: diamond shapes are disabled for this style")
    native_blocks = counts.get("rectangle", 0) + counts.get("ellipse", 0)
    if native_blocks < 3:
        raise AssertionError(f"{case_path.name}: expected at least 3 native block shapes")
    if counts.get("image", 0) < 4:
        raise AssertionError(f"{case_path.name}: expected image-backed handwritten text blocks")
    if counts.get("arrow", 0) < 2 and len(fixture.get("blocks", [])) > 3:
        raise AssertionError(f"{case_path.name}: expected relationship arrows")
    if len(scene.get("files", {})) < counts.get("image", 0):
        raise AssertionError(f"{case_path.name}: embedded image files are missing")
    if fixture.get("style") != "excalidraw-plus":
        raise AssertionError(f"{case_path.name}: fixture must exercise excalidraw-plus style")
    if not fixture.get("talk_track"):
        raise AssertionError(f"{case_path.name}: fixture must include copyable talk track")
    return counts


def run_case(case_path: Path, out_dir: Path, renderer: Path) -> tuple[str, dict[str, int], str]:
    fixture = load_json(case_path)
    slug = case_path.stem.replace(".", "-")
    case_out = out_dir / slug
    case_out.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(renderer),
        "--content",
        str(case_path),
        "--out",
        str(case_out),
        "--slug",
        slug,
        "--no-share",
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    result = json.loads(completed.stdout)
    counts = validate_scene(case_path, fixture, result)
    return str(fixture.get("layout") or "auto"), counts, result["preview"]


def main() -> None:
    args = parse_args()
    case_paths = sorted(args.case_dir.glob("*.json"))
    if not case_paths:
        raise SystemExit(f"No fixtures found in {args.case_dir}")

    layouts: set[str] = set()
    print(f"Rendering {len(case_paths)} fixtures into {args.out}")
    for case_path in case_paths:
        layout, counts, preview = run_case(case_path, args.out, args.renderer)
        layouts.add(layout)
        compact_counts = ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
        print(f"PASS {case_path.name} [{layout}] {compact_counts} -> {preview}")

    required_layouts = {"architecture", "comparison", "concept-map", "decision", "modular-composite", "pipeline"}
    missing = required_layouts - layouts
    if missing:
        raise AssertionError(f"Missing required layout coverage: {sorted(missing)}")
    print(f"Covered layouts: {', '.join(sorted(layouts))}")


if __name__ == "__main__":
    main()
