"""Checks the run folder: lines that reach the disk, best programs, run.json."""

import ast
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from my_evolve.checks import fingerprint
from my_evolve.program import Program, Result, Status
from my_evolve.storage import HistoryRow, RunInfo, Storage


def program(description: str | None = None) -> Program:
    code = "# EVOLVE-BLOCK-START\ndef solve():\n    return 2\n# EVOLVE-BLOCK-END\n"
    return Program(code, Result(Status.OK, score=2.0), iteration=3, description=description)


class StorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory())) / "run"
        self.storage = Storage(self.folder)

    def test_lines_are_appended_and_reach_the_disk(self) -> None:
        """Each append is flushed and synced before it returns."""
        with mock.patch("os.fsync", wraps=os.fsync) as fsync:
            self.storage.append_program(program())
            self.storage.append_llm_call({"iteration": 1, "reply": "x"})
        self.assertEqual(fsync.call_count, 2)
        self.assertTrue(self.storage.holds_a_run())
        lines = (self.folder / "programs.jsonl").read_text().splitlines()
        self.assertEqual(json.loads(lines[0])["iteration"], 3)

    def test_history_rows_with_their_header(self) -> None:
        self.storage.append_history(HistoryRow(1, 1, "a", "ok", 0.5, 0.5, "a", "m"))
        self.storage.append_history(HistoryRow(2, 2, "", "skipped", None, 0.5, "a", "m"))
        self.assertEqual(
            (self.folder / "history.csv").read_text(),
            "iteration,completed,program_id,status,score,best_score,best_id,model\n"
            "1,1,a,ok,0.5,0.5,a,m\n"
            "2,2,,skipped,,0.5,a,m\n",
        )

    def test_the_best_programs_header_is_comments_only(self) -> None:
        """best_program.py, description of several lines included, is the same program."""
        best = program("Rings of circles.\nThen a local search.")
        self.storage.write_best(best)
        text = (self.folder / "best_program.py").read_text()
        self.assertIn("# Description:\n#   Rings of circles.\n#   Then a local search.\n", text)
        self.assertEqual(fingerprint(ast.parse(text)), fingerprint(ast.parse(best.code)))
        self.storage.write_snapshot(best, 20)
        self.assertTrue((self.folder / "best" / "iteration_0020.py").exists())

    def test_run_json_round_trip_and_a_crash_while_writing_it(self) -> None:
        """A crash while writing leaves the previous run.json whole."""
        info = RunInfo("abc", 7, [{"started_at": "now"}])
        self.storage.write_run_info(info)
        self.assertEqual(self.storage.read_run_info(), info)
        with mock.patch("os.replace", side_effect=OSError("disk full")), self.assertRaises(OSError):
            self.storage.write_run_info(RunInfo("abc", 7, [{}, {}]))
        self.assertEqual(self.storage.read_run_info(), info)

    def test_no_run_json_yet(self) -> None:
        self.assertIsNone(self.storage.read_run_info())
        self.assertFalse(self.storage.holds_a_run())


if __name__ == "__main__":
    unittest.main()
