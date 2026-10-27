"""Checks the run folder: appended lines, the best program, run.json, and reading it all back."""

import ast
import io
import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from my_evolve.checks import fingerprint
from my_evolve.logs import setup_logging, stop_logging
from my_evolve.program import LLMUsage, Program, Result, Status
from my_evolve.storage import (
    HistoryRow,
    LLMCallRecord,
    RunInfo,
    SessionRecord,
    Storage,
    StorageError,
)

CODE = "def run():\n    return 'été ✓'\n"


def initial() -> Program:
    return Program.initial(CODE, Result(Status.OK, score=0.5), fingerprint(ast.parse(CODE)), 3)


def child_of(parent: Program, result: Result, description: str | None = None) -> Program:
    return Program.new_child(
        parent,
        code=CODE.replace("été", "hiver"),
        result=result,
        island=0,
        iteration=1,
        description=description,
        fingerprint=None,
        code_complexity=None,
        example_ids=(),
        llm=LLMUsage("m", 10, 20, 1.5),
    )


def history_row(iteration: int, status: str = "ok", score: float | None = 0.75) -> HistoryRow:
    return HistoryRow(
        iteration=iteration,
        completed=iteration,
        program_id=None if status in ("skipped", "error") else f"id-{iteration}",
        status=status,
        score=score,
        best_score=0.9487666034155601,
        best_id="best-id",
        model=None if status == "error" else "qwen3-coder:30b",
    )


def session() -> SessionRecord:
    return SessionRecord(
        started_at="2026-10-27T10:00:00+00:00",
        ended_at=None,
        git_commit="abc1234",
        command_line=["scripts/run.py", "a.py", "b.py"],
        llm={"models": [{"name": "m"}]},
        flags={"iterations": 100, "seed": None},
        system_message="You are an expert.",
    )


class StorageTestCase(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name) / "runs" / "circle_packing_1"
        self.storage = Storage(self.folder)


class TestPrograms(StorageTestCase):
    def test_folder_is_created_with_the_folders_above_it(self) -> None:
        self.assertTrue(self.folder.is_dir())

    def test_folder_is_new_until_a_program_is_saved(self) -> None:
        self.assertTrue(self.storage.is_new())
        self.storage.append_program(initial())
        self.assertFalse(self.storage.is_new())

    def test_nothing_saved_loads_as_nothing(self) -> None:
        self.assertEqual(self.storage.load_programs(), [])
        self.assertEqual(self.storage.load_history(), [])
        self.assertEqual(self.storage.load_llm_calls(), [])

    def test_programs_come_back_in_order_and_unchanged(self) -> None:
        first = initial()
        programs = [
            first,
            child_of(first, Result.failure(Status.INVALID, "circles 2 and 7 overlap"), "A grid."),
            child_of(first, Result(Status.OK, score=0.75, output_data={"radii": [0.1]})),
        ]
        for program in programs:
            self.storage.append_program(program)
        self.assertEqual(Storage(self.folder).load_programs(), programs)

    def test_each_program_is_one_line_with_null_for_a_missing_score(self) -> None:
        self.storage.append_program(child_of(initial(), Result.failure(Status.FAILED, "x")))
        lines = self.storage.programs_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn('"score": null', lines[0])
        # Text outside plain English is written as it is, not as \u escapes.
        self.assertIn("hiver ✓", lines[0])

    def test_each_append_is_forced_to_the_disk(self) -> None:
        with mock.patch("my_evolve.storage.os.fsync") as fsync:
            self.storage.append_program(initial())
        fsync.assert_called_once()

    def test_last_line_cut_off_by_a_crash_is_dropped(self) -> None:
        self.storage.append_program(initial())
        with self.storage.programs_path.open("a", encoding="utf-8") as file:
            file.write('{"id": "cut-off-in-the-midd')
        self.assertEqual(len(self.storage.load_programs()), 1)
        # The file was rewritten without it, so new lines start on a line of their own.
        self.storage.append_program(initial())
        self.assertEqual(len(self.storage.load_programs()), 2)

    def test_damaged_line_in_the_middle_is_reported(self) -> None:
        self.storage.append_program(initial())
        with self.storage.programs_path.open("a", encoding="utf-8") as file:
            file.write("not json\n")
        self.storage.append_program(initial())
        with self.assertRaisesRegex(StorageError, r"programs\.jsonl, line 2"):
            self.storage.load_programs()

    def test_last_line_without_its_newline_is_kept_and_mended(self) -> None:
        line = json.dumps(initial().to_dict())
        self.storage.programs_path.write_text(line, encoding="utf-8")
        self.assertEqual(len(self.storage.load_programs()), 1)
        self.storage.append_program(initial())
        self.assertEqual(len(self.storage.load_programs()), 2)


class TestHistoryAndCalls(StorageTestCase):
    def test_history_rows_come_back(self) -> None:
        rows = [history_row(1), history_row(2, "invalid", None), history_row(3, "skipped", None)]
        rows.append(history_row(4, "error", None))
        for row in rows:
            self.storage.append_history(row)
        self.assertEqual(self.storage.load_history(), rows)

    def test_history_starts_with_its_header_and_is_plain_csv(self) -> None:
        self.storage.append_history(history_row(1))
        lines = self.storage.history_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(
            lines[0], "iteration,completed,program_id,status,score,best_score,best_id,model"
        )
        self.assertEqual(lines[1], "1,1,id-1,ok,0.75,0.9487666034155601,best-id,qwen3-coder:30b")

    def test_cut_off_history_row_is_dropped(self) -> None:
        self.storage.append_history(history_row(1))
        with self.storage.history_path.open("a", encoding="utf-8") as file:
            file.write("2,2,id-2,o")
        self.assertEqual(self.storage.load_history(), [history_row(1)])
        self.storage.append_history(history_row(2))
        self.assertEqual(len(self.storage.load_history()), 2)

    def test_cut_off_header_is_dropped(self) -> None:
        self.storage.history_path.write_text("iteration,compl", encoding="utf-8")
        self.assertEqual(self.storage.load_history(), [])
        self.storage.append_history(history_row(1))
        self.assertEqual(self.storage.load_history(), [history_row(1)])

    def test_llm_calls_come_back(self) -> None:
        calls = [
            LLMCallRecord(
                1, "id-1", "m", "Improve it.", "```python\nx = 1\n```", 100, 20, 2.5, None
            ),
            LLMCallRecord(
                2, None, "m", "Improve it.", None, 0, 0, 300.0, "APITimeoutError: timed out"
            ),
        ]
        for call in calls:
            self.storage.append_llm_call(call)
        self.assertEqual(self.storage.load_llm_calls(), calls)


class TestBestProgram(StorageTestCase):
    def test_best_program_has_a_header_then_the_code(self) -> None:
        program = child_of(
            initial(), Result(Status.OK, score=0.75), "A grid.\nWith a corner circle."
        )
        self.storage.write_best(program)
        text = self.storage.best_path.read_text(encoding="utf-8")
        self.assertTrue(
            text.startswith("# Best program so far: score 0.75, found at iteration 1\n")
        )
        self.assertIn(f"# Program id: {program.id}\n", text)
        self.assertIn("# Description:\n#   A grid.\n#   With a corner circle.\n", text)
        self.assertTrue(text.endswith(program.code))

    def test_header_does_not_change_the_program(self) -> None:
        program = child_of(initial(), Result(Status.OK, score=0.75), "A grid.\n\nTwo paragraphs.")
        self.storage.write_best(program)
        tree = ast.parse(self.storage.best_path.read_text(encoding="utf-8"))
        self.assertEqual(fingerprint(tree), fingerprint(ast.parse(program.code)))

    def test_best_program_is_replaced_by_a_better_one(self) -> None:
        self.storage.write_best(initial())
        better = child_of(initial(), Result(Status.OK, score=0.9))
        self.storage.write_best(better)
        self.assertIn(better.id, self.storage.best_path.read_text(encoding="utf-8"))

    def test_snapshots_are_named_by_completed_iterations(self) -> None:
        self.storage.write_snapshot(initial(), 0)
        self.storage.write_snapshot(initial(), 10)
        self.assertEqual(
            sorted(path.name for path in self.storage.snapshots_folder.iterdir()),
            ["iteration_0000.py", "iteration_0010.py"],
        )
        text = self.storage.snapshot_path(10).read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# Best program after 10 completed iterations: score 0.5"))


class TestRunInfo(StorageTestCase):
    def test_no_run_info_yet(self) -> None:
        self.assertIsNone(self.storage.read_run_info())

    def test_run_info_comes_back(self) -> None:
        info = RunInfo("run-1", 42, {"initial_program": "aa", "image": "bb"}, [session()])
        self.storage.write_run_info(info)
        self.assertEqual(self.storage.read_run_info(), info)

    def test_failed_write_leaves_the_previous_file(self) -> None:
        self.storage.write_run_info(RunInfo("run-1", 42, {}, []))
        with mock.patch("my_evolve.storage.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.storage.write_run_info(RunInfo("run-2", 7, {}, []))
        info = self.storage.read_run_info()
        assert info is not None
        self.assertEqual(info.run_id, "run-1")

    def test_damaged_run_info_is_reported(self) -> None:
        self.storage.run_info_path.write_text("{", encoding="utf-8")
        with self.assertRaisesRegex(StorageError, "run.json"):
            self.storage.read_run_info()

    def test_problem_file_is_copied(self) -> None:
        source = self.folder.parent / "problem_source.yaml"
        source.write_text("name: test\n", encoding="utf-8")
        self.storage.save_problem(source)
        self.assertEqual(self.storage.problem_copy_path.read_text(encoding="utf-8"), "name: test\n")


class TestLogging(StorageTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.console = io.StringIO()
        self.addCleanup(stop_logging)

    def test_console_shows_messages_alone_and_the_file_everything(self) -> None:
        setup_logging(self.folder, verbose=False, console=self.console)
        logger = logging.getLogger("my_evolve.loop")
        logger.info("Iteration 1/10: island 0, ok, score 0.36")
        logger.debug("Parent drawn: 3f2a9c1e")
        logger.warning("The model m failed")
        stop_logging()
        self.assertEqual(
            self.console.getvalue(),
            "Iteration 1/10: island 0, ok, score 0.36\nWarning: The model m failed\n",
        )
        log = (self.folder / "log.txt").read_text(encoding="utf-8")
        self.assertIn("DEBUG   my_evolve.loop: Parent drawn: 3f2a9c1e", log)
        self.assertRegex(log, r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} INFO ")

    def test_verbose_console_shows_the_details(self) -> None:
        setup_logging(None, verbose=True, console=self.console)
        logging.getLogger("my_evolve.loop").debug("Parent drawn: 3f2a9c1e")
        self.assertIn("Parent drawn", self.console.getvalue())

    def test_setting_up_twice_does_not_log_twice(self) -> None:
        setup_logging(self.folder, verbose=False, console=self.console)
        setup_logging(self.folder, verbose=False, console=self.console)
        logging.getLogger("my_evolve.loop").info("once")
        self.assertEqual(self.console.getvalue(), "once\n")

    def test_http_requests_are_not_logged(self) -> None:
        setup_logging(self.folder, verbose=True, console=self.console)
        self.assertEqual(logging.getLogger("httpx").level, logging.WARNING)


if __name__ == "__main__":
    unittest.main()
