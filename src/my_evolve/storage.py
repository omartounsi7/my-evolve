"""The Storage class: the run folder (D47, D69).

Every line is written as soon as its program, call or iteration is done, and reaches the
disk before the write returns, so nothing finished is lost if the run stops abruptly.

    programs.jsonl       one line per program: the initial program, its island copies,
                         every child whatever its status, every migrant
    llm_calls.jsonl      one line per LLM call: the user message, the reply, the tokens
    history.csv          one row per completed iteration: the progress of the run
    best_program.py      the best program so far, under a comment header
    best/iteration_0010.py   the best program after every snapshot_every iterations
    run.json             the run's id, its seed, and one record per session
    problem.yaml         a copy of the problem file
    log.txt              everything logged (logs.py)

Only the main thread uses the run folder (D36).
"""

import csv
import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from my_evolve.program import Program

# The files of the run folder
PROGRAMS_FILE = "programs.jsonl"
LLM_CALLS_FILE = "llm_calls.jsonl"
HISTORY_FILE = "history.csv"
BEST_PROGRAM_FILE = "best_program.py"
SNAPSHOT_FOLDER = "best"
RUN_FILE = "run.json"
PROBLEM_COPY = "problem.yaml"


@dataclass
class HistoryRow:
    """One completed iteration: one row of history.csv."""

    # The iteration's number
    iteration: int
    # How many iterations were completed with it, this one included
    completed: int
    # The child's id; empty when there is no child (a failed LLM call)
    program_id: str
    # The child's status; "skipped" when the LLM call failed
    status: str
    # The child's score; None when it has none
    score: float | None
    # The best score of the run so far, and the id of the program that has it
    best_score: float | None
    best_id: str
    # The model drawn for the iteration
    model: str


@dataclass
class RunInfo:
    """What run.json holds (D50)."""

    # Identifies the run; its containers are labelled with it
    run_id: str
    # The seed of the run's random generator
    seed: int
    # One record per session: when it ran, how it was started, how it ended
    sessions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return the information as plain JSON values."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunInfo":
        """Rebuild the information from what to_dict wrote."""
        return cls(run_id=data["run_id"], seed=data["seed"], sessions=list(data["sessions"]))


def header(program: Program, title: str) -> str:
    """Return the comment header of a saved best program: score, iteration, id, description."""
    lines = [
        f"# {title}",
        f"# Score: {program.result.score}",
        f"# Iteration: {program.iteration}",
        f"# Id: {program.id}",
    ]
    if program.description:
        lines.append("# Description:")
        lines.extend(f"#   {line}".rstrip() for line in program.description.splitlines())
    return "\n".join(lines) + "\n\n"


class Storage:
    """Owns one run folder: appends its lines, rewrites its best program, keeps run.json."""

    def __init__(self, folder: Path) -> None:
        """Prepare to write into folder, creating it if needed."""
        # The run folder
        self.folder: Path = folder
        folder.mkdir(parents=True, exist_ok=True)

    def holds_a_run(self) -> bool:
        """Return True once programs have been saved here."""
        return (self.folder / PROGRAMS_FILE).exists()

    def append_line(self, file_name: str, line: str) -> None:
        """Add one line to a file, and make sure it reaches the disk before returning."""
        with (self.folder / file_name).open("a", encoding="utf-8", newline="") as file:
            file.write(line + "\n")
            file.flush()
            os.fsync(file.fileno())

    def append_program(self, program: Program) -> None:
        """Add a program to programs.jsonl."""
        # allow_nan=False: scores are finite numbers or null, so the file is plain JSON.
        self.append_line(PROGRAMS_FILE, json.dumps(program.to_dict(), allow_nan=False))

    def append_llm_call(self, record: dict[str, Any]) -> None:
        """Add an LLM call's record to llm_calls.jsonl."""
        self.append_line(LLM_CALLS_FILE, json.dumps(record, allow_nan=False))

    def append_history(self, row: HistoryRow) -> None:
        """Add a completed iteration's row to history.csv, with its header first if new."""
        path = self.folder / HISTORY_FILE
        values = asdict(row)
        if not path.exists():
            self.append_line(HISTORY_FILE, ",".join(values))
        cells = ["" if value is None else str(value) for value in values.values()]
        with path.open("a", encoding="utf-8", newline="") as file:
            csv.writer(file, lineterminator="\n").writerow(cells)
            file.flush()
            os.fsync(file.fileno())

    def write_best(self, program: Program) -> None:
        """Rewrite best_program.py: a comment header, then the program's code."""
        text = header(program, "Best program of the run") + program.code
        self.write_whole(self.folder / BEST_PROGRAM_FILE, text)

    def write_snapshot(self, program: Program, completed: int) -> None:
        """Write best/iteration_NNNN.py: the best program after that many iterations."""
        folder = self.folder / SNAPSHOT_FOLDER
        folder.mkdir(exist_ok=True)
        title = f"Best program after {completed} iterations"
        self.write_whole(
            folder / f"iteration_{completed:04d}.py", header(program, title) + program.code
        )

    def save_problem(self, path: Path) -> None:
        """Copy the problem file into the run folder, as problem.yaml."""
        shutil.copyfile(path, self.folder / PROBLEM_COPY)

    def read_run_info(self) -> RunInfo | None:
        """Return the content of run.json, or None if there is none yet."""
        path = self.folder / RUN_FILE
        if not path.exists():
            return None
        return RunInfo.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def write_run_info(self, info: RunInfo) -> None:
        """Write run.json whole, or not at all."""
        self.write_whole(self.folder / RUN_FILE, json.dumps(info.to_dict(), indent=2) + "\n")

    def write_whole(self, path: Path, text: str) -> None:
        """Write a file through a temporary file then a rename, so a crash never leaves half
        of it."""
        temporary = path.with_name(path.name + ".tmp")
        with temporary.open("w", encoding="utf-8") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
