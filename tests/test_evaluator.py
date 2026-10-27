"""Checks the evaluator: loading evaluation files, the statuses, and the cascade's rules.

Evaluation files are written for each test in a temporary folder; programs run in
the local sandbox, so no Docker is needed.
"""

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any

from my_evolve.evaluator import EvaluationFileError, Evaluator
from my_evolve.problem import Problem
from my_evolve.program import Result, Status
from my_evolve.sandbox import LocalSandbox, Sandbox, SandboxError, SandboxSession

PROGRAM = """\
import time

CALLS = []


def answer(value=0.8):
    CALLS.append(1)
    return value


def calls():
    return len(CALLS)


def crash():
    print("crashing now")
    return [][1]


def sleep(seconds):
    time.sleep(seconds)
    return seconds
"""

HEADER = "from my_evolve.evaluation_api import *\n"


def problem_with(thresholds: tuple[float, ...] = (), stage_limit: float = 30) -> Problem:
    """Return a minimal problem with the given cascade settings."""
    return Problem.from_dict(
        {
            "name": "test",
            "description": "Return a large number.",
            "entry_functions": ["answer"],
            "evaluation": {"stage_time_limit": stage_limit, "thresholds": list(thresholds)},
            "llm": {"models": [{"name": "m", "api_base": "http://localhost:1/v1"}]},
        }
    )


class EvaluatorTestCase(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def write_evaluation(self, code: str, name: str = "evaluation.py") -> Path:
        path = self.folder / name
        path.write_text(HEADER + textwrap.dedent(code), encoding="utf-8")
        return path

    def evaluator(
        self,
        code: str,
        thresholds: tuple[float, ...] = (),
        stage_limit: float = 30,
        output_features: tuple[str, ...] = (),
        sandbox: Sandbox | None = None,
    ) -> Evaluator:
        return Evaluator(
            self.write_evaluation(code),
            problem_with(thresholds, stage_limit),
            sandbox or LocalSandbox(),
            output_features,
        )

    def evaluate(self, code: str, program: str = PROGRAM, **settings: Any) -> Result:
        return self.evaluator(code, **settings).evaluate(program)


class TestLoading(EvaluatorTestCase):
    def test_single_evaluate_is_one_stage(self) -> None:
        evaluator = self.evaluator("def evaluate(namespace):\n    return StageResult(1.0)\n")
        self.assertEqual(len(evaluator.stages), 1)
        self.assertIsNone(evaluator.visualize)

    def test_stages_are_found_in_order_and_preferred_to_evaluate(self) -> None:
        evaluator = self.evaluator(
            """
            def evaluate(namespace):
                return StageResult(0.0)
            def evaluate_stage1(namespace):
                return StageResult(1.0)
            def evaluate_stage2(namespace):
                return StageResult(2.0)
            def evaluate_stage4(namespace):
                return StageResult(4.0)
            def visualize(output_data, path):
                pass
            """,
            thresholds=(0.5,),
        )
        self.assertEqual(
            [stage.__name__ for stage in evaluator.stages], ["evaluate_stage1", "evaluate_stage2"]
        )
        self.assertIsNotNone(evaluator.visualize)

    def test_file_without_a_stage_is_refused(self) -> None:
        with self.assertRaisesRegex(EvaluationFileError, "must define evaluate"):
            self.evaluator("def score(namespace):\n    return 1.0\n")

    def test_thresholds_must_match_the_stages(self) -> None:
        two_stages = (
            "def evaluate_stage1(namespace):\n    return StageResult(1.0)\n"
            "def evaluate_stage2(namespace):\n    return StageResult(2.0)\n"
        )
        for thresholds in ((), (0.5, 0.75)):
            with self.subTest(thresholds=thresholds):
                with self.assertRaisesRegex(EvaluationFileError, "needs 1 threshold"):
                    self.evaluator(two_stages, thresholds=thresholds)

    def test_missing_file_is_refused(self) -> None:
        with self.assertRaisesRegex(EvaluationFileError, "no such file"):
            Evaluator(self.folder / "absent.py", problem_with(), LocalSandbox())

    def test_file_raising_while_loading_is_refused(self) -> None:
        with self.assertRaisesRegex(EvaluationFileError, "ZeroDivisionError"):
            self.evaluator("x = 1 / 0\n")

    def test_helper_next_to_the_file_is_imported_then_forgotten(self) -> None:
        (self.folder / "my_evolve_test_helper.py").write_text("BONUS = 0.25\n", encoding="utf-8")
        evaluator = self.evaluator(
            """
            from my_evolve_test_helper import BONUS
            def evaluate(namespace):
                return StageResult(namespace["answer"]() + BONUS)
            """
        )
        self.assertNotIn("my_evolve_test_helper", sys.modules)
        self.assertEqual(evaluator.evaluate(PROGRAM).score, 1.05)


class TestStatuses(EvaluatorTestCase):
    def test_working_program_is_ok_with_everything_the_stage_gave(self) -> None:
        result = self.evaluate(
            """
            def evaluate(namespace):
                value = namespace["answer"]()
                return StageResult(
                    score=value,
                    metrics={"value": value, "calls": 1},
                    features={"spread": 0.25},
                    feedback="All good.",
                    output_data={"values": [value]},
                )
            """
        )
        self.assertEqual(result.status, Status.OK)
        self.assertEqual(result.score, 0.8)
        self.assertEqual(result.metrics, {"value": 0.8, "calls": 1.0})
        self.assertEqual(result.features, {"spread": 0.25})
        self.assertEqual(result.feedback, "All good.")
        self.assertEqual(result.output_data, {"values": [0.8]})
        self.assertEqual(result.stage_reached, 1)
        self.assertIsNone(result.error)
        self.assertGreater(result.duration, 0)

    def test_program_failing_to_load_is_failed(self) -> None:
        result = self.evaluate(
            "def evaluate(namespace):\n    return StageResult(1.0)\n",
            program="import package_that_does_not_exist\n",
        )
        self.assertEqual(result.status, Status.FAILED)
        self.assertIn("ModuleNotFoundError", str(result.error))
        self.assertIsNone(result.score)

    def test_program_raising_in_a_call_is_failed_with_its_traceback_and_prints(self) -> None:
        result = self.evaluate(
            'def evaluate(namespace):\n    return StageResult(namespace["crash"]())\n'
        )
        self.assertEqual(result.status, Status.FAILED)
        error = str(result.error)
        self.assertTrue(error.startswith("IndexError: list index out of range"))
        self.assertIn("in crash", error)
        self.assertIn("crashing now", error)

    def test_missing_entry_function_at_run_time_is_failed(self) -> None:
        result = self.evaluate(
            'def evaluate(namespace):\n    return StageResult(namespace["run_packing"]())\n'
        )
        self.assertEqual(result.status, Status.FAILED)
        self.assertIn("defines no name 'run_packing'", str(result.error))

    def test_stage_running_out_of_time_is_timeout(self) -> None:
        result = self.evaluate(
            'def evaluate(namespace):\n    return StageResult(namespace["sleep"](30))\n',
            stage_limit=1,
        )
        self.assertEqual(result.status, Status.TIMEOUT)
        self.assertIn("ran out of time", str(result.error))

    def test_call_timeout_not_handled_by_the_evaluator_is_timeout(self) -> None:
        result = self.evaluate(
            """
            def evaluate(namespace):
                return StageResult(call_with_timeout(namespace["sleep"], 0.5, 30))
            """
        )
        self.assertEqual(result.status, Status.TIMEOUT)
        self.assertIn("ran over its time limit", str(result.error))

    def test_call_timeout_handled_by_the_evaluator_is_its_decision(self) -> None:
        result = self.evaluate(
            """
            def evaluate(namespace):
                try:
                    call_with_timeout(namespace["sleep"], 0.5, 30)
                    slow = 0.0
                except CallTimeout:
                    slow = 1.0
                return StageResult(namespace["answer"]() - slow * 0.5)
            """
        )
        self.assertEqual(result.status, Status.OK)
        self.assertAlmostEqual(result.score or 0.0, 0.3)

    def test_illegal_answer_is_invalid_with_its_reason(self) -> None:
        result = self.evaluate(
            """
            def evaluate(namespace):
                raise InvalidProgram("circles 3 and 7 overlap", feedback="Check the radii.")
            """
        )
        self.assertEqual(result.status, Status.INVALID)
        self.assertEqual(result.error, "circles 3 and 7 overlap")
        self.assertEqual(result.feedback, "Check the radii.")

    def test_evaluation_file_raising_is_an_error_not_the_programs_fault(self) -> None:
        result = self.evaluate(
            "def evaluate(namespace):\n    raise ValueError('bug in the evaluator')\n"
        )
        self.assertEqual(result.status, Status.ERROR)
        self.assertTrue(str(result.error).startswith("evaluator:"))
        self.assertIn("bug in the evaluator", str(result.error))

    def test_sandbox_failing_is_an_error(self) -> None:
        class BrokenSandbox(LocalSandbox):
            def start(self, code: str, stage_limit: float) -> SandboxSession:
                raise SandboxError("Docker is not running")

        result = self.evaluate(
            "def evaluate(namespace):\n    return StageResult(1.0)\n", sandbox=BrokenSandbox()
        )
        self.assertEqual(result.status, Status.ERROR)
        self.assertEqual(result.error, "sandbox: Docker is not running")


class TestUnusableResults(EvaluatorTestCase):
    def assert_refused(self, returned: str, message: str, **settings: Any) -> None:
        with self.subTest(returned=returned):
            result = self.evaluate(
                f"import numpy as np\ndef evaluate(namespace):\n    return {returned}\n",
                **settings,
            )
            self.assertEqual(result.status, Status.ERROR)
            self.assertIn(message, str(result.error))

    def test_results_the_framework_cannot_use_are_errors(self) -> None:
        self.assert_refused("0.5", "not a StageResult")
        self.assert_refused("StageResult(True)", "finite number")
        self.assert_refused("StageResult(float('nan'))", "finite number")
        self.assert_refused("StageResult('0.5')", "finite number")
        self.assert_refused("StageResult(1.0, metrics={'x': float('inf')})", "metrics['x']")
        self.assert_refused("StageResult(1.0, features={'x': None})", "features['x']")
        self.assert_refused("StageResult(1.0, feedback=3)", "feedback must be text")
        self.assert_refused("StageResult(1.0, output_data=np.zeros(3))", "use .tolist()")
        self.assert_refused("StageResult(1.0, output_data={'xy': (1, 2)})", "use a list")
        self.assert_refused("StageResult(1.0, output_data=[float('nan')])", "not a finite")
        self.assert_refused("StageResult(1.0, output_data={1: 'one'})", "not text")

    def test_missing_output_feature_is_an_error(self) -> None:
        self.assert_refused(
            "StageResult(1.0, features={'other': 0.1})",
            "did not give the output feature 'spread'",
            output_features=("spread",),
        )

    def test_whole_number_score_is_a_decimal(self) -> None:
        result = self.evaluate("def evaluate(namespace):\n    return StageResult(1)\n")
        self.assertEqual(result.score, 1.0)
        self.assertIsInstance(result.score, float)


TWO_STAGES = """
def evaluate_stage1(namespace):
    value = namespace["answer"]({first})
    return StageResult(
        score=value,
        metrics={{"value": value, "first_only": 1}},
        features={{"spread": 0.25}},
        feedback="Stage 1 checked.",
        output_data={{"stage": 1}},
    )

def evaluate_stage2(namespace):
    {second}
"""


class TestCascade(EvaluatorTestCase):
    def cascade(self, second: str, first: float = 0.8, threshold: float = 0.5) -> Result:
        code = TWO_STAGES.format(first=first, second=second)
        return self.evaluate(code, thresholds=(threshold,))

    def test_score_below_the_threshold_ends_the_cascade(self) -> None:
        result = self.cascade("raise AssertionError('stage 2 must not run')", first=0.3)
        self.assertEqual(result.status, Status.OK)
        self.assertEqual(result.score, 0.3)
        self.assertEqual(result.stage_reached, 1)

    def test_score_reaching_the_threshold_runs_the_next_stage(self) -> None:
        result = self.cascade("return StageResult(0.9)", first=0.5, threshold=0.5)
        self.assertEqual(result.score, 0.9)
        self.assertEqual(result.stage_reached, 2)

    def test_later_stage_merges_into_the_earlier_result(self) -> None:
        result = self.cascade(
            'return StageResult(0.9, metrics={"value": 0.9, "second_only": 2}, '
            'features={"spread": 0.99}, feedback="Stage 2 checked.", output_data={"stage": 2})'
        )
        self.assertEqual(result.score, 0.9)
        self.assertEqual(result.metrics, {"value": 0.9, "first_only": 1.0, "second_only": 2.0})
        # Features are always stage 1's (D17).
        self.assertEqual(result.features, {"spread": 0.25})
        self.assertEqual(result.feedback, "Stage 1 checked.\nStage 2 checked.")
        self.assertEqual(result.output_data, {"stage": 2})

    def test_later_stage_without_output_data_keeps_the_earlier(self) -> None:
        result = self.cascade("return StageResult(0.9)")
        self.assertEqual(result.output_data, {"stage": 1})

    def test_each_stage_gets_a_freshly_loaded_program(self) -> None:
        result = self.cascade('return StageResult(float(namespace["calls"]()))', first=0.8)
        # Stage 1 called answer() once; stage 2's program has not been called yet.
        self.assertEqual(result.score, 0.0)

    def test_later_stage_failing_keeps_the_earlier_result(self) -> None:
        result = self.cascade('return StageResult(namespace["crash"]())')
        self.assertEqual(result.status, Status.OK)
        self.assertEqual(result.score, 0.8)
        self.assertEqual(result.stage_reached, 1)
        self.assertTrue(str(result.error).startswith("stage 2: IndexError"))

    def test_later_stage_timing_out_keeps_the_earlier_result(self) -> None:
        code = TWO_STAGES.format(first=0.8, second='return StageResult(namespace["sleep"](30))')
        result = self.evaluate(code, thresholds=(0.5,), stage_limit=2)
        self.assertEqual(result.status, Status.OK)
        self.assertEqual(result.score, 0.8)
        self.assertIn("stage 2: the stage ran out of time", str(result.error))

    def test_illegal_answer_at_a_later_stage_makes_the_program_invalid(self) -> None:
        result = self.cascade('raise InvalidProgram("circle 4 is outside", feedback="Too big.")')
        self.assertEqual(result.status, Status.INVALID)
        self.assertIsNone(result.score)
        self.assertEqual(result.error, "circle 4 is outside")
        self.assertEqual(result.feedback, "Stage 1 checked.\nToo big.")
        self.assertEqual(result.stage_reached, 1)

    def test_evaluator_bug_at_a_later_stage_is_an_error(self) -> None:
        result = self.cascade("return 'not a result'")
        self.assertEqual(result.status, Status.ERROR)


if __name__ == "__main__":
    unittest.main()
