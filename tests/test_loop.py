"""Checks the loop end to end: a tiny problem, the fake LLM server, and the local sandbox.

The test problem's programs define value(), inside the evolve block, and run(),
outside it; the score is what run() returns. A negative value is illegal (invalid),
and a value of 13 makes the evaluation file itself fail (error).
"""

import contextlib
import io
import json
import tempfile
import time
import unittest
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fake_llm_server import FakeLLMServer, PreparedReply, serve

from my_evolve.database import Database
from my_evolve.loop import RunError, RunSettings, run
from my_evolve.program import Status
from my_evolve.storage import Storage

INITIAL_PROGRAM = """\
# EVOLVE-BLOCK-START
def value():
    return 1
# EVOLVE-BLOCK-END


def run():
    return value()
"""

EVALUATION = """\
from my_evolve.evaluation_api import InvalidProgram, StageResult


def evaluate(namespace):
    value = namespace["run"]()
    if value == 13:
        raise RuntimeError("the evaluation file has a bug")
    if value < 0:
        raise InvalidProgram(f"the value {value} is negative")
    return StageResult(score=float(value), feedback=f"run() returned {value}.")
"""


def program_returning(value: str) -> str:
    """Return the initial program with value() returning the given expression."""
    return INITIAL_PROGRAM.replace("return 1", f"return {value}")


def reply_with(value: str, description: str = "Returns a constant.") -> str:
    """Return a well-formed reply whose program returns value."""
    return (
        f"<DESCRIPTION>\n{description}\n</DESCRIPTION>\n```python\n{program_returning(value)}```\n"
    )


class LoopTestCase(unittest.TestCase):
    """Writes the test problem in a temporary folder and runs it."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        (self.folder / "initial_program.py").write_text(INITIAL_PROGRAM, encoding="utf-8")
        (self.folder / "evaluation.py").write_text(EVALUATION, encoding="utf-8")
        self.console = ""

    def write_problem(self, server: FakeLLMServer, **changes: Any) -> Path:
        """Write the problem file, its llm section pointing at the fake server."""
        settings: dict[str, Any] = {"snapshot_every": 2, **changes}
        lines = [
            "name: test",
            "description: Make run() return a large number.",
            "entry_functions: [run]",
            *(f"{key}: {json.dumps(value)}" for key, value in settings.items()),
            "llm:",
            f"  api_base: {server.url}",
            "  retries: 0",
            "  models:",
            "    - name: test-model",
        ]
        path = self.folder / "problem.yaml"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def settings(self, server: FakeLLMServer, iterations: int = 3, **changes: Any) -> RunSettings:
        problem_changes = changes.pop("problem", {})
        values: dict[str, Any] = {
            "initial_program": self.folder / "initial_program.py",
            "evaluation_file": self.folder / "evaluation.py",
            "problem_file": self.write_problem(server, **problem_changes),
            "output": self.folder / "run",
            "iterations": iterations,
            "seed": 1,
            "unsafe_local_sandbox": True,
        }
        values.update(changes)
        return RunSettings(**values)

    def run_quietly(self, settings: RunSettings) -> Database:
        """Run, keeping the console's lines in self.console."""
        console = io.StringIO()
        with contextlib.redirect_stdout(console):
            try:
                return run(settings)
            finally:
                self.console = console.getvalue()

    def run_with(
        self, replies: Sequence[PreparedReply], iterations: int = 3, **changes: Any
    ) -> Database:
        """Serve the replies (after the start-up check's) and run.

        The fake server gives its replies in order, then again from the first.
        """
        self.server = serve(self, ["OK", *replies], **changes.pop("server", {}))
        return self.run_quietly(self.settings(self.server, iterations, **changes))

    @property
    def storage(self) -> Storage:
        return Storage(self.folder / "run")

    def children_statuses(self) -> list[Status]:
        return [p.result.status for p in self.storage.load_programs() if p.llm is not None]

    def stop_reason(self) -> str | None:
        info = self.storage.read_run_info()
        assert info is not None
        return info.sessions[-1].end


class TestOneRun(LoopTestCase):
    def test_a_run_stores_everything_in_its_folder(self) -> None:
        self.run_with([reply_with("2"), reply_with("5"), reply_with("3")], iterations=3)
        storage = self.storage
        programs = storage.load_programs()
        # The initial program, its copy on island 0, and three children.
        self.assertEqual(
            [program.origin.value for program in programs], ["initial", "copy", "llm", "llm", "llm"]
        )
        self.assertEqual([row.iteration for row in storage.load_history()], [1, 2, 3])
        self.assertEqual(len(storage.load_llm_calls()), 3)
        self.assertIn("return 5", storage.best_path.read_text(encoding="utf-8"))
        self.assertEqual(
            sorted(path.name for path in storage.snapshots_folder.iterdir()),
            ["iteration_0000.py", "iteration_0002.py"],
        )
        self.assertTrue(storage.problem_copy_path.is_file())
        self.assertIn(
            "Run finished: 3 iterations completed.",
            (self.folder / "run" / "log.txt").read_text(encoding="utf-8"),
        )
        self.assertEqual(self.stop_reason(), "3 iterations completed")

    def test_child_keeps_its_description_score_and_call(self) -> None:
        self.run_with([reply_with("4", "Returns four.")], iterations=1)
        child = self.storage.load_programs()[-1]
        self.assertEqual(child.result.score, 4.0)
        self.assertEqual(child.description, "Returns four.")
        self.assertEqual(child.result.feedback, "run() returned 4.")
        assert child.llm is not None
        self.assertEqual((child.llm.model, child.llm.input_tokens), ("test-model", 120))
        self.assertEqual(child.generation, 1)

    def test_prompt_shows_the_parent_and_the_best_score(self) -> None:
        self.run_with([reply_with("6"), reply_with("2")], iterations=2)
        second_prompt = self.server.bodies[2]["messages"][1]["content"]
        self.assertIn("best score so far in this run: 6", second_prompt)
        self.assertIn("```python\n# EVOLVE-BLOCK-START", second_prompt)
        system = self.server.bodies[1]["messages"][0]["content"]
        self.assertIn("Make run() return a large number.", system)

    def test_children_become_parents(self) -> None:
        self.run_with([reply_with(str(n)) for n in range(2, 12)], iterations=10)
        programs = self.storage.load_programs()
        ids = {program.id for program in programs}
        self.assertTrue(all(program.parent_id in ids for program in programs[1:]))
        self.assertGreater(max(program.generation for program in programs), 1)

    def test_console_shows_one_line_per_iteration(self) -> None:
        self.run_with([reply_with("2"), reply_with("-1")], iterations=2)
        self.assertIn("Iteration 1/2: island 0, test-model: ok 2; best 2", self.console)
        self.assertIn(
            "Iteration 2/2: island 0, test-model: invalid (the value -1 is negative); best 2",
            self.console,
        )
        self.assertIn("Children by status: invalid 1, ok 1.", self.console)

    def test_seed_is_drawn_and_saved_when_none_is_given(self) -> None:
        self.run_with([reply_with("2")], iterations=1, seed=None)
        info = self.storage.read_run_info()
        assert info is not None
        self.assertIsInstance(info.seed, int)
        self.assertEqual(
            set(info.fingerprints), {"initial_program", "evaluation_file", "problem", "image"}
        )
        self.assertEqual(info.fingerprints["image"], "local")

    def test_same_seed_and_replies_give_the_same_prompts(self) -> None:
        replies = [reply_with(str(n)) for n in (3, 2, 5, 4, 6, 1)]
        prompts = []
        for attempt in range(2):
            self.run_with(replies, iterations=6, output=self.folder / f"run{attempt}")
            prompts.append([body["messages"][1]["content"] for body in self.server.bodies[1:]])
        # Programs differ only by their ids, which are not in the prompts.
        self.assertEqual(prompts[0], prompts[1])


class TestStatuses(LoopTestCase):
    def test_each_kind_of_child_is_stored_with_its_status(self) -> None:
        outside_change = reply_with("2").replace("def run():", "def run(x=0):")
        self.run_with(
            [
                outside_change,
                "I could not think of anything.",
                reply_with("-3"),
                reply_with("[][1]"),
                reply_with("1"),
            ],
            iterations=5,
        )
        programs = [p for p in self.storage.load_programs() if p.llm is not None]
        statuses = [program.result.status for program in programs]
        self.assertEqual(
            statuses,
            [Status.REJECTED, Status.REJECTED, Status.INVALID, Status.FAILED, Status.REJECTED],
        )
        errors = [str(program.result.error) for program in programs]
        self.assertIn("code outside the evolve blocks was changed", errors[0])
        self.assertIn("syntax error", errors[1])
        self.assertEqual(errors[2], "the value -3 is negative")
        self.assertIn("IndexError", errors[3])
        # The same program as the initial one.
        self.assertIn("same program as", errors[4])

    def test_failed_llm_call_skips_the_iteration_which_still_counts(self) -> None:
        self.run_with([500, reply_with("2")], iterations=2)
        history = self.storage.load_history()
        self.assertEqual([row.status for row in history], ["skipped", "ok"])
        self.assertEqual([row.completed for row in history], [1, 2])
        calls = self.storage.load_llm_calls()
        self.assertIsNone(calls[0].reply)
        self.assertIn("InternalServerError", str(calls[0].error))

    def test_model_failing_three_times_in_a_row_ends_the_run(self) -> None:
        self.run_with([500] * 20, iterations=10)
        self.assertEqual(len(self.storage.load_history()), 3)
        self.assertEqual(self.stop_reason(), "no LLM model left")

    def test_infrastructure_errors_in_a_row_end_the_run(self) -> None:
        self.run_with([reply_with("13")] * 10, iterations=10)
        self.assertEqual(self.children_statuses(), [Status.ERROR] * 3)
        self.assertEqual(self.stop_reason(), "too many errors in a row (3)")

    def test_a_working_child_resets_the_error_count(self) -> None:
        replies = [reply_with("13"), reply_with("13"), reply_with("2"), reply_with("13")]
        self.run_with(replies, iterations=4)
        self.assertEqual(len(self.storage.load_history()), 4)
        self.assertEqual(self.stop_reason(), "4 iterations completed")

    def test_error_programs_do_not_block_their_code(self) -> None:
        # An error is not the program's fault: the same code may be tried again.
        self.run_with([reply_with("13"), reply_with("13")], iterations=2)
        self.assertEqual(self.children_statuses(), [Status.ERROR, Status.ERROR])


class TestRefusals(LoopTestCase):
    def test_initial_program_must_work(self) -> None:
        (self.folder / "initial_program.py").write_text(program_returning("-1"), encoding="utf-8")
        with self.assertRaisesRegex(RunError, "must work, but it is invalid"):
            self.run_with([], iterations=1)

    def test_initial_program_needs_its_evolve_blocks(self) -> None:
        (self.folder / "initial_program.py").write_text(
            "def run():\n    return 1\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(RunError, "evolve blocks are broken"):
            self.run_with([], iterations=1)

    def test_folder_holding_a_run_is_refused_for_now(self) -> None:
        self.run_with([reply_with("2")], iterations=1)
        with self.assertRaisesRegex(RunError, "already holds a run"):
            self.run_with([reply_with("2")], iterations=1)


class TestWorkers(LoopTestCase):
    def test_several_workers_run_at_the_same_time(self) -> None:
        replies = [reply_with(str(n)) for n in (2, 3, 4, 5)]
        started = time.monotonic()
        self.run_with(replies, iterations=4, workers=4, server={"delay": 1.0})
        elapsed = time.monotonic() - started
        # One at a time would take at least 5 s (the check, then 4 replies).
        self.assertLess(elapsed, 4.5)
        self.assertEqual(len(self.storage.load_history()), 4)

    def test_identical_children_in_flight_are_evaluated_once(self) -> None:
        self.run_with([reply_with("7")] * 2, iterations=2, workers=2, server={"delay": 0.5})
        statuses = self.children_statuses()
        self.assertEqual(sorted(statuses), [Status.OK, Status.REJECTED])
        rejected = [p for p in self.storage.load_programs() if p.result.status is Status.REJECTED]
        self.assertIn("still being evaluated", str(rejected[0].result.error))

    def test_only_the_main_thread_writes_every_line_whole(self) -> None:
        self.run_with([reply_with(str(n)) for n in range(2, 10)], iterations=8, workers=4)
        self.assertEqual(len(self.storage.load_programs()), 10)
        self.assertEqual([row.completed for row in self.storage.load_history()], list(range(1, 9)))


if __name__ == "__main__":
    unittest.main()
