"""Checks the database: every program kept, the best tracked, islands, and the draws."""

import math
import random
import statistics
import unittest
from collections import Counter

from my_evolve.database import Database, WeightedSelector
from my_evolve.problem import IslandSettings, ParentSettings
from my_evolve.program import Origin, Program, Result, Status

# Most tests use a database with a single island, island 0
ONE_ISLAND = IslandSettings(count=1)


def working(score: float, island: int = 0) -> Program:
    """Return a program on an island, with that score."""
    return Program(f"x = {score}\n", Result(Status.OK, score=score), island=island)


def failed(island: int = 0) -> Program:
    """Return a program on an island, that failed its evaluation."""
    result = Result.failure(Status.FAILED, "SyntaxError: '(' was never closed")
    return Program("x = (\n", result, island=island)


def one_island(seed: int = 0, parents: ParentSettings | None = None) -> Database:
    """Return an empty database with a single island."""
    return Database(random.Random(seed), parents, ONE_ISLAND)


def filled_database(seed: int = 0) -> Database:
    """Return a one-island database holding five working programs and five failed ones."""
    database = one_island(seed)
    for score in range(5):
        database.add(working(float(score)))
        database.add(failed())
    return database


class DatabaseTest(unittest.TestCase):
    def test_every_program_is_kept(self) -> None:
        """Failed programs are stored too, in the order added."""
        database = filled_database()
        self.assertEqual(len(database.programs), 10)
        self.assertEqual(len(database.working_programs(0)), 5)

    def test_the_best_is_the_highest_score_and_the_earliest_on_a_tie(self) -> None:
        """A later program with the same score does not replace the best."""
        database = one_island()
        self.assertIsNone(database.best())
        database.add(failed())
        self.assertIsNone(database.best_score())
        first = working(2.0)
        database.add(first)
        database.add(working(1.0))
        database.add(working(2.0))
        self.assertIs(database.best(), first)
        self.assertEqual(database.best_score(), 2.0)

    def test_parents_work_and_examples_are_other_programs(self) -> None:
        """Parents are working programs; examples are distinct and never the parent."""
        database = filled_database()
        for _ in range(200):
            parent, examples = database.sample(0, 2)
            self.assertTrue(parent.result.is_ok)
            self.assertEqual(len(examples), 2)
            drawn = [parent, *examples]
            self.assertEqual(len({program.id for program in drawn}), len(drawn))

    def test_failed_programs_can_be_examples(self) -> None:
        """With the initial program alone working, the failed program is its example."""
        database = one_island()
        initial = working(1.0)
        broken = failed()
        database.add(initial)
        database.add(broken)
        self.assertEqual(database.sample(0, 2), (initial, [broken]))

    def test_errors_and_children_without_code_are_never_examples(self) -> None:
        """An error is not the program's fault; a reply without code shows nothing."""
        database = one_island()
        parent = working(1.0)
        database.add(parent)
        database.add(Program("x = 2\n", Result.failure(Status.ERROR, "down"), island=0))
        database.add(Program("", Result.rejected("no code in the reply"), island=0))
        rejected = Program("x = (\n", Result.rejected("does not compile"), island=0)
        database.add(rejected)
        for _ in range(50):
            self.assertEqual(database.sample_examples(0, parent, 3), [rejected])

    def test_the_same_seed_draws_the_same(self) -> None:
        """Two databases with the same seed and programs make the same draws."""
        first, second = filled_database(seed=7), filled_database(seed=7)
        # The programs differ only by id: compare their scores.
        for _ in range(20):
            (parent_1, examples_1), (parent_2, examples_2) = first.sample(0, 2), second.sample(0, 2)
            self.assertEqual(
                [p.result.score for p in [parent_1, *examples_1]],
                [p.result.score for p in [parent_2, *examples_2]],
            )

    def test_every_working_program_can_be_drawn(self) -> None:
        """The draw is not stuck on the best: every working program is drawn sometimes."""
        database = filled_database()
        parents = {database.sample(0, 2)[0].result.score for _ in range(200)}
        self.assertEqual(parents, {0.0, 1.0, 2.0, 3.0, 4.0})

    def test_the_number_of_examples_is_a_setting(self) -> None:
        """No examples with a count of 0; as many as asked, while there are enough."""
        database = filled_database()
        self.assertEqual(database.sample(0, 0)[1], [])
        self.assertEqual(len(database.sample(0, 4)[1]), 4)
        self.assertEqual(len(database.sample(0, 20)[1]), 9)

    def test_sampling_an_empty_database_is_refused(self) -> None:
        """Without a working program, there is nothing to build on."""
        database = one_island()
        database.add(failed())
        with self.assertRaisesRegex(ValueError, "no working program"):
            database.sample(0, 2)


class FingerprintTest(unittest.TestCase):
    def test_only_programs_that_ran_count_for_duplicates(self) -> None:
        """ok, failed, timeout and invalid programs are recorded; rejected and error ones not."""
        database = one_island()
        for status in Status:
            result = Result(status, score=1.0) if status is Status.OK else Result(status, error="x")
            database.add(Program("x = 1\n", result, fingerprint=status.value))
        self.assertEqual(set(database.fingerprints), {"ok", "failed", "timeout", "invalid"})

    def test_the_first_program_with_a_fingerprint_keeps_it(self) -> None:
        database = one_island()
        first = Program("x = 1\n", Result(Status.OK, score=1.0), fingerprint="same")
        database.add(first)
        database.add(Program("x = 1\n", Result(Status.OK, score=2.0), fingerprint="same"))
        self.assertEqual(database.fingerprints, {"same": first.id})


def child_of(parent: Program, status: Status) -> Program:
    """Return a child of parent with that status."""
    result = Result(status, score=1.0) if status is Status.OK else Result(status, error="x")
    return Program.new_child(parent, "x = 2\n", result, iteration=1, island=parent.island)


class ChildrenTest(unittest.TestCase):
    def test_every_child_counts_except_errors(self) -> None:
        """A failed, invalid or rejected child cost an LLM call; an error is not the program's."""
        database = one_island()
        parent = working(1.0)
        database.add(parent)
        for status in (Status.OK, Status.FAILED, Status.REJECTED, Status.ERROR, Status.INVALID):
            database.add(child_of(parent, status))
        self.assertEqual(database.children_count(parent.id), 4)
        self.assertEqual(database.children_count("unknown"), 0)


class WeightedSelectorTest(unittest.TestCase):
    def population(self, scores: list[float], children: list[int]) -> Database:
        """Return a database of working programs with these scores and numbers of children."""
        database = one_island(parents=ParentSettings(lam=1.0))
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
        working_programs = database.working_programs(0)
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


class IslandTest(unittest.TestCase):
    def three_islands(self) -> tuple[Database, Program]:
        """Return a database of three islands seeded with the initial program, and that program."""
        database = Database(random.Random(0), islands=IslandSettings(count=3))
        initial = Program("x = 1\n", Result(Status.OK, score=1.0), fingerprint="f")
        database.add(initial)
        for copy in database.seed_islands(initial):
            database.add(copy)
        return database, initial

    def test_each_island_starts_with_a_copy_of_the_initial_program(self) -> None:
        database, initial = self.three_islands()
        self.assertIsNone(initial.island)
        for island in range(3):
            (copy,) = database.island_programs(island)
            self.assertEqual(
                (copy.origin, copy.island, copy.parent_id), (Origin.COPY, island, initial.id)
            )
            self.assertEqual(
                (copy.code, copy.result, copy.fingerprint), (initial.code, initial.result, "f")
            )
            self.assertEqual((copy.generation, copy.iteration), (0, 0))

    def test_a_copy_never_replaces_the_initial_program_as_the_best(self) -> None:
        database, initial = self.three_islands()
        self.assertIs(database.best(), initial)
        self.assertEqual(database.fingerprints, {"f": initial.id})

    def test_draws_stay_on_the_island(self) -> None:
        """Parents and examples of island 1 are programs made on island 1."""
        database, _ = self.three_islands()
        for score in (2.0, 3.0):
            database.add(working(score, island=0))
            database.add(working(score + 10, island=1))
            database.add(failed(island=1))
        island_1 = {program.id for program in database.island_programs(1)}
        for _ in range(100):
            parent, examples = database.sample(1, 2)
            self.assertTrue({parent.id, *(example.id for example in examples)} <= island_1)

    def test_a_copys_children_count_for_the_copy(self) -> None:
        database, initial = self.three_islands()
        copy = database.island_programs(2)[0]
        database.add(child_of(copy, Status.OK))
        self.assertEqual(
            (database.children_count(copy.id), database.children_count(initial.id)), (1, 0)
        )

    def test_islands_are_drawn_uniformly(self) -> None:
        database, _ = self.three_islands()
        counts = Counter(database.sample_island() for _ in range(9_000))
        for island in range(3):
            self.assertAlmostEqual(counts[island] / 9_000, 1 / 3, delta=0.03)


if __name__ == "__main__":
    unittest.main()
