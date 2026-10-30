"""Checks the MAP-Elites grid: features, bins, elites and their order."""

import unittest

from my_evolve.grid import Grid
from my_evolve.problem import CODE_COMPLEXITY, FeatureSpec
from my_evolve.program import Program, Result, Status

# Code complexity from -1 to +3 in 10 bins, each 0.4 wide, measured against 100 nodes
FEATURES = (FeatureSpec(CODE_COMPLEXITY, -1.0, 3.0, 10),)


def program(nodes: int, score: float) -> Program:
    """Return a working program with that many nodes inside its evolve blocks."""
    return Program("x = 1\n", Result(Status.OK, score=score), code_complexity=nodes)


class FeatureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.grid = Grid(FEATURES, reference_nodes=100)

    def test_code_complexity_is_log2_of_the_ratio_to_the_initial_program(self) -> None:
        self.assertEqual(self.grid.feature_values(program(100, 1.0)), [0.0])
        self.assertEqual(self.grid.feature_values(program(200, 1.0)), [1.0])
        self.assertEqual(self.grid.feature_values(program(50, 1.0)), [-1.0])
        # No node at all counts as one, so that the logarithm exists.
        self.assertEqual(self.grid.feature_values(program(0, 1.0)), [-6.643856189774724])

    def test_a_program_without_a_measure_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "no code complexity"):
            self.grid.feature_values(Program("x = 1\n", Result(Status.OK, score=1.0)))


class BinTest(unittest.TestCase):
    def setUp(self) -> None:
        self.grid = Grid(FEATURES, reference_nodes=100)

    def test_bins(self) -> None:
        """The initial program's size, log2 = 0, is 1 above low: bin 2.5, rounded down."""
        for nodes, cell in [(100, 2), (99, 2), (141, 3), (200, 5), (400, 7), (790, 9)]:
            with self.subTest(nodes=nodes):
                self.assertEqual(self.grid.cell_of(program(nodes, 1.0)), (cell,))

    def test_the_edges_of_the_range(self) -> None:
        """low is bin 0; high, and anything above, the last bin; anything below, bin 0."""
        self.assertEqual(self.grid.cell_of(program(50, 1.0)), (0,))
        self.assertEqual(self.grid.cell_of(program(800, 1.0)), (9,))
        self.assertEqual(self.grid.cell_of(program(100_000, 1.0)), (9,))
        self.assertEqual(self.grid.cell_of(program(1, 1.0)), (0,))

    def test_one_bin_per_feature(self) -> None:
        grid = Grid(FEATURES + (FeatureSpec(CODE_COMPLEXITY, 0.0, 1.0, 2),), reference_nodes=100)
        self.assertEqual(grid.cell_of(program(100, 1.0)), (2, 0))


class OutputFeatureTest(unittest.TestCase):
    def test_an_output_feature_comes_from_the_result(self) -> None:
        """A 2D grid: code complexity, then the spread of the radii, from 0 to 1 in 5 bins."""
        grid = Grid(
            (FeatureSpec(CODE_COMPLEXITY, -1.0, 3.0, 5), FeatureSpec("radii_spread", 0.0, 1.0, 5)),
            reference_nodes=100,
        )
        result = Result(Status.OK, score=1.0, features={"radii_spread": 0.45})
        packing = Program("x = 1\n", result, code_complexity=100)
        self.assertEqual(grid.feature_values(packing), [0.0, 0.45])
        self.assertEqual(grid.cell_of(packing), (1, 2))

    def test_a_missing_output_feature_is_refused(self) -> None:
        grid = Grid((FeatureSpec("radii_spread", 0.0, 1.0, 5),), reference_nodes=100)
        with self.assertRaisesRegex(ValueError, "has no feature 'radii_spread'"):
            grid.cell_of(program(100, 1.0))


class PlaceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.grid = Grid(FEATURES, reference_nodes=100)

    def test_an_empty_cell_is_taken(self) -> None:
        self.assertEqual(self.grid.place(program(100, 1.0)), (True, (2,), None))

    def test_only_a_strictly_higher_score_takes_a_cell(self) -> None:
        first = program(100, 1.0)
        self.grid.place(first)
        self.assertEqual(self.grid.place(program(105, 1.0)), (False, (2,), None))
        better = program(105, 2.0)
        self.assertEqual(self.grid.place(better), (True, (2,), first))
        self.assertEqual(self.grid.elite_list(), [better])

    def test_a_program_that_does_not_work_is_refused(self) -> None:
        broken = Program("x = (\n", Result.failure(Status.FAILED, "SyntaxError"), code_complexity=5)
        with self.assertRaisesRegex(ValueError, "cannot enter a grid"):
            self.grid.place(broken)

    def test_elites_come_in_cell_order_and_the_best_is_the_first_on_a_tie(self) -> None:
        big, small, middle = program(800, 1.0), program(50, 3.0), program(200, 3.0)
        for elite in (big, small, middle):
            self.grid.place(elite)
        self.assertEqual(self.grid.elite_list(), [small, middle, big])
        self.assertIs(self.grid.best(), small)

    def test_remove(self) -> None:
        elite = program(100, 1.0)
        self.grid.place(elite)
        self.grid.remove(elite.id)
        self.assertEqual(self.grid.elite_list(), [])
        self.assertIsNone(self.grid.best())


if __name__ == "__main__":
    unittest.main()
