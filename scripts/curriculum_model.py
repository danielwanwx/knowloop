#!/usr/bin/env python3
"""Load and validate the position-based bundled curriculum."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


class CurriculumError(ValueError):
    """Raised when bundled curriculum input is not safe to use."""


@dataclass(frozen=True)
class CurriculumModel:
    route: dict[str, Any]
    weeks: dict[int, dict[str, Any]]
    cases: dict[int, dict[str, Any]]
    algorithms: dict[str, Any]
    projects: dict[str, dict[str, Any]]


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CurriculumError(f"Cannot read {path}: {exc}") from exc


def load_model(root: Path = ROOT) -> CurriculumModel:
    curriculum = root / "curriculum"
    route = load_json(curriculum / "route.json")
    weeks = {
        number: load_json(curriculum / f"week-{number:02d}.json")
        for number in range(1, 13)
    }
    cases = {
        number: load_json(root / "cases" / f"week-{number:02d}.json")
        for number in range(1, 13)
    }
    projects = {
        str(project["slug"]): project
        for payload in cases.values()
        for project in payload.get("projects", [])
        if isinstance(project, dict) and project.get("slug")
    }
    return CurriculumModel(
        route=route,
        weeks=weeks,
        cases=cases,
        algorithms=load_json(curriculum / "algorithm-blocks.json"),
        projects=projects,
    )


def local_day(first_day: date, week: int, day: int) -> date:
    """Map a user-provided local Week 1 date to a course position."""
    if not 1 <= week <= 12 or not 1 <= day <= 7:
        raise CurriculumError("Week and Day are outside the bundled curriculum")
    return first_day + timedelta(days=(week - 1) * 7 + day - 1)


def scheduled_algorithms(model: CurriculumModel, block_id: str, day: int) -> tuple[str, str, list[dict[str, Any]]]:
    if not 1 <= day <= 7:
        raise CurriculumError("Day must be between 1 and 7")
    blocks = {str(block.get("id")): block for block in model.algorithms.get("blocks", [])}
    block = blocks.get(block_id)
    if not block:
        raise CurriculumError(f"Unknown algorithm block: {block_id}")
    problems = list(block.get("problems", []))
    if len(problems) < 3:
        raise CurriculumError(f"Algorithm block {block_id} has too few problems")
    offset = ((day - 1) * 3) % len(problems)
    return str(block.get("tag", "")), str(block.get("mode", "")), [problems[(offset + index) % len(problems)] for index in range(3)]


def _retired_fields() -> tuple[str, ...]:
    return ("start" + "_date", "end" + "_date", "date", "public" + "_url", "page")


def validate_model(model: CurriculumModel) -> list[str]:
    errors: list[str] = []
    route_weeks = model.route.get("weeks") if isinstance(model.route, dict) else None
    if not isinstance(route_weeks, list) or len(route_weeks) != 12:
        return ["route must contain exactly 12 Week positions"]
    if any(field in model.route for field in _retired_fields()[:2]):
        errors.append("route contains retired calendar fields")
    declared_blocks = [str(block.get("id")) for block in model.algorithms.get("blocks", [])]
    routed_blocks = [str(item.get("algorithm_block")) for item in route_weeks]
    if routed_blocks != declared_blocks:
        errors.append("route must use every algorithm tag block exactly once in declared order")
    for expected_week, route_week in enumerate(route_weeks, start=1):
        if int(route_week.get("week", -1)) != expected_week:
            errors.append(f"route Week {expected_week} is out of order")
        route_projects = [str(project) for project in route_week.get("projects", [])]
        case_projects = [str(project.get("slug")) for project in model.cases.get(expected_week, {}).get("projects", [])]
        if route_projects != case_projects:
            errors.append(f"week {expected_week}: project route drifted from the bundled cases")
        days = route_week.get("days")
        if not isinstance(days, list) or len(days) != 7:
            errors.append(f"route Week {expected_week} must contain seven Day positions")
        week = model.weeks.get(expected_week, {})
        if int(week.get("week", -1)) != expected_week:
            errors.append(f"week-{expected_week:02d}.json has the wrong Week number")
            continue
        if any(field in week for field in _retired_fields()[:2]):
            errors.append(f"Week {expected_week} contains retired calendar fields")
        manifest_days = week.get("days")
        if not isinstance(manifest_days, list) or len(manifest_days) != 7:
            errors.append(f"Week {expected_week} must contain seven Day positions")
            continue
        for expected_day, item in enumerate(manifest_days, start=1):
            if int(item.get("week", -1)) != expected_week or int(item.get("day", -1)) != expected_day:
                errors.append(f"Week {expected_week} Day {expected_day} has an invalid position")
            if any(field in item for field in _retired_fields()[2:]):
                errors.append(f"Week {expected_week} Day {expected_day} contains retired calendar fields")
            blocks = item.get("time_blocks")
            if not isinstance(blocks, list) or not blocks:
                errors.append(f"Week {expected_week} Day {expected_day} has no duration blocks")
            elif any(type(block.get("minutes")) is not int or block["minutes"] <= 0 for block in blocks if isinstance(block, dict)) or any(not isinstance(block, dict) for block in blocks):
                errors.append(f"Week {expected_week} Day {expected_day} has an invalid duration block")
            for field in ("title", "artifact", "repair"):
                if not isinstance(item.get(field), str) or not item[field].strip():
                    errors.append(f"Week {expected_week} Day {expected_day} is missing {field}")
            if not isinstance(item.get("sources"), list) or not item["sources"]:
                errors.append(f"Week {expected_week} Day {expected_day} has no sources")
        read_positions: dict[str, int] = {}
        deep_positions: dict[str, int] = {}
        kinds: dict[str, int] = {}
        for day_number, route_day in enumerate(days or [], start=1):
            kind = str(route_day.get("kind"))
            kinds[kind] = kinds.get(kind, 0) + 1
            project = route_day.get("project")
            if project is not None and str(project) not in route_projects:
                errors.append(f"week {expected_week} day {day_number}: project {project!r} is not declared in this week")
            if kind == "project-read" and project is not None:
                read_positions[str(project)] = day_number
            if kind == "project-deep" and project is not None:
                deep_positions[str(project)] = day_number
        for project, read_day in read_positions.items():
            if deep_positions.get(project) != read_day + 1:
                errors.append(f"week {expected_week} {project}: deep day must immediately follow read day")
        if len(route_projects) == 3 and kinds.get("mock", 0) != 1:
            errors.append(f"week {expected_week}: expected 1 mock day")
        for project in model.weeks.get(expected_week, {}).get("projects", []):
            if expected_week != 12 and isinstance(project, dict) and project.get("ai_extensions"):
                errors.append(f"week {expected_week}: AI extensions are allowed only for ChatGPT")
    bitly = model.projects.get("bitly", {})
    headings = bitly.get("read", {}).get("headings", [])
    if len(headings) < 7 or "High-Level Design" not in headings:
        errors.append("bitly: complete read must include every linkable source heading")
    concepts = {str(item.get("source")) for item in bitly.get("concepts", []) if isinstance(item, dict)}
    if "hi.core.api-design" not in concepts:
        errors.append("week 1: required Bitly/Dropbox source coverage is missing")
    return errors
