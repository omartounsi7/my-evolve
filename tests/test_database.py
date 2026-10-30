"""Checks the database: every program kept, the best tracked, islands, and the draws."""

import math
import random
import statistics
import unittest
from collections import Counter

from my_evolve.database import Database, OpenEvolveSelector, WeightedSelector
from my_evolve.problem import CODE_COMPLEXITY, FeatureSpec, IslandSettings, ParentSettings
from my_evolve.program import Origin, Program, Result, Status

# Most tests use a database with a single island, island 0
ONE_ISLAND = IslandSettings(count=1)
# A grid whose bin k holds the programs of 2**k nodes (measured against 1 node)
TEST_GRID = (FeatureSpec(CODE_COMPLEXITY, 0.0, 10.0, 10),)


def working(score: float, island: int = 0, cell: int | None = None) -> Program:
    """Return a working program on an island, with that score.

    It falls in grid cell `cell` of TEST_GRID; by default the whole part of its score, so
    that programs of different scores have cells of their own.
    """
    nodes = 2 ** (int(score) % 10 if cell is None else cell)
    result = Result(Status.OK, score=score)
    return Program(f"x = {score}\n", result, island=island, code_complexity=nodes)


def failed(island: int = 0) -> Program:
    """Return a program on an island, that failed its evaluation."""
    result = Result.failure(Status.FAILED, "SyntaxError: '(' was never closed")
    return Program("x = (\n", result, island=island)


def one_island(seed: int = 0, parents: ParentSettings | None = None) -> Database:
    """Return an empty database with a single island."""
    return Database(random.Random(seed), parents, ONE_ISLAND, TEST_GRID)


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
    return Program.new_child(
        parent,
        "x = 2\n",
        result,
        iteration=1,
        island=parent.island,
        code_complexity=parent.code_complexity,
    )


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
        for cell, (score, count) in enumerate(zip(scores, children, strict=True)):
            program = working(score, cell=cell)
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
        """Return how often each elite is drawn as parent, in cell order (the order added)."""
        elites = database.islands[0].elites()
        selector = WeightedSelector(1.0)
        rng = random.Random(1)
        counts = Counter(selector.choose(0, database, rng).id for _ in range(draws))
        return [counts[program.id] / draws for program in elites]

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
        database = Database(random.Random(0), None, IslandSettings(count=3), TEST_GRID)
        initial = Program(
            "x = 1\n", Result(Status.OK, score=1.0), fingerprint="f", code_complexity=1
        )
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
            database.add(working(score + 10, island=1, cell=int(score)))
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


class GridPopulationTest(unittest.TestCase):
    def test_parents_are_elites_and_displaced_elites_stay_examples(self) -> None:
        """A better program in the same cell takes it. The one displaced is no longer a
        parent, but stays in the database and can still be an example."""
        database = one_island()
        weaker, stronger, other = working(1.0, cell=3), working(2.0, cell=3), working(0.5, cell=7)
        for program in (weaker, stronger, other):
            database.add(program)
        self.assertEqual(database.islands[0].elites(), [stronger, other])
        self.assertIs(database.islands[0].best(), stronger)
        self.assertIn(weaker.id, database.programs)
        parents = {database.sample_parent(0).id for _ in range(200)}
        self.assertEqual(parents, {stronger.id, other.id})
        examples = {
            example.id for _ in range(200) for example in database.sample_examples(0, other, 2)
        }
        self.assertIn(weaker.id, examples)

    def test_a_cell_changes_hands_only_for_a_strictly_higher_score(self) -> None:
        database = one_island()
        first, tie = working(1.0, cell=3), working(1.0, cell=3)
        database.add(first)
        database.add(tie)
        self.assertEqual(database.islands[0].elites(), [first])

    def test_failed_programs_never_enter_the_grid(self) -> None:
        database = one_island()
        database.add(working(1.0))
        database.add(failed())
        self.assertEqual(len(database.islands[0].elites()), 1)


def islands_of(count: int, **migration: object) -> Database:
    """Return a database of that many islands, with these migration settings."""
    settings = IslandSettings(count=count, **migration)  # type: ignore[arg-type]
    return Database(random.Random(0), None, settings, TEST_GRID)


def fill(database: Database, island: int, scores: list[float]) -> list[Program]:
    """Add working programs to an island, each in its own cell; return them."""
    programs = [working(score, island=island, cell=cell) for cell, score in enumerate(scores)]
    for program in programs:
        database.add(program)
    return programs


class MigrationTest(unittest.TestCase):
    def test_the_default_copies_one_non_best_elite_to_every_other_island(self) -> None:
        """10% of 5 elites rounds down to 0: at least one migrates, never the island's best."""
        database = islands_of(3)
        programs = fill(database, 0, [1.0, 2.0, 5.0, 3.0, 4.0])
        for _ in range(20):
            arrivals = database.migrate(25)
            from_island_0 = [
                arrival
                for arrival in arrivals
                if arrival.parent_id in database.programs
                and database.programs[arrival.parent_id].island == 0
            ]
            self.assertEqual(sorted(arrival.island or 0 for arrival in from_island_0), [1, 2])
            self.assertEqual(len({arrival.parent_id for arrival in from_island_0}), 1)
            self.assertNotEqual(from_island_0[0].parent_id, programs[2].id)
        arrival = from_island_0[0]
        self.assertEqual((arrival.origin, arrival.iteration), (Origin.COPY, 25))
        self.assertEqual(arrival.code, database.programs[arrival.parent_id or ""].code)

    def test_the_share_and_the_choice_of_migrants(self) -> None:
        database = islands_of(2, migration_share=0.5, migrants="random")
        fill(database, 0, [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(len(database.migrate(1)), 2)
        database = islands_of(2, migrants="best")
        programs = fill(database, 0, [1.0, 5.0, 3.0])
        (arrival,) = database.migrate(1)
        self.assertEqual(arrival.parent_id, programs[1].id)

    def test_ring_destinations(self) -> None:
        """With a ring, each island sends to the next, the last to the first."""
        database = islands_of(3, destinations="ring", migrants="best")
        for island in range(3):
            fill(database, island, [1.0 + island])
        arrivals = database.migrate(1)
        routes = sorted((database.programs[a.parent_id or ""].island, a.island) for a in arrivals)
        self.assertEqual(routes, [(0, 1), (1, 2), (2, 0)])

    def test_an_arrival_takes_a_cell_only_if_empty_or_worse(self) -> None:
        database = islands_of(2, migrants="best")
        strong = fill(database, 0, [5.0])[0]
        weak_here = working(1.0, island=1, cell=0)
        database.add(weak_here)
        stronger_there = working(9.0, island=1, cell=1)
        database.add(stronger_there)
        for arrival in database.migrate(1):
            database.add(arrival)
        island_1 = {elite.parent_id or elite.id for elite in database.islands[1].elites()}
        self.assertIn(strong.id, island_1)
        self.assertNotIn(weak_here.id, island_1)
        island_0 = {elite.parent_id or elite.id for elite in database.islands[0].elites()}
        # Island 1's best, 9.0 in cell 1, took the empty cell 1 of island 0.
        self.assertIn(stronger_there.id, island_0)

    def test_arrivals_do_not_migrate_again_in_the_same_round(self) -> None:
        database = islands_of(3, migrants="best")
        originals = {program.id for island in range(3) for program in fill(database, island, [1.0])}
        self.assertTrue(all(arrival.parent_id in originals for arrival in database.migrate(1)))

    def test_a_copy_starts_without_children_and_a_move_keeps_them(self) -> None:
        for mode, origin, children in [("copy", Origin.COPY, 0), ("move", Origin.MOVE, 2)]:
            with self.subTest(mode=mode):
                database = islands_of(2, migrants="random", mode=mode, migration_share=0.5)
                programs = fill(database, 0, [1.0, 2.0])
                for program in programs:
                    for _ in range(2):
                        database.add(child_of(program, Status.FAILED))
                (arrival,) = database.migrate(1)
                database.add(arrival)
                self.assertEqual(
                    (arrival.origin, database.children_count(arrival.id)), (origin, children)
                )

    def test_a_move_leaves_its_grid_and_never_empties_an_island(self) -> None:
        database = islands_of(2, migrants="random", mode="move", migration_share=1.0)
        programs = fill(database, 0, [1.0, 2.0, 3.0])
        arrivals = database.migrate(1)
        self.assertEqual(len(arrivals), 2)
        for arrival in arrivals:
            database.add(arrival)
        moved = {arrival.parent_id for arrival in arrivals}
        self.assertEqual(len(database.islands[0].elites()), 1)
        self.assertNotIn(database.islands[0].elites()[0].id, moved)
        self.assertEqual(len(database.islands[1].elites()), 2)
        self.assertTrue(all(program.id in database.programs for program in programs))

    def test_a_replay_rebuilds_the_database_without_drawing(self) -> None:
        """Migrations replay from their stored records (D49)."""
        database = islands_of(2, migrants="random", mode="move", migration_share=1.0)
        stored = fill(database, 0, [1.0, 2.0, 3.0])
        stored.append(child_of(stored[0], Status.FAILED))
        database.add(stored[-1])
        for arrival in database.migrate(1):
            database.add(arrival)
            stored.append(arrival)
        replayed = islands_of(2, migrants="random", mode="move", migration_share=1.0)
        state = replayed.rng.getstate()
        replayed.replay(stored)
        self.assertEqual(replayed.rng.getstate(), state)
        self.assertEqual(list(replayed.programs), list(database.programs))
        self.assertEqual(replayed.best_id, database.best_id)
        self.assertEqual(replayed.children, database.children)
        for island in (0, 1):
            self.assertEqual(
                replayed.islands[island].grid.elites, database.islands[island].grid.elites
            )

    def test_one_island_has_nowhere_to_send(self) -> None:
        database = islands_of(1)
        fill(database, 0, [1.0, 2.0])
        self.assertEqual(database.migrate(1), [])


class ArchiveTest(unittest.TestCase):
    def test_the_best_programs_first_and_the_earlier_on_a_tie(self) -> None:
        database = islands_of(2)
        programs = fill(database, 0, [1.0, 4.0, 2.0]) + fill(database, 1, [4.0, 3.0])
        self.assertEqual(database.archive(4), [programs[1], programs[3], programs[4], programs[2]])
        self.assertEqual(len(database.archive(10)), 5)

    def test_copies_of_one_program_count_once(self) -> None:
        database = islands_of(3)
        initial = Program(
            "x = 1\n", Result(Status.OK, score=1.0), fingerprint="f", code_complexity=1
        )
        database.add(initial)
        for copy in database.seed_islands(initial):
            database.add(copy)
        self.assertEqual(database.archive(10), [initial])

    def test_failed_programs_are_not_in_the_archive(self) -> None:
        database = one_island()
        database.add(failed())
        self.assertEqual(database.archive(10), [])


class OpenEvolveSelectorTest(unittest.TestCase):
    def frequencies(self, database: Database, draws: int = 20_000) -> Counter[str]:
        selector = OpenEvolveSelector(archive_size=1)
        rng = random.Random(3)
        counts = Counter(selector.choose(0, database, rng).id for _ in range(draws))
        return Counter({key: value / draws for key, value in counts.items()})

    def test_the_three_branches(self) -> None:
        """Island 0's elites score 1 and 2; the archive (size 1) is island 1's 9.

        No archive program was made on island 0, so the archive branch draws from the whole
        archive: 70% for the 9; the uniform branch gives each elite 10%; the proportional
        branch gives them 1/3 and 2/3 of 10%.
        """
        database = islands_of(2)
        low, high = fill(database, 0, [1.0, 2.0])
        (far,) = fill(database, 1, [9.0])
        frequencies = self.frequencies(database)
        self.assertAlmostEqual(frequencies[far.id], 0.70, delta=0.015)
        self.assertAlmostEqual(frequencies[low.id], 0.10 + 0.1 / 3, delta=0.015)
        self.assertAlmostEqual(frequencies[high.id], 0.10 + 0.2 / 3, delta=0.015)

    def test_the_archive_branch_prefers_the_island(self) -> None:
        """With the island's own program in the archive, the archive branch keeps to it."""
        database = islands_of(2)
        (best,) = fill(database, 0, [9.0])
        fill(database, 1, [5.0])
        selector = OpenEvolveSelector(archive_size=2)
        rng = random.Random(4)
        self.assertEqual({selector.choose(0, database, rng).id for _ in range(500)}, {best.id})


if __name__ == "__main__":
    unittest.main()
