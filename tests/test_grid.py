"""Checks the MAP-Elites grid: binning, placing elites, and their order."""

import math
import unittest

from my_evolve.grid import Grid
from my_evolve.problem import CODE_COMPLEXITY, FeatureSpec
from my_evolve.program import Program, Result, Status

# Code complexity from -1 to +3 in 10 bins (each 0.4 wide), measured against 100 nodes
FEATURES = (FeatureSpec(CODE_COMPLEXITY, -1.0, 3.0, 10),)


def program(nodes: int, score: float) -> Program:
    """Return a working program of that many nodes inside its blocks."""
    return Program("x = 1\n", Result(Status.OK, score=score), code_complexity=nodes)


class BinTest(unittest.TestCase):
    def setUp(self) -> None:
        self.grid = Grid(FEATURES, reference_nodes=100)

    def test_the_feature_is_log2_of_the_ratio(self) -> None:
        self.assertEqual(self.grid.feature_values(program(100, 1.0)), [0.0])
        self.assertEqual(self.grid.feature_values(program(200, 1.0)), [1.0])
        self.assertAlmostEqual(self.grid.feature_values(program(50, 1.0))[0], -1.0)

    def test_bins_and_their_edges(self) -> None:
        """The initial program's size is in bin 2; the ends of the range in the end bins."""
        for nodes, cell in [(100, 2), (50, 0), (800, 9), (141, 3), (142, 3), (99, 2)]:
            with self.subTest(nodes=nodes):
                self.assertEqual(self.grid.cell_of(program(nodes, 1.0)), (cell,))
        # log2(2**0.4) is 0.4 exactly at the edge between bins 3 and 4
        edge = 100 * 2**0.4
        self.assertEqual(self.grid.cell_of(program(math.ceil(edge), 1.0)), (3,))

    def test_values_out_of_range_go_to_the_nearest_end_bin(self) -> None:
        self.assertEqual(self.grid.cell_of(program(1, 1.0)), (0,))
        self.assertEqual(self.grid.cell_of(program(100_000, 1.0)), (9,))
        self.assertEqual(self.grid.cell_of(program(0, 1.0)), (0,))

    def test_two_features_give_two_bins(self) -> None:
        grid = Grid(
            (FeatureSpec(CODE_COMPLEXITY, -1.0, 3.0, 10), FeatureSpec(CODE_COMPLEXITY, 0, 1, 2)),
            reference_nodes=100,
        )
        self.assertEqual(grid.cell_of(program(100, 1.0)), (2, 0))


class PlaceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.grid = Grid(FEATURES, reference_nodes=100)

    def test_an_empty_cell_is_taken(self) -> None:
        first = program(100, 1.0)
        self.assertEqual(self.grid.place(first), (True, (2,), None))

    def test_only_a_strictly_higher_score_takes_a_cell(self) -> None:
        first = program(100, 1.0)
        self.grid.place(first)
        self.assertEqual(self.grid.place(program(100, 1.0)), (False, (2,), None))
        better = program(105, 2.0)
        self.assertEqual(self.grid.place(better), (True, (2,), first))
        self.assertEqual(self.grid.elite_list(), [better])

    def test_elites_in_cell_order_and_the_best(self) -> None:
        big, small, middle = program(800, 1.0), program(50, 3.0), program(200, 3.0)
        for elite in (big, small, middle):
            self.grid.place(elite)
        self.assertEqual(self.grid.elite_list(), [small, middle, big])
        # On a tie, the first in cell order.
        self.assertIs(self.grid.best(), small)

    def test_remove(self) -> None:
        elite = program(100, 1.0)
        self.grid.place(elite)
        self.grid.remove(elite.id)
        self.assertEqual(self.grid.elite_list(), [])
        self.assertIsNone(self.grid.best())


if __name__ == "__main__":
    unittest.main()
