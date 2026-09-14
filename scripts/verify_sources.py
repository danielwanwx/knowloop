#!/usr/bin/env python3
"""Fail-closed live verification for curriculum source links.

The source manifest is a reviewed snapshot, not a cache that silently absorbs
upstream changes.  Normal verification fetches every declared source and fails
when the official roster, display title, heading sequence, URL, or LeetCode
problem metadata differs from the snapshot.

The module is intentionally dependency-free so the site generator can import
``verify_manifest`` and ``resolve_reference`` before producing any output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "sources" / "source-manifest.json"
DEFAULT_ALGORITHM_BLOCKS = ROOT / "curriculum" / "algorithm-blocks.json"
HELLO_INTERVIEW_ORIGIN = "https://www.hellointerview.com"
HELLO_INTERVIEW_ROSTER_URL = (
    f"{HELLO_INTERVIEW_ORIGIN}/learn/system-design/in-a-hurry/problem-breakdowns"
)
HELLO_INTERVIEW_BREAKDOWN_PREFIX = (
    f"{HELLO_INTERVIEW_ORIGIN}/learn/system-design/problem-breakdowns/"
)
HELLO_INTERVIEW_CORE_PREFIX = (
    f"{HELLO_INTERVIEW_ORIGIN}/learn/system-design/core-concepts/"
)
HELLO_INTERVIEW_TECHNOLOGY_PREFIX = (
    f"{HELLO_INTERVIEW_ORIGIN}/learn/system-design/deep-dives/"
)
HELLO_INTERVIEW_PATTERN_PREFIX = (
    f"{HELLO_INTERVIEW_ORIGIN}/learn/system-design/patterns/"
)
HELLO_INTERVIEW_SENIOR_URL = (
    f"{HELLO_INTERVIEW_ORIGIN}/blog/"
    "the-system-design-interview-what-is-expected-at-each-level"
)
DDIA_CHINESE_PREFIX = "https://ddia.vonng.com/"
LEETCODE_CATALOG_URL = "https://leetcode.com/api/problems/all/"
LEETCODE_PROBLEM_PREFIX = "https://leetcode.com/problems/"
OPENAI_BUILDING_AGENTS_URL = "https://developers.openai.com/tracks/building-agents"
ANTHROPIC_BUILDING_EFFECTIVE_AGENTS_URL = (
    "https://www.anthropic.com/engineering/building-effective-agents"
)
ELEVENLABS_TTS_GUIDE_URL = (
    "https://elevenlabs.io/docs/eleven-creative/playground/text-to-speech"
)
DEFAULT_TIMEOUT_SECONDS = 25.0
DEFAULT_WORKERS = 6
USER_AGENT = "crack-system-interview-source-verifier/1.0"

ALLOWED_SOURCE_KINDS = {
    "hello_interview_breakdown",
    "hello_interview_core_concept",
    "hello_interview_key_technology",
    "hello_interview_pattern",
    "hello_interview_senior_expectations",
    "ddia_chinese_chapter",
    "official_ai_extension",
    "optional_generation_tool",
}


class VerificationError(RuntimeError):
    """Raised when a source cannot be proven to match the reviewed manifest."""


@dataclass(frozen=True)
class FetchResult:
    """A single HTTP response after redirects."""

    requested_url: str
    final_url: str
    status: int
    body: bytes
    headers: Mapping[str, str]

    def text(self) -> str:
        content_type = self.headers.get("content-type", "")
        match = re.search(r"charset=([A-Za-z0-9._-]+)", content_type, re.IGNORECASE)
        encoding = match.group(1) if match else "utf-8"
        try:
            return self.body.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            return self.body.decode("utf-8", errors="replace")


Fetcher = Callable[[str], FetchResult]


@dataclass(frozen=True)
class ParsedHeading:
    text: str
    id: str | None
    level: int

    def as_dict(self) -> dict[str, Any]:
        return {"text": self.text, "id": self.id, "level": self.level}


@dataclass(frozen=True)
class ParsedAnchor:
    text: str
    href: str


@dataclass(frozen=True)
class ParsedHtml:
    document_title: str
    headings: tuple[ParsedHeading, ...]
    anchors: tuple[ParsedAnchor, ...]

    @property
    def h1_titles(self) -> tuple[str, ...]:
        return tuple(heading.text for heading in self.headings if heading.level == 1)


@dataclass(frozen=True)
class VerificationReport:
    source_count: int
    breakdown_count: int
    leetcode_problem_count: int
    source_manifest_sha256: str
    algorithm_blocks_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_count": self.source_count,
            "breakdown_count": self.breakdown_count,
            "leetcode_problem_count": self.leetcode_problem_count,
            "source_manifest_sha256": self.source_manifest_sha256,
            "algorithm_blocks_sha256": self.algorithm_blocks_sha256,
        }


def collapse_whitespace(value: str) -> str:
    """Return the browser-visible whitespace-normalized text."""

    return re.sub(r"\s+", " ", value).strip()


def url_origin(url: str) -> tuple[str, str, int | None]:
    parsed = urllib.parse.urlsplit(url)
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    port = parsed.port
    if (scheme == "https" and port == 443) or (scheme == "http" and port == 80):
        port = None
    return scheme, hostname, port


def canonical_url(url: str) -> str:
    """Normalize only representation details, never paths or query strings."""

    parsed = urllib.parse.urlsplit(url)
    scheme, hostname, port = url_origin(url)
    if not scheme or not hostname:
        raise VerificationError(f"absolute https URL required: {url!r}")
    if scheme != "https":
        raise VerificationError(f"https URL required: {url!r}")
    netloc = hostname if port is None else f"{hostname}:{port}"
    path = parsed.path or "/"
    return urllib.parse.urlunsplit((scheme, netloc, path, parsed.query, ""))


def ensure_safe_fetch_result(expected_url: str, result: FetchResult) -> None:
    if result.status < 200 or result.status >= 300:
        raise VerificationError(
            f"{expected_url}: expected HTTP 2xx, got {result.status}"
        )
    if url_origin(expected_url) != url_origin(result.final_url):
        raise VerificationError(
            f"{expected_url}: cross-origin redirect to {result.final_url}"
        )
    if canonical_url(expected_url) != canonical_url(result.final_url):
        raise VerificationError(
            f"{expected_url}: canonical URL drifted to {result.final_url}"
        )


class _SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, requested_url: str) -> None:
        super().__init__()
        self.requested_url = requested_url

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Mapping[str, str],
        newurl: str,
    ) -> urllib.request.Request | None:
        absolute = urllib.parse.urljoin(req.full_url, newurl)
        if url_origin(self.requested_url) != url_origin(absolute):
            raise VerificationError(
                f"{self.requested_url}: cross-origin redirect to {absolute}"
            )
        return super().redirect_request(req, fp, code, msg, headers, absolute)


def live_fetch(url: str, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> FetchResult:
    """GET one URL while rejecting cross-origin redirects."""

    canonical_url(url)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "identity",
        },
        method="GET",
    )
    opener = urllib.request.build_opener(_SameOriginRedirectHandler(url))
    try:
        with opener.open(request, timeout=timeout) as response:
            result = FetchResult(
                requested_url=url,
                final_url=response.geturl(),
                status=int(response.status),
                body=response.read(),
                headers={key.lower(): value for key, value in response.headers.items()},
            )
    except VerificationError:
        raise
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        raise VerificationError(f"{url}: live GET failed: {exc}") from exc
    ensure_safe_fetch_result(url, result)
    return result


class _DocumentParser(HTMLParser):
    _NON_VISIBLE_TEXT_TAGS = {"noscript", "script", "style", "svg", "template"}
    _VOID_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._suppressed_tags: list[str] = []
        self._element_depth = 0
        self._heading_anchor_containers: list[tuple[str, str, int]] = []
        self._title_depth = 0
        self._title_parts: list[str] = []
        self._heading_tag: str | None = None
        self._heading_id: str | None = None
        self._heading_descendant_ids: list[str] = []
        self._heading_fragment_ids: list[str] = []
        self._heading_parts: list[str] = []
        self._anchor_depth = 0
        self._anchor_href: str | None = None
        self._anchor_parts: list[str] = []
        self.headings: list[ParsedHeading] = []
        self.anchors: list[ParsedAnchor] = []

    @property
    def document_title(self) -> str:
        return collapse_whitespace(" ".join(self._title_parts))

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attrs_dict = dict(attrs)
        hidden = (
            tag in self._NON_VISIBLE_TEXT_TAGS
            or str(attrs_dict.get("aria-hidden", "")).lower() == "true"
            or "hidden" in attrs_dict
        )
        if self._suppressed_tags or hidden:
            if tag not in self._VOID_TAGS:
                self._suppressed_tags.append(tag)
            return
        if tag not in self._VOID_TAGS:
            self._element_depth += 1
        classes = set(str(attrs_dict.get("class") or "").split())
        if (
            tag == "div"
            and "fern-step" in classes
            and isinstance(attrs_dict.get("id"), str)
            and attrs_dict["id"]
        ):
            self._heading_anchor_containers.append(
                (tag, str(attrs_dict["id"]), self._element_depth)
            )
        if tag == "title":
            self._title_depth += 1
        if re.fullmatch(r"h[1-6]", tag):
            if self._heading_tag is not None:
                raise VerificationError("nested heading elements are not supported")
            self._heading_tag = tag
            self._heading_id = attrs_dict.get("id") or (
                self._heading_anchor_containers[-1][1]
                if self._heading_anchor_containers
                else None
            )
            self._heading_descendant_ids = []
            self._heading_fragment_ids = []
            self._heading_parts = []
        elif self._heading_tag is not None:
            # DDIA's published HTML places the real fragment target on an
            # empty span inside each heading rather than on the H2/H3 itself.
            # Accept it only when the heading also contains a self-link to the
            # same fragment; arbitrary accordion/button ids are not anchors.
            descendant_id = attrs_dict.get("id") or (
                attrs_dict.get("name") if tag == "a" else None
            )
            if descendant_id:
                self._heading_descendant_ids.append(descendant_id)
            href = attrs_dict.get("href")
            if tag == "a" and isinstance(href, str) and href.startswith("#"):
                fragment_id = urllib.parse.unquote(href[1:])
                if fragment_id:
                    self._heading_fragment_ids.append(fragment_id)
        if tag == "a":
            if self._anchor_depth == 0:
                self._anchor_href = attrs_dict.get("href")
                self._anchor_parts = []
            self._anchor_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._suppressed_tags:
            if tag in self._suppressed_tags:
                while self._suppressed_tags:
                    opened = self._suppressed_tags.pop()
                    if opened == tag:
                        break
            return
        if tag == "title" and self._title_depth:
            self._title_depth -= 1
        if tag == self._heading_tag:
            text = collapse_whitespace(" ".join(self._heading_parts))
            heading_id = self._heading_id
            if heading_id is None:
                linked_descendant_ids = {
                    heading_id
                    for heading_id in self._heading_descendant_ids
                    if heading_id in self._heading_fragment_ids
                }
                if len(linked_descendant_ids) == 1:
                    heading_id = next(iter(linked_descendant_ids))
            if text:
                self.headings.append(
                    ParsedHeading(
                        text=text,
                        id=heading_id,
                        level=int(tag[1]),
                    )
                )
            self._heading_tag = None
            self._heading_id = None
            self._heading_descendant_ids = []
            self._heading_fragment_ids = []
            self._heading_parts = []
        if tag == "a" and self._anchor_depth:
            self._anchor_depth -= 1
            if self._anchor_depth == 0:
                text = collapse_whitespace(" ".join(self._anchor_parts))
                if self._anchor_href and text:
                    self.anchors.append(ParsedAnchor(text=text, href=self._anchor_href))
                self._anchor_href = None
                self._anchor_parts = []
        if (
            self._heading_anchor_containers
            and self._heading_anchor_containers[-1][0] == tag
            and self._heading_anchor_containers[-1][2] == self._element_depth
        ):
            self._heading_anchor_containers.pop()
        if tag not in self._VOID_TAGS:
            self._element_depth = max(0, self._element_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._suppressed_tags:
            return
        if self._title_depth:
            self._title_parts.append(data)
        if self._heading_tag is not None:
            self._heading_parts.append(data)
        if self._anchor_depth:
            self._anchor_parts.append(data)


def parse_html(html: str) -> ParsedHtml:
    parser = _DocumentParser()
    try:
        parser.feed(html)
        parser.close()
    except VerificationError:
        raise
    except Exception as exc:
        raise VerificationError(f"invalid HTML: {exc}") from exc
    return ParsedHtml(
        document_title=parser.document_title,
        headings=tuple(parser.headings),
        anchors=tuple(parser.anchors),
    )


def display_title(document: ParsedHtml, mode: str) -> str:
    if mode == "document_title":
        if not document.document_title:
            raise VerificationError("document has no non-empty <title>")
        return document.document_title
    if mode != "h1":
        raise VerificationError(f"unsupported title_mode {mode!r}")
    if not document.h1_titles:
        raise VerificationError("document has no non-empty H1")
    # The first H1 is the canonical article heading in document order. Some
    # official pages also server-render auxiliary dialogs (for example a
    # "Changelog" H1) or repeat the article H1 for responsive layouts. Those
    # elements remain in the complete heading snapshot, but cannot redefine
    # the page's display title.
    return document.h1_titles[0]


def heading_structure_digest(title: str, headings: Sequence[Mapping[str, Any]]) -> str:
    # Keep the complete raw heading snapshot in the manifest, but hash the
    # linkable article structure. Official pages A/B-test unanchored CTA and
    # navigation headings ("Try This Problem Yourself", video prompts, footer
    # labels); those cannot be linked and are not source-anchor drift.
    linkable_headings = [
        dict(heading) for heading in headings if heading.get("id") is not None
    ]
    payload = json.dumps(
        {"title": title, "linkable_headings": linkable_headings},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _manifest_heading(entry: Mapping[str, Any], source_id: str) -> dict[str, Any]:
    required_keys = {"text", "id", "level"}
    if set(entry) != required_keys:
        raise VerificationError(
            f"{source_id}: heading must contain exactly {sorted(required_keys)}"
        )
    text = entry["text"]
    heading_id = entry["id"]
    level = entry["level"]
    if not isinstance(text, str) or not text or text != collapse_whitespace(text):
        raise VerificationError(f"{source_id}: invalid exact heading text {text!r}")
    if heading_id is not None and (
        not isinstance(heading_id, str) or not heading_id.strip()
    ):
        raise VerificationError(f"{source_id}: invalid heading id {heading_id!r}")
    if not isinstance(level, int) or level < 1 or level > 6:
        raise VerificationError(f"{source_id}: invalid heading level {level!r}")
    return {"text": text, "id": heading_id, "level": level}


def validate_source_provenance(source_id: str, kind: str, url: str) -> None:
    """Bind every source category to its reviewed first-party origin and path."""

    if kind not in ALLOWED_SOURCE_KINDS:
        raise VerificationError(f"{source_id}: unsupported source kind {kind!r}")
    canonical = canonical_url(url)
    parsed = urllib.parse.urlsplit(url)
    if url != canonical or parsed.query or parsed.fragment:
        raise VerificationError(
            f"{source_id}: source URL must be an exact canonical page URL"
        )

    prefix_rules = {
        "hello_interview_breakdown": (
            "hi.breakdown.",
            HELLO_INTERVIEW_BREAKDOWN_PREFIX,
        ),
        "hello_interview_core_concept": (
            "hi.core.",
            HELLO_INTERVIEW_CORE_PREFIX,
        ),
        "hello_interview_key_technology": (
            "hi.deep.",
            HELLO_INTERVIEW_TECHNOLOGY_PREFIX,
        ),
        "hello_interview_pattern": (
            "hi.pattern.",
            HELLO_INTERVIEW_PATTERN_PREFIX,
        ),
    }
    if kind in prefix_rules:
        id_prefix, url_prefix = prefix_rules[kind]
        if not source_id.startswith(id_prefix) or not url.startswith(url_prefix):
            raise VerificationError(
                f"{source_id}: {kind} must use {id_prefix!r} and {url_prefix!r}"
            )
        id_slug = source_id.removeprefix(id_prefix)
        url_slug = url.removeprefix(url_prefix)
        if (
            not id_slug
            or id_slug != url_slug
            or "/" in url_slug
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", url_slug)
        ):
            raise VerificationError(
                f"{source_id}: source id and official URL slug do not match"
            )
        return

    if kind == "hello_interview_senior_expectations":
        if source_id != "hi.senior.expectations" or url != HELLO_INTERVIEW_SENIOR_URL:
            raise VerificationError(
                f"{source_id}: senior expectations must use the reviewed "
                "Hello Interview article"
            )
        return

    if kind == "ddia_chinese_chapter":
        match = re.fullmatch(r"ddia\.ch([1-9]|1[0-3])", source_id)
        expected = (
            f"{DDIA_CHINESE_PREFIX}ch{match.group(1)}/" if match else None
        )
        if expected is None or url != expected:
            raise VerificationError(
                f"{source_id}: DDIA source must map exactly to ddia.vonng.com/chN/"
            )
        return

    official_ai_sources = {
        "openai.building-agents": OPENAI_BUILDING_AGENTS_URL,
        "anthropic.building-effective-agents": (
            ANTHROPIC_BUILDING_EFFECTIVE_AGENTS_URL
        ),
    }
    if kind == "official_ai_extension":
        if official_ai_sources.get(source_id) != url:
            raise VerificationError(
                f"{source_id}: AI extensions are limited to the reviewed "
                "official OpenAI and Anthropic pages"
            )
        return

    if (
        source_id != "elevenlabs.tts.optional"
        or kind != "optional_generation_tool"
        or url != ELEVENLABS_TTS_GUIDE_URL
    ):
        raise VerificationError(
            f"{source_id}: optional generation tools are limited to the "
            "reviewed ElevenLabs Text to Speech page"
        )


def validate_manifest_shape(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema_version") != 1:
        raise VerificationError("source manifest schema_version must be 1")
    roster = manifest.get("roster")
    if not isinstance(roster, Mapping):
        raise VerificationError("source manifest must contain roster")
    if roster.get("url") != HELLO_INTERVIEW_ROSTER_URL:
        raise VerificationError("roster URL is not the official Hello Interview URL")
    if roster.get("expected_count") != 30:
        raise VerificationError("Hello Interview roster gate must be exactly 30")
    roster_entries = roster.get("entries")
    if not isinstance(roster_entries, list) or len(roster_entries) != 30:
        raise VerificationError("manifest roster must contain exactly 30 entries")
    roster_by_id: dict[str, Mapping[str, Any]] = {}
    for entry in roster_entries:
        if not isinstance(entry, Mapping) or set(entry) != {
            "source_id",
            "title",
            "url",
        }:
            raise VerificationError(
                "roster entries must contain exactly source_id, title, and url"
            )
        source_id = entry["source_id"]
        title = entry["title"]
        url = entry["url"]
        if (
            not isinstance(source_id, str)
            or not isinstance(title, str)
            or not title
            or title != collapse_whitespace(title)
            or not isinstance(url, str)
        ):
            raise VerificationError("malformed exact roster entry")
        slug = _slug_from_breakdown_url(canonical_url(url))
        if source_id != f"hi.breakdown.{slug}":
            raise VerificationError(
                f"roster source id {source_id!r} does not match URL slug {slug!r}"
            )
        if source_id in roster_by_id:
            raise VerificationError(f"duplicate roster source id {source_id!r}")
        roster_by_id[source_id] = entry

    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise VerificationError("source manifest must contain a non-empty sources list")
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    sources_by_id: dict[str, Mapping[str, Any]] = {}
    gap_fallbacks: list[tuple[str, str]] = []
    for source in sources:
        if not isinstance(source, Mapping):
            raise VerificationError("source entries must be objects")
        source_id = source.get("id")
        title = source.get("title")
        url = source.get("url")
        if not isinstance(source_id, str) or not source_id:
            raise VerificationError("every source requires a stable id")
        if source_id in seen_ids:
            raise VerificationError(f"duplicate source id {source_id!r}")
        seen_ids.add(source_id)
        sources_by_id[source_id] = source
        kind = source.get("kind")
        if not isinstance(kind, str) or not kind:
            raise VerificationError(f"{source_id}: source kind is required")
        if source.get("title_mode", "h1") not in {"h1", "document_title"}:
            raise VerificationError(f"{source_id}: unsupported title_mode")
        if not isinstance(title, str) or not title or title != collapse_whitespace(title):
            raise VerificationError(f"{source_id}: invalid exact source title {title!r}")
        if not isinstance(url, str):
            raise VerificationError(f"{source_id}: URL must be a string")
        validate_source_provenance(source_id, kind, url)
        normalized_url = canonical_url(url)
        if normalized_url in seen_urls:
            raise VerificationError(f"duplicate source URL {normalized_url}")
        seen_urls.add(normalized_url)
        headings = source.get("headings")
        if not isinstance(headings, list):
            raise VerificationError(f"{source_id}: headings must be a list")
        normalized_headings = [
            _manifest_heading(heading, source_id) for heading in headings
        ]
        ids = [
            heading["id"]
            for heading in normalized_headings
            if heading["id"] is not None
        ]
        if len(ids) != len(set(ids)):
            raise VerificationError(f"{source_id}: duplicate non-empty heading ids")
        digest = source.get("structure_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise VerificationError(f"{source_id}: invalid structure_sha256")
        expected_digest = heading_structure_digest(title, normalized_headings)
        if digest != expected_digest:
            raise VerificationError(f"{source_id}: stale structure_sha256")
        for section in source.get("sections", []):
            if not isinstance(section, Mapping):
                raise VerificationError(f"{source_id}: section references must be objects")
            resolve_heading(
                source,
                text=section.get("text"),
                heading_id=section.get("id"),
                level=section.get("level"),
            )
        for gap in source.get("source_gaps", []):
            if not isinstance(gap, Mapping) or not isinstance(gap.get("text"), str):
                raise VerificationError(f"{source_id}: malformed source_gaps entry")
            if any(heading["text"] == gap["text"] for heading in normalized_headings):
                raise VerificationError(
                    f"{source_id}: declared source gap {gap['text']!r} now exists"
                )
            fallback_source_id = gap.get("fallback_source_id")
            if fallback_source_id is not None:
                if not isinstance(fallback_source_id, str):
                    raise VerificationError(
                        f"{source_id}: source gap fallback must be a source id"
                    )
                gap_fallbacks.append((source_id, fallback_source_id))

    for source_id, roster_entry in roster_by_id.items():
        source = sources_by_id.get(source_id)
        if (
            source is None
            or source.get("kind") != "hello_interview_breakdown"
            or source.get("title") != roster_entry["title"]
            or canonical_url(str(source.get("url"))) != roster_entry["url"]
        ):
            raise VerificationError(
                f"{source_id}: breakdown source does not match roster snapshot"
            )
    breakdown_ids = {
        source_id
        for source_id, source in sources_by_id.items()
        if source.get("kind") == "hello_interview_breakdown"
    }
    if breakdown_ids != set(roster_by_id):
        raise VerificationError(
            "breakdown source ids must exactly match the 30-item roster"
        )
    for source_id, fallback_source_id in gap_fallbacks:
        if fallback_source_id not in sources_by_id:
            raise VerificationError(
                f"{source_id}: unknown source gap fallback {fallback_source_id!r}"
            )

    official_ai_sources = {
        "openai.building-agents": OPENAI_BUILDING_AGENTS_URL,
        "anthropic.building-effective-agents": (
            ANTHROPIC_BUILDING_EFFECTIVE_AGENTS_URL
        ),
    }
    for source_id, exact_url in official_ai_sources.items():
        source = sources_by_id.get(source_id)
        if (
            source is None
            or source.get("kind") != "official_ai_extension"
            or source.get("url") != exact_url
        ):
            raise VerificationError(
                f"{source_id}: required official AI extension is missing"
            )
    elevenlabs = sources_by_id.get("elevenlabs.tts.optional")
    if (
        elevenlabs is None
        or elevenlabs.get("kind") != "optional_generation_tool"
        or elevenlabs.get("title") != "Text to Speech"
        or elevenlabs.get("url") != ELEVENLABS_TTS_GUIDE_URL
    ):
        raise VerificationError("canonical optional ElevenLabs guide is required")
    resolve_heading(
        elevenlabs,
        text="Text input",
        heading_id="text-input",
        level=3,
    )

    leetcode = manifest.get("leetcode")
    if not isinstance(leetcode, Mapping):
        raise VerificationError("source manifest must contain leetcode metadata")
    if leetcode.get("catalog_url") != LEETCODE_CATALOG_URL:
        raise VerificationError("LeetCode catalog URL must use the official GET endpoint")
    if not isinstance(leetcode.get("problems"), list):
        raise VerificationError("leetcode.problems must be a list")


def source_index(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {str(source["id"]): source for source in manifest["sources"]}


def resolve_heading(
    source: Mapping[str, Any],
    *,
    text: Any,
    heading_id: Any = None,
    level: Any = None,
) -> Mapping[str, Any]:
    """Resolve only an exact displayed heading, failing on aliases or ambiguity."""

    source_id = str(source.get("id") or "<unknown-source>")
    if not isinstance(text, str) or not text or text != collapse_whitespace(text):
        raise VerificationError(f"{source_id}: exact heading text is required")
    if heading_id is not None and not isinstance(heading_id, str):
        raise VerificationError(f"{source_id}: heading id must be a string or null")
    if level is not None and not isinstance(level, int):
        raise VerificationError(f"{source_id}: heading level must be an integer or null")
    matches = [
        heading
        for heading in source.get("headings", [])
        if heading["text"] == text
        and (heading_id is None or heading["id"] == heading_id)
        and (level is None or heading["level"] == level)
    ]
    if not matches:
        raise VerificationError(
            f"{source_id}: no exact heading match for text={text!r}, "
            f"id={heading_id!r}, level={level!r}"
        )
    if len(matches) != 1:
        raise VerificationError(
            f"{source_id}: duplicate heading match for text={text!r}; "
            "supply the reviewed id and level"
        )
    if matches[0]["id"] is None:
        raise VerificationError(
            f"{source_id}: heading {text!r} has no HTML id and cannot be linked"
        )
    return matches[0]


def resolve_reference(
    manifest: Mapping[str, Any],
    *,
    source_id: str,
    source_title: str,
    heading_text: str,
    heading_id: str | None = None,
    heading_level: int | None = None,
) -> str:
    """Return a verified fragment URL for generators.

    The caller must provide the source's exact displayed title as an additional
    guard against abbreviated or stale labels.
    """

    sources = source_index(manifest)
    source = sources.get(source_id)
    if source is None:
        raise VerificationError(f"unknown source id {source_id!r}")
    if source_title != source["title"]:
        raise VerificationError(
            f"{source_id}: source title must be exact; expected "
            f"{source['title']!r}, got {source_title!r}"
        )
    heading = resolve_heading(
        source,
        text=heading_text,
        heading_id=heading_id,
        level=heading_level,
    )
    return f"{source['url']}#{heading['id']}"


def discover_hello_interview_roster(
    document: ParsedHtml,
) -> list[dict[str, str]]:
    """Extract the first concise label for each unique official breakdown URL."""

    entries: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    for anchor in document.anchors:
        absolute = urllib.parse.urljoin(HELLO_INTERVIEW_ROSTER_URL, anchor.href)
        parsed = urllib.parse.urlsplit(absolute)
        if url_origin(absolute) != url_origin(HELLO_INTERVIEW_ROSTER_URL):
            continue
        if not absolute.startswith(HELLO_INTERVIEW_BREAKDOWN_PREFIX):
            continue
        if parsed.query or parsed.fragment:
            continue
        slug = parsed.path.removeprefix(
            "/learn/system-design/problem-breakdowns/"
        ).strip("/")
        if not slug or "/" in slug:
            continue
        url = f"{HELLO_INTERVIEW_BREAKDOWN_PREFIX}{slug}"
        if url in seen_urls:
            continue
        title = anchor.text
        if not title or title != collapse_whitespace(title):
            raise VerificationError(f"invalid roster title for {url}: {title!r}")
        if title in seen_titles:
            raise VerificationError(f"duplicate roster display title {title!r}")
        entries.append({"title": title, "url": url})
        seen_urls.add(url)
        seen_titles.add(title)
    return entries


def _roster_map(entries: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for entry in entries:
        title = entry.get("title")
        url = entry.get("url")
        if not isinstance(title, str) or not isinstance(url, str):
            raise VerificationError("roster entries require exact title and URL")
        if url in result:
            raise VerificationError(f"duplicate roster URL {url}")
        result[url] = title
    return result


def verify_roster(
    manifest: Mapping[str, Any],
    document: ParsedHtml,
) -> list[dict[str, str]]:
    live_entries = discover_hello_interview_roster(document)
    expected_count = int(manifest["roster"]["expected_count"])
    if len(live_entries) < expected_count:
        raise VerificationError(
            f"Hello Interview roster gate failed: expected {expected_count}, "
            f"found {len(live_entries)}"
        )
    live_map = _roster_map(live_entries)
    snapshot_map = _roster_map(manifest["roster"]["entries"])
    if any(live_map.get(url) != title for url, title in snapshot_map.items()):
        missing = sorted(set(snapshot_map) - set(live_map))
        added = sorted(set(live_map) - set(snapshot_map))
        renamed = sorted(
            url
            for url in set(live_map) & set(snapshot_map)
            if live_map[url] != snapshot_map[url]
        )
        raise VerificationError(
            "Hello Interview roster drift: "
            f"missing={missing}, added={added}, renamed={renamed}"
        )
    breakdown_sources = [
        source
        for source in manifest["sources"]
        if source.get("kind") == "hello_interview_breakdown"
    ]
    breakdown_map = {source["url"]: source["title"] for source in breakdown_sources}
    if len(breakdown_sources) != expected_count or breakdown_map != snapshot_map:
        raise VerificationError(
            "manifest breakdown sources must exactly match the 30-item roster"
        )
    # Upstream additions are outside the reviewed curriculum, not source drift.
    return [entry for entry in live_entries if entry["url"] in snapshot_map]


def _actual_heading_dicts(document: ParsedHtml) -> list[dict[str, Any]]:
    return [heading.as_dict() for heading in document.headings]


def verify_source_document(
    source: Mapping[str, Any],
    result: FetchResult,
) -> None:
    source_id = str(source["id"])
    ensure_safe_fetch_result(str(source["url"]), result)
    document = parse_html(result.text())
    actual_title = display_title(document, str(source.get("title_mode", "h1")))
    if actual_title != source["title"]:
        raise VerificationError(
            f"{source_id}: display title drift; expected {source['title']!r}, "
            f"got {actual_title!r}"
        )
    actual_headings = _actual_heading_dicts(document)
    expected_headings = [
        _manifest_heading(heading, source_id) for heading in source["headings"]
    ]
    actual_linkable = [
        heading for heading in actual_headings if heading["id"] is not None
    ]
    expected_linkable = [
        heading for heading in expected_headings if heading["id"] is not None
    ]
    if actual_linkable != expected_linkable:
        mismatch_index = next(
            (
                index
                for index, (expected, actual) in enumerate(
                    zip(expected_linkable, actual_linkable)
                )
                if expected != actual
            ),
            min(len(expected_linkable), len(actual_linkable)),
        )
        expected_value = (
            expected_linkable[mismatch_index]
            if mismatch_index < len(expected_linkable)
            else "<end>"
        )
        actual_value = (
            actual_linkable[mismatch_index]
            if mismatch_index < len(actual_linkable)
            else "<end>"
        )
        raise VerificationError(
            f"{source_id}: anchored heading drift at index {mismatch_index}; "
            f"expected {expected_value!r}, got {actual_value!r}"
        )
    digest = heading_structure_digest(actual_title, actual_headings)
    if digest != source["structure_sha256"]:
        raise VerificationError(f"{source_id}: live structure digest drift")
    for section in source.get("sections", []):
        resolve_heading(
            source,
            text=section.get("text"),
            heading_id=section.get("id"),
            level=section.get("level"),
        )
    for gap in source.get("source_gaps", []):
        if any(heading["text"] == gap["text"] for heading in actual_headings):
            raise VerificationError(
                f"{source_id}: source gap {gap['text']!r} was filled upstream; "
                "review the curriculum before refreshing"
            )


def _problem_slug_from_url(url: str) -> str:
    canonical = canonical_url(url)
    if not canonical.startswith(LEETCODE_PROBLEM_PREFIX):
        raise VerificationError(f"not an official LeetCode problem URL: {url!r}")
    parsed = urllib.parse.urlsplit(canonical)
    slug = parsed.path.removeprefix("/problems/").strip("/")
    if not slug or "/" in slug or parsed.query:
        raise VerificationError(f"invalid LeetCode problem URL: {url!r}")
    expected = f"{LEETCODE_PROBLEM_PREFIX}{slug}/"
    if canonical != expected:
        raise VerificationError(
            f"LeetCode URL must be canonical {expected!r}, got {url!r}"
        )
    return slug


def extract_algorithm_problems(data: Any) -> list[dict[str, str]]:
    """Validate the reviewed block schema and return canonical problem records."""

    if not isinstance(data, Mapping):
        raise VerificationError("algorithm-blocks.json must be an object")
    if data.get("schema_version") != "1.0":
        raise VerificationError("algorithm-blocks schema_version must be '1.0'")
    if data.get("provider") != "LeetCode":
        raise VerificationError("algorithm-blocks provider must be 'LeetCode'")
    url_template = data.get("url_template")
    if url_template != f"{LEETCODE_PROBLEM_PREFIX}{{slug}}/":
        raise VerificationError(
            "algorithm-blocks url_template must be the canonical LeetCode template"
        )
    blocks = data.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise VerificationError("algorithm-blocks must contain a non-empty blocks list")

    occurrences: list[dict[str, str]] = []
    block_ids: set[str] = set()
    for block in blocks:
        if not isinstance(block, Mapping):
            raise VerificationError("algorithm blocks must be objects")
        block_id = block.get("id")
        tag = block.get("tag")
        if not isinstance(block_id, str) or not block_id:
            raise VerificationError("every algorithm block requires an id")
        if block_id in block_ids:
            raise VerificationError(f"duplicate algorithm block id {block_id!r}")
        block_ids.add(block_id)
        if not isinstance(tag, str) or not tag or tag != collapse_whitespace(tag):
            raise VerificationError(f"{block_id}: invalid exact NeetCode tag {tag!r}")
        problems = block.get("problems")
        if not isinstance(problems, list) or not problems:
            raise VerificationError(f"{block_id}: problems must be a non-empty list")
        for problem in problems:
            if not isinstance(problem, Mapping) or set(problem) != {"slug", "title"}:
                raise VerificationError(
                    f"{block_id}: each problem must contain exactly slug and title"
                )
            title = problem["title"]
            slug = problem["slug"]
            if (
                not isinstance(title, str)
                or not title
                or title != collapse_whitespace(title)
            ):
                raise VerificationError(
                    f"{block_id}: algorithm problem has invalid exact title {title!r}"
                )
            if (
                not isinstance(slug, str)
                or not slug
                or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug)
            ):
                raise VerificationError(
                    f"{block_id}: algorithm problem has invalid slug {slug!r}"
                )
            url = url_template.format(slug=slug)
            if _problem_slug_from_url(url) != slug:
                raise VerificationError(
                    f"{block_id}: problem slug {slug!r} cannot form a canonical URL"
                )
            occurrences.append({"title": title, "slug": slug, "url": url})

        day_mode = block.get("day_mode")
        days = block.get("days")
        if not isinstance(days, list) or not days:
            raise VerificationError(f"{block_id}: days must be a non-empty list")
        if (
            not isinstance(day_mode, list)
            or len(day_mode) != len(days)
            or not all(isinstance(mode, str) and mode for mode in day_mode)
        ):
            raise VerificationError(
                f"{block_id}: day_mode must align one-to-one with days"
            )
        for day_number, day in enumerate(days, start=1):
            if (
                not isinstance(day, list)
                or len(day) != 3
                or not all(
                    isinstance(index, int)
                    and not isinstance(index, bool)
                    and 0 <= index < len(problems)
                    for index in day
                )
            ):
                raise VerificationError(
                    f"{block_id}: day {day_number} must contain three valid indices"
                )
            if len(set(day)) != 3:
                raise VerificationError(
                    f"{block_id}: day {day_number} repeats a problem index"
                )

    by_slug: dict[str, dict[str, str]] = {}
    for problem in occurrences:
        previous = by_slug.get(problem["slug"])
        if previous is not None and previous != problem:
            raise VerificationError(
                f"conflicting algorithm metadata for slug {problem['slug']!r}"
            )
        by_slug[problem["slug"]] = problem
    return occurrences


def parse_leetcode_catalog(payload: Any) -> dict[str, dict[str, str]]:
    if not isinstance(payload, Mapping):
        raise VerificationError("LeetCode catalog must be a JSON object")
    pairs = payload.get("stat_status_pairs")
    if not isinstance(pairs, list) or not pairs:
        raise VerificationError("LeetCode catalog has no stat_status_pairs")
    catalog: dict[str, dict[str, str]] = {}
    for pair in pairs:
        if not isinstance(pair, Mapping) or not isinstance(pair.get("stat"), Mapping):
            raise VerificationError("malformed LeetCode stat_status_pairs entry")
        stat = pair["stat"]
        slug = stat.get("question__title_slug")
        title = stat.get("question__title")
        frontend_id = stat.get("frontend_question_id")
        if not isinstance(slug, str) or not isinstance(title, str):
            raise VerificationError("LeetCode catalog entry lacks title or title slug")
        candidate = {
            "slug": slug,
            "title": title,
            "url": f"{LEETCODE_PROBLEM_PREFIX}{slug}/",
            "frontend_id": str(frontend_id),
        }
        previous = catalog.get(slug)
        if previous is not None and previous != candidate:
            raise VerificationError(f"duplicate conflicting LeetCode slug {slug!r}")
        catalog[slug] = candidate
    return catalog


def _load_json_bytes(result: FetchResult, label: str) -> Any:
    try:
        return json.loads(result.text())
    except json.JSONDecodeError as exc:
        raise VerificationError(f"{label}: invalid JSON: {exc}") from exc


def verify_algorithm_blocks(
    manifest: Mapping[str, Any],
    algorithm_blocks: Any,
    leetcode_catalog: Any,
) -> int:
    occurrences = extract_algorithm_problems(algorithm_blocks)
    official = parse_leetcode_catalog(leetcode_catalog)
    unique: dict[str, dict[str, str]] = {}
    for problem in occurrences:
        live = official.get(problem["slug"])
        if live is None:
            raise VerificationError(
                f"LeetCode slug {problem['slug']!r} is absent from official catalog"
            )
        if live["title"] != problem["title"]:
            raise VerificationError(
                f"LeetCode title drift for {problem['slug']!r}: expected official "
                f"{live['title']!r}, got {problem['title']!r}"
            )
        if live["url"] != problem["url"]:
            raise VerificationError(
                f"LeetCode URL drift for {problem['slug']!r}: "
                f"expected {live['url']!r}, got {problem['url']!r}"
            )
        unique[problem["slug"]] = {
            "slug": live["slug"],
            "title": live["title"],
            "url": live["url"],
            "frontend_id": live["frontend_id"],
        }
    snapshot_list = manifest["leetcode"]["problems"]
    snapshot: dict[str, dict[str, str]] = {}
    for problem in snapshot_list:
        if not isinstance(problem, Mapping):
            raise VerificationError("leetcode.problems entries must be objects")
        frontend_id = problem.get("frontend_id")
        if not isinstance(frontend_id, (str, int)) or isinstance(frontend_id, bool):
            raise VerificationError("malformed leetcode.problems frontend_id")
        normalized = {
            "slug": problem.get("slug"),
            "title": problem.get("title"),
            "url": problem.get("url"),
            "frontend_id": str(frontend_id),
        }
        if not all(
            isinstance(normalized[key], str) and normalized[key]
            for key in ("slug", "title", "url", "frontend_id")
        ):
            raise VerificationError("malformed leetcode.problems entry")
        if _problem_slug_from_url(normalized["url"]) != normalized["slug"]:
            raise VerificationError("manifest LeetCode slug and URL disagree")
        if normalized["slug"] in snapshot:
            raise VerificationError(
                f"duplicate manifest LeetCode slug {normalized['slug']!r}"
            )
        snapshot[normalized["slug"]] = normalized
    if snapshot != unique:
        missing = sorted(set(snapshot) - set(unique))
        added = sorted(set(unique) - set(snapshot))
        changed = sorted(
            slug
            for slug in set(snapshot) & set(unique)
            if snapshot[slug] != unique[slug]
        )
        raise VerificationError(
            "LeetCode manifest drift: "
            f"missing_from_blocks={missing}, added_to_blocks={added}, changed={changed}"
        )
    return len(unique)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise VerificationError(f"required JSON file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise VerificationError(f"{path}: invalid JSON: {exc}") from exc


def load_json_snapshot(path: Path) -> tuple[Any, str]:
    """Parse one immutable byte snapshot and return its SHA-256."""

    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise VerificationError(f"required JSON file does not exist: {path}") from exc
    try:
        return json.loads(raw), hashlib.sha256(raw).hexdigest()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise VerificationError(f"{path}: invalid JSON: {exc}") from exc


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT.resolve()))
    except ValueError:
        return str(resolved)


def verify_manifest(
    manifest_path: Path = DEFAULT_MANIFEST,
    algorithm_blocks_path: Path = DEFAULT_ALGORITHM_BLOCKS,
    *,
    fetcher: Fetcher | None = None,
    max_workers: int = DEFAULT_WORKERS,
) -> VerificationReport:
    """Live-verify the complete manifest and return audited counts."""

    manifest, manifest_digest = load_json_snapshot(manifest_path)
    validate_manifest_shape(manifest)
    algorithm_blocks, algorithm_digest = load_json_snapshot(algorithm_blocks_path)
    if fetcher is None:
        fetcher = live_fetch

    roster_result = fetcher(str(manifest["roster"]["url"]))
    ensure_safe_fetch_result(str(manifest["roster"]["url"]), roster_result)
    roster_document = parse_html(roster_result.text())
    live_roster = verify_roster(manifest, roster_document)

    errors: list[str] = []
    sources = list(manifest["sources"])
    worker_count = max(1, min(int(max_workers), len(sources)))

    def verify_one(source: Mapping[str, Any]) -> None:
        result = fetcher(str(source["url"]))
        verify_source_document(source, result)

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_sources = {
            executor.submit(verify_one, source): source for source in sources
        }
        for future in as_completed(future_sources):
            source = future_sources[future]
            try:
                future.result()
            except Exception as exc:
                errors.append(f"{source['id']}: {exc}")
    if errors:
        raise VerificationError(
            "live source verification failed:\n- " + "\n- ".join(sorted(errors))
        )

    leetcode_result = fetcher(str(manifest["leetcode"]["catalog_url"]))
    ensure_safe_fetch_result(
        str(manifest["leetcode"]["catalog_url"]), leetcode_result
    )
    leetcode_count = verify_algorithm_blocks(
        manifest,
        algorithm_blocks,
        _load_json_bytes(leetcode_result, "LeetCode catalog"),
    )
    return VerificationReport(
        source_count=len(sources),
        breakdown_count=len(live_roster),
        leetcode_problem_count=leetcode_count,
        source_manifest_sha256=manifest_digest,
        algorithm_blocks_sha256=algorithm_digest,
    )


def _slug_from_breakdown_url(url: str) -> str:
    if not url.startswith(HELLO_INTERVIEW_BREAKDOWN_PREFIX):
        raise VerificationError(f"not a Hello Interview breakdown URL: {url}")
    slug = url.removeprefix(HELLO_INTERVIEW_BREAKDOWN_PREFIX)
    if not slug or "/" in slug:
        raise VerificationError(f"invalid breakdown slug in {url}")
    return slug


def _refresh_one_source(
    source: Mapping[str, Any],
    fetcher: Fetcher,
) -> dict[str, Any]:
    result = fetcher(str(source["url"]))
    ensure_safe_fetch_result(str(source["url"]), result)
    document = parse_html(result.text())
    title = display_title(document, str(source.get("title_mode", "h1")))
    refreshed = dict(source)
    refreshed["title"] = title
    refreshed["headings"] = _actual_heading_dicts(document)
    refreshed["structure_sha256"] = heading_structure_digest(
        title, refreshed["headings"]
    )
    for section in refreshed.get("sections", []):
        resolve_heading(
            refreshed,
            text=section.get("text"),
            heading_id=section.get("id"),
            level=section.get("level"),
        )
    for gap in refreshed.get("source_gaps", []):
        if any(
            heading["text"] == gap.get("text")
            for heading in refreshed["headings"]
        ):
            raise VerificationError(
                f"{refreshed['id']}: source gap {gap.get('text')!r} now exists"
            )
    return refreshed


def refresh_manifest(
    manifest_path: Path = DEFAULT_MANIFEST,
    algorithm_blocks_path: Path = DEFAULT_ALGORITHM_BLOCKS,
    *,
    fetcher: Fetcher | None = None,
    max_workers: int = DEFAULT_WORKERS,
) -> VerificationReport:
    """Explicitly refresh the reviewed snapshot after upstream review."""

    manifest = load_json(manifest_path)
    if manifest.get("schema_version") != 1:
        raise VerificationError("source manifest schema_version must be 1")

    # Refresh is allowed to repair reviewed titles, headings, and digests after
    # upstream drift, but it must never use an unreviewed URL as a fetch target.
    # Perform this provenance-only preflight before invoking the supplied
    # fetcher even once.
    roster = manifest.get("roster")
    if not isinstance(roster, Mapping):
        raise VerificationError("source manifest must contain roster")
    if roster.get("url") != HELLO_INTERVIEW_ROSTER_URL:
        raise VerificationError("roster URL is not the official Hello Interview URL")
    expected_count = roster.get("expected_count")
    if (
        not isinstance(expected_count, int)
        or isinstance(expected_count, bool)
        or expected_count != 30
    ):
        raise VerificationError("Hello Interview roster gate must be exactly 30")

    source_entries = manifest.get("sources")
    if not isinstance(source_entries, list) or not source_entries:
        raise VerificationError("source manifest must contain a non-empty sources list")
    existing_sources: dict[str, dict[str, Any]] = {}
    for source in source_entries:
        if not isinstance(source, Mapping):
            raise VerificationError("source entries must be objects")
        source_id = source.get("id")
        kind = source.get("kind")
        url = source.get("url")
        if not isinstance(source_id, str) or not source_id:
            raise VerificationError("every source requires a stable id")
        if source_id in existing_sources:
            raise VerificationError(f"duplicate source id {source_id!r}")
        if not isinstance(kind, str) or not kind:
            raise VerificationError(f"{source_id}: source kind is required")
        if not isinstance(url, str):
            raise VerificationError(f"{source_id}: URL must be a string")
        validate_source_provenance(source_id, kind, url)
        existing_sources[source_id] = dict(source)

    if fetcher is None:
        fetcher = live_fetch

    roster_result = fetcher(HELLO_INTERVIEW_ROSTER_URL)
    ensure_safe_fetch_result(HELLO_INTERVIEW_ROSTER_URL, roster_result)
    roster_document = parse_html(roster_result.text())
    live_roster = discover_hello_interview_roster(roster_document)
    pinned_urls = {source["url"] for source in existing_sources.values()
                   if source.get("kind") == "hello_interview_breakdown"}
    live_roster = [entry for entry in live_roster if entry["url"] in pinned_urls]
    if len(live_roster) != expected_count or len(pinned_urls) != expected_count:
        raise VerificationError("refusing refresh: a pinned breakdown is missing")

    non_breakdowns = [
        source
        for source in existing_sources.values()
        if source.get("kind") != "hello_interview_breakdown"
    ]
    breakdowns: list[dict[str, Any]] = []
    roster_snapshot: list[dict[str, str]] = []
    for item in live_roster:
        slug = _slug_from_breakdown_url(item["url"])
        source_id = f"hi.breakdown.{slug}"
        source = existing_sources.get(
            source_id,
            {
                "id": source_id,
                "kind": "hello_interview_breakdown",
                "title_mode": "h1",
                "title": item["title"],
                "url": item["url"],
                "headings": [],
                "structure_sha256": "0" * 64,
            },
        )
        source["kind"] = "hello_interview_breakdown"
        source["title_mode"] = "h1"
        source["title"] = item["title"]
        source["url"] = item["url"]
        breakdowns.append(source)
        roster_snapshot.append(
            {"source_id": source_id, "title": item["title"], "url": item["url"]}
        )

    all_sources = breakdowns + non_breakdowns
    refreshed_sources: list[dict[str, Any]] = []
    errors: list[str] = []
    lock = threading.Lock()
    worker_count = max(1, min(int(max_workers), len(all_sources)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(_refresh_one_source, source, fetcher): source
            for source in all_sources
        }
        for future in as_completed(futures):
            source = futures[future]
            try:
                refreshed = future.result()
                with lock:
                    refreshed_sources.append(refreshed)
            except Exception as exc:
                errors.append(f"{source['id']}: {exc}")
    if errors:
        raise VerificationError(
            "manifest refresh failed:\n- " + "\n- ".join(sorted(errors))
        )
    refreshed_sources.sort(key=lambda source: str(source["id"]))

    algorithm_blocks, algorithm_digest = load_json_snapshot(algorithm_blocks_path)
    occurrences = extract_algorithm_problems(algorithm_blocks)
    leetcode_result = fetcher(LEETCODE_CATALOG_URL)
    ensure_safe_fetch_result(LEETCODE_CATALOG_URL, leetcode_result)
    official = parse_leetcode_catalog(
        _load_json_bytes(leetcode_result, "LeetCode catalog")
    )
    refreshed_problems: dict[str, dict[str, str]] = {}
    for problem in occurrences:
        live = official.get(problem["slug"])
        if live is None:
            raise VerificationError(
                f"LeetCode slug {problem['slug']!r} is absent from official catalog"
            )
        if problem["title"] != live["title"] or problem["url"] != live["url"]:
            raise VerificationError(
                f"algorithm metadata for {problem['slug']!r} does not exactly match "
                "the official LeetCode catalog"
            )
        refreshed_problems[problem["slug"]] = live

    manifest["generated_at"] = datetime.now(timezone.utc).isoformat()
    manifest["roster"] = {
        "url": HELLO_INTERVIEW_ROSTER_URL,
        "expected_count": 30,
        "entries": roster_snapshot,
    }
    manifest["sources"] = refreshed_sources
    manifest["leetcode"] = {
        "catalog_url": LEETCODE_CATALOG_URL,
        "algorithm_blocks": _display_path(algorithm_blocks_path),
        "problems": [
            refreshed_problems[slug] for slug in sorted(refreshed_problems)
        ],
    }
    validate_manifest_shape(manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    return VerificationReport(
        source_count=len(refreshed_sources),
        breakdown_count=len(live_roster),
        leetcode_problem_count=len(refreshed_problems),
        source_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        algorithm_blocks_sha256=algorithm_digest,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Live-verify exact source titles, headings, and curriculum links."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--algorithm-blocks", type=Path, default=DEFAULT_ALGORITHM_BLOCKS
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Explicitly rewrite the reviewed snapshot from live sources.",
    )
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.refresh:
            report = refresh_manifest(
                args.manifest,
                args.algorithm_blocks,
                max_workers=args.workers,
            )
        else:
            report = verify_manifest(
                args.manifest,
                args.algorithm_blocks,
                max_workers=args.workers,
            )
    except VerificationError as exc:
        print(f"source verification failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report.as_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
