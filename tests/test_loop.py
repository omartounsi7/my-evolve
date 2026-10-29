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
from my_evolve.llm import LLMError
from my_evolve.loop import RunError, run
from my_evolve.problem import Problem

REPOSITORY_FOLDER = Path(__file__).parent.parent
TOY_FOLDER = Path(__file__).parent / "toy"
RUN_SCRIPT = REPOSITORY_FOLDER / "scripts" / "run.py"


def reply_returning(value: str) -> str:
    """Return an LLM reply whose program's solve() returns that value."""
    return f"Here is a better program:\n\n```python\ndef solve():\n    return {value}\n```\n"


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
            llm=llm,
            evaluator=Evaluator(TOY_FOLDER / "evaluation.py"),
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
            "I cannot write that program.",
            LLMError("fake-model: the server is down"),
            reply_returning("7"),
        ]
        database, llm, console = run_toy(replies, self.output)

        # The initial program and one child per iteration, except the skipped one.
        programs = list(database.programs.values())
        self.assertEqual([program.iteration for program in programs], [0, 1, 2, 3, 5])
        scores = [program.result.score for program in programs]
        self.assertEqual(scores, [1.0, 5.0, None, None, 7.0])
        self.assertIn("ZeroDivisionError", programs[2].result.error or "")
        self.assertIn("SyntaxError", programs[3].result.error or "")
        for child in programs[1:]:
            parent = database.programs[child.parent_id or ""]
            self.assertEqual(child.generation, parent.generation + 1)
        best = database.best()
        self.assertIsNotNone(best)
        self.assertEqual(best.result.score if best else None, 7.0)

        # The first prompt shows the initial program alone; every call got a prompt.
        self.assertEqual(len(llm.prompts), 5)
        self.assertNotIn("Previous attempts", llm.prompts[0].user)
        self.assertIn("score 1.0\n```python\n# EVOLVE-BLOCK-START\n", llm.prompts[0].user)

        # The console has one line per iteration.
        self.assertIn("Initial program: score 1.000000", console)
        self.assertIn("Iteration 1/5: score 5.000000 (best 5.000000)", console)
        self.assertIn("Iteration 2/5: failed: ZeroDivisionError: division by zero", console)
        self.assertIn("Iteration 4/5: skipped, no reply (fake-model: the server is down)", console)

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
                initial_code="def solve():\n    return 11\n",
                llm=FakeLLM([]),
                evaluator=Evaluator(TOY_FOLDER / "evaluation.py"),
                iterations=1,
                output=self.output,
                seed=0,
            )
        self.assertFalse(self.output.exists())

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
        ]

    def test_the_script_runs_with_an_unreachable_llm(self) -> None:
        """The toy problem's LLM address has no server: the iteration is skipped, the run ends."""
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "run"
            completed = self.run_script(*self.toy_arguments(output), "--seed", "1")
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("Seed: 1\nInitial program: score 1.000000", completed.stdout)
            self.assertIn("Iteration 1/1: skipped, no reply", completed.stdout)
            self.assertEqual(len((output / "programs.jsonl").read_text().splitlines()), 1)

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
