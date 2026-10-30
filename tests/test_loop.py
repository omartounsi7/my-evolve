"""Checks that the loop runs from start to finish, and the command line around it.

The end-to-end test of the implementation plan: the toy problem, evolved with a fake LLM.
It keeps passing at every step, and grows with every phase.
"""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fakes import FakeLLM

from my_evolve.database import Database
from my_evolve.evaluator import Evaluator
from my_evolve.llm import Ensemble, LLMError
from my_evolve.loop import RunError, run
from my_evolve.problem import Problem
from my_evolve.program import Status
from my_evolve.sandbox import LocalSandbox

REPOSITORY_FOLDER = Path(__file__).parent.parent
TOY_FOLDER = Path(__file__).parent / "toy"
# Long enough for any test program: the tests of time limits set their own
STAGE_TIME_LIMIT = 30.0
RUN_SCRIPT = REPOSITORY_FOLDER / "scripts" / "run.py"


def reply_returning(value: str) -> str:
    """Return an LLM reply whose program's solve() returns that value, with a description."""
    return (
        f"<DESCRIPTION>Returns {value}.</DESCRIPTION>\n"
        "Here is a better program:\n\n```python\n# EVOLVE-BLOCK-START\n"
        f"def solve():\n    return {value}\n# EVOLVE-BLOCK-END\n```\n"
    )


def run_toy(
    replies: list[str | Exception], output: Path, seed: int = 0, iterations: int | None = None
) -> tuple[Database, FakeLLM, str]:
    """Evolve the toy problem with a fake LLM; return the database, the LLM and the console text."""
    llm = FakeLLM(replies)
    console = io.StringIO()
    with contextlib.redirect_stdout(console):
        database = run(
            problem=Problem.load(TOY_FOLDER / "problem.yaml"),
            initial_code=(TOY_FOLDER / "initial_program.py").read_text(),
            ensemble=Ensemble([llm], [1.0], max_failures=3),
            evaluator=Evaluator(TOY_FOLDER / "evaluation.py", LocalSandbox(), STAGE_TIME_LIMIT),
            iterations=iterations if iterations is not None else len(replies),
            output=output,
            seed=seed,
        )
    return database, llm, console.getvalue()


class LoopTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.output = self.folder / "run"

    def test_a_run_from_start_to_finish(self) -> None:
        """Each iteration stores a child, failed or not; a failed LLM call skips its iteration."""
        replies: list[str | Exception] = [
            reply_returning("5"),
            reply_returning("1 / 0"),
            "```python\n# EVOLVE-BLOCK-START\ndef answer():\n    return 9\n# EVOLVE-BLOCK-END\n```",
            LLMError("fake-model", "the server is down"),
            reply_returning("7"),
        ]
        database, llm, console = run_toy(replies, self.output)

        # The initial program and one child per iteration, except the skipped one.
        programs = list(database.programs.values())
        self.assertEqual([program.iteration for program in programs], [0, 1, 2, 3, 5])
        scores = [program.result.score for program in programs]
        self.assertEqual(scores, [1.0, 5.0, None, None, 7.0])
        self.assertIn("ZeroDivisionError", programs[2].result.error or "")
        self.assertEqual(programs[3].result.status, Status.REJECTED)
        self.assertIn("must define the function solve()", programs[3].result.error or "")
        self.assertEqual((programs[1].description, programs[3].description), ("Returns 5.", None))
        for child in programs[1:]:
            parent = database.programs[child.parent_id or ""]
            self.assertEqual(child.generation, parent.generation + 1)
        best = database.best()
        self.assertIsNotNone(best)
        self.assertEqual(best.result.score if best else None, 7.0)

        # The first prompt shows the initial program alone; every call got a prompt.
        self.assertEqual(len(llm.prompts), 5)
        self.assertNotIn("Previous attempts", llm.prompts[0].user)
        self.assertIn(
            "score 1.0; best score so far in this run: 1.0\nFeedback: solve() returned 1.0.\n",
            llm.prompts[0].user,
        )

        # The console has one line per iteration.
        self.assertIn("Initial program: score 1.000000", console)
        self.assertIn("Iteration 1/5, fake-model: score 5.000000 (best 5.000000)", console)
        self.assertIn("Iteration 2/5, fake-model: failed: ZeroDivisionError: division by", console)
        self.assertIn(
            "Iteration 4/5, fake-model: skipped, no reply (fake-model: the server is down)", console
        )

    def test_the_run_folder(self) -> None:
        """programs.jsonl has one line per program; best_program.py holds the best one."""
        database, _, _ = run_toy([reply_returning("4"), reply_returning("2")], self.output)
        lines = (self.output / "programs.jsonl").read_text().splitlines()
        saved = [json.loads(line) for line in lines]
        self.assertEqual([entry["id"] for entry in saved], list(database.programs))
        self.assertEqual([entry["result"]["score"] for entry in saved], [1.0, 4.0, 2.0])
        best_file = (self.output / "best_program.py").read_text()
        self.assertTrue(best_file.startswith("# Best program of the run: score 4.0, iteration 1"))
        self.assertIn("    return 4\n", best_file)

    def test_a_failing_model_is_dropped_and_the_run_stops_without_models(self) -> None:
        """Each iteration draws a model; a model failing 3 times in a row is dropped."""
        down = LLMError("down-model", "the server is down")
        good = FakeLLM([reply_returning(str(n)) for n in range(2, 8)], name="good-model")
        bad = FakeLLM([down, down, down], name="down-model")
        console = io.StringIO()
        with contextlib.redirect_stdout(console), self.assertLogs("my_evolve.llm", "WARNING"):
            database = run(
                problem=Problem.load(TOY_FOLDER / "problem.yaml"),
                initial_code=(TOY_FOLDER / "initial_program.py").read_text(),
                ensemble=Ensemble([good, bad], [1.0, 1.0], max_failures=3),
                evaluator=Evaluator(TOY_FOLDER / "evaluation.py", LocalSandbox(), STAGE_TIME_LIMIT),
                iterations=9,
                output=self.output,
                seed=1,
            )
        self.assertEqual(len(bad.prompts), 3)
        self.assertEqual(len(database.programs), 1 + 6)
        self.assertIn("good-model: score", console.getvalue())
        # With no model left, the run stops before its last iterations.
        lonely = FakeLLM([down], name="lonely")
        with contextlib.redirect_stdout(console), self.assertLogs("my_evolve.llm", "WARNING"):
            run(
                problem=Problem.load(TOY_FOLDER / "problem.yaml"),
                initial_code=(TOY_FOLDER / "initial_program.py").read_text(),
                ensemble=Ensemble([lonely], [1.0], max_failures=1),
                evaluator=Evaluator(TOY_FOLDER / "evaluation.py", LocalSandbox(), STAGE_TIME_LIMIT),
                iterations=5,
                output=self.folder / "second",
                seed=1,
            )
        self.assertIn("Stopping: every model has been dropped", console.getvalue())

    def test_a_duplicate_costs_no_evaluation(self) -> None:
        """A child identical to an earlier program (comments aside) is rejected."""
        initial = (TOY_FOLDER / "initial_program.py").read_text()
        replies: list[str | Exception] = [
            reply_returning("5"),
            "```python\n" + initial.replace("return 1.0", "return 1.0  # unchanged") + "```",
            reply_returning("5"),
        ]
        database, _, _ = run_toy(replies, self.output)
        programs = list(database.programs.values())
        self.assertEqual(
            [program.result.status for program in programs[1:]],
            [Status.OK, Status.REJECTED, Status.REJECTED],
        )
        self.assertEqual(programs[2].result.error, f"same program as {programs[0].id}")
        self.assertEqual(programs[3].result.error, f"same program as {programs[1].id}")
        self.assertEqual(programs[2].result.duration, 0.0)
        # Each child records the example programs its prompt showed.
        shown = [set(program.example_ids) for program in programs[1:]]
        self.assertEqual(shown[0], set())
        self.assertEqual(shown[1], {programs[0].id, programs[1].id} - {programs[2].parent_id})

    def test_every_llm_call_is_saved(self) -> None:
        """llm_calls.jsonl: one line per call, failed ones included; children keep their usage."""
        replies: list[str | Exception] = [
            reply_returning("5"),
            LLMError("fake-model", "the server is down"),
            reply_returning("6"),
        ]
        database, llm, _ = run_toy(replies, self.output, seed=3)
        lines = (self.output / "llm_calls.jsonl").read_text().splitlines()
        calls = [json.loads(line) for line in lines]
        self.assertEqual([call["iteration"] for call in calls], [1, 2, 3])
        self.assertEqual(calls[0]["user_message"], llm.prompts[0].user)
        self.assertEqual(calls[0]["reply"], reply_returning("5"))
        self.assertIsNone(calls[0]["error"])
        self.assertGreater(calls[0]["input_tokens"], 0)
        self.assertEqual(
            (calls[1]["program_id"], calls[1]["reply"], calls[1]["error"]),
            (None, None, "fake-model: the server is down"),
        )
        child = database.programs[calls[2]["program_id"]]
        self.assertEqual(child.iteration, 3)
        self.assertIsNotNone(child.llm)
        assert child.llm is not None
        words = len(reply_returning("6").split())
        self.assertEqual((child.llm.model, child.llm.output_tokens), ("fake-model", words))
        info = json.loads((self.output / "run.json").read_text())
        self.assertEqual(info["seed"], 3)
        self.assertEqual(info["system_message"], llm.prompts[0].system)
        self.assertEqual(len(info["run_id"]), 32)

    def test_the_same_seed_repeats_the_run(self) -> None:
        """With the same seed and the same replies, the same parents are drawn."""
        replies: list[str | Exception] = [reply_returning(str(n)) for n in range(2, 9)]

        def parent_iterations(output: Path) -> list[int]:
            database, _, _ = run_toy(list(replies), output, seed=42)
            return [
                database.programs[program.parent_id].iteration
                for program in database.programs.values()
                if program.parent_id is not None
            ]

        self.assertEqual(parent_iterations(self.folder / "a"), parent_iterations(self.folder / "b"))

    def test_a_failing_initial_program_stops_the_run(self) -> None:
        """Evolution needs a working starting point; nothing is saved without one."""
        with (
            self.assertRaisesRegex(RunError, r"does not work \(invalid\): solve\(\) returned 11"),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            run(
                problem=Problem.load(TOY_FOLDER / "problem.yaml"),
                initial_code=(
                    "# EVOLVE-BLOCK-START\ndef solve():\n    return 11\n# EVOLVE-BLOCK-END\n"
                ),
                ensemble=Ensemble([FakeLLM([])], [1.0], max_failures=3),
                evaluator=Evaluator(TOY_FOLDER / "evaluation.py", LocalSandbox(), STAGE_TIME_LIMIT),
                iterations=1,
                output=self.output,
                seed=0,
            )
        self.assertFalse(self.output.exists())

    def test_an_initial_program_without_evolve_blocks_is_refused(self) -> None:
        """The blocks are what the LLM may change: the initial program must have them."""
        with (
            self.assertRaisesRegex(RunError, "evolve blocks are broken: no evolve block"),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            run(
                problem=Problem.load(TOY_FOLDER / "problem.yaml"),
                initial_code="def solve():\n    return 1\n",
                ensemble=Ensemble([FakeLLM([])], [1.0], max_failures=3),
                evaluator=Evaluator(TOY_FOLDER / "evaluation.py", LocalSandbox(), STAGE_TIME_LIMIT),
                iterations=1,
                output=self.output,
            )

    def test_a_folder_holding_a_run_is_refused(self) -> None:
        """Continuing a run comes later: for now an existing run is never overwritten."""
        run_toy([reply_returning("2")], self.output)
        with self.assertRaisesRegex(RunError, "already holds a run"):
            run_toy([reply_returning("3")], self.output)


class RunScriptTest(unittest.TestCase):
    def run_script(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        """Run scripts/run.py with these arguments; return its exit code and output."""
        return subprocess.run(
            [sys.executable, str(RUN_SCRIPT), *arguments],
            capture_output=True,
            text=True,
            timeout=60,
        )

    def toy_arguments(self, output: Path, config: Path = TOY_FOLDER / "problem.yaml") -> list[str]:
        """Return the arguments that evolve the toy problem for one iteration."""
        return [
            str(TOY_FOLDER / "initial_program.py"),
            str(TOY_FOLDER / "evaluation.py"),
            "--config",
            str(config),
            "--iterations",
            "1",
            "--output",
            str(output),
            "--unsafe-local-sandbox",
        ]

    def test_a_model_that_does_not_answer_stops_the_run_at_once(self) -> None:
        """The toy problem's model address has no server: its check fails before any run."""
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "run"
            completed = self.run_script(*self.toy_arguments(output), "--seed", "1")
            self.assertEqual(completed.returncode, 1, completed.stdout)
            self.assertIn("a model did not answer its check: fake-model:", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)
            self.assertFalse(output.exists())

    def test_wrong_arguments_are_usage_errors(self) -> None:
        """A number of iterations below 1, or a missing file, stops the script at once."""
        with tempfile.TemporaryDirectory() as folder:
            arguments = self.toy_arguments(Path(folder) / "run")
            arguments[arguments.index("--iterations") + 1] = "0"
            completed = self.run_script(*arguments)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("must be 1 or more", completed.stderr)
            completed = self.run_script(*self.toy_arguments(Path(folder), Path("missing.yaml")))
            self.assertEqual(completed.returncode, 2)
            self.assertIn("no such file: missing.yaml", completed.stderr)

    def test_a_problem_file_mistake_is_one_clear_message(self) -> None:
        """A mistake in the problem file is reported in one line, without a traceback."""
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "problem.yaml"
            config.write_text((TOY_FOLDER / "problem.yaml").read_text() + "colour: blue\n")
            completed = self.run_script(*self.toy_arguments(Path(folder) / "run", config))
            self.assertEqual(completed.returncode, 1)
            self.assertIn("unknown key 'colour' in the problem file", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)


if __name__ == "__main__":
    unittest.main()
