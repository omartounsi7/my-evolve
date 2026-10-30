"""Checks that the database keeps every program, tracks the best, and draws only working ones."""

import math
import random
import statistics
import unittest
from collections import Counter

from my_evolve.database import Database, WeightedSelector
from my_evolve.problem import ParentSettings
from my_evolve.program import Program, Result, Status


def working(score: float) -> Program:
    """Return a program with that score."""
    return Program(f"x = {score}\n", Result(Status.OK, score=score))


def failed() -> Program:
    """Return a program that failed its evaluation."""
    return Program("x = (\n", Result.failure(Status.FAILED, "SyntaxError: '(' was never closed"))


def filled_database(seed: int = 0) -> Database:
    """Return a database holding five working programs and five failed ones."""
    database = Database(random.Random(seed))
    for score in range(5):
        database.add(working(float(score)))
        database.add(failed())
    return database


class DatabaseTest(unittest.TestCase):
    def test_every_program_is_kept(self) -> None:
        """Failed programs are stored too, in the order added."""
        database = filled_database()
        self.assertEqual(len(database.programs), 10)
        self.assertEqual(len(database.working_programs()), 5)

    def test_the_best_is_the_highest_score_and_the_earliest_on_a_tie(self) -> None:
        """A later program with the same score does not replace the best."""
        database = Database(random.Random(0))
        self.assertIsNone(database.best())
        database.add(failed())
        self.assertIsNone(database.best_score())
        first = working(2.0)
        database.add(first)
        database.add(working(1.0))
        database.add(working(2.0))
        self.assertIs(database.best(), first)
        self.assertEqual(database.best_score(), 2.0)

    def test_draws_are_working_programs_and_the_parent_is_not_an_example(self) -> None:
        """Failed programs are never drawn; the examples are other, distinct programs."""
        database = filled_database()
        for _ in range(200):
            parent, examples = database.sample(2)
            self.assertEqual(len(examples), 2)
            drawn = [parent, *examples]
            self.assertTrue(all(program.result.is_ok for program in drawn))
            self.assertEqual(len({program.id for program in drawn}), len(drawn))

    def test_fewer_examples_when_fewer_programs_work(self) -> None:
        """With the initial program alone, there is no example to show."""
        database = Database(random.Random(0))
        initial = working(1.0)
        database.add(initial)
        database.add(failed())
        self.assertEqual(database.sample(2), (initial, []))

    def test_the_same_seed_draws_the_same(self) -> None:
        """Two databases with the same seed and programs make the same draws."""
        first, second = filled_database(seed=7), filled_database(seed=7)
        # The programs differ only by id: compare their scores.
        for _ in range(20):
            (parent_1, examples_1), (parent_2, examples_2) = first.sample(2), second.sample(2)
            self.assertEqual(
                [p.result.score for p in [parent_1, *examples_1]],
                [p.result.score for p in [parent_2, *examples_2]],
            )

    def test_every_working_program_can_be_drawn(self) -> None:
        """The draw is not stuck on the best: every working program is drawn sometimes."""
        database = filled_database()
        parents = {database.sample(2)[0].result.score for _ in range(200)}
        self.assertEqual(parents, {0.0, 1.0, 2.0, 3.0, 4.0})

    def test_the_number_of_examples_is_a_setting(self) -> None:
        """No examples with a count of 0; as many as asked, while there are enough."""
        database = filled_database()
        self.assertEqual(database.sample(0)[1], [])
        self.assertEqual(len(database.sample(4)[1]), 4)
        self.assertEqual(len(database.sample(9)[1]), 4)

    def test_sampling_an_empty_database_is_refused(self) -> None:
        """Without a working program, there is nothing to build on."""
        database = Database(random.Random(0))
        database.add(failed())
        with self.assertRaisesRegex(ValueError, "no working program"):
            database.sample(2)


class FingerprintTest(unittest.TestCase):
    def test_only_programs_that_ran_count_for_duplicates(self) -> None:
        """ok, failed, timeout and invalid programs are recorded; rejected and error ones not."""
        database = Database(random.Random(0))
        for status in Status:
            result = Result(status, score=1.0) if status is Status.OK else Result(status, error="x")
            database.add(Program("x = 1\n", result, fingerprint=status.value))
        self.assertEqual(set(database.fingerprints), {"ok", "failed", "timeout", "invalid"})

    def test_the_first_program_with_a_fingerprint_keeps_it(self) -> None:
        database = Database(random.Random(0))
        first = Program("x = 1\n", Result(Status.OK, score=1.0), fingerprint="same")
        database.add(first)
        database.add(Program("x = 1\n", Result(Status.OK, score=2.0), fingerprint="same"))
        self.assertEqual(database.fingerprints, {"same": first.id})


def child_of(parent: Program, status: Status) -> Program:
    """Return a child of parent with that status."""
    result = Result(status, score=1.0) if status is Status.OK else Result(status, error="x")
    return Program.new_child(parent, "x = 2\n", result, iteration=1)


class ChildrenTest(unittest.TestCase):
    def test_every_child_counts_except_errors(self) -> None:
        """A failed, invalid or rejected child cost an LLM call; an error is not the program's."""
        database = Database(random.Random(0))
        parent = working(1.0)
        database.add(parent)
        for status in (Status.OK, Status.FAILED, Status.REJECTED, Status.ERROR, Status.INVALID):
            database.add(child_of(parent, status))
        self.assertEqual(database.children_count(parent.id), 4)
        self.assertEqual(database.children_count("unknown"), 0)


class WeightedSelectorTest(unittest.TestCase):
    def population(self, scores: list[float], children: list[int]) -> Database:
        """Return a database of working programs with these scores and numbers of children."""
        database = Database(random.Random(0), ParentSettings(lam=1.0))
        for score, count in zip(scores, children, strict=True):
            program = working(score)
            database.add(program)
            for _ in range(count):
                database.add(child_of(program, Status.FAILED))
        return database

    def expected(self, scores: list[float], children: list[int], spread: float) -> list[float]:
        """Return the probabilities the rule gives, computed by hand."""
        median = statistics.median(scores)
        weights = [
            (0.5 if spread == 0 else 1 / (1 + math.exp(-(score - median) / spread))) / (1 + count)
            for score, count in zip(scores, children, strict=True)
        ]
        return [weight / sum(weights) for weight in weights]

    def frequencies(self, database: Database, draws: int = 20_000) -> list[float]:
        """Return how often each working program is drawn as parent, in the order added."""
        working_programs = database.working_programs()
        selector = WeightedSelector(1.0)
        rng = random.Random(1)
        counts = Counter(selector.choose(working_programs, database, rng).id for _ in range(draws))
        return [counts[program.id] / draws for program in working_programs]

    def test_draws_follow_the_formula(self) -> None:
        """sigmoid((score - median) / MAD) * 1 / (1 + children), normalized."""
        scores, children = [1.0, 2.0, 3.0, 4.0, 5.0], [0, 0, 1, 0, 3]
        database = self.population(scores, children)
        # The median is 3; the absolute deviations 2, 1, 0, 1, 2 have a median of 1.
        for found, wanted in zip(
            self.frequencies(database), self.expected(scores, children, 1.0), strict=True
        ):
            self.assertAlmostEqual(found, wanted, delta=0.015)

    def test_the_standard_deviation_when_the_mad_is_zero(self) -> None:
        scores, children = [1.0, 1.0, 1.0, 5.0], [0, 0, 0, 0]
        database = self.population(scores, children)
        spread = statistics.pstdev(scores)
        for found, wanted in zip(
            self.frequencies(database), self.expected(scores, children, spread), strict=True
        ):
            self.assertAlmostEqual(found, wanted, delta=0.015)

    def test_equal_scores_leave_only_the_children_count(self) -> None:
        """With every score equal, each sigmoid term is 0.5: fewer children, more draws."""
        scores, children = [2.0, 2.0, 2.0], [0, 1, 3]
        database = self.population(scores, children)
        for found, wanted in zip(
            self.frequencies(database), self.expected(scores, children, 0.0), strict=True
        ):
            self.assertAlmostEqual(found, wanted, delta=0.015)


if __name__ == "__main__":
    unittest.main()
