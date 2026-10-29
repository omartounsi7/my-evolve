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
    """Score a program with an evaluation file written for the test (StageResult imported)."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "evaluation.py"
        path.write_text("from my_evolve.evaluation_api import StageResult\n" + evaluation_code)
        return Evaluator(path, LocalSandbox(), STAGE_TIME_LIMIT).evaluate(program_code)


class EvaluatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = Evaluator(TOY_FOLDER / "evaluation.py", LocalSandbox(), STAGE_TIME_LIMIT)

    def test_a_working_program_gets_its_score(self) -> None:
        """The toy initial program scores the number it returns, with feedback and a duration."""
        result = self.evaluator.evaluate((TOY_FOLDER / "initial_program.py").read_text())
        self.assertEqual((result.status, result.score, result.error), (Status.OK, 1.0, None))
        self.assertEqual(result.feedback, "solve() returned 1.0.")
        self.assertGreater(result.duration, 0.0)

    def test_metrics_and_feedback_reach_the_result(self) -> None:
        """The circle-packing evaluation reports the sum of radii and describes the packing."""
        evaluator = Evaluator(CIRCLE_PACKING_FOLDER / "evaluation.py", LocalSandbox(), 30.0)
        result = evaluator.evaluate((CIRCLE_PACKING_FOLDER / "initial_program.py").read_text())
        self.assertAlmostEqual(result.metrics["sum_radii"], 0.9598, places=3)
        self.assertIn("Valid packing", result.feedback or "")

    def test_an_invalid_program_keeps_the_feedback_given(self) -> None:
        """InvalidProgram may carry feedback beside its reason."""
        evaluation = (
            "from my_evolve.evaluation_api import InvalidProgram\n"
            "def evaluate(namespace):\n"
            "    raise InvalidProgram('too big', feedback='Try a smaller number.')\n"
        )
        result = evaluate_with(evaluation, "x = 1\n")
        self.assertEqual((result.status, result.error), (Status.INVALID, "too big"))
        self.assertEqual(result.feedback, "Try a smaller number.")

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
            "    return StageResult(namespace['solve'](namespace['N']))\n"
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
            "    return StageResult(float(centers.sum()) + sum(pair))\n"
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
        self.assertEqual(result.error, "the stage ran over its time limit of 1 s")

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


# The program the cascade tests evaluate: f counts its calls since the program was loaded
COUNTING_PROGRAM = """\
import time

calls = []


def f(seconds=0.0):
    time.sleep(seconds)
    calls.append(1)
    return len(calls)


def boom():
    raise RuntimeError("stage 2 broke the program")


def spin():
    while True:
        pass
"""


def cascade(stages: str, thresholds: list[float], limit: float = 30.0) -> Evaluator:
    """Return an evaluator for an evaluation file holding these stage functions."""
    folder = Path(tempfile.mkdtemp())
    path = folder / "evaluation.py"
    path.write_text("from my_evolve.evaluation_api import InvalidProgram, StageResult\n\n" + stages)
    return Evaluator(path, LocalSandbox(), limit, thresholds)


class CascadeTest(unittest.TestCase):
    def test_every_stage_passed(self) -> None:
        """Stage 2's score replaces stage 1's, metrics are merged, feedback gathered."""
        evaluator = cascade(
            "def evaluate_stage1(namespace):\n"
            "    return StageResult(0.6, {'a': 1.0, 'b': 1.0}, 'first look')\n"
            "def evaluate_stage2(namespace):\n"
            "    return StageResult(0.9, {'b': 2.0, 'c': 3.0}, 'full check')\n",
            [0.5],
        )
        result = evaluator.evaluate(COUNTING_PROGRAM)
        self.assertEqual((result.status, result.score, result.stage_reached), (Status.OK, 0.9, 2))
        self.assertEqual(result.metrics, {"a": 1.0, "b": 2.0, "c": 3.0})
        self.assertEqual(result.feedback, "first look\n\nfull check")

    def test_a_score_below_the_threshold_ends_the_cascade(self) -> None:
        """Stage 2 does not run when stage 1 scores below its threshold."""
        evaluator = cascade(
            "def evaluate_stage1(namespace):\n    return StageResult(0.4)\n"
            "def evaluate_stage2(namespace):\n    raise AssertionError('must not run')\n",
            [0.5],
        )
        result = evaluator.evaluate(COUNTING_PROGRAM)
        self.assertEqual((result.status, result.score, result.stage_reached), (Status.OK, 0.4, 1))

    def test_each_stage_loads_the_program_afresh(self) -> None:
        """A fresh session per stage: the program's state does not carry over."""
        evaluator = cascade(
            "def evaluate_stage1(namespace):\n    return StageResult(namespace['f']())\n"
            "def evaluate_stage2(namespace):\n    return StageResult(namespace['f']() * 10)\n",
            [1.0],
        )
        self.assertEqual(evaluator.evaluate(COUNTING_PROGRAM).score, 10.0)

    def test_a_later_failure_keeps_the_earlier_result(self) -> None:
        """A program failing or timing out at stage 2 stays ok, with stage 1's score."""
        for function, error in [
            ("boom", "stage 2: RuntimeError"),
            ("spin", "stage 2: the stage ran"),
        ]:
            with self.subTest(function=function):
                evaluator = cascade(
                    "def evaluate_stage1(namespace):\n    return StageResult(0.7, {'a': 1.0})\n"
                    "def evaluate_stage2(namespace):\n"
                    f"    return StageResult(namespace['{function}']())\n",
                    [0.5],
                    limit=1.0,
                )
                result = evaluator.evaluate(COUNTING_PROGRAM)
                self.assertEqual((result.status, result.score), (Status.OK, 0.7))
                self.assertEqual((result.stage_reached, result.metrics), (1, {"a": 1.0}))
                self.assertTrue((result.error or "").startswith(error))

    def test_an_illegal_answer_at_any_stage_is_invalid(self) -> None:
        """InvalidProgram at stage 2 makes the whole program invalid."""
        evaluator = cascade(
            "def evaluate_stage1(namespace):\n    return StageResult(0.7, feedback='looks fine')\n"
            "def evaluate_stage2(namespace):\n    raise InvalidProgram('circles overlap')\n",
            [0.5],
        )
        result = evaluator.evaluate(COUNTING_PROGRAM)
        self.assertEqual((result.status, result.score), (Status.INVALID, None))
        self.assertEqual((result.error, result.feedback), ("circles overlap", "looks fine"))

    def test_a_mistake_at_a_later_stage_is_an_error(self) -> None:
        """The evaluation file failing at stage 2 is not the program's fault: error."""
        evaluator = cascade(
            "def evaluate_stage1(namespace):\n    return StageResult(0.7)\n"
            "def evaluate_stage2(namespace):\n    return StageResult(1 / 0)\n",
            [0.5],
        )
        self.assertEqual(evaluator.evaluate(COUNTING_PROGRAM).status, Status.ERROR)

    def test_each_stage_has_its_own_time_limit(self) -> None:
        """Two stages of 0.7 s each pass with a limit of 1.5 s per stage."""
        evaluator = cascade(
            "def evaluate_stage1(namespace):\n    return StageResult(namespace['f'](0.7))\n"
            "def evaluate_stage2(namespace):\n    return StageResult(namespace['f'](0.7))\n",
            [0.5],
            limit=1.5,
        )
        result = evaluator.evaluate(COUNTING_PROGRAM)
        self.assertEqual((result.status, result.stage_reached), (Status.OK, 2))

    def test_the_thresholds_must_match_the_stages(self) -> None:
        """One threshold per stage after the first: fewer or more is refused."""
        stages = (
            "def evaluate_stage1(namespace):\n    return StageResult(1)\n"
            "def evaluate_stage2(namespace):\n    return StageResult(1)\n"
        )
        for thresholds in [[], [0.5, 0.75]]:
            with self.subTest(thresholds=thresholds):
                with self.assertRaisesRegex(EvaluationFileError, "needs 1 threshold"):
                    cascade(stages, thresholds)
        with self.assertRaisesRegex(EvaluationFileError, "needs 0 threshold"):
            cascade("def evaluate(namespace):\n    return StageResult(1)\n", [0.5])


class ErrorStatusTest(unittest.TestCase):
    def test_a_mistake_in_the_evaluation_file_is_an_error(self) -> None:
        """The evaluation file raising is not the program's fault: status error."""
        result = evaluate_with("def evaluate(namespace):\n    return {}['k']\n", "x = 1\n")
        self.assertEqual(result.status, Status.ERROR)
        self.assertTrue((result.error or "").startswith("evaluator: KeyError: 'k'"))

    def test_results_that_cannot_be_saved_are_errors(self) -> None:
        """evaluate must return a StageResult with a finite score, finite metrics, text feedback."""
        for outcome, error in [
            ("1.0", "evaluate must return a StageResult, got float"),
            ("StageResult(True)", "the score must be a number, got bool"),
            ("StageResult('high')", "the score must be a number, got str"),
            ("StageResult(float('inf'))", "the score must be a finite number"),
            ("StageResult(1.0, metrics={'m': float('nan')})", "the metric 'm' must be a finite"),
            ("StageResult(1.0, metrics={3: 1.0})", "the metrics must be a dictionary with text"),
            ("StageResult(1.0, feedback=3)", "the feedback must be text, got int"),
        ]:
            with self.subTest(outcome=outcome):
                evaluation = f"def evaluate(namespace):\n    return {outcome}\n"
                result = evaluate_with(evaluation, "x = 1\n")
                self.assertEqual(result.status, Status.ERROR)
                self.assertIn(error, result.error or "")

    def test_a_sandbox_that_cannot_start_is_an_error(self) -> None:
        """When the worker cannot be started, the program is not to blame."""

        class BrokenSandbox(Sandbox):
            def command(self, name: str, stage_limit: float) -> list[str]:
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
                "from my_evolve_test_helper import BONUS\n"
                "from my_evolve.evaluation_api import StageResult\n\n"
                "def evaluate(namespace):\n    return StageResult(namespace['solve']() + BONUS)\n"
            )
            evaluator = Evaluator(path, LocalSandbox(), STAGE_TIME_LIMIT)
            self.assertNotIn("my_evolve_test_helper", sys.modules)
            self.assertEqual(evaluator.evaluate("def solve():\n    return 1\n").score, 6.0)


if __name__ == "__main__":
    unittest.main()
