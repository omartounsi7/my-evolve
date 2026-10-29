"""Checks that the examples' evaluations give exactly OpenEvolve's scores (D3).

The parity programs in tests/parity/programs are scored here by my-evolve, and were scored
by OpenEvolve's own evaluators once, by tests/parity/record_openevolve_scores.py. A working
program must get exactly OpenEvolve's score; a program OpenEvolve scores 0 must be
invalid or failed here, with the status given below.

Programs run in the local sandbox with one thread, as the Docker sandbox runs them. Slow
tests (OpenEvolve's best circle packing takes about 12 s per stage) run only when the
environment variable MY_EVOLVE_SLOW_TESTS is set to 1.
"""

import json
import os
import unittest
from pathlib import Path

from docker_check import docker_is_available

from my_evolve.evaluator import Evaluator
from my_evolve.problem import Problem
from my_evolve.program import Result, Status
from my_evolve.sandbox import DockerSandbox, LocalSandbox, Sandbox, ensure_image

REPOSITORY = Path(__file__).resolve().parent.parent
EXAMPLES = REPOSITORY / "examples"
PARITY = Path(__file__).resolve().parent / "parity"
OPENEVOLVE_SCORES = json.loads((PARITY / "openevolve_scores.json").read_text(encoding="utf-8"))
SLOW_TESTS = os.environ.get("MY_EVOLVE_SLOW_TESTS") == "1"

# The status here of each program OpenEvolve scores 0 (every other program must be ok).
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
}
# The programs too slow for every test run
SLOW_PROGRAMS = {"best_program_1_threads", "best_program_8_threads"}


def make_evaluator(problem_name: str, sandbox: Sandbox) -> Evaluator:
    """Return the evaluator of an example problem, with its problem file's settings."""
    problem = Problem.load(EXAMPLES / problem_name / "problem.yaml")
    return Evaluator(
        EXAMPLES / problem_name / "evaluation.py",
        sandbox,
        problem.evaluation.stage_time_limit,
        problem.evaluation.thresholds,
    )


def program_code(problem_name: str, program: str) -> str:
    """Return the code of a parity program, or of the problem's initial program."""
    if program == "initial_program":
        path = EXAMPLES / problem_name / "initial_program.py"
    else:
        # best_program_1_threads and best_program_8_threads are both best_program.py.
        file_name = program.removesuffix("_1_threads").removesuffix("_8_threads")
        path = PARITY / "programs" / problem_name / f"{file_name}.py"
    return path.read_text(encoding="utf-8")


class CirclePackingParityTest(unittest.TestCase):
    problem = "circle_packing"

    def assert_parity(self, program: str, result: Result) -> None:
        """Check one program's result against OpenEvolve's score for it."""
        expected_score = OPENEVOLVE_SCORES[self.problem][program]
        expected_status = NOT_OK[self.problem].get(program, Status.OK)
        self.assertEqual(result.status, expected_status, result.error)
        if expected_status is Status.OK:
            self.assertEqual(result.score, expected_score)
        else:
            self.assertEqual(expected_score, 0.0)

    def test_every_program_scores_as_in_openevolve(self) -> None:
        """Each fast parity program: the same score, or a status saying why it is 0."""
        evaluator = make_evaluator(self.problem, LocalSandbox(cpus=1))
        for program in OPENEVOLVE_SCORES[self.problem]:
            if program in SLOW_PROGRAMS:
                continue
            with self.subTest(program=program):
                result = evaluator.evaluate(program_code(self.problem, program))
                self.assert_parity(program, result)

    def test_both_stages_run_for_a_good_packing(self) -> None:
        """A packing scoring at least 0.5 goes through stage 2; a weaker one stops at stage 1."""
        evaluator = make_evaluator(self.problem, LocalSandbox(cpus=1))
        grid = evaluator.evaluate(program_code(self.problem, "grid"))
        weak = evaluator.evaluate(program_code(self.problem, "weak_grid"))
        self.assertEqual((grid.stage_reached, weak.stage_reached), (2, 1))
        lying = evaluator.evaluate(program_code(self.problem, "wrong_reported_sum"))
        self.assertIn("reports a sum of radii of 99.0", lying.feedback or "")

    @unittest.skipUnless(SLOW_TESTS, "slow: set MY_EVOLVE_SLOW_TESTS=1")
    def test_openevolves_best_program_depends_on_threads(self) -> None:
        """With one thread its circles overlap (OpenEvolve scores it 0); with eight, 1.0004."""
        for threads in (1, 8):
            with self.subTest(threads=threads):
                evaluator = make_evaluator(self.problem, LocalSandbox(cpus=threads))
                result = evaluator.evaluate(program_code(self.problem, "best_program"))
                self.assert_parity(f"best_program_{threads}_threads", result)

    @unittest.skipUnless(SLOW_TESTS and docker_is_available(), "slow, and needs Docker")
    def test_openevolves_best_program_fits_in_the_sandbox_time_limit(self) -> None:
        """In Docker, with one CPU, its evaluation ends within the 60 s stage limit."""
        problem = Problem.load(EXAMPLES / self.problem / "problem.yaml")
        sandbox = DockerSandbox(ensure_image(problem.packages), problem.sandbox, "test")
        result = make_evaluator(self.problem, sandbox).evaluate(
            program_code(self.problem, "best_program")
        )
        self.assert_parity("best_program_1_threads", result)
        self.assertLess(result.duration, 60.0)


if __name__ == "__main__":
    unittest.main()
