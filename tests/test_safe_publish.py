from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import build_curriculum as build  # noqa: E402
import sync_plugin_content as sync  # noqa: E402


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


class SafePublishTests(unittest.TestCase):
    def test_live_verifier_failure_surfaces_source_diagnostic(self) -> None:
        failure = subprocess.CalledProcessError(
            1,
            ["verify_sources.py"],
            stderr="hi.breakdown.bitly: heading drift at High-Level Design",
        )
        with mock.patch.object(build.subprocess, "run", side_effect=failure):
            with self.assertRaisesRegex(
                build.CurriculumError,
                "hi.breakdown.bitly: heading drift",
            ):
                build.verify_live(2)

    def test_publish_deletes_only_known_generated_files(self) -> None:
        with tempfile.TemporaryDirectory() as target_name, tempfile.TemporaryDirectory() as stage_name:
            target = Path(target_name)
            stage = Path(stage_name)
            write(target / "docs/week13/day-1.html", "stale")
            write(target / "docs/week13/user-notes.html", "keep")
            write(stage / "docs/index.html", "new")
            write(
                stage / build.GENERATED_INDEX,
                json.dumps(
                    {
                        "schema_version": 1,
                        "files": [
                            str(build.GENERATED_INDEX),
                            "docs/index.html",
                        ],
                    }
                ),
            )
            generated = {build.GENERATED_INDEX, Path("docs/index.html")}

            build._publish_staged(stage, target, generated)

            self.assertEqual(
                (target / "docs/week13/user-notes.html").read_text(), "keep"
            )
            self.assertFalse((target / "docs/week13/day-1.html").exists())
            self.assertEqual((target / "docs/index.html").read_text(), "new")

    def test_publish_rolls_back_if_a_copy_fails(self) -> None:
        with tempfile.TemporaryDirectory() as target_name, tempfile.TemporaryDirectory() as stage_name:
            target = Path(target_name)
            stage = Path(stage_name)
            write(target / "docs/index.html", "old index")
            write(
                target / "docs/system-design-project-route.html",
                "old route",
            )
            generated = {
                build.GENERATED_INDEX,
                Path("docs/index.html"),
                Path("docs/system-design-project-route.html"),
            }
            for relative in generated:
                write(stage / relative, f"new {relative}")

            original_copy = build._copy_atomically
            calls = 0

            def fail_once(source: Path, destination: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise OSError("simulated publish failure")
                original_copy(source, destination)

            with mock.patch.object(build, "_copy_atomically", side_effect=fail_once):
                with self.assertRaisesRegex(OSError, "simulated publish failure"):
                    build._publish_staged(stage, target, generated)

            self.assertEqual(
                (target / "docs/index.html").read_text(), "old index"
            )
            self.assertEqual(
                (target / "docs/system-design-project-route.html").read_text(),
                "old route",
            )
            self.assertFalse((target / build.GENERATED_INDEX).exists())

    def test_plugin_sync_preflight_does_not_delete_existing_tree(self) -> None:
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name) / "canonical"
            plugin = Path(root_name) / "plugin"
            write(plugin / "skills/card/old.txt", "preserve")

            with self.assertRaisesRegex(RuntimeError, "sync source is missing"):
                sync.sync_all(root=root, plugin=plugin)

            self.assertEqual(
                (plugin / "skills/card/old.txt").read_text(), "preserve"
            )

    def test_plugin_sync_rolls_back_every_tree_if_replace_fails_mid_publish(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name) / "canonical"
            plugin = Path(root_name) / "plugin"
            targets = sync.sync_targets(root=root, plugin=plugin)
            for index, (source, destination) in enumerate(targets):
                write(source / "new.txt", f"new-{index}")
                write(destination / "old.txt", f"old-{index}")

            real_replace = sync.os.replace
            staged_publish_attempts = 0
            injected_failures = 0

            def fail_once_mid_publish(source: Path, destination: Path) -> None:
                nonlocal staged_publish_attempts, injected_failures
                source_path = Path(source)
                if source_path.parent.name == "stage":
                    staged_publish_attempts += 1
                    if staged_publish_attempts == 4:
                        injected_failures += 1
                        raise OSError("simulated plugin swap failure")
                real_replace(source, destination)

            with mock.patch.object(
                sync.os,
                "replace",
                side_effect=fail_once_mid_publish,
            ):
                with self.assertRaisesRegex(
                    OSError,
                    "simulated plugin swap failure",
                ):
                    sync.sync_all(root=root, plugin=plugin)

            self.assertEqual(injected_failures, 1)
            self.assertEqual(staged_publish_attempts, 4)
            for index, (_, destination) in enumerate(targets):
                self.assertEqual(
                    (destination / "old.txt").read_text(encoding="utf-8"),
                    f"old-{index}",
                )
                self.assertFalse((destination / "new.txt").exists())


if __name__ == "__main__":
    unittest.main()
