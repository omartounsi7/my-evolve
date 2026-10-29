"""Checks that the evaluator scores programs through the sandbox, giving each outcome a status."""

import sys
import tempfile
import time
import unittest
from pathlib import Path

from my_evolve.evaluator import EvaluationFileError, Evaluator
from my_evolve.program import Result, Status
from my_evolve.sandbox import LocalSandbox, Sandbox

REPOSITORY_FOLDER = Path(__file__).parent.parent
TOY_FOLDER = Path(__file__).parent / "toy"
# Long enough for any test program: the tests of time limits set their own
STAGE_TIME_LIMIT = 30.0
CIRCLE_PACKING_FOLDER = REPOSITORY_FOLDER / "examples" / "circle_packing"


def evaluate_with(evaluation_code: str, program_code: str) -> Result:
    """Score a program with an evaluation file written for the test."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "evaluation.py"
        path.write_text(evaluation_code)
        return Evaluator(path, LocalSandbox(), STAGE_TIME_LIMIT).evaluate(program_code)


class EvaluatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = Evaluator(TOY_FOLDER / "evaluation.py", LocalSandbox(), STAGE_TIME_LIMIT)

    def test_a_working_program_gets_its_score(self) -> None:
        """The toy initial program scores the number it returns."""
        result = self.evaluator.evaluate((TOY_FOLDER / "initial_program.py").read_text())
        self.assertEqual((result.status, result.score, result.error), (Status.OK, 1.0, None))

    def test_the_circle_packing_initial_program_scores(self) -> None:
        """The example's initial program scores 0.364 through the sandbox: numpy arrays travel."""
        evaluator = Evaluator(
            CIRCLE_PACKING_FOLDER / "evaluation.py", LocalSandbox(), STAGE_TIME_LIMIT
        )
        result = evaluator.evaluate((CIRCLE_PACKING_FOLDER / "initial_program.py").read_text())
        self.assertEqual(result.status, Status.OK, result.error)
        self.assertAlmostEqual(result.score or 0.0, 0.3642, places=3)

    def test_a_failing_program_is_failed(self) -> None:
        """When the program fails, while loading or in a function, its status is failed."""
        cases = {
            "def solve(:\n": "SyntaxError",
            "raise RuntimeError('boom')\n": "RuntimeError: boom",
            "import sys\nsys.exit(3)\n": "SystemExit: 3",
            "def solve():\n    return 1 / 0\n": "ZeroDivisionError: division by zero",
            "x = 1\n": "the program defines no 'solve'",
            "import os\ndef solve():\n    os._exit(1)\n": "the program's process ended",
        }
        for code, error in cases.items():
            with self.subTest(error=error):
                result = self.evaluator.evaluate(code)
                self.assertEqual(result.status, Status.FAILED)
                self.assertIsNone(result.score)
                self.assertIn(error, (result.error or "").splitlines()[0])

    def test_a_failure_shows_where_in_the_program(self) -> None:
        """The error is followed by a traceback showing the program's line."""
        result = self.evaluator.evaluate("def solve():\n    return [][1]\n")
        self.assertTrue((result.error or "").startswith("IndexError: list index out of range\n"))
        self.assertIn('File "<program>", line 2, in solve\n    return [][1]', result.error or "")

    def test_an_illegal_answer_is_invalid(self) -> None:
        """InvalidProgram from the evaluation file gives the status invalid, with the reason."""
        result = self.evaluator.evaluate("def solve():\n    return 11\n")
        self.assertEqual(result.status, Status.INVALID)
        self.assertEqual(result.error, "solve() returned 11, more than 10.0")

    def test_the_main_part_of_a_program_does_not_run(self) -> None:
        """A program's `if __name__ == "__main__":` part is not run."""
        code = "def solve():\n    return 2\n\nif __name__ == '__main__':\n    raise SystemExit\n"
        self.assertEqual(self.evaluator.evaluate(code).score, 2.0)

    def test_the_evaluation_file_sees_plain_data_only(self) -> None:
        """Globals arrive as values, functions as stand-ins; modules are not reachable."""
        evaluation = (
            "def evaluate(namespace):\n"
            "    assert 'np' in namespace and 'missing' not in namespace\n"
            "    return namespace['solve'](namespace['N'])\n"
        )
        program = "import numpy as np\nN = 4\ndef solve(n):\n    return float(np.float64(n))\n"
        self.assertEqual(evaluate_with(evaluation, program).score, 4.0)
        evaluation = "def evaluate(namespace):\n    return namespace['np'].pi\n"
        result = evaluate_with(evaluation, program)
        self.assertEqual(result.status, Status.FAILED)
        self.assertIn("'np' is neither a function nor plain data", result.error or "")


class ExactDataTest(unittest.TestCase):
    def test_the_evaluation_file_receives_arrays_and_tuples(self) -> None:
        """A program's (array, tuple) answer reaches the evaluation file as it was returned."""
        evaluation = (
            "import numpy as np\n"
            "def evaluate(namespace):\n"
            "    centers, pair = namespace['f']()\n"
            "    assert isinstance(centers, np.ndarray) and centers.shape == (26, 2)\n"
            "    assert isinstance(pair, tuple)\n"
            "    return float(centers.sum()) + sum(pair)\n"
        )
        program = "import numpy as np\ndef f():\n    return np.ones((26, 2)), (1, 2)\n"
        self.assertEqual(evaluate_with(evaluation, program).score, 55.0)


class TimeoutTest(unittest.TestCase):
    def test_a_program_that_never_returns_times_out(self) -> None:
        """A function that never returns is stopped at the time limit: status timeout."""
        evaluator = Evaluator(TOY_FOLDER / "evaluation.py", LocalSandbox(), stage_time_limit=1.0)
        started = time.monotonic()
        result = evaluator.evaluate("def solve():\n    while True:\n        pass\n")
        self.assertLess(time.monotonic() - started, 5.0)
        self.assertEqual(result.status, Status.TIMEOUT)
        self.assertEqual(result.error, "the evaluation ran over its time limit of 1 s")

    def test_loading_counts_toward_the_limit(self) -> None:
        """A program that never finishes loading times out too."""
        evaluator = Evaluator(TOY_FOLDER / "evaluation.py", LocalSandbox(), stage_time_limit=1.0)
        result = evaluator.evaluate("import time\ntime.sleep(60)\n")
        self.assertEqual(result.status, Status.TIMEOUT)

    def test_an_evaluation_file_cannot_hide_a_timeout(self) -> None:
        """Even if the evaluation file catches every exception, the status is timeout."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "evaluation.py"
            path.write_text(
                "def evaluate(namespace):\n"
                "    try:\n        return namespace['solve']()\n"
                "    except Exception:\n        return 0.0\n"
            )
            evaluator = Evaluator(path, LocalSandbox(), stage_time_limit=1.0)
            result = evaluator.evaluate("def solve():\n    while True:\n        pass\n")
            self.assertEqual(result.status, Status.TIMEOUT)


class ErrorStatusTest(unittest.TestCase):
    def test_a_mistake_in_the_evaluation_file_is_an_error(self) -> None:
        """The evaluation file raising is not the program's fault: status error."""
        result = evaluate_with("def evaluate(namespace):\n    return {}['k']\n", "x = 1\n")
        self.assertEqual(result.status, Status.ERROR)
        self.assertTrue((result.error or "").startswith("evaluator: KeyError: 'k'"))

    def test_scores_that_are_not_finite_numbers_are_errors(self) -> None:
        """evaluate must return a finite number: not a bool, text, or infinity."""
        for score, error in [
            ("True", "must be a number, got bool"),
            ("'high'", "must be a number, got str"),
            ("float('inf')", "must be a finite number"),
        ]:
            with self.subTest(score=score):
                result = evaluate_with(f"def evaluate(namespace):\n    return {score}\n", "x = 1\n")
                self.assertEqual(result.status, Status.ERROR)
                self.assertIn(error, result.error or "")

    def test_a_sandbox_that_cannot_start_is_an_error(self) -> None:
        """When the worker cannot be started, the program is not to blame."""

        class BrokenSandbox(Sandbox):
            def command(self) -> list[str]:
                return ["/no/such/python", "-m", "my_evolve.sandbox_worker"]

        evaluator = Evaluator(TOY_FOLDER / "evaluation.py", BrokenSandbox(), STAGE_TIME_LIMIT)
        result = evaluator.evaluate("def solve():\n    return 1\n")
        self.assertEqual(result.status, Status.ERROR)
        self.assertIn("sandbox: cannot start the worker", result.error or "")


class EvaluationFileTest(unittest.TestCase):
    def test_a_file_without_evaluate_is_refused(self) -> None:
        """An evaluation file must define evaluate."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "evaluation.py"
            path.write_text("def score(namespace):\n    return 1\n")
            with self.assertRaisesRegex(EvaluationFileError, "must define a function"):
                Evaluator(path, LocalSandbox(), STAGE_TIME_LIMIT)
            with self.assertRaisesRegex(EvaluationFileError, "no such evaluation file"):
                Evaluator(Path(folder) / "missing.py", LocalSandbox(), STAGE_TIME_LIMIT)

    def test_helper_files_are_imported_then_forgotten(self) -> None:
        """An evaluation file may import a helper next to it, which is forgotten afterwards."""
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "my_evolve_test_helper.py").write_text("BONUS = 5\n")
            path = Path(folder) / "evaluation.py"
            path.write_text(
                "from my_evolve_test_helper import BONUS\n\n"
                "def evaluate(namespace):\n    return namespace['solve']() + BONUS\n"
            )
            evaluator = Evaluator(path, LocalSandbox(), STAGE_TIME_LIMIT)
            self.assertNotIn("my_evolve_test_helper", sys.modules)
            self.assertEqual(evaluator.evaluate("def solve():\n    return 1\n").score, 6.0)


if __name__ == "__main__":
    unittest.main()
