"""Checks that the loop runs from start to finish, and the command line around it.

The end-to-end test of the implementation plan: the toy problem, evolved with a fake LLM.
It keeps passing at every step, and grows with every phase.
"""

import contextlib
import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from fakes import FakeLLM

from my_evolve.database import Database
from my_evolve.evaluator import Evaluator
from my_evolve.llm import Ensemble, LLMError
from my_evolve.loop import RunError, run, summary
from my_evolve.problem import IslandSettings, ParentSettings, Problem
from my_evolve.program import Origin, Result, Status
from my_evolve.sandbox import LocalSandbox
from my_evolve.storage import HistoryRow, Storage

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

        # The initial program, its copy on the island, then one child per iteration,
        # except the skipped one.
        programs = list(database.programs.values())
        self.assertEqual([program.iteration for program in programs], [0, 0, 1, 2, 3, 5])
        self.assertEqual(
            [program.origin for program in programs[:2]], [Origin.INITIAL, Origin.COPY]
        )
        scores = [program.result.score for program in programs]
        self.assertEqual(scores, [1.0, 1.0, 5.0, None, None, 7.0])
        children = programs[2:]
        self.assertIn("ZeroDivisionError", children[1].result.error or "")
        self.assertEqual(children[2].result.status, Status.REJECTED)
        self.assertIn("must define the function solve()", children[2].result.error or "")
        self.assertEqual((children[0].description, children[2].description), ("Returns 5.", None))
        for child in children:
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
        self.assertIn("Iteration 1/5, island 0, fake-model: score 5.000000 (best 5.0", console)
        self.assertIn("Iteration 2/5, island 0, fake-model: failed: ZeroDivisionError", console)
        self.assertIn(
            "Iteration 4/5, island 0, fake-model: skipped, no reply (fake-model: the server is",
            console,
        )

    def test_the_run_folder(self) -> None:
        """programs.jsonl has one line per program; best_program.py holds the best one."""
        database, _, _ = run_toy([reply_returning("4"), reply_returning("2")], self.output)
        lines = (self.output / "programs.jsonl").read_text().splitlines()
        saved = [json.loads(line) for line in lines]
        self.assertEqual([entry["id"] for entry in saved], list(database.programs))
        self.assertEqual([entry["result"]["score"] for entry in saved], [1.0, 1.0, 4.0, 2.0])
        best_file = (self.output / "best_program.py").read_text()
        self.assertTrue(best_file.startswith("# Best program of the run\n# Score: 4.0\n"))
        self.assertIn("# Iteration: 1\n", best_file)
        self.assertIn("# Description:\n#   Returns 4.\n", best_file)
        self.assertIn("    return 4\n", best_file)

    def test_history_snapshots_and_the_session(self) -> None:
        """history.csv has a row per completed iteration; snapshots every 2 iterations;
        problem.yaml is copied; run.json records the session and how it ended."""
        problem = replace(Problem.load(TOY_FOLDER / "problem.yaml"), snapshot_every=2)
        replies: list[str | Exception] = [
            reply_returning("4"),
            LLMError("fake-model", "down"),
            reply_returning("2"),
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            database = run(
                problem=problem,
                initial_code=(TOY_FOLDER / "initial_program.py").read_text(),
                ensemble=Ensemble([FakeLLM(replies)], [1.0], 3),
                evaluator=Evaluator(TOY_FOLDER / "evaluation.py", LocalSandbox(), STAGE_TIME_LIMIT),
                iterations=3,
                output=self.output,
                seed=0,
                problem_file=TOY_FOLDER / "problem.yaml",
                command=["scripts/run.py", "--iterations", "3"],
            )
        with (self.output / "history.csv").open() as file:
            rows = list(csv.DictReader(file))
        self.assertEqual([row["status"] for row in rows], ["ok", "skipped", "ok"])
        self.assertEqual([row["best_score"] for row in rows], ["4.0", "4.0", "4.0"])
        self.assertEqual((rows[1]["program_id"], rows[1]["score"]), ("", ""))
        self.assertEqual(rows[0]["model"], "fake-model")
        snapshots = sorted(path.name for path in (self.output / "best").iterdir())
        self.assertEqual(snapshots, ["iteration_0000.py", "iteration_0002.py"])
        self.assertIn("# Score: 4.0", (self.output / "best" / "iteration_0002.py").read_text())
        self.assertEqual(
            (self.output / "problem.yaml").read_text(), (TOY_FOLDER / "problem.yaml").read_text()
        )
        info = json.loads((self.output / "run.json").read_text())
        (session,) = info["sessions"]
        self.assertEqual(session["command"], ["scripts/run.py", "--iterations", "3"])
        self.assertEqual(session["end"], "every iteration done")
        self.assertEqual(session["flags"], {"iterations": 3, "workers": 1, "verbose": False})
        self.assertEqual(session["llm"]["models"][0]["name"], "fake-model")
        self.assertIsNotNone(session["ended_at"])
        self.assertTrue(all(program.created_at for program in database.programs.values()))

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
        self.assertEqual(len(database.programs), 2 + 6)
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

    def test_children_live_on_the_island_of_their_iteration(self) -> None:
        """With three islands, each starts with a copy; a child lives on its parent's island."""
        problem = replace(
            Problem.load(TOY_FOLDER / "problem.yaml"), islands=IslandSettings(count=3)
        )
        with contextlib.redirect_stdout(io.StringIO()):
            database = run(
                problem=problem,
                initial_code=(TOY_FOLDER / "initial_program.py").read_text(),
                ensemble=Ensemble(
                    [FakeLLM([reply_returning(str(n)) for n in range(2, 8)])], [1.0], 3
                ),
                evaluator=Evaluator(TOY_FOLDER / "evaluation.py", LocalSandbox(), STAGE_TIME_LIMIT),
                iterations=6,
                output=self.output,
                seed=4,
            )
        copies = [
            program for program in database.programs.values() if program.origin is Origin.COPY
        ]
        self.assertEqual(sorted(copy.island or 0 for copy in copies), [0, 1, 2])
        children = [
            program for program in database.programs.values() if program.origin is Origin.LLM
        ]
        self.assertEqual(len(children), 6)
        for child in children:
            self.assertEqual(child.island, database.programs[child.parent_id or ""].island)
        self.assertGreater(len({child.island for child in children}), 1)

    def test_migrations_happen_every_interval_and_are_stored(self) -> None:
        """Every 2 completed iterations, skipped ones included, copies are stored."""
        problem = replace(
            Problem.load(TOY_FOLDER / "problem.yaml"),
            islands=IslandSettings(count=2, migration_interval=2, migrants="best"),
        )
        replies: list[str | Exception] = [
            reply_returning("5"),
            LLMError("fake-model", "down"),
            reply_returning("6"),
            reply_returning("7"),
        ]
        console = io.StringIO()
        with contextlib.redirect_stdout(console):
            run(
                problem=problem,
                initial_code=(TOY_FOLDER / "initial_program.py").read_text(),
                ensemble=Ensemble([FakeLLM(replies)], [1.0], 3),
                evaluator=Evaluator(TOY_FOLDER / "evaluation.py", LocalSandbox(), STAGE_TIME_LIMIT),
                iterations=4,
                output=self.output,
                seed=2,
            )
        saved = [
            json.loads(line) for line in (self.output / "programs.jsonl").read_text().splitlines()
        ]
        migrants = [
            entry for entry in saved if entry["origin"] == "copy" and entry["iteration"] > 0
        ]
        self.assertEqual(sorted({entry["iteration"] for entry in migrants}), [2, 4])
        self.assertEqual(len(migrants), 4)
        self.assertIn("Migration after iteration 2: 2 programs copied", console.getvalue())

    def test_with_openevolves_rule_the_child_lives_on_the_drawn_island(self) -> None:
        """The archive branch may give a parent from another island, or the initial program
        (on none); the child still lives on its iteration's island."""
        problem = replace(
            Problem.load(TOY_FOLDER / "problem.yaml"),
            islands=IslandSettings(count=3),
            parents=ParentSettings(strategy="openevolve"),
        )
        with contextlib.redirect_stdout(io.StringIO()):
            database = run(
                problem=problem,
                initial_code=(TOY_FOLDER / "initial_program.py").read_text(),
                ensemble=Ensemble(
                    [FakeLLM([reply_returning(str(n)) for n in range(2, 10)])], [1.0], 3
                ),
                evaluator=Evaluator(TOY_FOLDER / "evaluation.py", LocalSandbox(), STAGE_TIME_LIMIT),
                iterations=8,
                output=self.output,
                seed=5,
            )
        children = [
            program for program in database.programs.values() if program.origin is Origin.LLM
        ]
        self.assertEqual(len(children), 8)
        self.assertTrue(all(child.island in (0, 1, 2) for child in children))
        parent_islands = [database.programs[child.parent_id or ""].island for child in children]
        self.assertTrue(
            any(
                parent is None or parent != child.island
                for parent, child in zip(parent_islands, children, strict=True)
            )
        )

    def run_with_workers(self, llm: FakeLLM, iterations: int, workers: int) -> Database:
        """Evolve the toy problem with that LLM and that many workers."""
        with contextlib.redirect_stdout(io.StringIO()):
            return run(
                problem=Problem.load(TOY_FOLDER / "problem.yaml"),
                initial_code=(TOY_FOLDER / "initial_program.py").read_text(),
                ensemble=Ensemble([llm], [1.0], 3),
                evaluator=Evaluator(TOY_FOLDER / "evaluation.py", LocalSandbox(), STAGE_TIME_LIMIT),
                iterations=iterations,
                output=self.output,
                seed=0,
                workers=workers,
            )

    def test_several_iterations_in_flight_at_once(self) -> None:
        """With 3 workers, 3 LLM calls wait at once; every iteration still completes once."""
        llm = FakeLLM([reply_returning(str(n)) for n in range(1, 7)], delay=0.5)
        started = time.monotonic()
        database = self.run_with_workers(llm, iterations=6, workers=3)
        self.assertEqual(llm.most_at_once, 3)
        self.assertLess(time.monotonic() - started, 6 * 0.5)
        children = [p for p in database.programs.values() if p.origin is Origin.LLM]
        self.assertEqual(sorted(child.iteration for child in children), [1, 2, 3, 4, 5, 6])
        with (self.output / "history.csv").open() as file:
            rows = list(csv.DictReader(file))
        self.assertEqual(sorted(int(row["completed"]) for row in rows), [1, 2, 3, 4, 5, 6])

    def test_only_the_main_thread_writes_the_run_folder(self) -> None:
        main = threading.main_thread()
        writers: set[str] = set()
        original = Storage.append_line

        def watched(storage: Storage, file_name: str, line: str) -> None:
            writers.add(threading.current_thread().name)
            original(storage, file_name, line)

        llm = FakeLLM([reply_returning(str(n)) for n in range(1, 5)], delay=0.1)
        with mock.patch.object(Storage, "append_line", watched):
            self.run_with_workers(llm, iterations=4, workers=2)
        self.assertEqual(writers, {main.name})

    def test_identical_children_in_flight_are_evaluated_once(self) -> None:
        """Two workers propose the same child at once: the second is a duplicate of the first."""
        llm = FakeLLM([reply_returning("5"), reply_returning("5")], delay=0.3)
        database = self.run_with_workers(llm, iterations=2, workers=2)
        children = sorted(
            (p for p in database.programs.values() if p.origin is Origin.LLM),
            key=lambda program: program.result.status.value,
        )
        self.assertEqual([child.result.status for child in children], [Status.OK, Status.REJECTED])
        self.assertEqual(children[1].result.error, f"same program as {children[0].id}")

    def run_toy_with(
        self, replies: list[str | Exception], iterations: int, evaluator: Evaluator | None = None
    ) -> tuple[Database, str]:
        """Evolve the toy problem with these replies; return the database and the console."""
        console = io.StringIO()
        with contextlib.redirect_stdout(console):
            database = run(
                problem=Problem.load(TOY_FOLDER / "problem.yaml"),
                initial_code=(TOY_FOLDER / "initial_program.py").read_text(),
                ensemble=Ensemble([FakeLLM(replies)], [1.0], 3),
                evaluator=evaluator
                or Evaluator(TOY_FOLDER / "evaluation.py", LocalSandbox(), STAGE_TIME_LIMIT),
                iterations=iterations,
                output=self.output,
                seed=0,
            )
        return database, console.getvalue()

    def test_an_unexpected_exception_is_recorded_and_the_run_goes_on(self) -> None:
        """An exception in a worker, other than an LLM failure, records the iteration as an
        error; an exception in the evaluation gives the child the status error."""

        class BreakingEvaluator(Evaluator):
            def evaluate(self, code: str) -> Result:
                if "return 8" in code:
                    raise RuntimeError("the evaluator broke")
                return super().evaluate(code)

        evaluator = BreakingEvaluator(
            TOY_FOLDER / "evaluation.py", LocalSandbox(), STAGE_TIME_LIMIT
        )
        replies: list[str | Exception] = [
            RuntimeError("the worker broke"),
            reply_returning("8"),
            reply_returning("5"),
        ]
        database, console = self.run_toy_with(replies, 3, evaluator)
        self.assertIn("Iteration 1/3, island 0, fake-model: error: RuntimeError", console)
        children = [p for p in database.programs.values() if p.origin is Origin.LLM]
        self.assertEqual([child.result.status for child in children], [Status.ERROR, Status.OK])
        self.assertIn(
            "evaluation: RuntimeError('the evaluator broke')", children[0].result.error or ""
        )
        with (self.output / "history.csv").open() as file:
            self.assertEqual(
                [row["status"] for row in csv.DictReader(file)], ["error", "error", "ok"]
            )

    def test_three_errors_in_a_row_stop_the_run(self) -> None:
        """Errors are counted apart from LLM failures, which do not break the count."""
        broke = RuntimeError("broke")
        down = LLMError("fake-model", "down")
        replies: list[str | Exception] = [broke, down, broke, down, broke]
        _, console = self.run_toy_with(replies, 10)
        self.assertIn("Run finished: 5 iterations done, too many errors in a row.", console)
        self.assertNotIn("dropped", console)

    def test_an_error_in_the_main_thread_stops_the_run_at_once(self) -> None:
        """The disk refusing a write is not an iteration's error: the run stops, and says so."""
        original = Storage.append_history
        calls = []

        def failing(storage: Storage, row: HistoryRow) -> None:
            calls.append(row)
            if len(calls) == 2:
                raise OSError("disk full")
            original(storage, row)

        with mock.patch.object(Storage, "append_history", failing), self.assertRaises(OSError):
            self.run_toy_with([reply_returning(str(n)) for n in range(2, 6)], 4)
        session = json.loads((self.output / "run.json").read_text())["sessions"][0]
        self.assertEqual(session["end"], "failed: OSError('disk full')")

    def test_a_duplicate_costs_no_evaluation(self) -> None:
        """A child identical to an earlier program (comments aside) is rejected."""
        initial = (TOY_FOLDER / "initial_program.py").read_text()
        replies: list[str | Exception] = [
            reply_returning("5"),
            "```python\n" + initial.replace("return 1.0", "return 1.0  # unchanged") + "```",
            reply_returning("5"),
        ]
        database, _, _ = run_toy(replies, self.output)
        first, copy, *children = database.programs.values()
        self.assertEqual(
            [child.result.status for child in children],
            [Status.OK, Status.REJECTED, Status.REJECTED],
        )
        self.assertEqual(children[1].result.error, f"same program as {first.id}")
        self.assertEqual(children[2].result.error, f"same program as {children[0].id}")
        self.assertEqual(children[1].result.duration, 0.0)
        # Each child records the example programs its prompt showed: programs of its island.
        self.assertEqual(children[0].example_ids, ())
        self.assertEqual(
            set(children[1].example_ids), {copy.id, children[0].id} - {children[1].parent_id}
        )

    def test_the_log_and_the_summary(self) -> None:
        """log.txt gets the details the console leaves out; the run ends with a summary."""
        replies: list[str | Exception] = [
            reply_returning("5"),
            reply_returning("1 / 0"),
            LLMError("fake-model", "down"),
        ]
        _, _, console = run_toy(replies, self.output)
        log = (self.output / "log.txt").read_text()
        self.assertIn("Iteration 1: island 0, parent", log)
        self.assertNotIn("Iteration 1: island 0, parent", console)
        self.assertIn("INFO my_evolve.loop: Seed: 0", log)
        self.assertIn("Run finished: 3 iterations done, every iteration done.", console)
        self.assertIn("Best score: 5.000000, found at iteration 1.", console)
        self.assertIn("Children: 2 (1 failed, 1 ok).", console)
        self.assertRegex(console, r"fake-model: 2 replies, [\d,]+ input and \d+ output tokens\.")

    def test_verbose_shows_the_details(self) -> None:
        llm = FakeLLM([reply_returning("5")])
        console = io.StringIO()
        with contextlib.redirect_stdout(console):
            run(
                problem=Problem.load(TOY_FOLDER / "problem.yaml"),
                initial_code=(TOY_FOLDER / "initial_program.py").read_text(),
                ensemble=Ensemble([llm], [1.0], max_failures=3),
                evaluator=Evaluator(TOY_FOLDER / "evaluation.py", LocalSandbox(), STAGE_TIME_LIMIT),
                iterations=1,
                output=self.output,
                seed=0,
                verbose=True,
            )
        self.assertIn("Iteration 1: island 0, parent", console.getvalue())
        self.assertIn("Iteration 1: LLM 0.0 s, evaluation", console.getvalue())

    def test_the_summary_prices_tokens_when_prices_are_given(self) -> None:
        problem = Problem.load(TOY_FOLDER / "problem.yaml")
        model = replace(problem.llm.models[0], price_input=2.0, price_output=10.0)
        problem = replace(problem, llm=replace(problem.llm, models=(model,)))
        database, _, _ = run_toy([reply_returning("5")], self.output)
        (child,) = [p for p in database.programs.values() if p.origin is Origin.LLM]
        assert child.llm is not None
        cost = (child.llm.input_tokens * 2.0 + child.llm.output_tokens * 10.0) / 1e6
        lines = summary(problem, database, 1, "every iteration done")
        self.assertTrue(lines[-1].endswith(f"tokens, ${cost:.4f}."))

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
        self.assertEqual(info["sessions"][0]["system_message"], llm.prompts[0].system)
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
        self.assertFalse((self.output / "programs.jsonl").exists())

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
            self.assertFalse((output / "programs.jsonl").exists())

    def test_no_api_key_reaches_any_output(self) -> None:
        """A key is read from its variable, and never printed nor written anywhere."""
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "problem.yaml"
            config.write_text(
                (TOY_FOLDER / "problem.yaml")
                .read_text()
                .replace(
                    "api_base: http://localhost:1/v1",
                    "api_base: http://localhost:1/v1\n  api_key: ${MY_EVOLVE_TEST_SECRET}",
                )
            )
            output = Path(folder) / "run"
            completed = subprocess.run(
                [sys.executable, str(RUN_SCRIPT), *self.toy_arguments(output, config), "--verbose"],
                capture_output=True,
                text=True,
                timeout=60,
                env={**os.environ, "MY_EVOLVE_TEST_SECRET": "sk-very-secret-value"},
            )
            self.assertEqual(completed.returncode, 1, completed.stderr)
            written = "".join(path.read_text() for path in output.rglob("*") if path.is_file())
            for text in (completed.stdout, completed.stderr, written):
                self.assertNotIn("sk-very-secret-value", text)

    def test_the_default_run_folder(self) -> None:
        """Without --output, the run folder is runs/<problem>_<date>_<time>, from where it runs."""
        with tempfile.TemporaryDirectory() as folder:
            arguments = self.toy_arguments(Path("unused"))
            index = arguments.index("--output")
            del arguments[index : index + 2]
            subprocess.run(
                [sys.executable, str(RUN_SCRIPT), *arguments],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=folder,
            )
            (run_folder,) = (Path(folder) / "runs").iterdir()
            self.assertRegex(run_folder.name, r"^toy_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$")
            self.assertTrue((run_folder / "log.txt").exists())

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
