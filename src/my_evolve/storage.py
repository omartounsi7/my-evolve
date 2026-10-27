"""The Storage class: the run folder, written as the run goes (D47 to D50, D69).

Files are appended to line by line, each line reaching the disk before the next
step of the run, so nothing finished is lost on a crash; a last line cut off by a
crash is dropped when the run is continued, as in my-alphaevolve.

| File | Contents |
|---|---|
| programs.jsonl | one Program per line: the initial program, island copies, every child, migrants |
| llm_calls.jsonl | one LLM call per line: the user message, the reply, tokens, duration, error |
| history.csv | one line per completed iteration, for the progress plot |
| best_program.py | the best program so far, with a comment header |
| best/iteration_NNNN.py | the best program every snapshot_every completed iterations |
| run.json | the run's id, seed, fingerprints, and one record per session |
| problem.yaml | a copy of the problem file |
| log.txt | everything logged, with times (logs.py) |

Only the main thread uses the storage (D36).
"""

import csv
import io
import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from my_evolve.program import JsonValue, Program, checked_keys

PROGRAMS_FILE = "programs.jsonl"
LLM_CALLS_FILE = "llm_calls.jsonl"
HISTORY_FILE = "history.csv"
BEST_PROGRAM_FILE = "best_program.py"
SNAPSHOTS_FOLDER = "best"
RUN_INFO_FILE = "run.json"
PROBLEM_COPY_FILE = "problem.yaml"
LOG_FILE = "log.txt"

# The columns of history.csv, in order.
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

Record = TypeVar("Record")


class StorageError(ValueError):
    """A file of the run folder that cannot be read; the message names it and the line."""


@dataclass(frozen=True)
class HistoryRow:
    """One line of history.csv: one completed iteration (D47)."""

    # The iteration's number.
    iteration: int
    # How many iterations had completed with this one.
    completed: int
    # The child's id; None when the iteration had no child.
    program_id: str | None
    # The child's status, "skipped" when the LLM call failed, or "error" when the
    # iteration failed before having a child.
    status: str
    # The child's score; None unless it is ok.
    score: float | None
    # The best score so far, and the best program's id.
    best_score: float
    best_id: str
    # The model asked; None if no model was drawn.
    model: str | None

    def to_row(self) -> list[str]:
        """Return the row's values as text, empty for None."""
        values = (
            self.iteration,
            self.completed,
            self.program_id,
            self.status,
            self.score,
            self.best_score,
            self.best_id,
            self.model,
        )
        return [
            "" if value is None else repr(value) if isinstance(value, float) else str(value)
            for value in values
        ]

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "HistoryRow":
        """Rebuild a row from history.csv; raises ValueError if it cannot be read."""
        if set(row) != set(HISTORY_COLUMNS) or None in row.values():
            raise ValueError("the row does not have the expected columns")
        return cls(
            iteration=int(row["iteration"]),
            completed=int(row["completed"]),
            program_id=row["program_id"] or None,
            status=row["status"],
            score=float(row["score"]) if row["score"] else None,
            best_score=float(row["best_score"]),
            best_id=row["best_id"],
            model=row["model"] or None,
        )


@dataclass(frozen=True)
class LLMCallRecord:
    """One line of llm_calls.jsonl: one call to a model (D47)."""

    iteration: int
    # The program written from the reply; None when the call failed.
    program_id: str | None
    model: str
    # The user message; the system message is saved once per session in run.json.
    user_message: str
    # The full reply; None when the call failed.
    reply: str | None
    input_tokens: int
    output_tokens: int
    duration: float
    # Why the call failed; None when it succeeded.
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "program_id": self.program_id,
            "model": self.model,
            "user_message": self.user_message,
            "reply": self.reply,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "duration": self.duration,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "LLMCallRecord":
        fields = checked_keys(data, LLM_CALL_KEYS, "llm call")
        return cls(**fields)


LLM_CALL_KEYS = (
    "iteration",
    "program_id",
    "model",
    "user_message",
    "reply",
    "input_tokens",
    "output_tokens",
    "duration",
    "error",
)


@dataclass
class SessionRecord:
    """One launch of the run: from a start to a stop (D50)."""

    # When it started and ended, in ISO 8601; ended_at is None while it runs.
    started_at: str
    ended_at: str | None
    # The commit of my-evolve's code, if it is a git checkout.
    git_commit: str | None
    # The command line, as typed.
    command_line: list[str]
    # The llm section of the problem file, which may change between sessions.
    llm: JsonValue
    # The command-line flags.
    flags: dict[str, JsonValue]
    # The system message of the session's prompts (D47).
    system_message: str
    # How it ended, such as "target score reached" or "interrupted"; None while it runs.
    end: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "git_commit": self.git_commit,
            "command_line": list(self.command_line),
            "llm": self.llm,
            "flags": dict(self.flags),
            "system_message": self.system_message,
            "end": self.end,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "SessionRecord":
        fields = checked_keys(data, SESSION_KEYS, "run.json session")
        return cls(**fields)


SESSION_KEYS = (
    "started_at",
    "ended_at",
    "git_commit",
    "command_line",
    "llm",
    "flags",
    "system_message",
    "end",
)


@dataclass
class RunInfo:
    """The content of run.json (D50)."""

    # Identifies the run, and labels its containers (D42).
    run_id: str
    # The seed of the run's random generator (D39).
    seed: int
    # Hashes of the initial program, the evaluation file, the problem without its llm
    # section, and the image: a resumed run must find the same ones.
    fingerprints: dict[str, str]
    sessions: list[SessionRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "seed": self.seed,
            "fingerprints": dict(self.fingerprints),
            "sessions": [session.to_dict() for session in self.sessions],
        }

    @classmethod
    def from_dict(cls, data: Any) -> "RunInfo":
        fields = checked_keys(data, ("run_id", "seed", "fingerprints", "sessions"), "run.json")
        return cls(
            run_id=fields["run_id"],
            seed=fields["seed"],
            fingerprints=dict(fields["fingerprints"]),
            sessions=[SessionRecord.from_dict(session) for session in fields["sessions"]],
        )


def best_header(program: Program, title: str) -> str:
    """Return the comment lines put before a best program's code."""
    lines = [
        f"# {title}: score {program.result.score!r}, found at iteration {program.iteration}",
        f"# Program id: {program.id}",
    ]
    if program.description:
        lines.append("# Description:")
        lines.extend(f"#   {line}".rstrip() for line in program.description.splitlines())
    return "\n".join(lines) + "\n\n"


class Storage:
    """Reads and writes the files of one run folder."""

    def __init__(self, folder: Path) -> None:
        """Use the folder for the run, creating it (and the folders above it) if needed."""
        self.folder: Path = folder
        folder.mkdir(parents=True, exist_ok=True)
        self.programs_path: Path = folder / PROGRAMS_FILE
        self.llm_calls_path: Path = folder / LLM_CALLS_FILE
        self.history_path: Path = folder / HISTORY_FILE
        self.best_path: Path = folder / BEST_PROGRAM_FILE
        self.snapshots_folder: Path = folder / SNAPSHOTS_FOLDER
        self.run_info_path: Path = folder / RUN_INFO_FILE
        self.problem_copy_path: Path = folder / PROBLEM_COPY_FILE
        self.log_path: Path = folder / LOG_FILE

    def is_new(self) -> bool:
        """True while no program has been saved in the folder."""
        return not self.programs_path.is_file()

    # Appending -------------------------------------------------------------------

    def append_line(self, path: Path, line: str) -> None:
        """Add one line at the end of a file, and make sure it reaches the disk."""
        with path.open("a", encoding="utf-8", newline="\n") as file:
            file.write(line + "\n")
            file.flush()
            os.fsync(file.fileno())

    def append_program(self, program: Program) -> None:
        """Add one program to programs.jsonl (D48)."""
        self.append_line(
            self.programs_path, json.dumps(program.to_dict(), ensure_ascii=False, allow_nan=False)
        )

    def append_llm_call(self, record: LLMCallRecord) -> None:
        """Add one LLM call to llm_calls.jsonl."""
        self.append_line(
            self.llm_calls_path, json.dumps(record.to_dict(), ensure_ascii=False, allow_nan=False)
        )

    def append_history(self, row: HistoryRow) -> None:
        """Add one completed iteration to history.csv, with the header first if the file is new."""
        text = io.StringIO()
        writer = csv.writer(text, lineterminator="\n")
        if not self.history_path.is_file() or self.history_path.stat().st_size == 0:
            writer.writerow(HISTORY_COLUMNS)
        writer.writerow(row.to_row())
        self.append_line(self.history_path, text.getvalue().rstrip("\n"))

    # Best program ------------------------------------------------------------------

    def write_best(self, program: Program) -> None:
        """Rewrite best_program.py: a comment header, then the code."""
        header = best_header(program, "Best program so far")
        self.write_whole(self.best_path, header + program.code)

    def write_snapshot(self, program: Program, completed: int) -> None:
        """Write best/iteration_NNNN.py: the best program after that many completed iterations."""
        self.snapshots_folder.mkdir(exist_ok=True)
        header = best_header(program, f"Best program after {completed} completed iterations")
        self.write_whole(self.snapshot_path(completed), header + program.code)

    def snapshot_path(self, completed: int) -> Path:
        """Return the path of the snapshot after that many completed iterations."""
        return self.snapshots_folder / f"iteration_{completed:04d}.py"

    # Whole files -------------------------------------------------------------------

    def write_whole(self, path: Path, text: str) -> None:
        """Write a whole file through a temporary file then a rename, so that a crash
        never leaves half a file: the previous version stays until the new one is complete."""
        temporary = path.with_name(path.name + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)

    def save_problem(self, path: Path) -> None:
        """Copy the problem file to problem.yaml (D50)."""
        shutil.copyfile(path, self.problem_copy_path)

    def read_run_info(self) -> RunInfo | None:
        """Return the content of run.json, or None if there is none yet."""
        if not self.run_info_path.is_file():
            return None
        try:
            return RunInfo.from_dict(json.loads(self.run_info_path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ValueError, TypeError) as error:
            raise StorageError(f"{self.run_info_path}: cannot be read ({error})") from error

    def write_run_info(self, info: RunInfo) -> None:
        """Rewrite run.json, whole or not at all."""
        self.write_whole(
            self.run_info_path, json.dumps(info.to_dict(), indent=2, ensure_ascii=False) + "\n"
        )

    def rewrite_programs(self, programs: list[Program]) -> None:
        """Replace programs.jsonl by one holding exactly these programs, whole or not at all."""
        lines = [json.dumps(p.to_dict(), ensure_ascii=False, allow_nan=False) for p in programs]
        self.write_whole(self.programs_path, "".join(line + "\n" for line in lines))

    def rewrite_llm_calls(self, records: list[LLMCallRecord]) -> None:
        """Replace llm_calls.jsonl by one holding exactly these records, whole or not at all."""
        lines = [json.dumps(r.to_dict(), ensure_ascii=False, allow_nan=False) for r in records]
        self.write_whole(self.llm_calls_path, "".join(line + "\n" for line in lines))

    # Reading back --------------------------------------------------------------------

    def load_programs(self) -> list[Program]:
        """Return every saved program, in the order saved."""
        return self.read_lines(self.programs_path, lambda line: Program.from_dict(json.loads(line)))

    def load_llm_calls(self) -> list[LLMCallRecord]:
        """Return every saved LLM call, in the order saved."""
        return self.read_lines(
            self.llm_calls_path, lambda line: LLMCallRecord.from_dict(json.loads(line))
        )

    def load_history(self) -> list[HistoryRow]:
        """Return every saved history row, in order."""

        def parse(line: str) -> HistoryRow:
            values = next(csv.reader([line]))
            if len(values) != len(HISTORY_COLUMNS):
                raise ValueError(f"expected {len(HISTORY_COLUMNS)} values, got {len(values)}")
            return HistoryRow.from_row(dict(zip(HISTORY_COLUMNS, values, strict=True)))

        return self.read_lines(self.history_path, parse, header=",".join(HISTORY_COLUMNS))

    def read_lines(
        self, path: Path, parse: Callable[[str], Record], header: str | None = None
    ) -> list[Record]:
        """Read a line-based file back, one record per line (D69).

        No file: nothing saved yet. A line that cannot be read is, if it is the last
        one, a line cut off by a crash: the file is rewritten without it. Anywhere
        else it raises StorageError, naming the file and the line.
        """
        if not path.is_file():
            return []
        text = path.read_text(encoding="utf-8")
        lines = text.split("\n")
        # A file ending with a newline splits into one empty string more.
        if lines and lines[-1] == "":
            lines.pop()
        complete = text.endswith("\n") or not text
        first = 0
        if header is not None and lines:
            if lines[0] != header:
                if len(lines) == 1 and not complete:
                    # Only part of the header was written.
                    self.write_whole(path, "")
                    return []
                raise StorageError(f"{path}, line 1: not the expected header")
            first = 1

        records: list[Record] = []
        for index in range(first, len(lines)):
            try:
                records.append(parse(lines[index]))
            except (ValueError, KeyError, TypeError) as error:
                if index == len(lines) - 1:
                    # The last line was cut off while it was written: drop it, so that
                    # new lines are not glued to its remains.
                    self.write_whole(path, "".join(line + "\n" for line in lines[:index]))
                    return records
                raise StorageError(f"{path}, line {index + 1}: cannot be read ({error})") from error
        if not complete:
            # The last line is whole but its newline is missing: add it.
            self.write_whole(path, text + "\n")
        return records
