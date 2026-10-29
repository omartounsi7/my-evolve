"""Checks that the database keeps every program, tracks the best, and draws only working ones."""

import random
import unittest

from my_evolve.database import EXAMPLE_PROGRAMS, Database
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
            parent, examples = database.sample()
            self.assertEqual(len(examples), EXAMPLE_PROGRAMS)
            drawn = [parent, *examples]
            self.assertTrue(all(program.result.is_ok for program in drawn))
            self.assertEqual(len({program.id for program in drawn}), len(drawn))

    def test_fewer_examples_when_fewer_programs_work(self) -> None:
        """With the initial program alone, there is no example to show."""
        database = Database(random.Random(0))
        initial = working(1.0)
        database.add(initial)
        database.add(failed())
        self.assertEqual(database.sample(), (initial, []))

    def test_the_same_seed_draws_the_same(self) -> None:
        """Two databases with the same seed and programs make the same draws."""
        first, second = filled_database(seed=7), filled_database(seed=7)
        # The programs differ only by id: compare their scores.
        for _ in range(20):
            (parent_1, examples_1), (parent_2, examples_2) = first.sample(), second.sample()
            self.assertEqual(
                [p.result.score for p in [parent_1, *examples_1]],
                [p.result.score for p in [parent_2, *examples_2]],
            )

    def test_every_working_program_can_be_drawn(self) -> None:
        """The draw is not stuck on the best: every working program is drawn sometimes."""
        database = filled_database()
        parents = {database.sample()[0].result.score for _ in range(200)}
        self.assertEqual(parents, {0.0, 1.0, 2.0, 3.0, 4.0})

    def test_sampling_an_empty_database_is_refused(self) -> None:
        """Without a working program, there is nothing to build on."""
        database = Database(random.Random(0))
        database.add(failed())
        with self.assertRaisesRegex(ValueError, "no working program"):
            database.sample()


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


if __name__ == "__main__":
    unittest.main()
