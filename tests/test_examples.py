"""Checks the two example problems, and that their scores are exactly OpenEvolve's (D3).

The parity programs in tests/parity/programs are scored by my-evolve here, and were
scored by OpenEvolve's own evaluators once, by tests/parity/record_openevolve_scores.py.
A working program must get exactly OpenEvolve's score; a program OpenEvolve scores 0
must be invalid, failed or timeout here, with the status given below.

Some tests are slow (OpenEvolve's best circle packing takes about 12 s per stage): they
run only when the environment variable MY_EVOLVE_SLOW_TESTS is set to 1.
"""

import json
import os
import unittest
from pathlib import Path

from docker_check import docker_is_available

from my_evolve.checks import check_child
from my_evolve.evaluator import Evaluator
from my_evolve.problem import Problem
from my_evolve.program import Result, Status
from my_evolve.sandbox import DockerSandbox, LocalSandbox, Sandbox

REPOSITORY = Path(__file__).resolve().parent.parent
EXAMPLES = REPOSITORY / "examples"
PARITY = Path(__file__).resolve().parent / "parity"
OPENEVOLVE_SCORES = json.loads((PARITY / "openevolve_scores.json").read_text(encoding="utf-8"))
SLOW_TESTS = os.environ.get("MY_EVOLVE_SLOW_TESTS") == "1"

# The status here of each program OpenEvolve scores 0 (any other program must be ok).
NOT_OK = {
    "circle_packing": {
        "best_program_1_threads": Status.INVALID,
        "crash": Status.FAILED,
        "nan_radius": Status.INVALID,
        "negative_radius": Status.INVALID,
        "outside": Status.INVALID,
        "overlap": Status.INVALID,
        "too_few_circles": Status.INVALID,
        "two_values": Status.FAILED,
    },
    "function_minimization": {
        "crash": Status.FAILED,
        "four_values": Status.FAILED,
        "list_answer": Status.FAILED,
        "not_finite": Status.INVALID,
        "text_coordinates": Status.INVALID,
        "too_slow": Status.TIMEOUT,
    },
}


def load_problem(name: str, file_name: str = "problem.yaml") -> Problem:
    return Problem.load(EXAMPLES / name / file_name)


def make_evaluator(name: str, sandbox: Sandbox) -> Evaluator:
    """Return the evaluator of an example problem, with the grid's two features required."""
    features = ("radii_spread", "radius_centre_correlation") if name == "circle_packing" else ()
    return Evaluator(EXAMPLES / name / "evaluation.py", load_problem(name), sandbox, features)


def program_code(name: str, program: str) -> str:
    """Return the code of a parity program, or of the problem's initial program."""
    if program == "initial_program":
        path = EXAMPLES / name / "initial_program.py"
    else:
        # best_program_1_threads and best_program_8_threads are both best_program.py.
        file_name = program.removesuffix("_1_threads").removesuffix("_8_threads")
        path = PARITY / "programs" / name / f"{file_name}.py"
    return path.read_text(encoding="utf-8")


class TestProblemFiles(unittest.TestCase):
    def test_both_batches_describe_the_same_problem(self) -> None:
        for name in ("circle_packing", "function_minimization"):
            with self.subTest(name=name):
                local = load_problem(name)
                claude = load_problem(name, "problem_claude.yaml")
                self.assertEqual(local.fingerprint_without_llm(), claude.fingerprint_without_llm())
                self.assertEqual(
                    [model.name for model in local.llm.models], ["qwen3-coder:30b", "qwen3:8b"]
                )
                self.assertEqual(
                    [model.name for model in claude.llm.models],
                    ["claude-haiku-5-5", "claude-sonnet-5-5"],
                )
                self.assertEqual(claude.llm.models[0].api_key_env, "ANTHROPIC_API_KEY")

    def test_descriptions_start_with_openevolves_system_messages(self) -> None:
        self.assertTrue(
            load_problem("circle_packing").description.startswith(
                "You are an expert mathematician specializing in circle packing problems"
            )
        )
        self.assertIn("run_packing()", load_problem("circle_packing").description)
        self.assertTrue(
            load_problem("function_minimization").description.startswith(
                "You are an expert programmer specializing in optimization algorithms."
            )
        )

    def test_evaluation_files_have_two_stages_and_fit_their_problems(self) -> None:
        for name in ("circle_packing", "function_minimization"):
            with self.subTest(name=name):
                evaluator = make_evaluator(name, LocalSandbox())
                self.assertEqual(len(evaluator.stages), 2)
                self.assertEqual(evaluator.stage_limit, 60)

    def test_initial_programs_pass_the_checks(self) -> None:
        for name in ("circle_packing", "function_minimization"):
            with self.subTest(name=name):
                code = program_code(name, "initial_program")
                checks = check_child(code, code, load_problem(name).entry_functions, {})
                self.assertIsNone(checks.reason)


class ParityTestCase(unittest.TestCase):
    """Scores parity programs with the local sandbox, one thread, as the Docker sandbox does."""

    problem = ""

    def setUp(self) -> None:
        self.evaluator = make_evaluator(self.problem, LocalSandbox(cpus=1))

    def evaluate(self, program: str) -> Result:
        return self.evaluator.evaluate(program_code(self.problem, program))

    def assert_parity(self, program: str, result: Result) -> None:
        """Check one program's result against OpenEvolve's score for it."""
        expected_score = OPENEVOLVE_SCORES[self.problem][program]
        expected_status = NOT_OK[self.problem].get(program, Status.OK)
        self.assertEqual(result.status, expected_status, result.error)
        if expected_status is Status.OK:
            self.assertEqual(result.score, expected_score)
        else:
            self.assertEqual(expected_score, 0.0)

    def check_every_fast_program(self) -> None:
        for program in OPENEVOLVE_SCORES[self.problem]:
            if program.startswith("best_program"):
                continue
            if self.problem == "function_minimization" and program == "initial_program":
                continue
            with self.subTest(program=program):
                self.assert_parity(program, self.evaluate(program))


class TestCirclePacking(ParityTestCase):
    problem = "circle_packing"

    def test_every_program_gets_openevolves_score(self) -> None:
        self.check_every_fast_program()

    def test_initial_program_scores_as_in_openevolve(self) -> None:
        result = self.evaluate("initial_program")
        self.assertEqual(result.score, 0.36423689449571406)
        # Below the threshold of 0.5: stage 2 does not run.
        self.assertEqual(result.stage_reached, 1)
        self.assertAlmostEqual(result.metrics["sum_radii"], 0.36423689449571406 * 2.635)

    def test_stage_two_runs_for_good_packings(self) -> None:
        self.assertEqual(self.evaluate("grid").stage_reached, 2)

    def test_features_describe_the_radii(self) -> None:
        features = self.evaluate("grid").features
        # 25 radii of 0.1 and one of 0: mean 0.0962, standard deviation 0.0192.
        self.assertAlmostEqual(features["radii_spread"], 0.2, places=6)
        self.assertGreaterEqual(features["radius_centre_correlation"], -1)
        self.assertLessEqual(features["radius_centre_correlation"], 1)
        zero = self.evaluate("zero_radii").features
        self.assertEqual(zero, {"radii_spread": 0.0, "radius_centre_correlation": 0.0})

    def test_circles_are_kept_for_the_report(self) -> None:
        output = self.evaluate("grid").output_data
        assert isinstance(output, dict)
        centers, radii = output["centers"], output["radii"]
        assert isinstance(centers, list) and isinstance(radii, list)
        self.assertEqual(len(centers), 26)
        self.assertEqual(radii[0], 0.1)

    def test_illegal_packing_names_the_broken_rule(self) -> None:
        result = self.evaluate("overlap")
        self.assertTrue(str(result.error).startswith("circles 2 and 7 overlap"))
        self.assertIn("rule(s)", str(result.feedback))

    def test_feedback_reports_a_wrong_sum(self) -> None:
        feedback = str(self.evaluate("wrong_reported_sum").feedback)
        self.assertIn("is not the sum of the radii", feedback)
        self.assertIn("Sum of the radii: 2.500000", feedback)

    @unittest.skipUnless(SLOW_TESTS, "slow: set MY_EVOLVE_SLOW_TESTS=1")
    def test_best_program_depends_on_the_number_of_threads(self) -> None:
        # One thread, as the sandbox gives programs (D41): OpenEvolve's record packing
        # then comes out invalid, in OpenEvolve's evaluator as here.
        self.assert_parity("best_program_1_threads", self.evaluate("best_program_1_threads"))
        evaluator = make_evaluator(self.problem, LocalSandbox(cpus=8))
        result = evaluator.evaluate(program_code(self.problem, "best_program"))
        self.assertEqual(result.status, Status.OK, result.error)
        self.assertAlmostEqual(
            result.score or 0.0, OPENEVOLVE_SCORES[self.problem]["best_program_8_threads"], 9
        )


class TestFunctionMinimization(ParityTestCase):
    problem = "function_minimization"

    def test_every_program_gets_openevolves_score(self) -> None:
        self.check_every_fast_program()

    def test_reported_value_is_never_trusted(self) -> None:
        lying = self.evaluate("global_minimum_lying_value")
        honest = self.evaluate("global_minimum_two_values")
        self.assertEqual(lying.score, honest.score)

    def test_good_programs_are_scored_on_ten_calls(self) -> None:
        result = self.evaluate("global_minimum_two_values")
        self.assertEqual(result.stage_reached, 2)
        self.assertEqual(result.metrics["reliability_score"], 1.0)

    def test_failed_calls_lower_reliability_and_are_reported(self) -> None:
        result = self.evaluate("fails_every_other_call")
        self.assertEqual(result.metrics["reliability_score"], 0.5)
        self.assertIn("5 of 10 calls succeeded", str(result.feedback))
        self.assertIn("call 2: IndexError", str(result.feedback))

    def test_initial_program_gets_a_real_score(self) -> None:
        # It searches at random, so its score changes from one evaluation to the next:
        # usually about 1.3, but below 0.5 in about one evaluation out of 70.
        result = self.evaluate("initial_program")
        self.assertEqual(result.status, Status.OK, result.error)
        self.assertGreater(result.score or 0.0, 0.0)


@unittest.skipUnless(docker_is_available(), "Docker is not available")
class TestExamplesInDocker(unittest.TestCase):
    """The initial programs in the problems' own images, with the sandbox's limits."""

    def docker_evaluator(self, name: str) -> Evaluator:
        problem = load_problem(name)
        image = DockerSandbox.ensure_image(problem.packages)
        sandbox = DockerSandbox(image, problem.sandbox, run_id=f"test-examples-{name}")
        self.addCleanup(sandbox.remove_leftovers)
        return make_evaluator(name, sandbox)

    def test_circle_packing_initial_program_scores_as_in_openevolve(self) -> None:
        result = self.docker_evaluator("circle_packing").evaluate(
            program_code("circle_packing", "initial_program")
        )
        self.assertEqual(result.status, Status.OK, result.error)
        self.assertEqual(result.score, OPENEVOLVE_SCORES["circle_packing"]["initial_program"])

    def test_function_minimization_initial_program_works(self) -> None:
        result = self.docker_evaluator("function_minimization").evaluate(
            program_code("function_minimization", "initial_program")
        )
        self.assertEqual(result.status, Status.OK, result.error)

    def test_programs_may_use_scipy(self) -> None:
        result = self.docker_evaluator("function_minimization").evaluate(
            "import scipy.optimize\n\n"
            "def run_search():\n"
            "    def distance(p):\n"
            "        return (p[0] + 1.704) ** 2 + (p[1] - 0.678) ** 2\n"
            "    found = scipy.optimize.minimize(distance, [0, 0])\n"
            "    return float(found.x[0]), float(found.x[1])\n"
        )
        self.assertEqual(result.status, Status.OK, result.error)
        self.assertGreater(result.score or 0.0, 1.4)

    @unittest.skipUnless(SLOW_TESTS, "slow: set MY_EVOLVE_SLOW_TESTS=1")
    def test_best_circle_packing_fits_the_stage_limit_on_one_cpu(self) -> None:
        result = self.docker_evaluator("circle_packing").evaluate(
            program_code("circle_packing", "best_program")
        )
        # One CPU and one thread: it ends in time, and is invalid as with one thread above.
        self.assertEqual(result.status, Status.INVALID, result.error)
        self.assertLess(result.duration, 2 * 60)


if __name__ == "__main__":
    unittest.main()
