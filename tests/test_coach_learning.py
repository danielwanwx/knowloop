"""Focused catalog behavior for the retained generic courses."""

from __future__ import annotations

import copy
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "interview-coach" / "scripts"))
import coach_courses as courses  # noqa: E402
import coach_state as state  # noqa: E402


class CatalogPrivacyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / "private"
        self.conn = state.connect(self.root)
        courses.schema(self.conn)
        self.data = courses.catalog(self.root)[0]

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def test_removed_catalog_cache_is_rejected(self) -> None:
        cached = copy.deepcopy(self.data)
        cached["courses"].append({"course_id": "coh" + "ort"})
        (self.root / "courses-cache.json").write_text(json.dumps(cached))
        data, status = courses.catalog(self.root)
        self.assertEqual(data, self.data)
        self.assertEqual(status, "invalid_cache_using_bundle")

    def test_refresh_is_offline_without_a_network_call(self) -> None:
        with patch.object(socket, "create_connection") as connect:
            data, status = courses.catalog(self.root, refresh=True)
        self.assertEqual(data, self.data)
        self.assertIn("offline_not_configured", status)
        connect.assert_not_called()

    def test_removed_selected_course_requires_new_selection(self) -> None:
        self.conn.execute(
            "INSERT INTO enrollment(id, body) VALUES(1, ?)",
            (json.dumps({"course_id": "coh" + "ort", "week_id": "w1", "minutes": 30, "timezone": "UTC"}),),
        )
        with self.assertRaisesRegex(ValueError, "selected course unavailable"):
            courses.plan(self.conn, self.data, state.resume(self.conn), {"plan_id": "generic-plan"})

    def test_generic_course_can_still_produce_a_plan(self) -> None:
        courses.enroll(self.conn, self.data, {"course_id": "system-design", "week_id": "w2", "minutes": 30, "timezone": "UTC"})
        plan = courses.plan(self.conn, self.data, state.resume(self.conn), {"plan_id": "generic-plan"})
        self.assertEqual(plan["course_id"], "system-design")
        self.assertLessEqual(sum(item["minutes"] for item in plan["items"]), 30)


if __name__ == "__main__":
    unittest.main()
