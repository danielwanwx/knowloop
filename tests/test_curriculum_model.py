from __future__ import annotations

import copy
import unittest

from scripts.curriculum_model import ROOT, load_model, validate_model


@unittest.skip("Retired full-course model invariants")
class CurriculumModelInvariantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = load_model(ROOT)


class CatalogCurriculumModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = load_model(ROOT)

    def test_position_based_curriculum_passes(self) -> None:
        self.assertEqual(validate_model(self.model), [])

    def test_missing_duration_is_rejected(self) -> None:
        model = copy.deepcopy(self.model)
        model.weeks[1]["days"][0]["time_blocks"][0]["minutes"] = 0
        self.assertTrue(any("duration" in error for error in validate_model(model)))

    def test_wrong_day_position_is_rejected(self) -> None:
        model = copy.deepcopy(self.model)
        model.weeks[1]["days"][0]["day"] = 2
        self.assertTrue(any("invalid position" in error for error in validate_model(model)))

    def test_retired_calendar_field_is_rejected(self) -> None:
        model = copy.deepcopy(self.model)
        model.weeks[1]["days"][0]["date"] = "not-published"
        self.assertTrue(any("retired calendar" in error for error in validate_model(model)))

    def errors_after(self, mutate) -> list[str]:
        model = copy.deepcopy(self.model)
        mutate(model)
        return validate_model(model)

    def test_canonical_curriculum_passes(self) -> None:
        self.assertEqual(validate_model(self.model), [])

    def test_algorithm_block_reuse_is_rejected(self) -> None:
        errors = self.errors_after(
            lambda model: model.route["weeks"][1].update(
                algorithm_block=model.route["weeks"][0]["algorithm_block"]
            )
        )
        self.assertTrue(
            any("every algorithm tag block exactly once" in error for error in errors)
        )

    def test_cross_week_project_day_is_rejected(self) -> None:
        foreign_slug = self.model.route["weeks"][1]["projects"][0]

        def mutate(model) -> None:
            model.route["weeks"][0]["days"][0]["project"] = foreign_slug

        errors = self.errors_after(mutate)
        self.assertTrue(
            any("is not declared in this week" in error for error in errors)
        )

    def test_reviewed_week_project_grouping_cannot_drift(self) -> None:
        def mutate(model) -> None:
            model.route["weeks"][0]["projects"].reverse()
            model.weeks[1]["projects"].reverse()

        errors = self.errors_after(mutate)
        self.assertTrue(
            any("project route drifted" in error for error in errors)
        )

    def test_read_and_deep_days_must_be_adjacent(self) -> None:
        def mutate(model) -> None:
            days = model.route["weeks"][0]["days"]
            days[1], days[2] = days[2], days[1]

        errors = self.errors_after(mutate)
        self.assertTrue(
            any("must immediately follow read day" in error for error in errors)
        )

    def test_complete_read_cannot_skip_an_intermediate_heading(self) -> None:
        def mutate(model) -> None:
            headings = model.projects["bitly"]["read"]["headings"]
            del headings[2]

        errors = self.errors_after(mutate)
        self.assertTrue(
            any(
                "must include every linkable source heading" in error
                for error in errors
            )
        )

    def test_mock_cannot_be_replaced_by_integration(self) -> None:
        def mutate(model) -> None:
            model.route["weeks"][1]["days"][-1]["kind"] = "integration"

        errors = self.errors_after(mutate)
        self.assertTrue(
            any("expected 1 mock day" in error for error in errors)
        )

    def test_ai_extensions_cannot_leak_to_another_project(self) -> None:
        def mutate(model) -> None:
            model.weeks[1]["projects"][0]["ai_extensions"] = [
                {
                    "source": "openai.building-agents",
                    "heading": "Augmenting your agents with tools",
                }
            ]

        errors = self.errors_after(mutate)
        self.assertTrue(
            any("allowed only for ChatGPT" in error for error in errors)
        )

    def test_week_one_required_mechanism_packet_cannot_shrink(self) -> None:
        def mutate(model) -> None:
            concepts = model.projects["bitly"]["concepts"]
            concepts[:] = [
                ref
                for ref in concepts
                if ref["source"] != "hi.core.api-design"
            ]

        errors = self.errors_after(mutate)
        self.assertTrue(
            any("required Bitly/Dropbox source coverage" in error for error in errors)
        )


if __name__ == "__main__":
    unittest.main()
