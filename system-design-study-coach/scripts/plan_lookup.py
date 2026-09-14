#!/usr/bin/env python3
"""Look up a generic Week/Day curriculum position.

The bundled curriculum is position-based. A learner who wants calendar mapping
supplies a local Week 1 start date; that date is never stored in the catalog.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any


def find_curriculum_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "curriculum"
        if (candidate / "week-01.json").exists():
            return candidate
    raise SystemExit("Could not find the bundled curriculum.")


def load_plan(curriculum_root: Path) -> list[dict[str, Any]]:
    publication = json.loads(
        (curriculum_root / "publication.json").read_text(encoding="utf-8")
    )
    if publication.get("schema_version") != 1 or publication.get("mode") != "catalog-only":
        raise SystemExit("Invalid catalog-only publication contract.")
    plan: list[dict[str, Any]] = []
    paths = sorted(curriculum_root.glob("week-*.json"))
    if len(paths) != 12:
        raise SystemExit(f"Expected 12 week manifests, found {len(paths)}.")
    prohibited = ("start" + "_date", "end" + "_date", "date", "public" + "_url", "page")
    for expected_week, path in enumerate(paths, start=1):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if int(payload.get("week", -1)) != expected_week:
            raise SystemExit(f"Expected Week {expected_week} in {path.name}.")
        if any(field in payload for field in prohibited[:2]):
            raise SystemExit(f"Week {expected_week} contains retired calendar fields.")
        days = payload.get("days", [])
        if len(days) != 7:
            raise SystemExit(f"Week {expected_week} must contain exactly seven days.")
        for expected_day, item in enumerate(days, start=1):
            if int(item.get("week", -1)) != expected_week or int(item.get("day", -1)) != expected_day:
                raise SystemExit(f"Week {expected_week}: invalid Day position.")
            if any(field in item for field in prohibited[2:]):
                raise SystemExit(f"Week {expected_week} Day {expected_day} contains retired calendar fields.")
            blocks = item.get("time_blocks", [])
            if not blocks or any(type(block.get("minutes")) is not int or block["minutes"] <= 0 for block in blocks):
                raise SystemExit(f"Week {expected_week} Day {expected_day} needs positive duration blocks.")
            plan.append(dict(item))
    return plan


def position_from_start(start: str, today: date | None = None) -> tuple[int, int]:
    try:
        first = date.fromisoformat(start)
    except ValueError as exc:
        raise SystemExit("--start-date must use YYYY-MM-DD.") from exc
    offset = ((today or date.today()) - first).days
    if not 0 <= offset < 84:
        raise SystemExit("The supplied local start date is outside this 12-week curriculum.")
    return offset // 7 + 1, offset % 7 + 1


def select_day(plan: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    if args.week is not None or args.day is not None:
        if args.week is None or args.day is None:
            raise SystemExit("--week and --day must be provided together.")
        week, day = args.week, args.day
    elif args.local_start:
        week, day = position_from_start(args.local_start)
    else:
        raise SystemExit("Pass --week N --day M, or provide your local --start-date.")
    matches = [
        item for item in plan
        if int(item["week"]) == week and int(item["day"]) == day
    ]
    if len(matches) != 1:
        raise SystemExit(f"Expected one matching day, found {len(matches)}.")
    return matches[0]


def render_text(item: dict[str, Any]) -> str:
    lines = [f"Week {item['week']} Day {item['day']}", item["title"], "", "学习块："]
    for block in item["time_blocks"]:
        lines.append(f"- {block['minutes']} 分钟 · {block['title']}: {block['instruction']}")
    lines.extend(["", "今日源包："])
    lines.extend(
        f"- {source['page_title']} · {source['heading']}: {source['url']}"
        for source in item["sources"]
    )
    lines.extend(["", f"产出物：{item['artifact']}", "", "验收标准："])
    lines.extend(f"- {criterion}" for criterion in item["acceptance"])
    lines.extend(["", f"修复路径：{item['repair']}", "", "算法三题："])
    lines.extend(f"- {problem['title']}: {problem['url']}" for problem in item["algorithms"]["problems"])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week", type=int, choices=range(1, 13))
    parser.add_argument("--day", type=int, choices=range(1, 8))
    parser.add_argument("--start-date", dest="local_start", help="Local calendar date for Week 1 Day 1, YYYY-MM-DD.")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    item = select_day(load_plan(find_curriculum_root()), args)
    if args.format == "json":
        print(json.dumps(item, ensure_ascii=False, indent=2))
    else:
        print(render_text(item))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
