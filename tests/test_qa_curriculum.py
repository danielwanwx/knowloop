from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import qa_curriculum as qa  # noqa: E402
from curriculum_model import ROOT, load_model  # noqa: E402


def write_page(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


class PageReferenceQaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = load_model(ROOT)

    def validate_single_page(self, body: str) -> list[str]:
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            page = root / "docs" / "index.html"
            write_page(page, body)
            pages = [page] * (3 + 12 + 12 * 11)
            with (
                mock.patch.object(qa, "ROOT", root),
                mock.patch.object(qa, "DOCS", root / "docs"),
                mock.patch.object(qa, "generated_html_paths", return_value=pages),
                mock.patch.object(qa, "publication_config", return_value={"mode": "full-course"}),
            ):
                errors, _ = qa.validate_pages(self.model)
            return errors

    def test_missing_same_page_fragment_is_rejected(self) -> None:
        errors = self.validate_single_page(
            """
            <html><head><meta name="viewport" content="width=device-width"></head>
            <body><h1>Test</h1><a href="#missing">Jump</a></body></html>
            """
        )
        self.assertTrue(
            any("missing same-page fragment 'missing'" in error for error in errors)
        )

    def test_existing_same_page_fragment_is_accepted(self) -> None:
        errors = self.validate_single_page(
            """
            <html><head><meta name="viewport" content="width=device-width"></head>
            <body><h1>Test</h1><a href="#present">Jump</a>
            <section id="present"></section></body></html>
            """
        )
        self.assertFalse(
            any("missing same-page fragment" in error for error in errors)
        )

    def test_missing_stylesheet_and_script_assets_are_rejected(self) -> None:
        errors = self.validate_single_page(
            """
            <html><head><meta name="viewport" content="width=device-width">
            <link rel="stylesheet" href="assets/missing.css"></head>
            <body><h1>Test</h1><script src="assets/missing.js"></script></body></html>
            """
        )
        self.assertTrue(
            any("missing local stylesheet asset assets/missing.css" in error for error in errors)
        )
        self.assertTrue(
            any("missing local script asset assets/missing.js" in error for error in errors)
        )


class GeneratedFileIndexQaTests(unittest.TestCase):
    def test_canonical_generated_file_index_is_accepted(self) -> None:
        payload = {
            "schema_version": 1,
            "files": sorted(qa.expected_generated_files()),
        }
        self.assertEqual(qa.validate_generated_file_index(payload), [])

    def test_duplicate_entry_is_rejected_before_set_comparison(self) -> None:
        files = sorted(qa.expected_generated_files())
        payload = {"schema_version": 1, "files": [*files, files[0]]}
        errors = qa.validate_generated_file_index(payload)
        self.assertTrue(any("duplicate entries" in error for error in errors))
        self.assertFalse(any("drifted" in error for error in errors))

    def test_non_string_entry_is_rejected_before_set_comparison(self) -> None:
        payload = {
            "schema_version": 1,
            "files": [*sorted(qa.expected_generated_files()), {"bad": "entry"}],
        }
        errors = qa.validate_generated_file_index(payload)
        self.assertTrue(any("non-string entries" in error for error in errors))
        self.assertFalse(any("drifted" in error for error in errors))


if __name__ == "__main__":
    unittest.main()

class PluginCacheQaTests(unittest.TestCase):
    def test_runtime_bytecode_is_ignored_but_missing_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canonical = root / 'system-design-study-coach'
            packaged = root / 'plugins/crack-system-interview-skill/skills/system-design-study-coach'
            for tree in (canonical, packaged):
                write_page(tree / 'SKILL.md', 'same skill')
            write_page(canonical / '__pycache__/module.cpython-311.pyc', 'runtime cache')
            with mock.patch.object(qa, 'ROOT', root):
                self.assertEqual(qa.validate_plugin_sync()[0], [])
                (packaged / 'SKILL.md').unlink()
                self.assertIn('plugin system-design-study-coach file set is out of sync', qa.validate_plugin_sync()[0])
