#!/usr/bin/env python3
"""Check publishable Git files without echoing potentially sensitive values.

This detects selected patterns, not all semantic privacy risks. Use --history to
also inspect reachable commits and blobs, including commit author metadata.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "personal-home-path": re.compile(r"(?:/Users/|/home/)[A-Za-z0-9._-]+/|[A-Za-z]:\\Users\\[A-Za-z0-9._-]+\\"),
    "local-machine-email": re.compile(r"[\w.+-]+@[\w.-]+\.local\b", re.I),
    "personal-email": re.compile(r"[\w.+-]+@(?:gmail|hotmail|outlook|icloud|yahoo|protonmail)\.[A-Za-z]+\b", re.I),
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "service-token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{24,}|AKIA[0-9A-Z]{16})\b"),
    "access-bearing-share-url": re.compile(r"https://excalidraw\.com/#json=[A-Za-z0-9_-]{5,},[A-Za-z0-9_-]{12,}"),
    "account-pages-url": re.compile(r"https://[A-Za-z0-9-]+\.github\.io(?:[/?#]|$)", re.I),
    "github-noreply-email": re.compile(r"\b[A-Za-z0-9._+-]+@users\.noreply\.github\.com\b", re.I),
    "retired-catalog-artifact": re.compile(r"\b(?:coh" r"ort|legacy-" r"system-design|verified_" r"coh" r"ort|legacy_" r"calendar|target[-_ ]" r"company|project[-_ ]" r"map)\b", re.I),
}
PRIVATE_DIRS = {".interview-coach-data", "interview-training", "transcripts", "recordings", "resumes", "sessions"}
PRIVATE_FILES = {"learner-state.md", ".env"}


def scan_text(text: str) -> list[dict[str, object]]:
    return [
        {"line": number, "rule": name}
        for number, line in enumerate(text.splitlines(), 1)
        for name, pattern in PATTERNS.items() if pattern.search(line)
    ]


def scan_path(path: str, data: bytes) -> list[dict[str, object]]:
    parts = Path(path).parts
    findings: list[dict[str, object]] = []
    if set(parts) & PRIVATE_DIRS or Path(path).name in PRIVATE_FILES or (Path(path).name.startswith('.env.') and Path(path).name != '.env.example'):
        findings.append({"path": path, "rule": "private-runtime-file"})
    if re.search(r'-(?:transcript|share-link)\.', Path(path).name, re.I):
        findings.append({"path": path, "rule": "private-runtime-file"})
    if re.fullmatch(r"docs/(?:system-design-12-week-master-plan|week[0-9]+-action-guide)\.html", path) or re.match(r"docs/week[0-9]+/", path):
        findings.append({"path": path, "rule": "retired-public-calendar-file"})
    if Path(path).suffix.lower() in {'.pem', '.key', '.p8', '.mp3', '.wav', '.m4a', '.sqlite3', '.sqlite3-wal', '.sqlite3-shm', '.sqlite3-journal'}:
        findings.append({"path": path, "rule": "credential-or-recording-file"})
    text = data.decode("utf-8", errors="replace")
    if path.startswith("curriculum/") and re.search(r'"(?:start' r'_date|end' r'_date|date|public' r'_url|page)"', text):
        findings.append({"path": path, "rule": "retired-calendar-field"})
    findings.extend({"path": path, **item} for item in scan_text(text))
    return findings


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args])


def check_current(root: Path) -> list[dict[str, object]]:
    paths = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").decode().split('\0')
    findings = []
    for relative in sorted(set(filter(None, paths))):
        path = root / relative
        if path.is_symlink():
            findings.append({"path": relative, "rule": "publishable-symlink"})
        elif path.is_file():
            findings.extend(scan_path(relative, path.read_bytes()))
    return findings


def check_history(root: Path) -> tuple[list[dict[str, object]], int]:
    findings = []
    count = 0
    for row in git(root, "rev-list", "--objects", "--all").decode().splitlines():
        sha, _, path = row.partition(' ')
        kind = git(root, "cat-file", "-t", sha).strip()
        if kind == b'blob':
            count += 1
            findings.extend({"object": sha, **item} for item in scan_path(path, git(root, "cat-file", "blob", sha)))
        elif kind == b'commit':
            # Covers author/committer as well as messages; no matched values printed.
            findings.extend({"object": sha, "path": "<commit-metadata>", **item} for item in scan_text(git(root, "cat-file", "commit", sha).decode(errors='replace')))
    for row in git(root, "for-each-ref", "--format=%(objecttype) %(objectname)", "refs/tags").decode().splitlines():
        kind, _, sha = row.partition(" ")
        if kind == "tag" and sha:
            findings.extend({"object": sha, "path": "<tag-metadata>", **item} for item in scan_text(git(root, "cat-file", "tag", sha).decode(errors="replace")))
    return findings, count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--history', action='store_true')
    args = parser.parse_args()
    findings = check_current(args.root)
    history, count = check_history(args.root) if args.history else ([], 0)
    print(json.dumps({"status": "failed" if findings or history else "passed", "current_findings": findings, "history_findings": history, "historical_blobs": count}, ensure_ascii=False, indent=2))
    return int(bool(findings or history))


if __name__ == '__main__':
    raise SystemExit(main())
