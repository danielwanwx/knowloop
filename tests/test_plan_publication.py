"""Focused checks for the catalog-only public boundary."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_coach_pages as pages  # noqa: E402
import build_curriculum as build  # noqa: E402
import qa_curriculum as qa  # noqa: E402


spec = importlib.util.spec_from_file_location("plan_lookup", ROOT / "system-design-study-coach" / "scripts" / "plan_lookup.py")
lookup = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(lookup)


class CatalogPublicationTests(unittest.TestCase):
    def test_publication_contract_is_catalog_only(self) -> None:
        self.assertEqual(build.publication_config()["mode"], "catalog-only")
        self.assertEqual(qa.validate_public_files(), [])

    def test_lookup_uses_positions_and_durations(self) -> None:
        item = lookup.select_day(lookup.load_plan(ROOT / "curriculum"), type("Args", (), {"week": 1, "day": 1, "local_start": None})())
        self.assertEqual((item["week"], item["day"]), (1, 1))
        self.assertTrue(all(block["minutes"] > 0 for block in item["time_blocks"]))
        self.assertNotIn("date", item)
        self.assertNotIn("page", item)

    def test_local_start_maps_without_becoming_catalog_data(self) -> None:
        self.assertEqual(lookup.position_from_start("2026-01-01", date(2026, 1, 8)), (2, 1))

    def test_dashboard_demo_is_explicitly_synthetic(self) -> None:
        output = pages.outputs()["dashboard-demo.html"]
        self.assertIn('"course_id": "demo-coding"', output)
        self.assertIn('"task_id": "demo-sliding-window"', output)
        self.assertIn("Synthetic", output)

    def test_only_catalog_pages_are_present(self) -> None:
        self.assertEqual(
            {str(path.relative_to(ROOT)) for path in (ROOT / "docs").rglob("*") if path.is_file()},
            build.PUBLIC_FILES,
        )


if __name__ == "__main__":
    unittest.main()
