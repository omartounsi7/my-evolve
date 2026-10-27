"""Checks the database's records and its weighted choice of parents."""

import math
import random
import unittest
from collections import Counter
from typing import Any

from my_evolve.database import Database, WeightedSelector, stable_sigmoid
from my_evolve.problem import Problem
from my_evolve.program import LLMUsage, Origin, Program, Result, Status

USAGE = LLMUsage("m", 1, 1, 1.0)


def make_problem(lam: float = 1.0) -> Problem:
    return Problem.from_dict(
        {
            "name": "test",
            "description": "Test.",
            "entry_functions": ["run"],
            "parents": {"lambda": lam},
            "llm": {"models": [{"name": "m", "api_base": "http://localhost:1/v1"}]},
        }
    )


def ok(score: float) -> Result:
    return Result(Status.OK, score=score)


class DatabaseTestCase(unittest.TestCase):
    """A database holding the initial program (score 0.5) and its copy on island 0."""

    def setUp(self) -> None:
        self.make(make_problem())

    def make(self, problem: Problem, seed: int = 1) -> None:
        self.initial = Program.initial("x = 0\n", ok(0.5), "fp-initial", 10)
        self.database = Database(problem, self.initial, random.Random(seed))
        self.database.add(self.initial)
        (self.copy,) = self.database.seed_islands(self.initial)
        self.saved = [self.initial, self.copy]

    def child(
        self, parent: Program, result: Result, fingerprint: str | None = None, **changes: Any
    ) -> Program:
        """Make a child of parent on island 0, add it with its completed count, and keep it."""
        child = Program.new_child(
            parent,
            code=f"x = {len(self.saved)}\n",
            result=result,
            island=0,
            iteration=len(self.saved),
            description=None,
            fingerprint=fingerprint if fingerprint is not None else f"fp-{len(self.saved)}",
            code_complexity=10,
            example_ids=(),
            llm=USAGE,
        )
        self.database.add(child, completed=changes.get("completed"))
        self.saved.append(child)
        return child


class TestAdding(DatabaseTestCase):
    def test_initial_program_lives_on_the_islands_through_its_copy(self) -> None:
        island = self.database.islands[0]
        self.assertEqual(island.program_ids, [self.copy.id])
        self.assertEqual(island.elites(), [self.copy])
        self.assertEqual(self.copy.origin, Origin.COPY)
        self.assertEqual(self.copy.iteration, 0)

    def test_initial_program_is_the_first_best(self) -> None:
        self.assertEqual(self.database.best(), self.initial)

    def test_fingerprints_count_programs_that_ran(self) -> None:
        for status in (Status.FAILED, Status.TIMEOUT, Status.INVALID):
            self.child(self.copy, Result.failure(status, "x"), f"fp-{status}")
        self.child(self.copy, Result.rejected("syntax error"), "fp-rejected")
        self.child(self.copy, Result.failure(Status.ERROR, "sandbox"), "fp-error")
        known = set(self.database.fingerprints)
        self.assertTrue({"fp-failed", "fp-timeout", "fp-invalid", "fp-initial"} <= known)
        self.assertNotIn("fp-rejected", known)
        self.assertNotIn("fp-error", known)

    def test_a_fingerprint_keeps_the_first_program_that_had_it(self) -> None:
        self.assertEqual(self.database.fingerprints["fp-initial"], self.initial.id)

    def test_children_are_llm_children_that_are_not_errors(self) -> None:
        self.child(self.copy, ok(0.4))
        self.child(self.copy, Result.rejected("no code in the reply"))
        self.child(self.copy, Result.failure(Status.FAILED, "IndexError"))
        self.child(self.copy, Result.failure(Status.ERROR, "sandbox: Docker stopped"))
        self.assertEqual(self.database.children_count(self.copy.id), 3)
        # The copy is not a child of the initial program.
        self.assertEqual(self.database.children_count(self.initial.id), 0)

    def test_only_working_programs_join_the_population(self) -> None:
        good = self.child(self.copy, ok(0.4))
        self.child(self.copy, Result.failure(Status.INVALID, "overlap"))
        self.assertEqual(self.database.islands[0].elites(), [self.copy, good])
        self.assertEqual(len(self.database.islands[0].program_ids), 3)

    def test_best_changes_only_for_a_strictly_higher_score(self) -> None:
        self.child(self.copy, ok(0.5))
        self.assertEqual(self.database.best(), self.initial)
        better = self.child(self.copy, ok(0.7), completed=4)
        self.assertEqual(self.database.best(), better)
        self.assertEqual(self.database.best_changed_at, 4)
        self.child(self.copy, ok(0.6), completed=5)
        self.assertEqual(self.database.best_changed_at, 4)

    def test_same_program_twice_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "already added"):
            self.database.add(self.initial)

    def test_child_of_an_unknown_parent_is_refused(self) -> None:
        orphan = Program.initial("x = 9\n", ok(0.1), None, None).copy_to(0, 0, Origin.COPY)
        with self.assertRaisesRegex(ValueError, "unknown parent"):
            self.database.add(orphan)

    def test_replay_rebuilds_the_same_state(self) -> None:
        first = self.child(self.copy, ok(0.7))
        self.child(first, Result.failure(Status.TIMEOUT, "slow"))
        self.child(first, ok(0.9))
        self.child(self.copy, Result.rejected("markers changed"))
        rebuilt = Database(make_problem(), self.initial, random.Random(1))
        rebuilt.replay(self.saved)
        self.assertEqual(rebuilt.programs, self.database.programs)
        self.assertEqual(rebuilt.fingerprints, self.database.fingerprints)
        self.assertEqual(rebuilt.children, self.database.children)
        self.assertEqual(rebuilt.best_id, self.database.best_id)
        self.assertEqual(rebuilt.islands[0].program_ids, self.database.islands[0].program_ids)
        self.assertEqual(rebuilt.islands[0].elites(), self.database.islands[0].elites())


class TestWeightedSelection(DatabaseTestCase):
    def weights(self) -> list[float]:
        selector = self.database.selector
        assert isinstance(selector, WeightedSelector)
        return selector.weights(self.database.islands[0].elites(), self.database)

    def test_failed_programs_are_never_drawn(self) -> None:
        for _ in range(5):
            self.child(self.copy, Result.failure(Status.FAILED, "x"))
        island = self.database.islands[0]
        drawn = {self.database.sample_parent(island).id for _ in range(200)}
        self.assertEqual(drawn, {self.copy.id})

    def test_weights_follow_the_formula(self) -> None:
        # Scores 0.5 (the copy, which now has 2 children), 0.6, 0.9 and 1.0.
        a = self.child(self.copy, ok(0.6))
        self.child(self.copy, ok(0.9))
        self.child(a, ok(1.0))
        median = 0.75
        # Deviations 0.25, 0.15, 0.15, 0.25: their median is 0.2.
        spread = 0.2
        expected = [
            stable_sigmoid((0.5 - median) / spread) / (1 + 2),
            stable_sigmoid((0.6 - median) / spread) / (1 + 1),
            stable_sigmoid((0.9 - median) / spread),
            stable_sigmoid((1.0 - median) / spread),
        ]
        for weight, value in zip(self.weights(), expected, strict=True):
            self.assertAlmostEqual(weight, value)

    def test_standard_deviation_is_the_spread_when_the_deviation_is_zero(self) -> None:
        # Scores 0.5, 0.5, 0.5, 0.9: the median absolute deviation is 0.
        self.child(self.copy, ok(0.5))
        self.child(self.copy, ok(0.5))
        self.child(self.copy, ok(0.9))
        scores = [0.5, 0.5, 0.5, 0.9]
        mean = sum(scores) / 4
        spread = math.sqrt(sum((score - mean) ** 2 for score in scores) / 4)
        top = self.weights()[3]
        self.assertAlmostEqual(top, stable_sigmoid((0.9 - 0.5) / spread))

    def test_equal_scores_give_half_to_everyone(self) -> None:
        self.child(self.copy, ok(0.5))
        # The copy has one child: 0.5 / 2; the child none: 0.5.
        self.assertEqual(self.weights(), [0.25, 0.5])

    def test_lambda_zero_ignores_scores(self) -> None:
        self.make(make_problem(lam=0))
        self.child(self.copy, ok(0.1))
        self.child(self.copy, ok(0.9))
        self.assertEqual(self.weights()[1:], [0.5, 0.5])

    def test_large_score_differences_do_not_overflow(self) -> None:
        self.make(make_problem(lam=1e6))
        self.child(self.copy, ok(0.6))
        self.child(self.copy, ok(0.9))
        self.assertTrue(all(math.isfinite(weight) for weight in self.weights()))

    def test_draws_favour_good_programs_with_few_children(self) -> None:
        good = self.child(self.copy, ok(0.9))
        well_tried = self.child(self.copy, ok(0.9))
        for _ in range(9):
            self.child(well_tried, Result.failure(Status.FAILED, "x"))
        island = self.database.islands[0]
        counts = Counter(self.database.sample_parent(island).id for _ in range(3000))
        self.assertGreater(counts[good.id], 5 * counts[well_tried.id])
        self.assertGreater(counts[good.id], counts[self.copy.id])

    def test_same_seed_gives_the_same_draws(self) -> None:
        draws = []
        for _ in range(2):
            self.make(make_problem(), seed=11)
            self.child(self.copy, ok(0.6))
            self.child(self.copy, ok(0.8))
            island = self.database.sample_island()
            draws.append([self.database.sample_parent(island).code for _ in range(30)])
        self.assertEqual(draws[0], draws[1])


if __name__ == "__main__":
    unittest.main()
