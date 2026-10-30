"""The Storage class: the run folder (D47, D69).

Every line is written as soon as its program, call or iteration is done, and reaches the
disk before the write returns, so nothing finished is lost if the run stops abruptly.

    programs.jsonl       one line per program: the initial program, its island copies,
                         every child whatever its status, every migrant
    llm_calls.jsonl      one line per LLM call: the user message, the reply, the tokens
    history.csv          one row per completed iteration: the progress of the run
    best_program.py      the best program so far, under a comment header
    best/iteration_0010.py   the best program after every snapshot_every iterations
    run.json             the run's id, its seed, its fingerprints, one record per session
    problem.yaml         a copy of the problem file, from the first session
    log.txt              everything logged (logs.py)

Only the main thread uses the run folder (D36).

Reading the folder back, to continue a run (D49), a last line cut off by a crash is
dropped, and the file rewritten without it; an unreadable line elsewhere is an error.
"""

import csv
import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from my_evolve.program import Origin, Program

# The columns of history.csv, in order
HISTORY_COLUMNS = (
    "iteration",
    "completed",
    "program_id",
    "status",
    "score",
    "best_score",
    "best_id",
    "model",
)
# The files of the run folder
PROGRAMS_FILE = "programs.jsonl"
LLM_CALLS_FILE = "llm_calls.jsonl"
HISTORY_FILE = "history.csv"
BEST_PROGRAM_FILE = "best_program.py"
SNAPSHOT_FOLDER = "best"
RUN_FILE = "run.json"
PROBLEM_COPY = "problem.yaml"


class RunFolderError(Exception):
    """Raised when the run folder cannot be read back; the message names the file and line."""


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

    @classmethod
    def from_csv(cls, row: dict[str, str]) -> "HistoryRow":
        """Rebuild a row from history.csv. Raises ValueError if it is incomplete."""
        if any(value is None for value in row.values()) or set(row) != set(HISTORY_COLUMNS):
            raise ValueError("an incomplete row")
        return cls(
            iteration=int(row["iteration"]),
            completed=int(row["completed"]),
            program_id=row["program_id"],
            status=row["status"],
            score=float(row["score"]) if row["score"] else None,
            best_score=float(row["best_score"]) if row["best_score"] else None,
            best_id=row["best_id"],
            model=row["model"],
        )


@dataclass
class RunInfo:
    """What run.json holds (D50)."""

    # Identifies the run; its containers are labelled with it
    run_id: str
    # The seed of the run's random generator
    seed: int
    # Hashes of what a continued run must not change (D50): the initial program, the
    # evaluation file, the problem without its llm section; and the image's tag
    fingerprints: dict[str, str] = field(default_factory=dict)
    # One record per session: when it ran, how it was started, how it ended
    sessions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return the information as plain JSON values."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunInfo":
        """Rebuild the information from what to_dict wrote."""
        return cls(
            run_id=data["run_id"],
            seed=data["seed"],
            # Runs started before fingerprints existed have none: they cannot be continued.
            fingerprints=dict(data.get("fingerprints", {})),
            sessions=list(data["sessions"]),
        )


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


def saved_run_info(folder: Path) -> RunInfo | None:
    """Return the content of a run folder's run.json, or None if there is none."""
    path = folder / RUN_FILE
    if not path.exists():
        return None
    return RunInfo.from_dict(json.loads(path.read_text(encoding="utf-8")))


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
        return saved_run_info(self.folder)

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

    def read_lines(self, file_name: str) -> list[str]:
        """Return a file's lines; none if it does not exist."""
        path = self.folder / file_name
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def drop_last_line(self, file_name: str) -> None:
        """Rewrite a file without its last line: one cut off by a crash."""
        path = self.folder / file_name
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        self.write_whole(path, "".join(lines[:-1]))

    def read_json_lines(self, file_name: str, repair: bool = True) -> list[dict[str, Any]]:
        """Return the records of a JSON-lines file, in order.

        A last line cut off by a crash is dropped, and, with repair, the file rewritten
        without it (without, the folder is only read: the report reads a run that may be
        in progress). Raises RunFolderError for an unreadable line elsewhere.
        """
        lines = self.read_lines(file_name)
        records = []
        for number, line in enumerate(lines, start=1):
            try:
                records.append(json.loads(line))
            except ValueError as error:
                if number == len(lines):
                    if repair:
                        self.drop_last_line(file_name)
                    break
                raise RunFolderError(
                    f"{file_name}: line {number} cannot be read: {error}"
                ) from None
        return records

    def write_json_lines(self, file_name: str, records: list[dict[str, Any]]) -> None:
        """Rewrite a JSON-lines file whole, as append_line writes each record."""
        text = "".join(json.dumps(record, allow_nan=False) + "\n" for record in records)
        self.write_whole(self.folder / file_name, text)

    def load_programs(self, repair: bool = True) -> list[Program]:
        """Read programs.jsonl back, in order (a last line cut off by a crash is dropped;
        with repair, from the file too).

        Raises RunFolderError for a line that is not a saved program.
        """
        programs = []
        for number, record in enumerate(self.read_json_lines(PROGRAMS_FILE, repair), start=1):
            try:
                programs.append(Program.from_dict(record))
            except (ValueError, TypeError, KeyError) as error:
                raise RunFolderError(
                    f"{PROGRAMS_FILE}: line {number} is not a program: {error}"
                ) from None
        return programs

    def load_history(self, repair: bool = True) -> list[HistoryRow]:
        """Read history.csv back, in order (a last row cut off by a crash is dropped; with
        repair, from the file too).

        Raises RunFolderError for an unreadable row elsewhere.
        """
        lines = self.read_lines(HISTORY_FILE)
        rows = []
        # Line 1 is the header.
        for number, row in enumerate(csv.DictReader(lines), start=2):
            try:
                rows.append(HistoryRow.from_csv(row))
            except (ValueError, TypeError) as error:
                if number == len(lines):
                    if repair:
                        self.drop_last_line(HISTORY_FILE)
                    break
                raise RunFolderError(
                    f"{HISTORY_FILE}: line {number} cannot be read: {error}"
                ) from None
        return rows

    def drop_unfinished(self, finished: set[int]) -> int:
        """Drop the LLM's children, and the LLM calls, of iterations without a history row.

        A crash between storing a child and its history row leaves a child whose
        iteration is done again on resume (the first plan's P3): it is dropped, as a
        cut-off line is. Returns how many children were dropped.
        """
        programs = self.read_json_lines(PROGRAMS_FILE)
        kept = [
            record
            for record in programs
            if record["origin"] != Origin.LLM.value or record["iteration"] in finished
        ]
        if len(kept) != len(programs):
            self.write_json_lines(PROGRAMS_FILE, kept)
        calls = self.read_json_lines(LLM_CALLS_FILE)
        kept_calls = [record for record in calls if record["iteration"] in finished]
        if len(kept_calls) != len(calls):
            self.write_json_lines(LLM_CALLS_FILE, kept_calls)
        return len(programs) - len(kept)
