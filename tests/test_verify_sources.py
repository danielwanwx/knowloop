from __future__ import annotations

import copy
import contextlib
import hashlib
import html
import io
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from scripts import verify_sources as vs


def _result(url: str, body: str, *, final_url: str | None = None) -> vs.FetchResult:
    return vs.FetchResult(
        requested_url=url,
        final_url=final_url or url,
        status=200,
        body=body.encode("utf-8"),
        headers={"content-type": "text/html; charset=utf-8"},
    )


def _source(title: str, url: str, index: int) -> dict:
    headings = [
        {"text": title, "id": None, "level": 1},
        {
            "text": "Potential Deep Dives",
            "id": "potential-deep-dives",
            "level": 2,
        },
    ]
    return {
        "id": f"hi.breakdown.problem-{index}",
        "kind": "hello_interview_breakdown",
        "title_mode": "h1",
        "title": title,
        "url": url,
        "headings": headings,
        "structure_sha256": vs.heading_structure_digest(title, headings),
    }


def _algorithm_blocks() -> dict:
    return {
        "schema_version": "1.0",
        "provider": "LeetCode",
        "url_template": "https://leetcode.com/problems/{slug}/",
        "blocks": [
            {
                "id": "arrays",
                "tag": "Arrays & Hashing",
                "problems": [
                    {"slug": "alpha", "title": "Alpha"},
                    {"slug": "beta", "title": "Beta"},
                    {"slug": "gamma", "title": "Gamma"},
                ],
                "day_mode": ["new"],
                "days": [[0, 1, 2]],
            }
        ],
    }


def _catalog() -> dict:
    return {
        "stat_status_pairs": [
            {
                "stat": {
                    "question__title_slug": slug,
                    "question__title": title,
                    "frontend_question_id": number,
                }
            }
            for number, (slug, title) in enumerate(
                [("alpha", "Alpha"), ("beta", "Beta"), ("gamma", "Gamma")],
                start=1,
            )
        ]
    }


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.manifest_path = root / "source-manifest.json"
        self.algorithm_path = root / "algorithm-blocks.json"
        self.responses: dict[str, vs.FetchResult] = {}

        roster_entries = []
        sources = []
        roster_links = []
        for index in range(30):
            title = f"Problem {index}"
            url = f"{vs.HELLO_INTERVIEW_BREAKDOWN_PREFIX}problem-{index}"
            source = _source(title, url, index)
            sources.append(source)
            roster_entries.append(
                {"source_id": source["id"], "title": title, "url": url}
            )
            roster_links.append(
                f'<a href="{html.escape(url)}">{html.escape(title)}</a>'
            )
            source_html = (
                f"<h1>{html.escape(title)}</h1>"
                '<h2 id="potential-deep-dives">Potential Deep Dives</h2>'
            )
            self.responses[url] = _result(url, source_html)

        extras = [
            (
                "openai.building-agents",
                "official_ai_extension",
                "Building agents",
                vs.OPENAI_BUILDING_AGENTS_URL,
                [
                    {"text": "Building agents", "id": None, "level": 1},
                    {
                        "text": "Augmenting your agents with tools",
                        "id": "augmenting-your-agents-with-tools",
                        "level": 3,
                    },
                ],
            ),
            (
                "anthropic.building-effective-agents",
                "official_ai_extension",
                "Building effective agents",
                vs.ANTHROPIC_BUILDING_EFFECTIVE_AGENTS_URL,
                [
                    {"text": "Building effective agents", "id": None, "level": 1},
                    {
                        "text": "When (and when not) to use agents",
                        "id": "when-and-when-not-to-use-agents",
                        "level": 2,
                    },
                ],
            ),
            (
                "elevenlabs.tts.optional",
                "optional_generation_tool",
                "Text to Speech",
                vs.ELEVENLABS_TTS_GUIDE_URL,
                [
                    {"text": "Text to Speech", "id": None, "level": 1},
                    {"text": "Text input", "id": "text-input", "level": 3},
                ],
            ),
        ]
        for source_id, kind, title, url, headings in extras:
            sources.append(
                {
                    "id": source_id,
                    "kind": kind,
                    "title_mode": "h1",
                    "title": title,
                    "url": url,
                    "headings": headings,
                    "structure_sha256": vs.heading_structure_digest(title, headings),
                }
            )
            rendered = "".join(
                f"<h{heading['level']}"
                + (
                    f' id="{heading["id"]}"'
                    if heading["id"] is not None
                    else ""
                )
                + f">{html.escape(heading['text'])}</h{heading['level']}>"
                for heading in headings
            )
            self.responses[url] = _result(url, rendered)

        self.roster_html = "".join(roster_links)
        self.responses[vs.HELLO_INTERVIEW_ROSTER_URL] = _result(
            vs.HELLO_INTERVIEW_ROSTER_URL, self.roster_html
        )
        self.responses[vs.LEETCODE_CATALOG_URL] = vs.FetchResult(
            requested_url=vs.LEETCODE_CATALOG_URL,
            final_url=vs.LEETCODE_CATALOG_URL,
            status=200,
            body=json.dumps(_catalog()).encode("utf-8"),
            headers={"content-type": "application/json; charset=utf-8"},
        )
        problems = [
            {
                "slug": item["slug"],
                "title": item["title"],
                "url": f"{vs.LEETCODE_PROBLEM_PREFIX}{item['slug']}/",
                "frontend_id": str(index),
            }
            for index, item in enumerate(
                _algorithm_blocks()["blocks"][0]["problems"], start=1
            )
        ]
        self.manifest = {
            "schema_version": 1,
            "generated_at": "test",
            "roster": {
                "url": vs.HELLO_INTERVIEW_ROSTER_URL,
                "expected_count": 30,
                "entries": roster_entries,
            },
            "sources": sources,
            "leetcode": {
                "catalog_url": vs.LEETCODE_CATALOG_URL,
                "algorithm_blocks": "algorithm-blocks.json",
                "problems": problems,
            },
        }
        self.write()

    def write(self) -> None:
        self.manifest_path.write_text(
            json.dumps(self.manifest, ensure_ascii=False), encoding="utf-8"
        )
        self.algorithm_path.write_text(
            json.dumps(_algorithm_blocks(), ensure_ascii=False), encoding="utf-8"
        )

    def fetch(self, url: str) -> vs.FetchResult:
        return self.responses[url]


class SourceManifestVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.fixture = Fixture(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def verify(self) -> vs.VerificationReport:
        return vs.verify_manifest(
            self.fixture.manifest_path,
            self.fixture.algorithm_path,
            fetcher=self.fixture.fetch,
            max_workers=4,
        )

    def test_complete_manifest_passes(self) -> None:
        report = self.verify()
        self.assertEqual(report.breakdown_count, 30)
        self.assertEqual(report.source_count, 33)
        self.assertEqual(report.leetcode_problem_count, 3)
        self.assertEqual(
            report.source_manifest_sha256,
            hashlib.sha256(self.fixture.manifest_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            report.algorithm_blocks_sha256,
            hashlib.sha256(self.fixture.algorithm_path.read_bytes()).hexdigest(),
        )

    def test_source_kind_is_bound_to_official_origin_and_path(self) -> None:
        with self.assertRaisesRegex(vs.VerificationError, "must use"):
            vs.validate_source_provenance(
                "hi.core.caching",
                "hello_interview_core_concept",
                "https://example.com/learn/system-design/core-concepts/caching",
            )
        with self.assertRaisesRegex(vs.VerificationError, "map exactly"):
            vs.validate_source_provenance(
                "ddia.ch6",
                "ddia_chinese_chapter",
                "https://ddia.vonng.com/ch7/",
            )

    def test_unreviewed_ai_and_source_kinds_are_rejected(self) -> None:
        with self.assertRaisesRegex(vs.VerificationError, "limited"):
            vs.validate_source_provenance(
                "vendor.agent-guide",
                "official_ai_extension",
                "https://vendor.example/agents",
            )
        with self.assertRaisesRegex(vs.VerificationError, "unsupported source kind"):
            vs.validate_source_provenance(
                "misc.guide",
                "miscellaneous",
                "https://example.com/guide",
            )

    def test_refresh_rejects_tampered_non_breakdown_before_any_fetch(self) -> None:
        source = next(
            source
            for source in self.fixture.manifest["sources"]
            if source["id"] == "openai.building-agents"
        )
        source["url"] = "https://example.com/tampered-agent-guide"
        self.fixture.write()
        fetched_urls: list[str] = []

        def fetch(url: str) -> vs.FetchResult:
            fetched_urls.append(url)
            return self.fixture.fetch(url)

        with self.assertRaisesRegex(vs.VerificationError, "AI extensions are limited"):
            vs.refresh_manifest(
                self.fixture.manifest_path,
                self.fixture.algorithm_path,
                fetcher=fetch,
            )
        self.assertEqual(fetched_urls, [])

    def test_roster_gate_rejects_29_live_breakdowns(self) -> None:
        links = vs.parse_html(self.fixture.roster_html).anchors[:-1]
        body = "".join(
            f'<a href="{html.escape(link.href)}">{html.escape(link.text)}</a>'
            for link in links
        )
        self.fixture.responses[vs.HELLO_INTERVIEW_ROSTER_URL] = _result(
            vs.HELLO_INTERVIEW_ROSTER_URL, body
        )
        with self.assertRaisesRegex(vs.VerificationError, "expected 30, found 29"):
            self.verify()

    def test_new_upstream_breakdowns_do_not_invalidate_pinned_curriculum(self) -> None:
        extra = '<a href="/learn/system-design/problem-breakdowns/new-example">New Example</a>'
        self.fixture.responses[vs.HELLO_INTERVIEW_ROSTER_URL] = _result(
            vs.HELLO_INTERVIEW_ROSTER_URL, self.fixture.roster_html + extra)
        self.verify()

    def test_extra_upstream_item_does_not_hide_missing_pinned_item(self) -> None:
        links = vs.parse_html(self.fixture.roster_html).anchors[:-1]
        body = ''.join(f'<a href="{html.escape(a.href)}">{html.escape(a.text)}</a>' for a in links)
        body += '<a href="/learn/system-design/problem-breakdowns/new-example">New Example</a>'
        self.fixture.responses[vs.HELLO_INTERVIEW_ROSTER_URL] = _result(vs.HELLO_INTERVIEW_ROSTER_URL, body)
        with self.assertRaisesRegex(vs.VerificationError, 'roster drift'):
            self.verify()

    def test_network_failure_is_fatal(self) -> None:
        broken_url = self.fixture.manifest["sources"][0]["url"]

        def fetch(url: str) -> vs.FetchResult:
            if url == broken_url:
                raise vs.VerificationError("simulated timeout")
            return self.fixture.fetch(url)

        with self.assertRaisesRegex(vs.VerificationError, "simulated timeout"):
            vs.verify_manifest(
                self.fixture.manifest_path,
                self.fixture.algorithm_path,
                fetcher=fetch,
            )

    def test_cross_origin_redirect_is_fatal(self) -> None:
        source = self.fixture.manifest["sources"][0]
        self.fixture.responses[source["url"]] = _result(
            source["url"],
            "<h1>Problem 0</h1>",
            final_url="https://example.invalid/problem-0",
        )
        with self.assertRaisesRegex(vs.VerificationError, "cross-origin redirect"):
            self.verify()

    def test_same_origin_path_redirect_is_canonical_drift(self) -> None:
        source = self.fixture.manifest["sources"][0]
        self.fixture.responses[source["url"]] = _result(
            source["url"],
            "<h1>Problem 0</h1>",
            final_url=f"{source['url']}-renamed",
        )
        with self.assertRaisesRegex(vs.VerificationError, "canonical URL drifted"):
            self.verify()

    def test_display_title_drift_is_fatal(self) -> None:
        source = self.fixture.manifest["sources"][0]
        self.fixture.responses[source["url"]] = _result(
            source["url"],
            "<h1>Renamed Problem</h1>"
            '<h2 id="potential-deep-dives">Potential Deep Dives</h2>',
        )
        with self.assertRaisesRegex(vs.VerificationError, "display title drift"):
            self.verify()

    def test_heading_anchor_drift_is_fatal(self) -> None:
        source = self.fixture.manifest["sources"][0]
        self.fixture.responses[source["url"]] = _result(
            source["url"],
            "<h1>Problem 0</h1>"
            '<h2 id="deep-dives">Potential Deep Dives</h2>',
        )
        with self.assertRaisesRegex(vs.VerificationError, "heading drift"):
            self.verify()

    def test_unanchored_page_chrome_variation_is_tolerated(self) -> None:
        source = self.fixture.manifest["sources"][0]
        self.fixture.responses[source["url"]] = _result(
            source["url"],
            "<h1>Problem 0</h1>"
            "<h6>Watch Video Walkthrough</h6>"
            '<h2 id="potential-deep-dives">Potential Deep Dives</h2>'
            "<h6>Dynamic Footer Label</h6>",
        )
        report = self.verify()
        self.assertEqual(report.breakdown_count, 30)

    def test_first_h1_is_canonical_and_auxiliary_h1_remains_in_snapshot(self) -> None:
        document = vs.parse_html(
            "<h1>FB News Feed</h1><h1 id='changelog'>Changelog</h1>"
        )
        self.assertEqual(vs.display_title(document, "h1"), "FB News Feed")
        self.assertEqual(
            [heading.text for heading in document.headings],
            ["FB News Feed", "Changelog"],
        )

    def test_non_visible_script_and_svg_text_is_not_heading_text(self) -> None:
        document = vs.parse_html(
            "<h1>Exact Title"
            "<script>window.noise = 'not visible'</script>"
            "<svg><title>decorative icon</title></svg>"
            "</h1>"
        )
        self.assertEqual(document.h1_titles, ("Exact Title",))

    def test_self_linked_descendant_span_is_the_heading_anchor(self) -> None:
        document = vs.parse_html(
            "<h2>描述性能"
            '<span id="sec_introduction_percentiles"></span>'
            '<a href="#sec_introduction_percentiles"></a>'
            "</h2>"
        )
        self.assertEqual(
            document.headings[0],
            vs.ParsedHeading(
                text="描述性能", id="sec_introduction_percentiles", level=2
            ),
        )

    def test_unlinked_descendant_control_id_is_not_a_heading_anchor(self) -> None:
        document = vs.parse_html(
            '<h3>Accordion label<button id="panel-header">Open</button></h3>'
        )
        self.assertIsNone(document.headings[0].id)

    def test_fern_step_container_id_is_the_nested_heading_anchor(self) -> None:
        document = vs.parse_html(
            '<div class="fern-step" id="text-input">'
            '<a href="#text-input"></a><h3>Text input</h3>'
            "</div><h3>Outside</h3>"
        )
        self.assertEqual(document.headings[0].id, "text-input")
        self.assertIsNone(document.headings[1].id)

    def test_abbreviated_source_or_heading_title_is_rejected(self) -> None:
        source = self.fixture.manifest["sources"][0]
        manifest = {"sources": [source]}
        with self.assertRaisesRegex(vs.VerificationError, "source title must be exact"):
            vs.resolve_reference(
                manifest,
                source_id=source["id"],
                source_title="Problem",
                heading_text="Potential Deep Dives",
            )
        with self.assertRaisesRegex(vs.VerificationError, "no exact heading match"):
            vs.resolve_reference(
                manifest,
                source_id=source["id"],
                source_title=source["title"],
                heading_text="Deep Dives",
            )

    def test_duplicate_heading_text_requires_exact_id(self) -> None:
        source = {
            "id": "senior-guide",
            "title": "Guide",
            "url": "https://example.com/guide",
            "headings": [
                {"text": "Senior", "id": "senior", "level": 4},
                {"text": "Senior", "id": "senior-1", "level": 4},
            ],
        }
        with self.assertRaisesRegex(vs.VerificationError, "duplicate heading match"):
            vs.resolve_heading(source, text="Senior")
        match = vs.resolve_heading(
            source, text="Senior", heading_id="senior-1", level=4
        )
        self.assertEqual(match["id"], "senior-1")

    def test_heading_without_id_cannot_be_linked(self) -> None:
        source = {
            "id": "no-anchor",
            "headings": [{"text": "Exact", "id": None, "level": 2}],
        }
        with self.assertRaisesRegex(vs.VerificationError, "has no HTML id"):
            vs.resolve_heading(source, text="Exact")

    def test_algorithm_schema_derives_canonical_urls(self) -> None:
        problems = vs.extract_algorithm_problems(_algorithm_blocks())
        self.assertEqual(
            problems[0]["url"], "https://leetcode.com/problems/alpha/"
        )

    def test_algorithm_day_must_contain_exactly_three_valid_indices(self) -> None:
        data = _algorithm_blocks()
        data["blocks"][0]["days"] = [[0, 1]]
        with self.assertRaisesRegex(vs.VerificationError, "three valid indices"):
            vs.extract_algorithm_problems(data)

    def test_official_leetcode_title_drift_is_fatal(self) -> None:
        data = _algorithm_blocks()
        data["blocks"][0]["problems"][0]["title"] = "Abbreviated"
        with self.assertRaisesRegex(vs.VerificationError, "title drift"):
            vs.verify_algorithm_blocks(
                self.fixture.manifest, data, _catalog()
            )

    def test_manifest_leetcode_frontend_id_is_required(self) -> None:
        manifest = copy.deepcopy(self.fixture.manifest)
        del manifest["leetcode"]["problems"][0]["frontend_id"]
        with self.assertRaisesRegex(vs.VerificationError, "frontend_id"):
            vs.verify_algorithm_blocks(manifest, _algorithm_blocks(), _catalog())

    def test_cli_returns_nonzero_on_verification_failure(self) -> None:
        stderr = io.StringIO()
        with mock.patch.object(
            vs,
            "verify_manifest",
            side_effect=vs.VerificationError("blocked by live gate"),
        ), contextlib.redirect_stderr(stderr):
            return_code = vs.main([])
        self.assertEqual(return_code, 1)
        self.assertIn("blocked by live gate", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
