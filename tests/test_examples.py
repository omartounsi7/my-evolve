"""Checks the example problems and the tests' toy problem, through their evaluation files."""

import os
import runpy
import tempfile
import unittest
from pathlib import Path
from typing import Any

import numpy as np

from my_evolve.evaluation_api import InvalidProgram

# The top folder of the repository, found relative to this test file
REPOSITORY_FOLDER = Path(__file__).parent.parent
CIRCLE_PACKING_FOLDER = REPOSITORY_FOLDER / "examples" / "circle_packing"
TOY_FOLDER = Path(__file__).parent / "toy"


def run_program(path: Path) -> dict[str, Any]:
    """Run a program's file and return the names it defines, as the evaluation receives them."""
    namespace: dict[str, Any] = {"__name__": "program"}
    exec(path.read_text(encoding="utf-8"), namespace)
    return namespace


def load_evaluate(folder: Path, name: str = "evaluate") -> Any:
    """Return a function of the evaluation file in a problem's folder: evaluate by default."""
    return runpy.run_path(str(folder / "evaluation.py"))[name]


def packing_of(centers: list[list[float]], radii: list[float]) -> dict[str, Any]:
    """Return a namespace whose run_packing returns the given circles."""
    return {"run_packing": lambda: (np.array(centers), np.array(radii), sum(radii))}


class CirclePackingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluate = load_evaluate(CIRCLE_PACKING_FOLDER, "evaluate_stage1")

    def test_the_initial_program_scores_as_in_openevolve(self) -> None:
        """The initial program's radii add up to about 0.959, a score of 0.364."""
        score = self.evaluate(run_program(CIRCLE_PACKING_FOLDER / "initial_program.py")).score
        self.assertAlmostEqual(score * 2.635, 0.9598, places=3)
        self.assertAlmostEqual(score, 0.3642, places=3)

    def test_overlapping_circles_are_refused(self) -> None:
        """Two circles closer than the sum of their radii break the rules."""
        centers = [[0.1 + 0.03 * i, 0.5] for i in range(26)]
        with self.assertRaisesRegex(InvalidProgram, "circles 0 and 1 overlap"):
            self.evaluate(packing_of(centers, [0.02] * 26))

    def test_a_circle_outside_the_square_is_refused(self) -> None:
        """A circle sticking out of the unit square breaks the rules."""
        centers = [[0.5, 0.5]] + [[0.03 * i, 0.9] for i in range(1, 26)]
        radii = [0.6] + [0.0] * 25
        with self.assertRaisesRegex(InvalidProgram, "circle 0 .* is outside the unit square"):
            self.evaluate(packing_of(centers, radii))

    def test_the_wrong_number_of_circles_is_refused(self) -> None:
        """A packing must have exactly 26 circles."""
        with self.assertRaisesRegex(InvalidProgram, "expected centers of shape"):
            self.evaluate(packing_of([[0.5, 0.5]], [0.1]))


class CirclePackingFeatureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluate = load_evaluate(CIRCLE_PACKING_FOLDER, "evaluate_stage1")

    def test_the_initial_programs_features(self) -> None:
        """The spread of the radii, and their correlation with the distance to the centre."""
        namespace = run_program(CIRCLE_PACKING_FOLDER / "initial_program.py")
        centers, radii, _ = namespace["run_packing"]()
        features = self.evaluate(namespace).features
        self.assertAlmostEqual(features["radii_spread"], np.std(radii) / np.mean(radii))
        distances = np.linalg.norm(centers - 0.5, axis=1)
        self.assertAlmostEqual(
            features["radius_centre_correlation"], np.corrcoef(radii, distances)[0, 1]
        )
        # Its big circle is in the middle, and smaller ones around it.
        self.assertLess(features["radius_centre_correlation"], 0.0)

    def test_equal_circles_have_no_spread_and_no_correlation(self) -> None:
        """A 5 x 5 grid of equal circles, and a 26th of radius 0 in a corner."""
        centers = [[0.1 + 0.2 * i, 0.1 + 0.2 * j] for i in range(5) for j in range(5)]
        equal = packing_of(centers + [[0.5, 0.5]], [0.0] * 26)
        self.assertEqual(
            self.evaluate(equal).features, {"radii_spread": 0.0, "radius_centre_correlation": 0.0}
        )


class CirclePackingDrawingTest(unittest.TestCase):
    def test_stage_1_keeps_the_packing_and_visualize_draws_it(self) -> None:
        namespace = run_program(CIRCLE_PACKING_FOLDER / "initial_program.py")
        output_data = load_evaluate(CIRCLE_PACKING_FOLDER, "evaluate_stage1")(namespace).output_data
        self.assertEqual((len(output_data["centers"]), len(output_data["radii"])), (26, 26))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "packing.png"
            load_evaluate(CIRCLE_PACKING_FOLDER, "visualize")(output_data, path)
            self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")


PRECISE_FOLDER = REPOSITORY_FOLDER / "examples" / "circle_packing_precise"


def grid_packing(grow: float = 0.0) -> dict[str, Any]:
    """Return a namespace whose run_packing gives 25 circles of radius 0.1 on a 5 x 5 grid,
    each touching its neighbours, and a 26th of radius 0; circle 12, in the middle, grown
    by grow."""
    centers = [[0.1 + 0.2 * i, 0.1 + 0.2 * j] for i in range(5) for j in range(5)] + [[0, 0]]
    radii = [0.1] * 25 + [0.0]
    radii[12] += grow
    return packing_of(centers, radii)


class PreciseCirclePackingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluate = load_evaluate(PRECISE_FOLDER)
        self.best = runpy.run_path(str(PRECISE_FOLDER / "evaluation.py"))["BEST_KNOWN_SUM"]

    def test_a_legal_packing_scores_its_sum(self) -> None:
        result = self.evaluate(grid_packing())
        self.assertAlmostEqual(result.metrics["sum_radii"], 2.5, places=12)
        self.assertAlmostEqual(result.score, 2.5 / self.best, places=12)
        # Touching circles overlap by round-off, about 1e-17: that is not a violation to fix.
        self.assertIn("within floating-point round-off", result.feedback)

    def test_a_violation_is_shrunk_away_from_every_radius(self) -> None:
        """Growing a circle by 5e-7 overlaps its neighbours by 5e-7: each of the 25 circles
        loses it (the 26th, of radius 0, has nothing to lose)."""
        result = self.evaluate(grid_packing(grow=5e-7))
        self.assertAlmostEqual(result.metrics["worst_violation"], 5e-7, places=15)
        self.assertAlmostEqual(result.metrics["sum_radii"], 2.5 + 5e-7 - 25 * 5e-7, places=12)
        self.assertIn("Every radius was shrunk", result.feedback)
        self.assertLess(result.score, self.evaluate(grid_packing()).score)

    def test_a_violation_above_1e_6_is_illegal(self) -> None:
        with self.assertRaisesRegex(InvalidProgram, "overlap by 2.000e-06"):
            self.evaluate(grid_packing(grow=2e-6))

    def test_the_initial_program_is_the_best_found(self) -> None:
        """Its legal sum is the reference, 2.6359830849 (run on the host: about 45 s)."""
        if not os.environ.get("MY_EVOLVE_SLOW_TESTS"):
            self.skipTest("slow; set MY_EVOLVE_SLOW_TESTS=1")
        result = self.evaluate(run_program(PRECISE_FOLDER / "initial_program.py"))
        self.assertAlmostEqual(result.metrics["sum_radii"], self.best, places=9)


class ToyProblemTest(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluate = load_evaluate(TOY_FOLDER)

    def test_the_initial_program_scores_its_number(self) -> None:
        """The toy initial program returns 1, its score."""
        self.assertEqual(self.evaluate(run_program(TOY_FOLDER / "initial_program.py")).score, 1.0)

    def test_a_number_above_the_limit_is_refused(self) -> None:
        """Returning more than 10 breaks the toy problem's rule."""
        with self.assertRaisesRegex(InvalidProgram, "more than 10"):
            self.evaluate({"solve": lambda: 11})


if __name__ == "__main__":
    unittest.main()
