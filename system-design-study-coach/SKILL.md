---
name: system-design-study-coach
description: Look up and adapt the bundled system-design and algorithms curriculum when a learner asks for a Week/Day assignment or chooses this course. Use interview-coach for actual practice, mock interviews, assessment and persistent learning records.
---

# Course assignment adapter

This skill supplies an optional course assignment. `interview-coach` owns the actual conversation, attempts, feedback and private state. Do not start a second scoring or repair system.

1. Honor explicit Week/Day. Otherwise read the learner's last selected course position through interview-coach; with no position ask which Week/Day they want or offer Week 1 Day 1. A learner who wants “today” must provide their local Week 1 start date; do not infer a shared calendar.
2. Resolve `scripts/plan_lookup.py` relative to **this installed SKILL.md**, and invoke that absolute path with `--week N --day M --format json`. For a local calendar mapping, pass `--start-date YYYY-MM-DD` instead. The script locates bundled curriculum relative to itself, regardless of working directory. Standalone copies require the course data; if absent, say so and offer to practice from supplied material.
3. Return a concise assignment with exact source links and one immediate output. Adapt the current session to its time budget and topic; keep remaining course tasks pending without calling partial work a completed course day.
4. Hand the assignment's topic/sources/acceptance/repair targets to `$interview-coach` if available. It runs Learn/Practice/Mock/Review and saves actual evidence. A mock requires user intent; don't call a sample-answer generator before the learner attempts.
5. `$card` can explain a requested diagram and `$senior-sde-interview-script` can provide an explicitly requested example. Optional audio or uploads require an explicit request for the current content; a course assignment never authorizes external sharing.

Canonical course data: `curriculum/`, top-level `cases/week-*.json`, and `sources/source-manifest.json`. Public Pages contains only the catalog and a synthetic demo; it is never a database of learner performance. Do not claim all projects use the experimental rich Interview Case schema. Read sources when their details are needed; manifest titles alone are not evidence of having read them.
