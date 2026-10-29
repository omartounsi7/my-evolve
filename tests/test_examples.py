"""Checks the example problems and the tests' toy problem, through their evaluation files."""

import runpy
import unittest
from pathlib import Path
from typing import Any

import numpy as np

# The top folder of the repository, found relative to this test file
REPOSITORY_FOLDER = Path(__file__).parent.parent
CIRCLE_PACKING_FOLDER = REPOSITORY_FOLDER / "examples" / "circle_packing"
TOY_FOLDER = Path(__file__).parent / "toy"


def run_program(path: Path) -> dict[str, Any]:
    """Run a program's file and return the names it defines, as the evaluation receives them."""
    namespace: dict[str, Any] = {"__name__": "program"}
    exec(path.read_text(encoding="utf-8"), namespace)
    return namespace


def load_evaluate(folder: Path) -> Any:
    """Return the evaluate function of the evaluation file in a problem's folder."""
    return runpy.run_path(str(folder / "evaluation.py"))["evaluate"]


def packing_of(centers: list[list[float]], radii: list[float]) -> dict[str, Any]:
    """Return a namespace whose run_packing returns the given circles."""
    return {"run_packing": lambda: (np.array(centers), np.array(radii), sum(radii))}


class CirclePackingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluate = load_evaluate(CIRCLE_PACKING_FOLDER)

    def test_the_initial_program_scores_as_in_openevolve(self) -> None:
        """The initial program's radii add up to about 0.959, a score of 0.364."""
        score = self.evaluate(run_program(CIRCLE_PACKING_FOLDER / "initial_program.py"))
        self.assertAlmostEqual(score * 2.635, 0.9598, places=3)
        self.assertAlmostEqual(score, 0.3642, places=3)

    def test_overlapping_circles_are_refused(self) -> None:
        """Two circles closer than the sum of their radii break the rules."""
        centers = [[0.1 + 0.03 * i, 0.5] for i in range(26)]
        with self.assertRaisesRegex(ValueError, "circles 0 and 1 overlap"):
            self.evaluate(packing_of(centers, [0.02] * 26))

    def test_a_circle_outside_the_square_is_refused(self) -> None:
        """A circle sticking out of the unit square breaks the rules."""
        centers = [[0.5, 0.5]] + [[0.03 * i, 0.9] for i in range(1, 26)]
        radii = [0.6] + [0.0] * 25
        with self.assertRaisesRegex(ValueError, "circle 0 .* leaves the unit square"):
            self.evaluate(packing_of(centers, radii))

    def test_the_wrong_number_of_circles_is_refused(self) -> None:
        """A packing must have exactly 26 circles."""
        with self.assertRaisesRegex(ValueError, "expected centers of shape"):
            self.evaluate(packing_of([[0.5, 0.5]], [0.1]))


class ToyProblemTest(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluate = load_evaluate(TOY_FOLDER)

    def test_the_initial_program_scores_its_number(self) -> None:
        """The toy initial program returns 1, its score."""
        self.assertEqual(self.evaluate(run_program(TOY_FOLDER / "initial_program.py")), 1.0)

    def test_a_number_above_the_limit_is_refused(self) -> None:
        """Returning more than 10 breaks the toy problem's rule."""
        with self.assertRaisesRegex(ValueError, "more than 10"):
            self.evaluate({"solve": lambda: 11})


if __name__ == "__main__":
    unittest.main()
