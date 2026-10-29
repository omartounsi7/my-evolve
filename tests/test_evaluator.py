"""Checks that the evaluator scores working programs and turns every failure into an error."""

import sys
import tempfile
import unittest
from pathlib import Path

from my_evolve.evaluator import EvaluationFileError, Evaluator
from my_evolve.program import Status

REPOSITORY_FOLDER = Path(__file__).parent.parent
TOY_FOLDER = Path(__file__).parent / "toy"
CIRCLE_PACKING_FOLDER = REPOSITORY_FOLDER / "examples" / "circle_packing"


class EvaluatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = Evaluator(TOY_FOLDER / "evaluation.py")

    def test_a_working_program_gets_its_score(self) -> None:
        """The toy initial program scores the number it returns."""
        result = self.evaluator.evaluate((TOY_FOLDER / "initial_program.py").read_text())
        self.assertEqual(result.status, Status.OK)
        self.assertEqual(result.score, 1.0)
        self.assertIsNone(result.error)

    def test_the_circle_packing_initial_program_scores(self) -> None:
        """The example's initial program scores 0.364 through the evaluator."""
        evaluator = Evaluator(CIRCLE_PACKING_FOLDER / "evaluation.py")
        result = evaluator.evaluate((CIRCLE_PACKING_FOLDER / "initial_program.py").read_text())
        self.assertIsNotNone(result.score)
        self.assertAlmostEqual(result.score or 0.0, 0.3642, places=3)

    def test_failures_become_errors(self) -> None:
        """Whatever goes wrong, the program fails: no score, and an error saying what."""
        cases = {
            "def solve(:\n": "SyntaxError",
            "raise RuntimeError('boom')\n": "RuntimeError: boom",
            "def solve():\n    return 1 / 0\n": "ZeroDivisionError: division by zero",
            "x = 1\n": "KeyError: 'solve'",
            "import sys\nsys.exit(3)\n": "SystemExit: 3",
        }
        for code, error in cases.items():
            with self.subTest(error=error):
                result = self.evaluator.evaluate(code)
                self.assertEqual(result.status, Status.FAILED)
                self.assertIsNone(result.score)
                self.assertIn(error, result.error or "")

    def test_an_illegal_answer_is_invalid(self) -> None:
        """InvalidProgram from the evaluation file gives the status invalid, with the reason."""
        result = self.evaluator.evaluate("def solve():\n    return 11\n")
        self.assertEqual(result.status, Status.INVALID)
        self.assertIsNone(result.score)
        self.assertEqual(result.error, "solve() returned 11, more than 10.0")

    def test_the_main_part_of_a_program_does_not_run(self) -> None:
        """A program's `if __name__ == "__main__":` part is not run."""
        code = "def solve():\n    return 2\n\nif __name__ == '__main__':\n    raise SystemExit\n"
        self.assertEqual(self.evaluator.evaluate(code).score, 2.0)


class ScoreCheckTest(unittest.TestCase):
    def test_scores_that_are_not_finite_numbers_are_refused(self) -> None:
        """evaluate must return a finite number: not a bool, text, or infinity."""
        with tempfile.TemporaryDirectory() as folder:
            for score, error in [
                ("True", "must be a number, got bool"),
                ("'high'", "must be a number, got str"),
                ("float('inf')", "must be a finite number"),
            ]:
                path = Path(folder) / "evaluation.py"
                path.write_text(f"def evaluate(namespace):\n    return {score}\n")
                with self.subTest(score=score):
                    result = Evaluator(path).evaluate("x = 1\n")
                    self.assertIsNone(result.score)
                    self.assertIn(error, result.error or "")


class EvaluationFileTest(unittest.TestCase):
    def test_a_file_without_evaluate_is_refused(self) -> None:
        """An evaluation file must define evaluate."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "evaluation.py"
            path.write_text("def score(namespace):\n    return 1\n")
            with self.assertRaisesRegex(EvaluationFileError, "must define a function"):
                Evaluator(path)
            with self.assertRaisesRegex(EvaluationFileError, "no such evaluation file"):
                Evaluator(Path(folder) / "missing.py")

    def test_helper_files_are_imported_then_forgotten(self) -> None:
        """An evaluation file may import a helper next to it, which is forgotten afterwards."""
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "my_evolve_test_helper.py").write_text("BONUS = 5\n")
            path = Path(folder) / "evaluation.py"
            path.write_text(
                "from my_evolve_test_helper import BONUS\n\n"
                "def evaluate(namespace):\n    return namespace['solve']() + BONUS\n"
            )
            evaluator = Evaluator(path)
            self.assertNotIn("my_evolve_test_helper", sys.modules)
            self.assertEqual(evaluator.evaluate("def solve():\n    return 1\n").score, 6.0)


if __name__ == "__main__":
    unittest.main()
