"""Checks the report: a run folder read back without changing it, and its drawings."""

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fakes import FakeLLM

from my_evolve.evaluator import Evaluator
from my_evolve.llm import Ensemble, LLMError
from my_evolve.loop import run
from my_evolve.problem import Problem
from my_evolve.program import Program, Result, Status
from my_evolve.report import (
    ReportError,
    RunData,
    best_at_snapshots,
    load_run,
    snapshot_counts,
    write_report,
)
from my_evolve.sandbox import LocalSandbox
from my_evolve.storage import HistoryRow

TOY_FOLDER = Path(__file__).parent / "toy"
REPORT_SCRIPT = Path(__file__).parent.parent / "scripts" / "report.py"
PNG_START = b"\x89PNG\r\n\x1a\n"


def reply_returning(value: str) -> str:
    """Return an LLM reply whose program's solve() returns that value."""
    return (
        "Here it is:\n\n```python\n# EVOLVE-BLOCK-START\n"
        f"def solve():\n    return {value}\n# EVOLVE-BLOCK-END\n```\n"
    )


def toy_run(folder: Path, replies: list[str | Exception], snapshot_every: int = 2) -> Path:
    """Evolve the toy problem into folder/run, with a problem file taking a snapshot every
    snapshot_every iterations; return the run folder."""
    problem_file = folder / "problem.yaml"
    problem_file.write_text(
        (TOY_FOLDER / "problem.yaml").read_text() + f"snapshot_every: {snapshot_every}\n"
    )
    output = folder / "run"
    with contextlib.redirect_stdout(io.StringIO()):
        run(
            problem=Problem.load(problem_file),
            initial_code=(TOY_FOLDER / "initial_program.py").read_text(),
            ensemble=Ensemble([FakeLLM(replies)], [1.0], max_failures=3),
            evaluator=Evaluator(TOY_FOLDER / "evaluation.py", LocalSandbox(), 30.0),
            iterations=len(replies),
            output=output,
            seed=0,
            problem_file=problem_file,
        )
    return output


class ReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_the_report_of_a_run(self) -> None:
        """progress.png, and the best program's output at 0, 2, 4 and the end, 5."""
        replies: list[str | Exception] = [
            reply_returning("3"),
            reply_returning("2"),
            LLMError("fake-model", "down"),
            reply_returning("7"),
            reply_returning("11"),
        ]
        output = toy_run(self.folder, replies)
        before = sorted(path.name for path in output.iterdir())
        written = write_report(output)
        names = [path.name for path in written]
        self.assertEqual(
            names,
            [
                "progress.png",
                "output_0000.png",
                "output_0002.png",
                "output_0004.png",
                "output_0005.png",
            ],
        )
        self.assertEqual((output / "report" / "progress.png").read_bytes()[:8], PNG_START)
        # The toy's visualize writes the number the best program returns.
        values = [(output / "report" / name).read_text() for name in names[1:]]
        self.assertEqual(values, ["1.0\n", "3\n", "7\n", "7\n"])
        self.assertEqual(
            sorted(path.name for path in output.iterdir()), sorted([*before, "report"])
        )

    def test_a_cut_off_last_line_is_left_out_but_not_removed(self) -> None:
        output = toy_run(self.folder, [reply_returning("3")])
        with (output / "programs.jsonl").open("a") as file:
            file.write('{"code": ')
        text = (output / "programs.jsonl").read_text()
        self.assertEqual(len(load_run(output).programs), 3)
        self.assertEqual((output / "programs.jsonl").read_text(), text)

    def test_a_folder_that_is_not_a_run_is_refused(self) -> None:
        with self.assertRaisesRegex(ReportError, "no problem.yaml: it is not a run folder"):
            load_run(self.folder)

    def test_the_script(self) -> None:
        output = toy_run(self.folder, [reply_returning("3")])
        finished = subprocess.run(
            [sys.executable, str(REPORT_SCRIPT), str(output)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(finished.returncode, 0, finished.stderr)
        self.assertIn("3 files written", finished.stdout)
        missing = subprocess.run(
            [sys.executable, str(REPORT_SCRIPT), str(self.folder)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(missing.returncode, 1)
        self.assertIn("Error:", missing.stderr)


class SnapshotTest(unittest.TestCase):
    def test_snapshot_counts(self) -> None:
        self.assertEqual(snapshot_counts(10, 25), [0, 10, 20, 25])
        self.assertEqual(snapshot_counts(10, 20), [0, 10, 20])
        self.assertEqual(snapshot_counts(10, 0), [0])

    def test_the_best_at_each_snapshot_follows_the_history(self) -> None:
        initial = Program("x = 1\n", Result(Status.OK, score=1.0))
        child = Program.new_child(initial, "x = 2\n", Result(Status.OK, score=2.0), 1)
        history = [
            HistoryRow(1, 1, child.id, "ok", 2.0, 2.0, child.id, "m"),
            HistoryRow(2, 2, "", "skipped", None, 2.0, child.id, "m"),
            HistoryRow(3, 3, "", "skipped", None, 2.0, child.id, "m"),
        ]
        problem = Problem.load(TOY_FOLDER / "problem.yaml")
        run_data = RunData(problem, [initial, child], history, None)
        self.assertEqual(best_at_snapshots(run_data), [(0, initial), (3, child)])


if __name__ == "__main__":
    unittest.main()
