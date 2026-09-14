#!/usr/bin/env python3
"""Render a senior SDE interview script card as Excalidraw + preview image.

The agent supplies already-summarized content as JSON. This script is purposely
dependency-light so Codex, Cursor, and Claude Code can all run it after clone.
It writes a local preview SVG and a .excalidraw file. Sharing and speech
synthesis require explicit command-line opt-in for the current content.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


HANDWRITING_FONT = (
    "Excalifont,Xiaolai,HanziPen SC,HanziPen TC,Kaiti SC,KaiTi,"
    "Bradley Hand,Comic Sans MS,cursive,sans-serif"
)

DIAGRAM_FONT = (
    "Comic Shanns,Excalifont,Xiaolai,HanziPen SC,HanziPen TC,Kaiti SC,"
    "Comic Sans MS,cursive,monospace"
)

PLUS_STYLE_ALIASES = {
    "plus",
    "excalidraw-plus",
    "excalidraw_plus",
    "whiteboard",
    "interview-whiteboard",
    "reference",
}

PLUS_BLUE = "#a5d8ff"
PLUS_STROKE = "#1e1e1e"
PLUS_PINK = "#fcc2d7"
PLUS_YELLOW = "#fffbe6"
PLUS_GREEN = "#f1fcf3"
PLUS_MINT = "#eef8ff"
PLUS_EDGE_BLUE = "#d0ebff"
PLUS_DATABASE_GREEN = "#d8f5a2"
PLUS_CACHE_MINT = "#c3fae8"
PLUS_QUEUE_LAVENDER = "#e5dbff"
PLUS_STORAGE_GREEN = "#d3f9d8"
PLUS_NOTE_GRAY = "#f8f9fa"
PLUS_CLIENT_FILL = "#ffffff"

WHITEBOARD_BOTTOM_PADDING = 185
DIAGRAM_BOTTOM_PADDING = 140
CONNECTOR_LABEL_MAX_WIDTH = 144
CONNECTOR_LABEL_GAP = 6
CONNECTOR_LABEL_OBSTACLE_PADDING = 10

MODULAR_LAYOUTS = {
    "modular",
    "composite",
    "modular-composite",
    "modular_composite",
    "multi-module",
    "multi_module",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render an interview answer card from structured JSON content.",
    )
    parser.add_argument(
        "--content",
        required=True,
        help="Path to JSON content file, or '-' to read JSON from stdin.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output directory. Defaults to /tmp/sde-interview-card-<timestamp>.",
    )
    parser.add_argument("--slug", default="interview-card", help="Output filename slug.")
    sharing = parser.add_mutually_exclusive_group()
    sharing.add_argument(
        "--share", dest="no_share", action="store_false",
        help="Explicitly upload this scene to Excalidraw and return a share link.",
    )
    sharing.add_argument(
        "--no-share", dest="no_share", action="store_true",
        help="Keep artifacts local (the default).",
    )
    parser.set_defaults(no_share=True)
    parser.add_argument(
        "--tts",
        choices=["none", "elevenlabs"],
        default="none",
        help="Optionally synthesize content.talk_track to audio. Requires --tts elevenlabs; defaults to none.",
    )
    parser.add_argument(
        "--tts-voice-id",
        default=os.environ.get("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb"),
        help="ElevenLabs voice ID. Defaults to ELEVENLABS_VOICE_ID or the public docs sample voice.",
    )
    parser.add_argument(
        "--tts-model-id",
        default=os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2"),
        help="ElevenLabs model ID. Defaults to ELEVENLABS_MODEL_ID or eleven_multilingual_v2.",
    )
    parser.add_argument(
        "--tts-output-format",
        default=os.environ.get("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128"),
        help="ElevenLabs output_format query value. Defaults to ELEVENLABS_OUTPUT_FORMAT or mp3_44100_128.",
    )
    parser.add_argument(
        "--tts-language-code",
        default=os.environ.get("ELEVENLABS_LANGUAGE_CODE"),
        help="Optional ElevenLabs language_code, e.g. zh or en.",
    )
    return parser.parse_args()


def load_content(path: str) -> dict[str, Any]:
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)
    if data.get("blocks") or data.get("nodes"):
        data["blocks"] = data.get("blocks") or data.get("nodes") or []
        data["connectors"] = data.get("connectors") or []
        data["callouts"] = data.get("callouts") or []
        data.setdefault("title", "Script Card")
        data.setdefault("summary", "")
        data.setdefault("layout", "auto")
        return data
    required = ["title", "summary", "script", "short", "flows"]
    missing = [key for key in required if not data.get(key)]
    if missing:
        raise SystemExit(f"Missing required content fields: {', '.join(missing)}")
    if not isinstance(data["flows"], list):
        raise SystemExit("content.flows must be a list")
    flows = [str(item) for item in data["flows"][:4]]
    while len(flows) < 4:
        flows.append("")
    data["flows"] = flows
    return data


def token_width(token: str, size: int) -> float:
    width = 0.0
    for char in token:
        code = ord(char)
        if char.isspace():
            width += size * 0.28
        elif 0x3400 <= code <= 0x9FFF:
            width += size * 0.90
        elif char in "`.,;:/|!()[]{}":
            width += size * 0.30
        else:
            width += size * 0.47
    return width


def tokenize(text: str) -> list[str]:
    return re.findall(
        r"`[^`]+`|[A-Za-z0-9_./?=&{}:#()+-]+|[\u3400-\u9fff]|\s+|[^\sA-Za-z0-9_./?=&{}:#()+\-\u3400-\u9fff`]",
        text,
    )


def wrap_paragraph(paragraph: str, size: int, max_width: int, break_long_words: bool = True) -> list[str]:
    lines: list[str] = []
    line = ""
    line_width = 0.0
    tokens = tokenize(paragraph) if break_long_words else re.findall(r"\S+|\s+", paragraph)
    for token in tokens:
        token = " " if token.isspace() else token
        width = token_width(token, size)
        if line and line_width + width > max_width:
            lines.append(line.rstrip())
            line = token.lstrip()
            line_width = token_width(line, size)
        else:
            line += token
            line_width += width

        while break_long_words and line_width > max_width and len(line) > 1:
            acc = ""
            acc_width = 0.0
            rest_start = 0
            for idx, char in enumerate(line):
                char_width = token_width(char, size)
                if acc and acc_width + char_width > max_width:
                    rest_start = idx
                    break
                acc += char
                acc_width += char_width
            else:
                break
            lines.append(acc.rstrip())
            line = line[rest_start:].lstrip()
            line_width = token_width(line, size)
    if line.strip():
        lines.append(line.rstrip())
    fixed: list[str] = []
    orphan_punctuation = set("。，、；：！？,.!?;:")
    for item in lines:
        if fixed and item.strip() in orphan_punctuation:
            fixed[-1] = fixed[-1] + item.strip()
        else:
            fixed.append(item)
    return fixed


def split_sentence_units(paragraph: str) -> list[str]:
    text = paragraph.strip()
    if not text:
        return []
    if text.startswith(("-", "•", "*")):
        return [text]
    parts = re.split(r"(?<=[。！？；!?;])\s*|(?<=[.!?;])\s+(?=[A-Z0-9\"'`])", text)
    return [part.strip() for part in parts if part.strip()]


def wrap_text(text: str, size: int, max_width: int, break_long_words: bool = True) -> list[str | None]:
    wrapped: list[str | None] = []
    paragraphs = text.split("\n")
    for idx, paragraph in enumerate(paragraphs):
        if paragraph:
            for sentence in split_sentence_units(paragraph):
                wrapped.extend(wrap_paragraph(sentence, size, max_width, break_long_words))
        else:
            wrapped.append(None)
        if idx != len(paragraphs) - 1:
            wrapped.append(None)
    return wrapped


def text_block_svg(
    text: str,
    size: int,
    max_width: int,
    color: str,
    line_gap: int,
    paragraph_gap: int,
    font_family: str = HANDWRITING_FONT,
    align: str = "left",
    break_long_words: bool = True,
) -> dict[str, Any]:
    lines = wrap_text(text, size, max_width, break_long_words)
    line_height = int(size * 1.26) + line_gap
    y = int(size * 1.1)
    text_nodes: list[str] = []
    max_line_width = 1.0
    centered = align == "center"
    svg_width = max_width + 8
    text_x = svg_width / 2 if centered else 0
    anchor = ' text-anchor="middle"' if centered else ""
    for line in lines:
        if line is None:
            y += paragraph_gap
            continue
        max_line_width = max(max_line_width, token_width(line, size))
        text_nodes.append(
            f'<text x="{text_x}" y="{y}" font-size="{size}" fill="{color}" '
            f'font-family="{font_family}"{anchor}>{html.escape(line)}</text>'
        )
        y += line_height
    if centered:
        width = svg_width
    elif break_long_words:
        width = min(max_width + 8, int(math.ceil(max_line_width)) + 10)
    else:
        width = max(max_width + 8, int(math.ceil(max_line_width)) + 10)
    height = max(1, y - int(size * 0.3))
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">' + "".join(text_nodes) + "</svg>"
    )
    data_url = "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode(
        "ascii",
    )
    return {"dataURL": data_url, "width": width, "height": height, "svg": svg, "lines": lines}


def rich_text_block_svg(
    title: str,
    body: str,
    max_width: int,
    color: str,
    title_size: int = 30,
    body_size: int = 26,
    align: str = "left",
    font_family: str = HANDWRITING_FONT,
) -> dict[str, Any]:
    title_lines = wrap_text(title, title_size, max_width) if title else []
    body_lines = wrap_text(body, body_size, max_width) if body else []
    y = int(title_size * 1.05)
    text_nodes: list[str] = []
    max_line_width = 1.0
    centered = align == "center"
    svg_width = max_width + 8
    text_x = svg_width / 2 if centered else 0
    anchor = ' text-anchor="middle"' if centered else ""
    for line in title_lines:
        if line is None:
            y += int(title_size * 0.65)
            continue
        max_line_width = max(max_line_width, token_width(line, title_size))
        text_nodes.append(
            f'<text x="{text_x}" y="{y}" font-size="{title_size}" font-weight="700" '
            f'fill="{color}" font-family="{font_family}"{anchor}>{html.escape(line)}</text>'
        )
        y += int(title_size * 1.45)
    if title_lines and body_lines:
        y += 8
    for line in body_lines:
        if line is None:
            y += int(body_size * 0.85)
            continue
        max_line_width = max(max_line_width, token_width(line, body_size))
        text_nodes.append(
            f'<text x="{text_x}" y="{y}" font-size="{body_size}" fill="{color}" '
            f'font-family="{font_family}"{anchor}>{html.escape(line)}</text>'
        )
        y += int(body_size * 1.58)
    width = svg_width if centered else min(max_width + 8, int(math.ceil(max_line_width)) + 10)
    height = max(1, y - int(body_size * 0.25))
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">' + "".join(text_nodes) + "</svg>"
    )
    data_url = "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode(
        "ascii",
    )
    return {"dataURL": data_url, "width": width, "height": height, "svg": svg}


def element_id(rng: random.Random, prefix: str) -> str:
    chars = "abcdefghijklmnopqrstuvwxyz0123456789"
    return f"{prefix}_" + "".join(rng.choice(chars) for _ in range(16))


def base_element(
    rng: random.Random,
    el_type: str,
    x: float,
    y: float,
    width: float,
    height: float,
    now: int,
) -> dict[str, Any]:
    return {
        "id": element_id(rng, el_type),
        "type": el_type,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "angle": 0,
        "strokeColor": "#1f2937",
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 2,
        "strokeStyle": "solid",
        "roughness": 2,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "roundness": {"type": 3},
        "seed": rng.randint(1, 2**31 - 1),
        "version": 1,
        "versionNonce": rng.randint(1, 2**31 - 1),
        "isDeleted": False,
        "boundElements": None,
        "updated": now,
        "link": None,
        "locked": False,
    }


def rectangle(
    rng: random.Random,
    x: float,
    y: float,
    width: float,
    height: float,
    stroke: str,
    stroke_width: int,
    now: int,
    background: str = "transparent",
    stroke_style: str = "solid",
) -> dict[str, Any]:
    element = base_element(rng, "rectangle", x, y, width, height, now)
    element.update(
        {
            "strokeColor": stroke,
            "backgroundColor": background,
            "strokeWidth": stroke_width,
            "strokeStyle": stroke_style,
        },
    )
    return element


def diamond(
    rng: random.Random,
    x: float,
    y: float,
    width: float,
    height: float,
    stroke: str,
    stroke_width: int,
    now: int,
    background: str = "transparent",
) -> dict[str, Any]:
    element = base_element(rng, "diamond", x, y, width, height, now)
    element.update(
        {
            "strokeColor": stroke,
            "backgroundColor": background,
            "strokeWidth": stroke_width,
        },
    )
    return element


def ellipse(
    rng: random.Random,
    x: float,
    y: float,
    width: float,
    height: float,
    stroke: str,
    stroke_width: int,
    now: int,
    background: str = "transparent",
) -> dict[str, Any]:
    element = base_element(rng, "ellipse", x, y, width, height, now)
    element.update(
        {
            "strokeColor": stroke,
            "backgroundColor": background,
            "strokeWidth": stroke_width,
        },
    )
    return element


def image_element(
    rng: random.Random,
    key: str,
    block: dict[str, Any],
    x: float,
    y: float,
    now: int,
) -> tuple[dict[str, Any], str]:
    file_id = f"{key}_{element_id(rng, 'file')}"
    element = base_element(rng, "image", x, y, block["width"], block["height"], now)
    element.update(
        {
            "strokeColor": "transparent",
            "backgroundColor": "transparent",
            "roundness": None,
            "fileId": file_id,
            "scale": [1, 1],
            "status": "saved",
            "crop": None,
            "customData": {"key": key},
        },
    )
    return element, file_id


def arrow(
    rng: random.Random,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    now: int,
    stroke: str = "#2563eb",
    stroke_width: int = 3,
) -> dict[str, Any]:
    element = base_element(rng, "arrow", x1, y1, x2 - x1, y2 - y1, now)
    element.update(
        {
            "strokeColor": stroke,
            "backgroundColor": "transparent",
            "roundness": None,
            "points": [[0, 0], [x2 - x1, y2 - y1]],
            "lastCommittedPoint": None,
            "startBinding": None,
            "endBinding": None,
            "startArrowhead": None,
            "endArrowhead": "arrow",
            "strokeWidth": stroke_width,
        },
    )
    return element


def routed_arrow(
    rng: random.Random,
    points: list[list[float]],
    now: int,
    stroke: str = "#2563eb",
    stroke_width: int = 3,
) -> dict[str, Any]:
    if len(points) < 2:
        raise ValueError("routed arrows require at least two points")
    x1, y1 = points[0]
    x2, y2 = points[-1]
    element = base_element(rng, "arrow", x1, y1, x2 - x1, y2 - y1, now)
    element.update(
        {
            "strokeColor": stroke,
            "backgroundColor": "transparent",
            "roundness": None,
            "points": [[px - x1, py - y1] for px, py in points],
            "lastCommittedPoint": None,
            "startBinding": None,
            "endBinding": None,
            "startArrowhead": None,
            "endArrowhead": "arrow",
            "strokeWidth": stroke_width,
        },
    )
    return element


def add_image_block(
    elements: list[dict[str, Any]],
    files: dict[str, Any],
    rng: random.Random,
    key: str,
    block: dict[str, Any],
    x: float,
    y: float,
    now: int,
) -> None:
    element, file_id = image_element(rng, key, block, x, y, now)
    elements.append(element)
    files[file_id] = {
        "id": file_id,
        "mimeType": "image/svg+xml",
        "dataURL": block["dataURL"],
        "created": now,
    }


def svg_data_block(svg: str, width: int, height: int) -> dict[str, Any]:
    data_url = "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return {"dataURL": data_url, "width": width, "height": height, "svg": svg}


def component_icon_svg(kind: str, label: str = "", size: int = 72) -> dict[str, Any]:
    kind = (kind or "service").lower()
    palette = {
        "api": ("#e64980", "API"),
        "gateway": ("#e64980", "API"),
        "lambda": ("#fd7e14", "λ"),
        "compute": ("#fd7e14", "λ"),
        "storage": ("#40c057", "S3"),
        "s3": ("#40c057", "S3"),
        "database": ("#4c6ef5", "DB"),
        "db": ("#4c6ef5", "DB"),
        "dynamodb": ("#4c6ef5", "DB"),
        "cache": ("#37b24d", "C"),
        "queue": ("#7950f2", "Q"),
        "cdn": ("#228be6", "CDN"),
        "client": ("#74c0fc", "U"),
        "user": ("#74c0fc", "U"),
        "service": ("#4dabf7", "S"),
    }
    bg, default_text = palette.get(kind, palette["service"])
    text = (label or default_text)[:4]
    radius = 9
    mark = ""
    if kind in {"database", "db", "dynamodb"}:
        mark = (
            '<ellipse cx="36" cy="24" rx="19" ry="8" fill="none" stroke="#fff" stroke-width="4"/>'
            '<path d="M17 24v22c0 5 8 9 19 9s19-4 19-9V24" fill="none" stroke="#fff" stroke-width="4"/>'
            '<path d="M17 36c0 5 8 9 19 9s19-4 19-9" fill="none" stroke="#fff" stroke-width="3"/>'
        )
        text = ""
    elif kind in {"storage", "s3"}:
        mark = (
            '<path d="M21 24h31l-3 33H24z" fill="none" stroke="#fff" stroke-width="4" stroke-linejoin="round"/>'
            '<path d="M25 24c2-5 20-5 23 0" fill="none" stroke="#fff" stroke-width="4"/>'
        )
        text = ""
    elif kind in {"queue"}:
        mark = (
            '<path d="M19 22h34M19 36h34M19 50h34" stroke="#fff" stroke-width="5" stroke-linecap="round"/>'
        )
        text = ""
    elif kind in {"cache"}:
        mark = '<path d="M39 12L22 39h16l-5 22 18-31H35z" fill="none" stroke="#fff" stroke-width="5" stroke-linejoin="round"/>'
        text = ""
    elif kind in {"client", "user"}:
        mark = (
            '<circle cx="36" cy="25" r="10" fill="none" stroke="#fff" stroke-width="4"/>'
            '<path d="M18 58c4-14 32-14 36 0" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round"/>'
        )
        text = ""
    if text:
        mark = (
            f'<text x="36" y="45" text-anchor="middle" font-family="{DIAGRAM_FONT}" '
            f'font-size="22" font-weight="700" fill="#fff">{html.escape(text)}</text>'
        )
    caption = html.escape(label) if label and label != text else ""
    caption_node = (
        f'<text x="36" y="88" text-anchor="middle" font-family="{DIAGRAM_FONT}" '
        f'font-size="12" fill="#1e1e1e">{caption}</text>'
        if caption
        else ""
    )
    height = size + (22 if caption else 0)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{height}" viewBox="0 0 72 {72 + (22 if caption else 0)}">'
        f'<rect x="6" y="6" width="60" height="60" rx="{radius}" fill="{bg}"/>'
        f'{mark}{caption_node}</svg>'
    )
    return svg_data_block(svg, size, height)


def dimension(value: Any, default: float, total: float) -> float:
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if 0 < number <= 1:
        return number * total
    return number


def block_kind(block: dict[str, Any]) -> str:
    return str(block.get("kind") or block.get("type") or block.get("shape") or "concept").lower()


def block_shape(block: dict[str, Any], allow_diamond: bool = True) -> str:
    shape = str(block.get("shape") or "").lower()
    kind = block_kind(block)
    if allow_diamond and (shape in {"diamond", "decision"} or kind in {"decision", "question", "choice"}):
        return "diamond"
    if shape in {"ellipse", "circle", "oval"} or kind in {"client", "actor", "user"}:
        return "ellipse"
    return "rectangle"


def block_stroke(block: dict[str, Any]) -> str:
    kind = block_kind(block)
    if kind in {"warning", "risk", "caveat", "anti-pattern"}:
        return "#b91c1c"
    if kind in {"note", "talk", "talk_track", "example"}:
        return "#111827"
    return "#2563eb"


def normalize_style(content: dict[str, Any]) -> str:
    return str(content.get("style") or content.get("visual_style") or "").strip().lower()


def is_plus_style(content: dict[str, Any]) -> bool:
    style = normalize_style(content)
    if not style and (content.get("task") or content.get("constraints")):
        return True
    return style in PLUS_STYLE_ALIASES


def plus_block_fill(block: dict[str, Any], index: int = 0) -> str:
    if block.get("fill") is not None:
        return str(block.get("fill"))
    if block.get("background") is not None:
        return str(block.get("background"))
    kind = block_kind(block)
    if kind in {"frame", "task", "constraints", "section"}:
        return "transparent"
    if kind in {"client", "actor", "user", "frontend"}:
        return PLUS_CLIENT_FILL
    if kind in {"api", "gateway", "edge", "cdn"}:
        return PLUS_EDGE_BLUE
    if kind in {"database", "db"}:
        return PLUS_DATABASE_GREEN
    if kind in {"cache", "redis"}:
        return PLUS_CACHE_MINT
    if kind in {"queue", "stream", "kafka"}:
        return PLUS_QUEUE_LAVENDER
    if kind in {"storage", "store", "data", "s3", "blob", "file"}:
        return PLUS_STORAGE_GREEN
    if kind in {"note", "callout", "example"}:
        return PLUS_NOTE_GRAY
    if kind in {"question", "followup", "follow-up", "interviewer"}:
        return PLUS_PINK
    if kind in {"caveat", "risk", "tradeoff", "trade-off", "warning"}:
        return PLUS_YELLOW
    if kind in {"answer", "principle", "takeaway", "conclusion"}:
        return PLUS_GREEN
    if kind in {"annotation", "hint"}:
        return PLUS_MINT
    return PLUS_BLUE


def plus_block_stroke(block: dict[str, Any]) -> str:
    return str(block.get("stroke") or PLUS_STROKE)


def plus_text_color(block: dict[str, Any]) -> str:
    return str(block.get("textColor") or block.get("text_color") or PLUS_STROKE)


def fit_text_y(y: float, height: float, text_height: float, preferred_padding: float = 18) -> float:
    free_space = height - text_height
    if free_space <= 0:
        return y
    if free_space < preferred_padding * 2:
        return y + free_space / 2
    return y + max(preferred_padding, free_space / 2)


def plus_icon_name(block: dict[str, Any]) -> str:
    show_icon = any(
        bool(block.get(key))
        for key in ("show_icon", "showIcon", "render_icon", "renderIcon")
    )
    return str(block.get("icon") or "").strip() if show_icon else ""


def coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(f"- {item}" for item in value)
    if isinstance(value, dict):
        parts = []
        if value.get("title"):
            parts.append(str(value["title"]))
        body = value.get("body") or value.get("text") or value.get("items")
        if isinstance(body, list):
            parts.extend(f"- {item}" for item in body)
        elif body:
            parts.append(str(body))
        return "\n".join(parts)
    return str(value)


def normalize_block(raw: Any, index: int) -> dict[str, Any]:
    if isinstance(raw, str):
        return {"id": f"b{index}", "title": raw, "body": "", "kind": "concept"}
    block = dict(raw)
    block.setdefault("id", f"b{index}")
    if "body" not in block:
        block["body"] = block.get("text") or block.get("description") or ""
    block.setdefault("title", block.get("label") or f"Block {index + 1}")
    return block


def auto_positions(
    blocks: list[dict[str, Any]],
    layout: str,
    top: float,
    canvas_width: float,
) -> dict[str, tuple[float, float, float, float]]:
    positions: dict[str, tuple[float, float, float, float]] = {}
    margin = 80
    content_width = canvas_width - 2 * margin
    layout = layout.lower()
    if layout in {"comparison", "tradeoff", "compare"}:
        left_x = margin
        right_x = margin + content_width / 2 + 40
        col_w = content_width / 2 - 40
        left_y = top
        right_y = top
        left_count = 0
        right_count = 0
        for index, block in enumerate(blocks):
            lane = str(block.get("lane") or block.get("side") or "").lower()
            choose_right = lane in {"right", "ap", "availability", "option-b"} or (
                not lane and index % 2 == 1
            )
            x = right_x if choose_right else left_x
            y = right_y if choose_right else left_y
            h = dimension(block.get("height"), 230, 900)
            positions[str(block["id"])] = (x, y, col_w, h)
            if choose_right:
                right_y += h + 42
                right_count += 1
            else:
                left_y += h + 42
                left_count += 1
        return positions

    if layout in {"decision", "decision-tree", "decision_tree"} and blocks:
        first = blocks[0]
        positions[str(first["id"])] = (margin + 520, top, 560, 260)
        branches = blocks[1:4]
        branch_w = 430 if len(branches) == 3 else 520
        gap = (content_width - len(branches) * branch_w) / max(1, len(branches) - 1)
        branch_y = top + 340
        for index, block in enumerate(branches):
            positions[str(block["id"])] = (margin + index * (branch_w + gap), branch_y, branch_w, 250)
        rest_y = branch_y + 330
        for index, block in enumerate(blocks[4:]):
            positions[str(block["id"])] = (margin + (index % 2) * 820, rest_y + (index // 2) * 290, 760, 230)
        return positions

    if layout in {"pipeline", "flow", "sequence"}:
        block_w = 440 if len(blocks) <= 3 else 360
        block_h = 225
        gap = 58
        max_cols = max(1, min(4, int((content_width + gap) // (block_w + gap))))
        start_x = margin + max(0, (content_width - min(len(blocks), max_cols) * block_w - (min(len(blocks), max_cols) - 1) * gap) / 2)
        for index, block in enumerate(blocks):
            row = index // max_cols
            col = index % max_cols
            row_count = min(max_cols, len(blocks) - row * max_cols)
            row_start_x = margin + max(0, (content_width - row_count * block_w - (row_count - 1) * gap) / 2)
            positions[str(block["id"])] = (
                row_start_x + col * (block_w + gap),
                top + row * 330,
                block_w,
                dimension(block.get("height"), block_h, 900),
            )
        return positions

    if layout in {"architecture", "system", "system-design"}:
        rows: dict[str, list[dict[str, Any]]] = {"top": [], "middle": [], "bottom": []}
        for index, block in enumerate(blocks):
            lane = str(block.get("lane") or block.get("tier") or "").lower()
            kind = block_kind(block)
            if lane in rows:
                rows[lane].append(block)
            elif kind in {"client", "actor", "user", "frontend", "edge"}:
                rows["top"].append(block)
            elif kind in {"db", "database", "cache", "queue", "store", "data"}:
                rows["bottom"].append(block)
            else:
                rows["middle"].append(block)
        if not rows["middle"] and rows["bottom"]:
            rows["middle"], rows["bottom"] = rows["bottom"], rows["middle"]
        y_by_row = {"top": top, "middle": top + 310, "bottom": top + 620}
        for row_name, row_blocks in rows.items():
            if not row_blocks:
                continue
            gap = 58
            block_w = min(430, (content_width - gap * (len(row_blocks) - 1)) / max(1, len(row_blocks)))
            block_w = max(320, block_w)
            total_w = len(row_blocks) * block_w + (len(row_blocks) - 1) * gap
            start_x = margin + max(0, (content_width - total_w) / 2)
            for index, block in enumerate(row_blocks):
                positions[str(block["id"])] = (
                    start_x + index * (block_w + gap),
                    y_by_row[row_name],
                    block_w,
                    dimension(block.get("height"), 225, 900),
                )
        return positions

    if layout in {"map", "concept", "concept-map", "concept_map"} and len(blocks) >= 3:
        positions[str(blocks[0]["id"])] = (margin + 580, top + 130, 440, 240)
        ring = blocks[1:]
        coords = [
            (margin, top, 430, 220),
            (margin + 1130, top, 430, 220),
            (margin, top + 360, 430, 220),
            (margin + 1130, top + 360, 430, 220),
            (margin + 560, top + 520, 480, 220),
        ]
        for block, pos in zip(ring, coords):
            positions[str(block["id"])] = pos
        return positions

    cols = min(4, max(1, len(blocks)))
    if len(blocks) > 4:
        cols = 3
    gap = 54
    block_w = (content_width - gap * (cols - 1)) / cols
    block_h = 245
    for index, block in enumerate(blocks):
        row = index // cols
        col = index % cols
        positions[str(block["id"])] = (
            margin + col * (block_w + gap),
            top + row * (block_h + 82),
            block_w,
            dimension(block.get("height"), block_h, 900),
        )
    return positions


def block_center(pos: tuple[float, float, float, float]) -> tuple[float, float]:
    x, y, w, h = pos
    return x + w / 2, y + h / 2


def localized_talk_label(language: str) -> str:
    normalized = language.lower()
    if "chinese" in normalized or "中文" in normalized or "zh" in normalized:
        return "讲稿"
    if "spanish" in normalized or "español" in normalized:
        return "Como decirlo"
    return "Say this"


def connector_points(
    src: tuple[float, float, float, float],
    dst: tuple[float, float, float, float],
    routing: str = "auto",
) -> tuple[float, float, float, float]:
    sx, sy, sw, sh = src
    dx, dy, dw, dh = dst
    scx, scy = sx + sw / 2, sy + sh / 2
    dcx, dcy = dx + dw / 2, dy + dh / 2
    horizontal_gap = max(dx - (sx + sw), sx - (dx + dw), 0)
    vertical_gap = max(dy - (sy + sh), sy - (dy + dh), 0)
    horizontal_clear = horizontal_gap > 0
    vertical_clear = vertical_gap > 0

    routing = routing.lower()
    if routing in {"horizontal", "left-right", "left_right", "lr"}:
        use_horizontal = True
    elif routing in {"vertical", "top-bottom", "top_bottom", "tb"}:
        use_horizontal = False
    elif horizontal_clear and not vertical_clear:
        use_horizontal = True
    elif horizontal_clear and vertical_clear:
        center_dx = abs(dcx - scx)
        center_dy = abs(dcy - scy)
        use_horizontal = not (vertical_gap >= 48 or center_dy >= center_dx * 0.65)
    elif not horizontal_clear and not vertical_clear:
        use_horizontal = abs(dcx - scx) >= abs(dcy - scy)
    else:
        use_horizontal = False

    if use_horizontal:
        start_x = sx + (sw if dcx >= scx else 0)
        end_x = dx + (0 if dcx >= scx else dw)
        return start_x, scy, end_x, dcy

    start_y = sy + (sh if dcy >= scy else 0)
    end_y = dy + (0 if dcy >= scy else dh)
    return scx, start_y, dcx, end_y


def orthogonal_points(
    src: tuple[float, float, float, float],
    dst: tuple[float, float, float, float],
    routing: str = "auto",
    stub: float = 38,
) -> list[list[float]]:
    routing = routing.lower()
    start, start_normal, end, end_normal, primary_axis = connector_ports(src, dst, routing)
    start_stub = [start[0] + start_normal[0] * stub, start[1] + start_normal[1] * stub]
    end_stub = [end[0] + end_normal[0] * stub, end[1] + end_normal[1] * stub]

    if primary_axis == "vertical":
        mid_y = start_stub[1] + (end_stub[1] - start_stub[1]) / 2
        points = [start, start_stub, [start_stub[0], mid_y], [end_stub[0], mid_y], end_stub, end]
    else:
        mid_x = start_stub[0] + (end_stub[0] - start_stub[0]) / 2
        points = [start, start_stub, [mid_x, start_stub[1]], [mid_x, end_stub[1]], end_stub, end]
    return dedupe_points(points)


def connector_ports(
    src: tuple[float, float, float, float],
    dst: tuple[float, float, float, float],
    routing: str = "auto",
) -> tuple[list[float], tuple[int, int], list[float], tuple[int, int], str]:
    sx, sy, sw, sh = src
    dx, dy, dw, dh = dst
    scx, scy = sx + sw / 2, sy + sh / 2
    dcx, dcy = dx + dw / 2, dy + dh / 2
    horizontal_gap = max(dx - (sx + sw), sx - (dx + dw), 0)
    vertical_gap = max(dy - (sy + sh), sy - (dy + dh), 0)
    routing = routing.lower()

    if routing in {"horizontal", "left-right", "left_right", "lr"}:
        primary_axis = "horizontal"
    elif routing in {"vertical", "top-bottom", "top_bottom", "tb"}:
        primary_axis = "vertical"
    elif vertical_gap >= 36:
        primary_axis = "vertical"
    elif horizontal_gap > 0:
        primary_axis = "horizontal"
    elif vertical_gap > 0:
        primary_axis = "vertical"
    else:
        primary_axis = "horizontal" if abs(dcx - scx) >= abs(dcy - scy) else "vertical"

    if primary_axis == "vertical":
        if dcy >= scy:
            return [scx, sy + sh], (0, 1), [dcx, dy], (0, -1), primary_axis
        return [scx, sy], (0, -1), [dcx, dy + dh], (0, 1), primary_axis

    if dcx >= scx:
        return [sx + sw, scy], (1, 0), [dx, dcy], (-1, 0), primary_axis
    return [sx, scy], (-1, 0), [dx + dw, dcy], (1, 0), primary_axis


def simplify_points(points: list[list[float]]) -> list[list[float]]:
    simplified: list[list[float]] = []
    for point in points:
        item = [float(point[0]), float(point[1])]
        if simplified and abs(simplified[-1][0] - item[0]) < 0.001 and abs(simplified[-1][1] - item[1]) < 0.001:
            continue
        if len(simplified) >= 2:
            prev = simplified[-1]
            prev_prev = simplified[-2]
            if (abs(prev_prev[0] - prev[0]) < 0.001 and abs(prev[0] - item[0]) < 0.001) or (
                abs(prev_prev[1] - prev[1]) < 0.001 and abs(prev[1] - item[1]) < 0.001
            ):
                simplified[-1] = item
                continue
        simplified.append(item)
    return simplified


def dedupe_points(points: list[list[float]]) -> list[list[float]]:
    deduped: list[list[float]] = []
    for point in points:
        item = [float(point[0]), float(point[1])]
        if deduped and abs(deduped[-1][0] - item[0]) < 0.001 and abs(deduped[-1][1] - item[1]) < 0.001:
            continue
        deduped.append(item)
    return deduped


def inflated_rect(
    rect: tuple[float, float, float, float],
    padding: float,
) -> tuple[float, float, float, float]:
    x, y, w, h = rect
    return x - padding, y - padding, w + padding * 2, h + padding * 2


def segment_intersects_rect(
    p1: list[float],
    p2: list[float],
    rect: tuple[float, float, float, float],
) -> bool:
    x, y, w, h = rect
    left, right = sorted((x, x + w))
    top, bottom = sorted((y, y + h))
    x1, y1 = p1
    x2, y2 = p2
    if abs(y1 - y2) < 0.001:
        seg_left, seg_right = sorted((x1, x2))
        return top <= y1 <= bottom and max(seg_left, left) <= min(seg_right, right)
    if abs(x1 - x2) < 0.001:
        seg_top, seg_bottom = sorted((y1, y2))
        return left <= x1 <= right and max(seg_top, top) <= min(seg_bottom, bottom)
    return False


def segment_clear(
    p1: list[float],
    p2: list[float],
    obstacles: list[tuple[float, float, float, float]],
) -> bool:
    return not any(segment_intersects_rect(p1, p2, obstacle) for obstacle in obstacles)


def rects_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return max(ax, bx) <= min(ax + aw, bx + bw) and max(ay, by) <= min(ay + ah, by + bh)


def route_around_obstacles(
    src: tuple[float, float, float, float],
    dst: tuple[float, float, float, float],
    obstacles: list[tuple[float, float, float, float]],
    routing: str = "auto",
    canvas_width: float = 1500,
) -> list[list[float]]:
    base = orthogonal_points(src, dst, routing)
    for stub in (38, 26, 16, 8):
        candidate = orthogonal_points(src, dst, routing, stub=stub)
        fixed_segments_clear = True
        if len(candidate) > 2:
            fixed_segments_clear = segment_clear(candidate[0], candidate[1], obstacles) and segment_clear(candidate[-2], candidate[-1], obstacles)
        if fixed_segments_clear:
            base = candidate
            break
    if all(segment_clear(base[index], base[index + 1], obstacles) for index in range(len(base) - 1)):
        return base

    start_port = base[0]
    end_port = base[-1]
    start = base[1] if len(base) > 2 else base[0]
    end = base[-2] if len(base) > 2 else base[-1]
    xs = {round(start[0], 1), round(end[0], 1), 40.0, round(canvas_width - 40, 1)}
    ys = {round(start[1], 1), round(end[1], 1)}
    for x, y, w, h in obstacles:
        xs.update({round(x, 1), round(x + w, 1), round(x - 36, 1), round(x + w + 36, 1)})
        ys.update({round(y, 1), round(y + h, 1), round(y - 36, 1), round(y + h + 36, 1)})
    xs = {x for x in xs if -80 <= x <= canvas_width + 80}

    points = [(x, y) for x in xs for y in ys]
    start_t = (round(start[0], 1), round(start[1], 1))
    end_t = (round(end[0], 1), round(end[1], 1))
    if start_t not in points:
        points.append(start_t)
    if end_t not in points:
        points.append(end_t)

    graph: dict[tuple[float, float], list[tuple[float, tuple[float, float]]]] = {point: [] for point in points}
    by_x: dict[float, list[tuple[float, float]]] = {}
    by_y: dict[float, list[tuple[float, float]]] = {}
    for point in points:
        by_x.setdefault(point[0], []).append(point)
        by_y.setdefault(point[1], []).append(point)

    def add_axis_edges(axis_points: list[tuple[float, float]]) -> None:
        for a_index, a in enumerate(axis_points):
            for b in axis_points[a_index + 1 :]:
                if a[0] != b[0] and a[1] != b[1]:
                    continue
                pa = [a[0], a[1]]
                pb = [b[0], b[1]]
                if segment_clear(pa, pb, obstacles):
                    distance = abs(a[0] - b[0]) + abs(a[1] - b[1])
                    graph[a].append((distance, b))
                    graph[b].append((distance, a))

    for axis_points in by_x.values():
        add_axis_edges(sorted(axis_points, key=lambda point: point[1]))
    for axis_points in by_y.values():
        add_axis_edges(sorted(axis_points, key=lambda point: point[0]))

    import heapq

    queue: list[tuple[float, int, tuple[float, float], Any]] = []
    heapq.heappush(queue, (0.0, 0, start_t, None))
    best: dict[tuple[float, float], float] = {start_t: 0.0}
    previous: dict[tuple[float, float], Any] = {start_t: None}

    while queue:
        cost, bends, current, incoming_dir = heapq.heappop(queue)
        if current == end_t:
            break
        if cost > best.get(current, float("inf")) + 0.001:
            continue
        for distance, neighbor in graph[current]:
            direction = (
                0 if abs(neighbor[0] - current[0]) < 0.001 else 1,
                0 if abs(neighbor[1] - current[1]) < 0.001 else 1,
            )
            bend_penalty = 80 if incoming_dir is not None and direction != incoming_dir else 0
            new_cost = cost + distance + bend_penalty
            if new_cost + 0.001 < best.get(neighbor, float("inf")):
                best[neighbor] = new_cost
                previous[neighbor] = current
                heapq.heappush(queue, (new_cost, bends + (1 if bend_penalty else 0), neighbor, direction))

    if end_t not in previous:
        return base

    route: list[tuple[float, float]] = []
    cursor: Any = end_t
    while cursor is not None:
        route.append(cursor)
        cursor = previous.get(cursor)
    route.reverse()

    routed = simplify_points([[float(point[0]), float(point[1])] for point in route])
    return dedupe_points([start_port, *routed, end_port])


def route_connector_points(
    src_id: str,
    dst_id: str,
    positions: dict[str, tuple[float, float, float, float]],
    routing: str,
    canvas_width: float,
) -> list[list[float]]:
    obstacles = [
        inflated_rect(pos, 12)
        for block_id, pos in positions.items()
        if block_id not in {src_id, dst_id}
    ]
    return route_around_obstacles(positions[src_id], positions[dst_id], obstacles, routing, canvas_width)


def label_bounds(x: float, y: float, block: dict[str, Any]) -> tuple[float, float, float, float]:
    return x, y, float(block["width"]), float(block["height"])


def connector_label_width(
    src: tuple[float, float, float, float],
    dst: tuple[float, float, float, float],
) -> int:
    sx, sy, sw, sh = src
    dx, dy, dw, dh = dst
    horizontal_gap = max(dx - (sx + sw), sx - (dx + dw), 0)
    vertical_overlap = max(sy, dy) < min(sy + sh, dy + dh)
    if horizontal_gap > 0 and vertical_overlap:
        clear_width = horizontal_gap - 2 * CONNECTOR_LABEL_OBSTACLE_PADDING - 18
        return int(max(54, min(CONNECTOR_LABEL_MAX_WIDTH, clear_width)))
    return CONNECTOR_LABEL_MAX_WIDTH


def rect_overlap_area(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    overlap_w = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    overlap_h = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    return overlap_w * overlap_h


def rect_to_segment_distance(
    rect: tuple[float, float, float, float],
    p1: list[float],
    p2: list[float],
) -> float:
    x, y, w, h = rect
    left, top, right, bottom = x, y, x + w, y + h
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


def rect_to_polyline_distance(rect: tuple[float, float, float, float], points: list[list[float]]) -> float:
    return min(
        rect_to_segment_distance(rect, points[index], points[index + 1])
        for index in range(len(points) - 1)
    )


def choose_label_position(
    points: list[list[float]],
    label_block: dict[str, Any],
    obstacles: list[tuple[float, float, float, float]],
    canvas_width: float,
    dx: float = 0,
    dy: float = 0,
) -> tuple[float, float]:
    candidates: list[tuple[float, float, int]] = []
    for index in range(len(points) - 1):
        x1, y1 = points[index]
        x2, y2 = points[index + 1]
        length = abs(x2 - x1) + abs(y2 - y1)
        fractions = [0.5]
        if length > 170:
            fractions.extend([0.35, 0.65])
        if length > 310:
            fractions.extend([0.2, 0.8])
        if abs(y1 - y2) < 0.001:
            for fraction in fractions:
                anchor_x = x1 + (x2 - x1) * fraction
                candidates.extend(
                    [
                        (
                            anchor_x - label_block["width"] / 2,
                            y1 - label_block["height"] - CONNECTOR_LABEL_GAP,
                            index,
                        ),
                        (anchor_x - label_block["width"] / 2, y1 + CONNECTOR_LABEL_GAP, index),
                    ],
                )
        elif abs(x1 - x2) < 0.001:
            for fraction in fractions:
                anchor_y = y1 + (y2 - y1) * fraction
                candidates.extend(
                    [
                        (x1 + CONNECTOR_LABEL_GAP, anchor_y - label_block["height"] / 2, index),
                        (
                            x1 - label_block["width"] - CONNECTOR_LABEL_GAP,
                            anchor_y - label_block["height"] / 2,
                            index,
                        ),
                    ],
                )
    mid = points[len(points) // 2]
    candidates.append((mid[0] - label_block["width"] / 2, mid[1] - label_block["height"] / 2, max(0, len(points) // 2 - 1)))

    inflated = [inflated_rect(obstacle, CONNECTOR_LABEL_OBSTACLE_PADDING) for obstacle in obstacles]

    def score(candidate_x: float, candidate_y: float) -> tuple[float, float]:
        bounds = label_bounds(candidate_x, candidate_y, label_block)
        overlap = sum(rect_overlap_area(bounds, obstacle) for obstacle in inflated)
        distance = rect_to_polyline_distance(bounds, points)
        return overlap, distance

    def usable(candidate_x: float, candidate_y: float) -> bool:
        bounds = label_bounds(candidate_x, candidate_y, label_block)
        if candidate_x < 10 or candidate_x + label_block["width"] > canvas_width - 10:
            return False
        return not any(rects_overlap(bounds, obstacle) for obstacle in inflated)

    best_usable: tuple[float, float, tuple[float, float]] | None = None
    for x, y, segment_index in candidates:
        x += dx
        y += dy
        if usable(x, y):
            _overlap, distance = score(x, y)
            ranked_score = (distance, float(segment_index))
            if best_usable is None or ranked_score < best_usable[2]:
                best_usable = (x, y, ranked_score)
    if best_usable is not None:
        return best_usable[0], best_usable[1]

    base_candidates = list(candidates)
    for radius in (12, 24, 40, 60):
        offsets = [
            (0, -radius),
            (0, radius),
            (-radius, 0),
            (radius, 0),
            (-radius, -radius),
            (radius, -radius),
            (-radius, radius),
            (radius, radius),
        ]
        for base_x, base_y, _segment_index in base_candidates:
            for ox, oy in offsets:
                x = base_x + dx + ox
                y = base_y + dy + oy
                if usable(x, y):
                    return x, y

    scored: list[tuple[float, float, float, float]] = []
    for x, y, _segment_index in candidates:
        x += dx
        y += dy
        overlap, distance = score(x, y)
        scored.append((overlap, distance, x, y))
    _, _, x, y = min(scored)
    return x, y


def centered_right_angle_points(
    src: tuple[float, float, float, float],
    dst: tuple[float, float, float, float],
) -> list[list[float]]:
    sx, sy, sw, sh = src
    dx, dy, dw, _ = dst
    start_x = sx + sw / 2
    start_y = sy + sh
    end_x = dx + dw / 2
    end_y = dy
    mid_y = start_y + max(36, (end_y - start_y) / 2)
    if abs(start_x - end_x) < 4:
        return [[start_x, start_y], [end_x, end_y]]
    return [[start_x, start_y], [start_x, mid_y], [end_x, mid_y], [end_x, end_y]]


def add_top_frame(
    elements: list[dict[str, Any]],
    files: dict[str, Any],
    blocks_svg: dict[str, Any],
    rng: random.Random,
    key: str,
    title: str,
    body: str,
    x: float,
    y: float,
    w: float,
    h: float,
    now: int,
) -> None:
    elements.append(
        rectangle(
            rng,
            x,
            y,
            w,
            h,
            PLUS_STROKE,
            2,
            now,
            background="transparent",
            stroke_style="solid",
        ),
    )
    title_width = int(w - 56)
    body_width = int(w - 56)
    title_size = 31 if len(title) > 12 else 34
    body_size = 22 if len(body) > 120 else 24
    title_block = text_block_svg(title, title_size, title_width, PLUS_STROKE, 5, 10, DIAGRAM_FONT)
    body_block = text_block_svg(body, body_size, body_width, PLUS_STROKE, 5, 9, DIAGRAM_FONT)
    blocks_svg[f"{key}_title"] = title_block
    blocks_svg[f"{key}_body"] = body_block
    title_x = x + 28
    title_y = y + 22
    add_image_block(elements, files, rng, f"{key}_title", title_block, title_x, title_y, now)
    underline_width = min(max(120, title_block["width"] * 0.95), w - 64)
    elements.append(
        rectangle(
            rng,
            title_x,
            title_y + title_block["height"] - 7,
            underline_width,
            4,
            str(PLUS_BLUE),
            1,
            now,
            background=str(PLUS_BLUE),
        ),
    )
    body_y = title_y + title_block["height"] + 20
    add_image_block(elements, files, rng, f"{key}_body", body_block, x + 28, body_y, now)


def add_module_frame(
    elements: list[dict[str, Any]],
    files: dict[str, Any],
    blocks_svg: dict[str, Any],
    rng: random.Random,
    frame: dict[str, Any],
    now: int,
) -> None:
    x = float(frame["x"])
    y = float(frame["y"])
    w = float(frame["w"])
    h = float(frame["h"])
    frame_element = rectangle(
        rng,
        x,
        y,
        w,
        h,
        PLUS_STROKE,
        2,
        now,
        background="transparent",
        stroke_style="dashed",
    )
    frame_element["customData"] = {
        "role": "module_frame",
        "moduleId": str(frame.get("id") or ""),
    }
    elements.append(frame_element)

    title = str(frame.get("title") or frame.get("id") or "Module")
    title_block = text_block_svg(title, 25, int(w - 48), PLUS_STROKE, 5, 9, DIAGRAM_FONT, align="left")
    key = f"wb_module_{frame.get('id')}_title"
    blocks_svg[key] = title_block
    add_image_block(elements, files, rng, key, title_block, x + 24, y + 18, now)


def add_whiteboard_text(
    elements: list[dict[str, Any]],
    files: dict[str, Any],
    blocks_svg: dict[str, Any],
    rng: random.Random,
    key: str,
    text: str,
    x: float,
    y: float,
    max_width: int,
    size: int,
    now: int,
    color: str = PLUS_STROKE,
    align: str = "center",
) -> dict[str, Any]:
    block = text_block_svg(text, size, max_width, color, 8, 12, DIAGRAM_FONT, align=align)
    blocks_svg[key] = block
    add_image_block(elements, files, rng, key, block, x, y, now)
    return block


def whiteboard_block_min_height(block: dict[str, Any], width: float, default_height: float) -> float:
    icon_name = plus_icon_name(block)
    icon_space = 92 if icon_name and width > 260 else 0
    text_width = int(max(130, width - 40 - icon_space))
    shape = str(block.get("shape") or "").lower()
    kind = block_kind(block)
    default_align = "center" if shape in {"circle", "ellipse", "oval"} or kind in {"client", "actor", "user"} else "left"
    text_block = rich_text_block_svg(
        str(block.get("title") or ""),
        str(block.get("body") or ""),
        text_width,
        plus_text_color(block),
        int(block.get("title_size") or 28),
        int(block.get("body_size") or 20),
        align=str(block.get("align") or default_align).lower(),
        font_family=DIAGRAM_FONT,
    )
    explicit_height = dimension(block.get("height") or block.get("h"), default_height, 900)
    return max(explicit_height, text_block["height"] + 48)


def normalize_module_key(value: Any) -> str:
    text = str(value or "main").strip().lower()
    if not text:
        return "main"
    text = re.sub(r"[^\w\u3400-\u9fff-]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "main"


def block_module_key(block: dict[str, Any]) -> str:
    return normalize_module_key(
        block.get("module")
        or block.get("section")
        or block.get("group")
        or block.get("cluster")
        or "main",
    )


def module_specs(content: dict[str, Any], blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    planning = content.get("planning") if isinstance(content.get("planning"), dict) else {}
    raw_modules = content.get("modules") or planning.get("modules") or []
    specs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_modules):
        if isinstance(raw, str):
            spec = {"id": raw, "title": raw}
        elif isinstance(raw, dict):
            spec = dict(raw)
        else:
            continue
        module_id = normalize_module_key(spec.get("id") or spec.get("key") or spec.get("title") or f"module-{index + 1}")
        if module_id in seen:
            continue
        spec["id"] = module_id
        spec.setdefault("title", str(raw) if isinstance(raw, str) else module_id.replace("-", " ").title())
        specs.append(spec)
        seen.add(module_id)

    for block in blocks:
        module_id = block_module_key(block)
        if module_id in seen:
            continue
        specs.append({"id": module_id, "title": module_id.replace("-", " ").title()})
        seen.add(module_id)
    return specs


def is_full_width_module(spec: dict[str, Any], index: int, total: int) -> bool:
    if bool(spec.get("full_width") or spec.get("fullWidth")):
        return True
    text = f"{spec.get('id', '')} {spec.get('title', '')} {spec.get('layout', '')}".lower()
    if any(token in text for token in ("overview", "context", "topology", "系统概览", "全局", "总览")):
        return True
    return index == 0 and total > 4 and str(spec.get("layout") or "").lower() in {"architecture", "overview"}


def module_column_count(spec: dict[str, Any], frame_w: float, block_count: int) -> int:
    requested = spec.get("columns") or spec.get("cols")
    if requested is not None:
        return max(1, min(4, int(dimension(requested, 1, 4))))
    layout = str(spec.get("layout") or "").lower()
    if frame_w >= 1120 and block_count >= 3:
        return 3
    if frame_w >= 930 and block_count >= 2 and layout in {"pipeline", "flow", "architecture", "overview"}:
        return 2
    return 1


def layout_module_content(
    module_blocks: list[dict[str, Any]],
    spec: dict[str, Any],
    frame_x: float,
    frame_y: float,
    frame_w: float,
) -> tuple[dict[str, tuple[float, float, float, float]], float]:
    positions: dict[str, tuple[float, float, float, float]] = {}
    padding_x = 26
    padding_bottom = 28
    title_area = 66
    block_gap_x = 34
    block_gap_y = 30
    cols = module_column_count(spec, frame_w, len(module_blocks))
    inner_w = frame_w - padding_x * 2
    block_w = (inner_w - block_gap_x * (cols - 1)) / cols
    y_cursor = frame_y + title_area

    for row_start in range(0, len(module_blocks), cols):
        row_blocks = module_blocks[row_start : row_start + cols]
        heights = [
            whiteboard_block_min_height(
                block,
                block_w,
                150 if frame_w < 900 else 160,
            )
            for block in row_blocks
        ]
        row_height = max(heights, default=150)
        row_count = len(row_blocks)
        row_w = row_count * block_w + max(0, row_count - 1) * block_gap_x
        x0 = frame_x + padding_x + max(0, (inner_w - row_w) / 2)
        for index, block in enumerate(row_blocks):
            x = x0 + index * (block_w + block_gap_x)
            h = heights[index]
            positions[str(block["id"])] = (x, y_cursor + (row_height - h) / 2, block_w, h)
        y_cursor += row_height + block_gap_y

    frame_h = max(180, y_cursor - frame_y - block_gap_y + padding_bottom)
    return positions, frame_h


def whiteboard_modular_positions(
    content: dict[str, Any],
    blocks: list[dict[str, Any]],
    top: float,
    canvas_width: float,
) -> tuple[dict[str, tuple[float, float, float, float]], list[dict[str, Any]]]:
    margin = 70
    content_width = canvas_width - 2 * margin
    specs = module_specs(content, blocks)
    groups: dict[str, list[dict[str, Any]]] = {str(spec["id"]): [] for spec in specs}
    for block in blocks:
        module_id = block_module_key(block)
        groups.setdefault(module_id, []).append(block)

    visible_specs = [spec for spec in specs if groups.get(str(spec["id"]))]
    positions: dict[str, tuple[float, float, float, float]] = {}
    frames: list[dict[str, Any]] = []
    full_specs: list[dict[str, Any]] = []
    regular_specs: list[dict[str, Any]] = []
    for index, spec in enumerate(visible_specs):
        if is_full_width_module(spec, index, len(visible_specs)):
            full_specs.append(spec)
        else:
            regular_specs.append(spec)

    y_cursor = top
    frame_gap_y = 56
    for spec in full_specs:
        frame_x = margin
        frame_w = content_width
        module_positions, frame_h = layout_module_content(groups[str(spec["id"])], spec, frame_x, y_cursor, frame_w)
        positions.update(module_positions)
        frames.append({"id": spec["id"], "title": spec.get("title") or spec["id"], "x": frame_x, "y": y_cursor, "w": frame_w, "h": frame_h})
        y_cursor += frame_h + frame_gap_y

    frame_gap_x = 62
    frame_w = (content_width - frame_gap_x) / 2
    for row_start in range(0, len(regular_specs), 2):
        row_specs = regular_specs[row_start : row_start + 2]
        row_frames: list[dict[str, Any]] = []
        row_positions: list[dict[str, tuple[float, float, float, float]]] = []
        row_heights: list[float] = []
        for index, spec in enumerate(row_specs):
            actual_frame_w = content_width if len(row_specs) == 1 else frame_w
            frame_x = margin if len(row_specs) == 1 or index == 0 else margin + frame_w + frame_gap_x
            module_positions, frame_h = layout_module_content(groups[str(spec["id"])], spec, frame_x, y_cursor, actual_frame_w)
            row_positions.append(module_positions)
            row_heights.append(frame_h)
            row_frames.append(
                {
                    "id": spec["id"],
                    "title": spec.get("title") or spec["id"],
                    "x": frame_x,
                    "y": y_cursor,
                    "w": actual_frame_w,
                    "h": frame_h,
                },
            )
        row_h = max(row_heights, default=180)
        for frame in row_frames:
            frame["h"] = row_h
            frames.append(frame)
        for module_positions in row_positions:
            positions.update(module_positions)
        y_cursor += row_h + frame_gap_y
    return positions, frames


def top_frame_min_height(title: str, body: str, width: float) -> float:
    title_width = int(width - 56)
    body_width = int(width - 56)
    title_size = 31 if len(title) > 12 else 34
    body_size = 22 if len(body) > 120 else 24
    title_block = text_block_svg(title, title_size, title_width, PLUS_STROKE, 5, 10, DIAGRAM_FONT)
    body_block = text_block_svg(body, body_size, body_width, PLUS_STROKE, 5, 9, DIAGRAM_FONT)
    return max(135, title_block["height"] + body_block["height"] + 70)


def add_whiteboard_block(
    elements: list[dict[str, Any]],
    files: dict[str, Any],
    blocks_svg: dict[str, Any],
    rng: random.Random,
    block: dict[str, Any],
    pos: tuple[float, float, float, float],
    index: int,
    now: int,
) -> None:
    x, y, w, h = pos
    shape = str(block.get("shape") or "").lower()
    kind = block_kind(block)
    if shape in {"circle", "ellipse", "oval"} or kind in {"client", "actor", "user"}:
        shape_element = ellipse(rng, x, y, w, h, plus_block_stroke(block), 2, now, background=plus_block_fill(block, index))
    else:
        if shape == "square":
            size = min(w, h)
            x += (w - size) / 2
            y += (h - size) / 2
            w = h = size
        shape_element = rectangle(
            rng,
            x,
            y,
            w,
            h,
            plus_block_stroke(block),
            int(block.get("strokeWidth") or 2),
            now,
            background=plus_block_fill(block, index),
            stroke_style=str(block.get("strokeStyle") or block.get("stroke_style") or "solid"),
        )
    shape_element["customData"] = {"role": "block", "blockId": str(block["id"])}
    elements.append(shape_element)

    icon_name = plus_icon_name(block)
    icon_space = 92 if icon_name and w > 260 else 0
    text_x = x + 22 + icon_space
    text_w = int(max(130, w - 44 - icon_space))
    default_align = "center" if shape in {"circle", "ellipse", "oval"} or kind in {"client", "actor", "user"} else "left"
    text_block = rich_text_block_svg(
        str(block.get("title") or ""),
        str(block.get("body") or ""),
        text_w,
        plus_text_color(block),
        int(block.get("title_size") or 28),
        int(block.get("body_size") or 20),
        align=str(block.get("align") or default_align).lower(),
        font_family=DIAGRAM_FONT,
    )
    key = f"wb_block_{block['id']}"
    blocks_svg[key] = text_block
    text_y = fit_text_y(y, h, text_block["height"])
    align = str(block.get("align") or default_align).lower()
    if icon_space:
        text_x = x + icon_space + (w - icon_space - text_block["width"]) / 2
    elif align == "center":
        text_x = x + (w - text_block["width"]) / 2
    add_image_block(elements, files, rng, key, text_block, text_x, text_y, now)

    if icon_name:
        icon = component_icon_svg(icon_name, str(block.get("icon_label") or block.get("iconLabel") or ""), int(block.get("icon_size") or 66))
        icon_key = f"wb_icon_{block['id']}"
        blocks_svg[icon_key] = icon
        add_image_block(elements, files, rng, icon_key, icon, x + 18, y + h - icon["height"] - 16, now)


def whiteboard_positions(
    blocks: list[dict[str, Any]],
    layout: str,
    top: float,
    canvas_width: float,
) -> dict[str, tuple[float, float, float, float]]:
    layout = layout.lower()
    positions: dict[str, tuple[float, float, float, float]] = {}
    margin = 70
    content_width = canvas_width - 2 * margin
    if layout in {"decision", "decision-tree", "decision_tree"} and blocks:
        center_w = 520
        center_h = whiteboard_block_min_height(blocks[0], center_w, 165)
        positions[str(blocks[0]["id"])] = (canvas_width / 2 - center_w / 2, top, center_w, center_h)
        branches = blocks[1:3]
        branch_w = 460
        branch_heights = [whiteboard_block_min_height(block, branch_w, 165) for block in branches]
        branch_y = top + center_h + 88
        if len(branches) == 1:
            positions[str(branches[0]["id"])] = (canvas_width / 2 - branch_w / 2, branch_y, branch_w, branch_heights[0])
        elif len(branches) >= 2:
            positions[str(branches[0]["id"])] = (margin, branch_y, branch_w, branch_heights[0])
            positions[str(branches[1]["id"])] = (canvas_width - margin - branch_w, branch_y, branch_w, branch_heights[1])
        rest = blocks[3:]
        y_cursor = branch_y + (max(branch_heights) if branch_heights else 0) + 88
        for row_start in range(0, len(rest), 2):
            row_blocks = rest[row_start : row_start + 2]
            row_width = 520 if len(row_blocks) == 1 else 420
            gap = 100
            total = len(row_blocks) * row_width + max(0, len(row_blocks) - 1) * gap
            start_x = (canvas_width - total) / 2
            row_heights = [whiteboard_block_min_height(block, row_width, 150) for block in row_blocks]
            row_height = max(row_heights, default=150)
            for index, block in enumerate(row_blocks):
                positions[str(block["id"])] = (start_x + index * (row_width + gap), y_cursor, row_width, row_heights[index])
            y_cursor += row_height + 78
        return positions

    if layout in {"comparison", "tradeoff", "compare"}:
        left = [block for index, block in enumerate(blocks) if str(block.get("lane") or block.get("side") or ("left" if index % 2 == 0 else "right")).lower() not in {"right", "ap", "availability", "option-b"}]
        right = [block for index, block in enumerate(blocks) if block not in left]
        left_x = margin
        col_w = min(600, (content_width - 170) / 2)
        right_x = canvas_width - margin - col_w
        gap_y = 74
        for lane_blocks, x in ((left, left_x), (right, right_x)):
            y = top
            for block in lane_blocks:
                h = whiteboard_block_min_height(block, col_w, 180)
                positions[str(block["id"])] = (x, y, col_w, h)
                y += h + gap_y
        return positions

    if layout in {"pipeline", "flow", "sequence"}:
        desired_w = 410 if len(blocks) > 3 else 460
        block_h = 155
        gap = 180
        max_cols = max(1, min(len(blocks), int((content_width + gap) // (desired_w + gap))))
        y_cursor = top
        for row_start in range(0, len(blocks), max_cols):
            row_blocks = blocks[row_start : row_start + max_cols]
            row_count = len(row_blocks)
            row_w = (
                (content_width - max(0, row_count - 1) * gap) / row_count
                if row_count > 1
                else min(620, content_width)
            )
            total = row_count * row_w + max(0, row_count - 1) * gap
            start_x = margin + max(0, (content_width - total) / 2)
            widths = [dimension(block.get("width") or block.get("w"), row_w, canvas_width) for block in row_blocks]
            heights = [whiteboard_block_min_height(block, widths[index], block_h) for index, block in enumerate(row_blocks)]
            row_height = max(heights, default=block_h)
            x_cursor = start_x
            for index, block in enumerate(row_blocks):
                positions[str(block["id"])] = (x_cursor, y_cursor, widths[index], heights[index])
                x_cursor += widths[index] + gap
            y_cursor += row_height + 88
        return positions

    if layout in {"architecture", "system", "system-design"}:
        rows: dict[str, list[dict[str, Any]]] = {"top": [], "middle": [], "bottom": []}
        for block in blocks:
            lane = str(block.get("lane") or block.get("tier") or "").lower()
            kind = block_kind(block)
            if lane in rows:
                rows[lane].append(block)
            elif kind in {"client", "actor", "user", "frontend"}:
                rows["top"].append(block)
            elif kind in {"database", "db", "cache", "queue", "storage", "store", "data"}:
                rows["bottom"].append(block)
            else:
                rows["middle"].append(block)
        y_cursor = top
        for row, row_blocks in rows.items():
            if not row_blocks:
                continue
            gap = 188
            row_widths: list[float] = []
            flexible_indexes: list[int] = []
            fixed_total = 0.0
            for index, block in enumerate(row_blocks):
                shape = str(block.get("shape") or "").lower()
                kind = block_kind(block)
                explicit_width = block.get("width") or block.get("w")
                if explicit_width is not None:
                    width = dimension(explicit_width, 320, canvas_width)
                    row_widths.append(width)
                    fixed_total += width
                elif shape in {"circle", "ellipse"} or kind in {"client", "actor", "user"}:
                    width = 250 if len(row_blocks) > 1 else 220
                    row_widths.append(width)
                    fixed_total += width
                else:
                    row_widths.append(0)
                    flexible_indexes.append(index)
            remaining = content_width - max(0, len(row_blocks) - 1) * gap - fixed_total
            flex_w = max(300, remaining / max(1, len(flexible_indexes))) if flexible_indexes else 0
            for index in flexible_indexes:
                row_widths[index] = flex_w
            total = sum(row_widths) + max(0, len(row_blocks) - 1) * gap
            x0 = margin if len(row_blocks) > 1 else (canvas_width - total) / 2
            row_items: list[tuple[dict[str, Any], float, float, float]] = []
            x_cursor = x0
            for index, block in enumerate(row_blocks):
                shape = str(block.get("shape") or "").lower()
                kind = block_kind(block)
                default_h = 170
                w = row_widths[index]
                if shape in {"circle", "ellipse"} or kind in {"client", "actor", "user"}:
                    default_h = 210 if len(row_blocks) > 1 else 180
                h = whiteboard_block_min_height(block, w, default_h)
                row_items.append((block, x_cursor, w, h))
                x_cursor += w + gap
            row_height = max((item[3] for item in row_items), default=170)
            for block, x, w, h in row_items:
                positions[str(block["id"])] = (x, y_cursor + (row_height - h) / 2, w, h)
            y_cursor += row_height + 84
        return positions

    if layout in {"map", "concept", "concept-map", "concept_map"} and blocks:
        center_w = 560
        center_h = whiteboard_block_min_height(blocks[0], center_w, 180)
        center_y = top + 190
        positions[str(blocks[0]["id"])] = (canvas_width / 2 - center_w / 2, center_y, center_w, center_h)
        top_w = 390
        bottom_w = 390
        bottom_y = center_y + center_h + 92
        slot_specs = [
            (margin, top, top_w, 150),
            (canvas_width - margin - top_w, top, top_w, 150),
            (margin, bottom_y, bottom_w, 150),
            (canvas_width - margin - bottom_w, bottom_y, bottom_w, 150),
            (canvas_width / 2 - 240, bottom_y + 230, 480, 150),
        ]
        for index, block in enumerate(blocks[1:]):
            if index < len(slot_specs):
                x, y, w, default_h = slot_specs[index]
            else:
                w = 420
                x = margin + ((index - len(slot_specs)) % 3) * 470
                y = bottom_y + 450 + ((index - len(slot_specs)) // 3) * 230
                default_h = 150
            h = whiteboard_block_min_height(block, w, default_h)
            positions[str(block["id"])] = (x, y, w, h)
        return positions

    cols = min(3, max(1, len(blocks)))
    gap = 62
    block_w = (content_width - gap * (cols - 1)) / cols
    y_cursor = top
    for row_start in range(0, len(blocks), cols):
        row_blocks = blocks[row_start : row_start + cols]
        heights = [whiteboard_block_min_height(block, block_w, 160) for block in row_blocks]
        row_height = max(heights, default=160)
        for index, block in enumerate(row_blocks):
            positions[str(block["id"])] = (margin + index * (block_w + gap), y_cursor, block_w, heights[index])
        y_cursor += row_height + 82
    return positions


def build_whiteboard_scene(content: dict[str, Any], slug: str) -> tuple[dict[str, Any], dict[str, Any], int, int]:
    rng = random.Random(20260620)
    now = int(time.time() * 1000)
    canvas_width = int(dimension(content.get("width"), 1500, 1500))
    margin = 70
    content_width = canvas_width - margin * 2
    elements: list[dict[str, Any]] = []
    files: dict[str, Any] = {}
    blocks_svg: dict[str, Any] = {}

    title = str(content.get("title") or "Interview Whiteboard")
    title_block = add_whiteboard_text(
        elements,
        files,
        blocks_svg,
        rng,
        "wb_title",
        title,
        0,
        52,
        canvas_width,
        44,
        now,
        align="center",
    )
    y_cursor = 52 + title_block["height"] + 34
    summary = str(content.get("summary") or "")
    if summary:
        summary_block = text_block_svg(summary, 25, int(content_width), PLUS_STROKE, 8, 12, DIAGRAM_FONT, align="center")
        blocks_svg["wb_summary"] = summary_block
        add_image_block(elements, files, rng, "wb_summary", summary_block, (canvas_width - summary_block["width"]) / 2, y_cursor, now)
        y_cursor += summary_block["height"] + 52

    task_text = coerce_text(content.get("task") or content.get("problem"))
    constraints_text = coerce_text(content.get("constraints"))
    if task_text or constraints_text:
        if task_text and constraints_text:
            task_w = 590
            gap = 44
            constraints_w = content_width - task_w - gap
            task_h = top_frame_min_height(str(content.get("task_title") or "Task:"), task_text, task_w)
            constraints_h = top_frame_min_height(str(content.get("constraints_title") or "Constraints:"), constraints_text, constraints_w)
            add_top_frame(elements, files, blocks_svg, rng, "wb_task", str(content.get("task_title") or "Task:"), task_text, margin, y_cursor, task_w, task_h, now)
            add_top_frame(
                elements,
                files,
                blocks_svg,
                rng,
                "wb_constraints",
                str(content.get("constraints_title") or "Constraints:"),
                constraints_text,
                margin + task_w + gap,
                y_cursor,
                constraints_w,
                constraints_h,
                now,
            )
            frame_h = max(task_h, constraints_h)
        else:
            frame_title = str(content.get("task_title") or ("Constraints:" if constraints_text else "Task:"))
            frame_body = task_text or constraints_text
            frame_h = top_frame_min_height(frame_title, frame_body, content_width)
            add_top_frame(
                elements,
                files,
                blocks_svg,
                rng,
                "wb_task",
                frame_title,
                frame_body,
                margin,
                y_cursor,
                content_width,
                frame_h,
                now,
            )
        y_cursor += frame_h + 86

    raw_blocks = content.get("blocks") or content.get("nodes") or []
    blocks = [normalize_block(block, index) for index, block in enumerate(raw_blocks)]
    planning = content.get("planning") if isinstance(content.get("planning"), dict) else {}
    layout = str(content.get("layout") or planning.get("diagram_strategy") or "auto")
    if layout.lower() == "auto":
        if content.get("modules") or planning.get("modules") or any(block_module_key(block) != "main" for block in blocks):
            layout = "modular-composite"
        elif any(str(block.get("lane") or block.get("side") or "") for block in blocks):
            layout = "comparison"
        elif any(block_kind(block) in {"service", "api", "database", "db", "cache", "queue", "storage", "client", "actor", "user"} for block in blocks):
            layout = "architecture"
        elif len(blocks) <= 5:
            layout = "concept-map"
        else:
            layout = "pipeline"
    module_frames: list[dict[str, Any]] = []
    if layout.lower() in MODULAR_LAYOUTS:
        positions, module_frames = whiteboard_modular_positions(content, blocks, y_cursor, canvas_width)
    else:
        positions = whiteboard_positions(blocks, layout, y_cursor, canvas_width)

    for frame in module_frames:
        add_module_frame(elements, files, blocks_svg, rng, frame, now)

    for index, block in enumerate(blocks):
        block_id = str(block["id"])
        default = positions.get(block_id, (margin, y_cursor, 300, 160))
        pos = (
            dimension(block.get("x"), default[0], canvas_width),
            dimension(block.get("y"), default[1], 1600),
            dimension(block.get("width") or block.get("w"), default[2], content_width),
            dimension(block.get("height") or block.get("h"), default[3], 800),
        )
        positions[block_id] = pos
        add_whiteboard_block(elements, files, blocks_svg, rng, block, pos, index, now)

    connectors = list(content.get("connectors") or [])
    if not connectors and blocks:
        if layout.lower() in {"decision", "decision-tree", "decision_tree"}:
            for block in blocks[1:3]:
                connectors.append({"from": blocks[0]["id"], "to": block["id"], "routing": "centered"})
            if len(blocks) > 3:
                for block in blocks[1:3]:
                    connectors.append({"from": block["id"], "to": blocks[3]["id"], "routing": "centered"})
        elif layout.lower() in {"comparison", "tradeoff", "compare"}:
            lane_groups: dict[str, list[dict[str, Any]]] = {}
            for index, block in enumerate(blocks):
                lane = str(block.get("lane") or block.get("side") or ("left" if index % 2 == 0 else "right")).lower()
                lane_groups.setdefault(lane, []).append(block)
            for lane_blocks in lane_groups.values():
                for idx in range(len(lane_blocks) - 1):
                    connectors.append({"from": lane_blocks[idx]["id"], "to": lane_blocks[idx + 1]["id"]})
        elif layout.lower() in {"map", "concept", "concept-map", "concept_map"}:
            for block in blocks[1:]:
                connectors.append({"from": blocks[0]["id"], "to": block["id"]})
        elif layout.lower() in MODULAR_LAYOUTS:
            specs = module_specs(content, blocks)
            previous_tail = None
            for spec in specs:
                module_blocks = [block for block in blocks if block_module_key(block) == str(spec["id"])]
                for idx in range(len(module_blocks) - 1):
                    connectors.append({"from": module_blocks[idx]["id"], "to": module_blocks[idx + 1]["id"]})
                if previous_tail and module_blocks:
                    connectors.append({"from": previous_tail["id"], "to": module_blocks[0]["id"]})
                if module_blocks:
                    previous_tail = module_blocks[-1]
        else:
            for idx in range(len(blocks) - 1):
                connectors.append({"from": blocks[idx]["id"], "to": blocks[idx + 1]["id"]})

    connector_label_max_y = y_cursor
    for index, connector in enumerate(connectors):
        src = str(connector.get("from") or connector.get("source") or "")
        dst = str(connector.get("to") or connector.get("target") or "")
        if connector.get("points"):
            points = [[float(p[0]), float(p[1])] for p in connector["points"] if isinstance(p, (list, tuple)) and len(p) >= 2]
        elif src in positions and dst in positions:
            if str(connector.get("routing") or "").lower() in {"centered", "center", "decision"}:
                points = centered_right_angle_points(positions[src], positions[dst])
            else:
                points = route_connector_points(
                    src,
                    dst,
                    positions,
                    str(connector.get("routing") or "auto"),
                    canvas_width,
                )
        else:
            continue
        if src in positions and dst in positions and not connector.get("preserve_points"):
            connector_obstacles = [
                inflated_rect(pos, 12)
                for block_id, pos in positions.items()
                if block_id not in {src, dst}
            ]
            if any(
                not segment_clear(points[point_index], points[point_index + 1], connector_obstacles)
                for point_index in range(len(points) - 1)
            ):
                points = route_connector_points(
                    src,
                    dst,
                    positions,
                    str(connector.get("routing") or "auto"),
                    canvas_width,
                )
        connector_element = routed_arrow(rng, points, now, stroke=str(connector.get("stroke") or PLUS_STROKE), stroke_width=int(connector.get("strokeWidth") or 2))
        connector_element["customData"] = {"role": "connector", "from": src, "to": dst}
        elements.append(connector_element)
        label = str(connector.get("label") or "")
        if label:
            label_block = text_block_svg(
                label,
                17,
                connector_label_width(positions[src], positions[dst]),
                PLUS_STROKE,
                10,
                14,
                DIAGRAM_FONT,
                align="left",
                break_long_words=False,
            )
            label_key = f"wb_connector_{index}"
            blocks_svg[label_key] = label_block
            label_dx = dimension(connector.get("label_dx") or connector.get("labelDx"), 0, canvas_width)
            label_dy = dimension(connector.get("label_dy") or connector.get("labelDy"), 0, 1600)
            label_obstacles = list(positions.values())
            label_x, label_y = choose_label_position(points, label_block, label_obstacles, canvas_width, label_dx, label_dy)
            add_image_block(
                elements,
                files,
                rng,
                label_key,
                label_block,
                label_x,
                label_y,
                now,
            )
            elements[-1]["customData"].update({
                "role": "connector_label",
                "from": src,
                "to": dst,
                "label": label,
                "labelLines": [line for line in label_block.get("lines", []) if line is not None],
            })
            connector_label_max_y = max(connector_label_max_y, label_y + label_block["height"])

    max_y = max(
        max((y + h for x, y, w, h in positions.values()), default=y_cursor),
        max((float(frame["y"]) + float(frame["h"]) for frame in module_frames), default=y_cursor),
        connector_label_max_y,
    )
    callouts = list(content.get("callouts") or [])
    for index, callout in enumerate(callouts):
        default_w = 420 if index < 2 else 620
        default_h = 130
        default_x = (canvas_width - default_w) / 2 if len(callouts) == 1 else margin + (index % 2) * (content_width - default_w)
        x = dimension(callout.get("x"), default_x, canvas_width)
        y = dimension(callout.get("y"), max_y + 54 + (index // 2) * 170, 2200)
        w = dimension(callout.get("width") or callout.get("w"), default_w, content_width)
        h = dimension(callout.get("height") or callout.get("h"), default_h, 600)
        note = dict(callout)
        note.setdefault("id", f"callout{index}")
        note.setdefault("kind", "note")
        note.setdefault("title_size", 24)
        note.setdefault("body_size", 20)
        h = max(h, whiteboard_block_min_height(note, w, default_h))
        add_whiteboard_block(elements, files, blocks_svg, rng, note, (x, y, w, h), index, now)
        max_y = max(max_y, y + h)

    canvas_height = int(max_y + WHITEBOARD_BOTTOM_PADDING)
    scene = {
        "type": "excalidraw",
        "version": 2,
        "source": "sde-interview-script-skill",
        "elements": elements,
        "appState": {
            "viewBackgroundColor": "#ffffff",
            "gridSize": None,
            "theme": "light",
            "name": slug,
            "scrollX": 0,
            "scrollY": 0,
            "zoom": {"value": 1},
        },
        "files": files,
    }
    return scene, blocks_svg, canvas_width, canvas_height


def build_diagram_scene(
    content: dict[str, Any],
    slug: str,
) -> tuple[dict[str, Any], dict[str, Any], int, int]:
    rng = random.Random(20260616)
    now = int(time.time() * 1000)
    plus_style = is_plus_style(content)
    canvas_width = int(dimension(content.get("width"), 1760, 1760))
    margin = 80
    content_width = canvas_width - margin * 2
    elements: list[dict[str, Any]] = []
    files: dict[str, Any] = {}
    blocks_svg: dict[str, Any] = {
        "title": text_block_svg(
            str(content.get("title", "Script Card")),
            44 if plus_style else 42,
            1320,
            PLUS_STROKE if plus_style else "#111827",
            14,
            22,
            DIAGRAM_FONT if plus_style else HANDWRITING_FONT,
            align="center" if plus_style else "left",
        ),
    }
    title_x = (canvas_width - blocks_svg["title"]["width"]) / 2 if plus_style else margin
    add_image_block(elements, files, rng, "title", blocks_svg["title"], title_x, 70, now)
    y_cursor = 70 + blocks_svg["title"]["height"] + 42
    summary = str(content.get("summary") or "")
    if summary:
        blocks_svg["summary"] = text_block_svg(
            summary,
            28,
            int(content_width),
            "#374151" if not plus_style else PLUS_STROKE,
            12,
            18,
            DIAGRAM_FONT if plus_style else HANDWRITING_FONT,
            align="center" if plus_style else "left",
        )
        summary_x = (canvas_width - blocks_svg["summary"]["width"]) / 2 if plus_style else margin
        add_image_block(elements, files, rng, "summary", blocks_svg["summary"], summary_x, y_cursor, now)
        y_cursor += blocks_svg["summary"]["height"] + 64

    task_text = coerce_text(content.get("task") or content.get("problem"))
    constraints_text = coerce_text(content.get("constraints"))
    if plus_style and (task_text or constraints_text):
        frame_h = 150
        gap = 48
        if task_text and constraints_text:
            left_w = 680
            right_w = content_width - left_w - gap
            add_top_frame(
                elements,
                files,
                blocks_svg,
                rng,
                "task",
                str(content.get("task_title") or "Task:"),
                task_text,
                margin,
                y_cursor,
                left_w,
                frame_h,
                now,
            )
            add_top_frame(
                elements,
                files,
                blocks_svg,
                rng,
                "constraints",
                str(content.get("constraints_title") or "Constraints:"),
                constraints_text,
                margin + left_w + gap,
                y_cursor,
                right_w,
                frame_h,
                now,
            )
        else:
            add_top_frame(
                elements,
                files,
                blocks_svg,
                rng,
                "task",
                str(content.get("task_title") or ("Constraints:" if constraints_text else "Task:")),
                task_text or constraints_text,
                margin,
                y_cursor,
                content_width,
                frame_h,
                now,
            )
        y_cursor += frame_h + 86

    raw_blocks = content.get("blocks") or content.get("nodes") or []
    diagram_blocks = [normalize_block(block, index) for index, block in enumerate(raw_blocks)]
    layout = str(content.get("layout") or "auto")
    if plus_style and layout.lower() == "auto":
        kinds = {block_kind(block) for block in diagram_blocks}
        if kinds & {"service", "api", "database", "db", "cache", "queue", "storage", "cdn", "client"}:
            layout = "architecture"
        elif any(str(block.get("lane") or block.get("side") or "") for block in diagram_blocks):
            layout = "comparison"
        else:
            layout = "concept-map"
    auto = auto_positions(diagram_blocks, layout, y_cursor, canvas_width)
    positions: dict[str, tuple[float, float, float, float]] = {}
    for block in diagram_blocks:
        block_id = str(block["id"])
        default = auto.get(block_id, (margin, y_cursor, 420, 220))
        x = dimension(block.get("x"), default[0], canvas_width)
        y = dimension(block.get("y"), default[1], 1600)
        w = dimension(block.get("width") or block.get("w"), default[2], content_width)
        h = dimension(block.get("height") or block.get("h"), default[3], 900)
        positions[block_id] = (x, y, w, h)

    if positions:
        min_diagram_y = min(pos[1] for pos in positions.values())
        if min_diagram_y < y_cursor:
            shift_y = y_cursor - min_diagram_y
            positions = {
                block_id: (x, y + shift_y, w, h)
                for block_id, (x, y, w, h) in positions.items()
            }

    for block in diagram_blocks:
        block_id = str(block["id"])
        x, y, w, h = positions[block_id]
        stroke = plus_block_stroke(block) if plus_style else str(block.get("stroke") or block_stroke(block))
        fill = plus_block_fill(block) if plus_style else str(block.get("fill") or block.get("background") or "transparent")
        text_color = plus_text_color(block) if plus_style else (stroke if stroke != "#111827" else "#111827")
        shape = block_shape(block, allow_diamond=(not plus_style or bool(block.get("allowDiamond"))))
        default_align = "left"
        default_valign = "center" if plus_style else "top"
        align = str(block.get("align") or content.get("align") or default_align).lower()
        valign = str(block.get("valign") or content.get("valign") or default_valign).lower()
        stroke_width = int(block.get("strokeWidth") or block.get("stroke_width") or (2 if plus_style else (3 if stroke == "#2563eb" else 2)))
        stroke_style = str(block.get("strokeStyle") or block.get("stroke_style") or "solid")
        icon_name = plus_icon_name(block) if plus_style else ""
        reserve_icon_space = bool(plus_style and icon_name)
        text_area_x = x
        text_area_w = w
        if shape == "diamond":
            shape_element = diamond(rng, x, y, w, h, stroke, stroke_width, now, background=fill)
            text_w = int(max(160, w * 0.62))
            text_x = x + (w - text_w) / 2
            text_y = y + h * 0.22
        elif shape == "ellipse":
            shape_element = ellipse(rng, x, y, w, h, stroke, stroke_width, now, background=fill)
            text_area_x = x + (96 if reserve_icon_space else 0)
            text_area_w = w - (116 if reserve_icon_space else 0)
            text_w = int(max(160, text_area_w * 0.68))
            text_x = text_area_x + (text_area_w - text_w) / 2
            text_y = y + h * 0.24
        else:
            shape_element = rectangle(
                rng,
                x,
                y,
                w,
                h,
                stroke,
                stroke_width,
                now,
                background=fill,
                stroke_style=stroke_style,
            )
            text_area_x = x + (118 if reserve_icon_space else 24)
            text_area_w = w - (148 if reserve_icon_space else 48)
            text_w = int(max(180, text_area_w))
            text_x = text_area_x + ((text_area_w - text_w) / 2 if align == "center" else 0)
            text_y = y + 28
        shape_element["customData"] = {"role": "block", "blockId": block_id}
        elements.append(shape_element)
        key = f"block{block_id}"
        blocks_svg[key] = rich_text_block_svg(
            str(block.get("title") or ""),
            str(block.get("body") or ""),
            text_w,
            text_color,
            31 if plus_style else 30,
            23 if plus_style else 26,
            align=align,
            font_family=DIAGRAM_FONT if plus_style else HANDWRITING_FONT,
        )
        if align == "center":
            if reserve_icon_space:
                text_x = text_area_x + (text_area_w - blocks_svg[key]["width"]) / 2
            else:
                text_x = x + (w - blocks_svg[key]["width"]) / 2
        if valign == "center":
            text_y = fit_text_y(y, h, blocks_svg[key]["height"])
        add_image_block(elements, files, rng, key, blocks_svg[key], text_x, text_y, now)

        if plus_style and icon_name:
            icon_label = str(block.get("icon_label") or block.get("iconLabel") or "")
            icon_size = int(dimension(block.get("icon_size"), 70, 120))
            icon_block = component_icon_svg(icon_name, icon_label, icon_size)
            icon_key = f"icon{block_id}"
            blocks_svg[icon_key] = icon_block
            icon_x = float(block.get("icon_x") or (x + 18))
            icon_y = float(block.get("icon_y") or (y + h - icon_block["height"] - 14))
            add_image_block(elements, files, rng, icon_key, icon_block, icon_x, icon_y, now)

    connectors = list(content.get("connectors") or [])
    if not connectors and diagram_blocks:
        if layout.lower() in {"decision", "decision-tree", "decision_tree"}:
            connectors = [
                {"from": str(diagram_blocks[0]["id"]), "to": str(block["id"])}
                for block in diagram_blocks[1:4]
            ]
        elif layout.lower() not in {"comparison", "tradeoff", "compare"}:
            connectors = [
                {"from": str(diagram_blocks[index]["id"]), "to": str(diagram_blocks[index + 1]["id"])}
                for index in range(len(diagram_blocks) - 1)
            ]
    for index, connector in enumerate(connectors):
        connector_stroke = str(connector.get("stroke") or connector.get("color") or (PLUS_STROKE if plus_style else "#2563eb"))
        connector_width = int(connector.get("strokeWidth") or connector.get("stroke_width") or (2 if plus_style else 3))
        if connector.get("points"):
            raw_points = connector.get("points") or []
            points = [
                [float(point[0]), float(point[1])]
                for point in raw_points
                if isinstance(point, (list, tuple)) and len(point) >= 2
            ]
            if len(points) < 2:
                continue
            src = str(connector.get("from") or connector.get("source") or "")
            dst = str(connector.get("to") or connector.get("target") or "")
            if src in positions and dst in positions and not connector.get("preserve_points"):
                connector_obstacles = [
                    inflated_rect(pos, 12)
                    for block_id, pos in positions.items()
                    if block_id not in {src, dst}
                ]
                if any(
                    not segment_clear(points[point_index], points[point_index + 1], connector_obstacles)
                    for point_index in range(len(points) - 1)
                ):
                    points = route_connector_points(
                        src,
                        dst,
                        positions,
                        str(connector.get("routing") or "auto"),
                        canvas_width,
                    )
            connector_element = routed_arrow(rng, points, now, stroke=connector_stroke, stroke_width=connector_width)
            connector_element["customData"] = {
                "role": "connector",
                "from": src,
                "to": dst,
            }
            elements.append(connector_element)
            label = str(connector.get("label") or "")
            if label:
                key = f"connector{index}"
                blocks_svg[key] = text_block_svg(
                    label,
                    18 if not plus_style else 19,
                    connector_label_width(positions[src], positions[dst]),
                    "#1e3a8a" if not plus_style else PLUS_STROKE,
                    10,
                    14,
                    DIAGRAM_FONT if plus_style else HANDWRITING_FONT,
                    align="left",
                    break_long_words=False,
                )
                label_obstacles = list(positions.values())
                label_x, label_y = choose_label_position(points, blocks_svg[key], label_obstacles, canvas_width)
                add_image_block(
                    elements,
                    files,
                    rng,
                    key,
                    blocks_svg[key],
                    label_x,
                    label_y,
                    now,
                )
                elements[-1]["customData"].update({
                    "role": "connector_label",
                    "from": src,
                    "to": dst,
                    "label": label,
                    "labelLines": [line for line in blocks_svg[key].get("lines", []) if line is not None],
                })
            continue
        src = str(connector.get("from") or connector.get("source") or "")
        dst = str(connector.get("to") or connector.get("target") or "")
        if src not in positions or dst not in positions:
            continue
        if plus_style or str(connector.get("routing") or "").lower() in {"orthogonal", "right-angle", "right_angle"}:
            points = route_connector_points(
                src,
                dst,
                positions,
                str(connector.get("routing") or "auto"),
                canvas_width,
            )
            connector_element = routed_arrow(rng, points, now, stroke=connector_stroke, stroke_width=connector_width)
            connector_element["customData"] = {"role": "connector", "from": src, "to": dst}
            elements.append(connector_element)
            label_x = sum(point[0] for point in points) / len(points)
            label_y = sum(point[1] for point in points) / len(points)
        else:
            x1, y1, x2, y2 = connector_points(positions[src], positions[dst])
            connector_element = arrow(rng, x1, y1, x2, y2, now, stroke=connector_stroke, stroke_width=connector_width)
            connector_element["customData"] = {"role": "connector", "from": src, "to": dst}
            elements.append(connector_element)
            label_x = (x1 + x2) / 2
            label_y = (y1 + y2) / 2
        label = str(connector.get("label") or "")
        if label:
            key = f"connector{index}"
            blocks_svg[key] = text_block_svg(
                label,
                18 if not plus_style else 19,
                connector_label_width(positions[src], positions[dst]),
                "#1e3a8a" if not plus_style else PLUS_STROKE,
                10,
                14,
                DIAGRAM_FONT if plus_style else HANDWRITING_FONT,
                align="left",
                break_long_words=False,
            )
            label_obstacles = list(positions.values())
            label_x, label_y = choose_label_position(points if plus_style else [[label_x, label_y], [label_x, label_y]], blocks_svg[key], label_obstacles, canvas_width)
            add_image_block(
                elements,
                files,
                rng,
                key,
                blocks_svg[key],
                label_x,
                label_y,
                now,
            )
            elements[-1]["customData"].update({
                "role": "connector_label",
                "from": src,
                "to": dst,
                "label": label,
                "labelLines": [line for line in blocks_svg[key].get("lines", []) if line is not None],
            })

    max_y = max((y + h for x, y, w, h in positions.values()), default=y_cursor)
    for index, callout in enumerate(content.get("callouts") or []):
        x = dimension(callout.get("x"), margin + (index % 2) * 820, canvas_width)
        y = dimension(callout.get("y"), max_y + 60 + (index // 2) * 190, 2000)
        w = dimension(callout.get("width") or callout.get("w"), 760, content_width)
        h = dimension(callout.get("height") or callout.get("h"), 160, 600)
        stroke = str(callout.get("stroke") or (PLUS_STROKE if plus_style else "#b91c1c"))
        callout_for_fill = dict(callout)
        callout_for_fill.setdefault("kind", "note")
        fill = str(
            callout.get("fill")
            or callout.get("background")
            or (plus_block_fill(callout_for_fill, index) if plus_style else "transparent")
        )
        elements.append(rectangle(rng, x, y, w, h, stroke, 1 if plus_style else 2, now, background=fill))
        key = f"callout{index}"
        blocks_svg[key] = rich_text_block_svg(
            str(callout.get("title") or "Caveat"),
            str(callout.get("body") or callout.get("text") or ""),
            int(w - 48),
            PLUS_STROKE if plus_style else stroke,
            24 if plus_style else 22,
            21 if plus_style else 20,
            align=str(callout.get("align") or "left").lower(),
            font_family=DIAGRAM_FONT if plus_style else HANDWRITING_FONT,
        )
        text_x = x + 24
        text_y = y + max(16, (h - blocks_svg[key]["height"]) / 2) if plus_style else y + 26
        add_image_block(elements, files, rng, key, blocks_svg[key], text_x, text_y, now)
        max_y = max(max_y, y + h)

    talk_track = content.get("talk_track") or content.get("short") or ""
    if isinstance(talk_track, list):
        talk_track = "\n".join(str(item) for item in talk_track)
    include_talk = bool(content.get("include_talk_track_in_board") or content.get("include_script_in_board"))
    if talk_track and (include_talk or not plus_style):
        y = max_y + 78
        h = 165
        elements.append(rectangle(rng, margin, y, content_width, h, "#111827", 2, now))
        blocks_svg["talk"] = rich_text_block_svg(
            localized_talk_label(str(content.get("language") or "")),
            str(talk_track),
            int(content_width - 64),
            "#111827",
            23,
            21,
            font_family=HANDWRITING_FONT,
        )
        add_image_block(elements, files, rng, "talk", blocks_svg["talk"], margin + 32, y + 26, now)
        max_y = y + h

    canvas_height = int(max_y + DIAGRAM_BOTTOM_PADDING)
    scene = {
        "type": "excalidraw",
        "version": 2,
        "source": "sde-interview-script-skill",
        "elements": elements,
        "appState": {
            "viewBackgroundColor": "#ffffff",
            "gridSize": None,
            "theme": "light",
            "name": slug,
            "scrollX": 0,
            "scrollY": 0,
            "zoom": {"value": 1},
        },
        "files": files,
    }
    return scene, blocks_svg, canvas_width, canvas_height


def build_legacy_scene(content: dict[str, Any], slug: str) -> tuple[dict[str, Any], dict[str, Any], int, int]:
    rng = random.Random(20260614)
    now = int(time.time() * 1000)
    blocks: dict[str, Any] = {
        "title": text_block_svg(content["title"], 42, 1100, "#111827", 14, 22),
        "summary": text_block_svg(content["summary"], 28, 1450, "#374151", 14, 22),
        "script": text_block_svg(content["script"], 27, 1450, "#111827", 14, 24),
        "short": text_block_svg(content["short"], 26, 1450, "#111827", 13, 20),
    }
    for index, flow in enumerate(content["flows"]):
        blocks[f"flow{index}"] = text_block_svg(flow, 24, 310, "#1e3a8a", 12, 16)

    margin = 80
    card_width = 1600
    padding = 46
    script_y = 70
    content_x = margin + padding
    y_cursor = script_y + 34
    elements: list[dict[str, Any]] = []
    files: dict[str, Any] = {}
    content_items: list[tuple[str, dict[str, Any], str]] = []
    for key in ["title", "summary", "script"]:
        element, file_id = image_element(rng, key, blocks[key], content_x, y_cursor, now)
        content_items.append((key, element, file_id))
        y_cursor += element["height"] + (24 if key == "title" else 22)
    script_card_height = y_cursor - script_y + 24
    elements.append(rectangle(rng, margin, script_y, card_width, script_card_height, "#111827", 2, now))
    for key, element, file_id in content_items:
        elements.append(element)
        files[file_id] = {
            "id": file_id,
            "mimeType": "image/svg+xml",
            "dataURL": blocks[key]["dataURL"],
            "created": now,
        }

    flow_y = script_y + script_card_height + 74
    flow_width = 360
    flow_height = 250
    gap = (card_width - 4 * flow_width) / 3
    flow_xs = [margin + index * (flow_width + gap) for index in range(4)]
    for index, flow_x in enumerate(flow_xs):
        elements.append(rectangle(rng, flow_x, flow_y, flow_width, flow_height, "#2563eb", 3, now))
        key = f"flow{index}"
        element, file_id = image_element(rng, key, blocks[key], flow_x + 24, flow_y + 30, now)
        elements.append(element)
        files[file_id] = {
            "id": file_id,
            "mimeType": "image/svg+xml",
            "dataURL": blocks[key]["dataURL"],
            "created": now,
        }
        if index < 3:
            elements.append(
                arrow(
                    rng,
                    flow_x + flow_width + 14,
                    flow_y + flow_height / 2,
                    flow_xs[index + 1] - 18,
                    flow_y + flow_height / 2,
                    now,
                ),
            )

    short_y = flow_y + flow_height + 74
    short_element, short_file_id = image_element(
        rng,
        "short",
        blocks["short"],
        margin + padding,
        short_y + 38,
        now,
    )
    short_height = short_element["height"] + 76
    elements.append(rectangle(rng, margin, short_y, card_width, short_height, "#111827", 2, now))
    elements.append(short_element)
    files[short_file_id] = {
        "id": short_file_id,
        "mimeType": "image/svg+xml",
        "dataURL": blocks["short"]["dataURL"],
        "created": now,
    }

    canvas_height = int(short_y + short_height + 80)
    scene = {
        "type": "excalidraw",
        "version": 2,
        "source": "sde-interview-script-skill",
        "elements": elements,
        "appState": {
            "viewBackgroundColor": "#ffffff",
            "gridSize": None,
            "theme": "light",
            "name": slug,
            "scrollX": 0,
            "scrollY": 0,
            "zoom": {"value": 1},
        },
        "files": files,
    }
    return scene, blocks, 1760, canvas_height


def build_scene(content: dict[str, Any], slug: str) -> tuple[dict[str, Any], dict[str, Any], int, int]:
    if is_plus_style(content):
        return build_whiteboard_scene(content, slug)
    if content.get("blocks") or content.get("nodes"):
        return build_diagram_scene(content, slug)
    return build_legacy_scene(content, slug)


def svg_image_tag(block: dict[str, Any], x: float, y: float) -> str:
    inner_svg = block["svg"].split(">", 1)[1].rsplit("</svg>", 1)[0]
    return (
        f'<g transform="translate({x:.0f} {y:.0f})">'
        f"{inner_svg}</g>"
    )


def rough_rng(seed: str) -> random.Random:
    return random.Random(sum((index + 1) * ord(char) for index, char in enumerate(seed)))


def rough_segment_points(
    start: tuple[float, float],
    end: tuple[float, float],
    rng: random.Random,
    amplitude: float,
) -> list[tuple[float, float]]:
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    length = max(1.0, math.hypot(dx, dy))
    nx = -dy / length
    ny = dx / length
    steps = max(1, int(length // 48))
    points: list[tuple[float, float]] = []
    for step in range(steps + 1):
        t = step / steps
        x = x1 + dx * t
        y = y1 + dy * t
        if 0 < step < steps:
            wobble = rng.uniform(-amplitude, amplitude)
            x += nx * wobble + rng.uniform(-amplitude * 0.35, amplitude * 0.35)
            y += ny * wobble + rng.uniform(-amplitude * 0.35, amplitude * 0.35)
        points.append((x, y))
    return points


def rough_points(
    points: list[tuple[float, float]],
    seed: str,
    amplitude: float,
    closed: bool = False,
) -> list[tuple[float, float]]:
    rng = rough_rng(seed)
    path_points = list(points)
    if closed and path_points[0] != path_points[-1]:
        path_points.append(path_points[0])
    result: list[tuple[float, float]] = []
    for index in range(len(path_points) - 1):
        segment = rough_segment_points(path_points[index], path_points[index + 1], rng, amplitude)
        if result:
            segment = segment[1:]
        result.extend(segment)
    return result


def polyline_svg(
    points: list[tuple[float, float]],
    color: str,
    stroke_width: float,
    marker_id: str | None = None,
    opacity: float = 1.0,
    closed: bool = False,
    dash: str | None = None,
) -> str:
    if closed and points and points[0] != points[-1]:
        points = [*points, points[0]]
    point_text = " ".join(f"{px:.1f},{py:.1f}" for px, py in points)
    marker = f' marker-end="url(#{marker_id})"' if marker_id else ""
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<polyline points="{point_text}" fill="none" stroke="{color}" '
        f'stroke-width="{stroke_width}" stroke-linecap="round" stroke-linejoin="round" '
        f'opacity="{opacity}"{dash_attr}{marker} />'
    )


def rough_polyline_svg(
    points: list[tuple[float, float]],
    color: str,
    stroke_width: float,
    seed: str,
    marker_id: str | None = None,
    closed: bool = False,
    dash: str | None = None,
) -> str:
    primary = rough_points(points, seed + "a", 2.2 if closed else 1.6, closed)
    secondary = rough_points(points, seed + "b", 1.7 if closed else 1.2, closed)
    return (
        polyline_svg(secondary, color, max(1.0, stroke_width * 0.8), None, 0.42, closed, dash)
        + polyline_svg(primary, color, stroke_width, marker_id, 0.95, closed, dash)
    )


def rounded_rect_points(x: float, y: float, w: float, h: float, r: float) -> list[tuple[float, float]]:
    r = min(r, w / 2, h / 2)
    return [
        (x + r, y),
        (x + w - r, y),
        (x + w - r / 2, y + r / 3),
        (x + w, y + r),
        (x + w, y + h - r),
        (x + w - r / 2, y + h - r / 3),
        (x + w - r, y + h),
        (x + r, y + h),
        (x + r / 2, y + h - r / 3),
        (x, y + h - r),
        (x, y + r),
        (x + r / 2, y + r / 3),
    ]


def jitter(value: float, rng: random.Random, amount: float = 1.7) -> float:
    return value + rng.uniform(-amount, amount)


def rounded_rect_path(x: float, y: float, w: float, h: float, r: float, seed: str) -> str:
    rng = rough_rng(seed)
    r = min(r, w / 2, h / 2)
    x0, y0, x1, y1 = x, y, x + w, y + h
    return " ".join(
        [
            f"M {jitter(x0 + r, rng):.1f} {jitter(y0, rng):.1f}",
            f"L {jitter(x1 - r, rng):.1f} {jitter(y0, rng):.1f}",
            f"Q {jitter(x1, rng):.1f} {jitter(y0, rng):.1f} {jitter(x1, rng):.1f} {jitter(y0 + r, rng):.1f}",
            f"L {jitter(x1, rng):.1f} {jitter(y1 - r, rng):.1f}",
            f"Q {jitter(x1, rng):.1f} {jitter(y1, rng):.1f} {jitter(x1 - r, rng):.1f} {jitter(y1, rng):.1f}",
            f"L {jitter(x0 + r, rng):.1f} {jitter(y1, rng):.1f}",
            f"Q {jitter(x0, rng):.1f} {jitter(y1, rng):.1f} {jitter(x0, rng):.1f} {jitter(y1 - r, rng):.1f}",
            f"L {jitter(x0, rng):.1f} {jitter(y0 + r, rng):.1f}",
            f"Q {jitter(x0, rng):.1f} {jitter(y0, rng):.1f} {jitter(x0 + r, rng):.1f} {jitter(y0, rng):.1f}",
        ],
    )


def rough_rounded_rect_svg(element: dict[str, Any]) -> str:
    x = float(element["x"])
    y = float(element["y"])
    w = float(element["width"])
    h = float(element["height"])
    stroke = element["strokeColor"]
    stroke_width = float(element.get("strokeWidth") or 2)
    fill = element.get("backgroundColor") or "transparent"
    rx = 28 if element.get("roundness") else 0
    dash = ' stroke-dasharray="8 10"' if element.get("strokeStyle") == "dashed" else ""
    fill_node = ""
    if fill not in {"transparent", "none", ""}:
        fill_node = (
            f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" '
            f'rx="{rx}" ry="{rx}" fill="{fill}" opacity="0.92" />'
        )
    if element.get("strokeStyle") == "dashed":
        return (
            fill_node
            + f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" '
            f'rx="{rx}" ry="{rx}" fill="none" stroke="{stroke}" '
            f'stroke-width="{stroke_width}" stroke-linecap="round"{dash} />'
        )
    path_a = rounded_rect_path(x, y, w, h, rx, element["id"] + "a")
    path_b = rounded_rect_path(x + 0.5, y - 0.3, w - 0.7, h + 0.4, rx, element["id"] + "b")
    return (
        fill_node
        + f'<path d="{path_b}" fill="none" stroke="{stroke}" stroke-width="{max(1.0, stroke_width * 0.8):.1f}" '
        'stroke-linecap="round" stroke-linejoin="round" opacity="0.42" />'
        + f'<path d="{path_a}" fill="none" stroke="{stroke}" stroke-width="{stroke_width:.1f}" '
        'stroke-linecap="round" stroke-linejoin="round" opacity="0.96" />'
    )


def rough_ellipse_svg(element: dict[str, Any]) -> str:
    x = float(element["x"])
    y = float(element["y"])
    w = float(element["width"])
    h = float(element["height"])
    cx = x + w / 2
    cy = y + h / 2
    rx = w / 2
    ry = h / 2
    stroke = element["strokeColor"]
    stroke_width = float(element.get("strokeWidth") or 2)
    fill = element.get("backgroundColor") or "transparent"
    fill_attr = fill if fill not in {"transparent", "none", ""} else "none"
    return (
        f'<ellipse cx="{cx:.0f}" cy="{cy:.0f}" rx="{rx:.0f}" ry="{ry:.0f}" fill="{fill_attr}" '
        f'stroke="{stroke}" stroke-width="{max(1.0, stroke_width * 0.75):.1f}" opacity="0.45" />'
        f'<ellipse cx="{cx + 1:.0f}" cy="{cy - 1:.0f}" rx="{max(1, rx - 1):.0f}" ry="{max(1, ry + 1):.0f}" fill="none" '
        f'stroke="{stroke}" stroke-width="{stroke_width:.1f}" />'
    )


def render_preview_svg(scene: dict[str, Any], blocks: dict[str, Any], width: int, height: int) -> str:
    nodes = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff" />',
    ]
    for element in scene["elements"]:
        if element["type"] == "rectangle":
            nodes.append(rough_rounded_rect_svg(element))
        elif element["type"] == "ellipse":
            nodes.append(rough_ellipse_svg(element))
        elif element["type"] == "diamond":
            x = element["x"]
            y = element["y"]
            w = element["width"]
            h = element["height"]
            points = [
                (x + w / 2, y),
                (x + w, y + h / 2),
                (x + w / 2, y + h),
                (x, y + h / 2),
            ]
            point_text = " ".join(f"{px:.0f},{py:.0f}" for px, py in points)
            fill = element.get("backgroundColor") or "transparent"
            if fill not in {"transparent", "none", ""}:
                nodes.append(f'<polygon points="{point_text}" fill="{fill}" opacity="0.92" />')
            nodes.append(
                rough_polyline_svg(points, element["strokeColor"], element["strokeWidth"], element["id"], closed=True),
            )
        elif element["type"] == "arrow":
            x1 = element["x"]
            y1 = element["y"]
            points = element.get("points") or [[0, 0], [element["width"], element["height"]]]
            absolute_points = [(x1 + point[0], y1 + point[1]) for point in points]
            marker_id = f"arrow-{element['id']}"
            nodes.append(
                f'<defs><marker id="{marker_id}" markerWidth="10" markerHeight="10" '
                'refX="8" refY="3" orient="auto" markerUnits="strokeWidth">'
                f'<path d="M0,0 L0,6 L9,3 z" fill="{element["strokeColor"]}" />'
                "</marker></defs>"
            )
            nodes.append(
                rough_polyline_svg(
                    absolute_points,
                    element["strokeColor"],
                    element.get("strokeWidth") or 3,
                    element["id"],
                    marker_id=marker_id,
                ),
            )
        elif element["type"] == "image":
            key = element["fileId"].split("_file_")[0]
            if key in blocks:
                nodes.append(svg_image_tag(blocks[key], element["x"], element["y"]))
    nodes.append("</svg>")
    return "".join(nodes)


def talk_track_text(content: dict[str, Any]) -> str:
    text = content.get("talk_track") or content.get("short") or ""
    if isinstance(text, list):
        return "\n".join(str(item) for item in text)
    return str(text).strip()


def synthesize_elevenlabs_tts(
    text: str,
    audio_path: Path,
    voice_id: str,
    model_id: str,
    output_format: str,
    language_code: str | None = None,
) -> dict[str, Any]:
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is not set")
    if not text.strip():
        raise RuntimeError("content.talk_track is empty; nothing to synthesize")

    quoted_voice = urllib.parse.quote(voice_id, safe="")
    quoted_format = urllib.parse.quote(output_format, safe="")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{quoted_voice}?output_format={quoted_format}"
    payload: dict[str, Any] = {
        "text": text,
        "model_id": model_id,
    }
    if language_code:
        payload["language_code"] = language_code
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            audio = response.read()
    except urllib.error.HTTPError as error:
        # Provider bodies can echo input text; do not persist them in result JSON.
        raise RuntimeError(f"ElevenLabs TTS failed: HTTP {error.code}") from error
    except urllib.error.URLError as error:
        raise RuntimeError("ElevenLabs TTS connection failed") from error

    if not audio:
        raise RuntimeError("ElevenLabs TTS returned an empty audio response")
    audio_path.write_bytes(audio)
    return {
        "provider": "elevenlabs",
        "audio": str(audio_path),
        "voice_id": voice_id,
        "model_id": model_id,
        "output_format": output_format,
        "bytes": len(audio),
    }


def maybe_synthesize_tts(args: argparse.Namespace, content: dict[str, Any], out_dir: Path, slug: str) -> dict[str, Any] | None:
    provider = str(args.tts or "none").lower()
    if provider == "none":
        return None
    if provider != "elevenlabs":
        return {"provider": provider, "error": f"Unsupported TTS provider: {provider}"}

    audio_path = out_dir / f"{slug}-talk-track.mp3"
    try:
        return synthesize_elevenlabs_tts(
            talk_track_text(content),
            audio_path,
            str(args.tts_voice_id),
            str(args.tts_model_id),
            str(args.tts_output_format),
            str(args.tts_language_code) if args.tts_language_code else None,
        )
    except Exception as error:  # pragma: no cover - depends on external API
        return {"provider": "elevenlabs", "error": "Speech synthesis failed; local card artifacts are available."}


def maybe_share(excalidraw_path: Path, skip: bool) -> dict[str, Any] | None:
    if skip or not shutil.which("node"):
        return None
    script_path = Path(__file__).with_name("share_excalidraw.mjs")
    try:
        completed = subprocess.run(
            ["node", str(script_path), "--input", str(excalidraw_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return json.loads(completed.stdout)
    except Exception as error:  # pragma: no cover - runtime/network fallback
        return {"error": "Sharing failed; local card artifacts are available."}


def main() -> None:
    args = parse_args()
    content = load_content(args.content)
    timestamp = int(time.time())
    out_dir = Path(args.out or f"/tmp/sde-interview-card-{timestamp}")
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", args.slug).strip("-") or "interview-card"

    scene, blocks, canvas_width, canvas_height = build_scene(content, slug)
    excalidraw_path = out_dir / f"{slug}.excalidraw"
    preview_path = out_dir / f"{slug}-preview.svg"
    result_path = out_dir / f"{slug}-result.json"
    excalidraw_path.write_text(json.dumps(scene, ensure_ascii=False, indent=2), encoding="utf-8")
    preview_svg = render_preview_svg(scene, blocks, canvas_width, canvas_height)
    preview_path.write_text(preview_svg, encoding="utf-8")
    share = maybe_share(excalidraw_path, args.no_share)
    tts = maybe_synthesize_tts(args, content, out_dir, slug)
    result = {
        "preview": str(preview_path),
        "excalidraw": str(excalidraw_path),
        "link": share.get("url") if isinstance(share, dict) else None,
        "share": share,
    }
    if tts:
        result["tts"] = tts
        if tts.get("audio"):
            result["audio"] = tts["audio"]
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
