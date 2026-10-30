"""The records of a run: how an evaluation ended (Status, Result), and one program (Program)."""

import enum
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


class Status(enum.Enum):
    """How a program's evaluation ended."""

    # Evaluated, and its answer is legal: the only status with a score
    OK = "ok"
    # Refused before evaluation by a check (D13), such as a change outside the evolve blocks
    REJECTED = "rejected"
    # Raised an exception while loading or while one of its functions ran
    FAILED = "failed"
    # Ran out of time
    TIMEOUT = "timeout"
    # Returned an answer the evaluation file judged illegal, such as overlapping circles
    INVALID = "invalid"
    # Not the program's fault: the sandbox failed, or the evaluation file itself raised
    ERROR = "error"


@dataclass(frozen=True)
class Result:
    """How a program's evaluation ended: its status, and a score or the reason it failed."""

    status: Status
    # How good the program is, higher is better; only an ok program has one
    score: float | None = None
    # Why the program failed, such as "ZeroDivisionError: division by zero"; None when ok
    error: str | None = None
    # Named numbers about the run, from the evaluation file; saved, not shown to the LLM
    metrics: dict[str, float] = field(default_factory=dict)
    # Named numbers describing the program's output, from stage 1, for the grid (D17)
    features: dict[str, float] = field(default_factory=dict)
    # What the evaluation file wants the LLM to know about the program; None if nothing
    feedback: str | None = None
    # How long the evaluation took, in seconds
    duration: float = 0.0
    # The last cascade stage the program completed; 0 if none
    stage_reached: int = 0

    def __post_init__(self) -> None:
        """Refuse a result that contradicts itself: a score belongs to ok programs only."""
        # An ok program may have an error too: that of a later stage it did not pass.
        if (self.status is Status.OK) != (self.score is not None):
            raise ValueError(f"status {self.status.value} cannot go with the score {self.score}")

    @property
    def is_ok(self) -> bool:
        """True when the program works: the only meaning of "correct"."""
        return self.status is Status.OK

    @classmethod
    def rejected(cls, reason: str) -> "Result":
        """Return the result of a child refused before evaluation, saying why."""
        return cls(status=Status.REJECTED, error=reason)

    @classmethod
    def failure(
        cls, status: Status, error: str, feedback: str | None = None, duration: float = 0.0
    ) -> "Result":
        """Return the result of a program that did not work, saying why."""
        return cls(status=status, error=error, feedback=feedback, duration=duration)

    def to_dict(self) -> dict[str, Any]:
        """Return the result as plain JSON values; a missing score is None (null in JSON)."""
        return {
            "status": self.status.value,
            "score": self.score,
            "error": self.error,
            "metrics": self.metrics,
            "features": self.features,
            "feedback": self.feedback,
            "duration": self.duration,
            "stage_reached": self.stage_reached,
        }


@dataclass(frozen=True)
class LLMUsage:
    """The LLM call that wrote a program, and what it cost."""

    # The model that wrote it
    model: str
    # The tokens of the prompt and of the reply
    input_tokens: int
    output_tokens: int
    # How long the call took, in seconds
    duration: float

    def to_dict(self) -> dict[str, Any]:
        """Return the usage as plain JSON values."""
        return {
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "duration": self.duration,
        }


class Origin(enum.Enum):
    """How a program came to exist."""

    # The problem's initial program
    INITIAL = "initial"
    # Written by the LLM: the only programs the checks and the children counts concern
    LLM = "llm"
    # Placed by the framework: the initial program on each island, or a copied migrant
    COPY = "copy"
    # A migrant moved to another island
    MOVE = "move"


def new_id() -> str:
    """Return a new, unique program id."""
    return str(uuid.uuid4())


def creation_time() -> str:
    """Return the current time, in UTC, as ISO 8601 text."""
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Program:
    """One program of the run: its code, its result, and where it came from.

    A program never changes once it exists: everything here is a fact about it.
    """

    # The full source code of the program
    code: str
    # How its evaluation ended
    result: Result
    # How it came to exist
    origin: Origin = Origin.INITIAL
    # The program it was made from (for a copy, the program copied); None for the initial one
    parent_id: str | None = None
    # The island it was made on (D23); None for the initial program, which belongs to none
    island: int | None = None
    # How many LLM rewrites separate it from the initial program; a copy keeps its original's
    generation: int = 0
    # The iteration of the run that produced it; 0 for the initial program and its copies
    iteration: int = 0
    # The LLM call that wrote it; None for the initial program
    llm: LLMUsage | None = None
    # How it solves the problem, in the words of the LLM that wrote it; None if unknown
    description: str | None = None
    # The hash of its syntax tree (D13); None if it does not compile
    fingerprint: str | None = None
    # The example programs shown in the prompt that wrote it (D26)
    example_ids: tuple[str, ...] = ()
    # Its syntax-tree nodes inside the evolve blocks (D17); None if not measured
    code_complexity: int | None = None
    # Identifies the program everywhere: in the database and in the saved files
    id: str = field(default_factory=new_id)
    # When it was made, in UTC
    created_at: str = field(default_factory=creation_time)

    @classmethod
    def new_child(
        cls,
        parent: "Program",
        code: str,
        result: Result,
        iteration: int,
        *,
        island: int | None = None,
        llm: LLMUsage | None = None,
        description: str | None = None,
        fingerprint: str | None = None,
        example_ids: tuple[str, ...] = (),
        code_complexity: int | None = None,
        program_id: str | None = None,
    ) -> "Program":
        """Return a program the LLM wrote from parent, one generation further.

        program_id gives it an id chosen earlier; by default a new one.
        """
        return cls(
            id=program_id or new_id(),
            code=code,
            result=result,
            origin=Origin.LLM,
            parent_id=parent.id,
            island=island,
            generation=parent.generation + 1,
            iteration=iteration,
            llm=llm,
            description=description,
            fingerprint=fingerprint,
            example_ids=example_ids,
            code_complexity=code_complexity,
        )

    def copy_to(self, island: int, iteration: int, origin: Origin = Origin.COPY) -> "Program":
        """Return a copy (or, with Origin.MOVE, a move) of this program onto an island.

        The copy is a new program, with this one as its parent; its code, result,
        generation, description, fingerprint and code complexity are carried over. It is
        not evaluated again.
        """
        return Program(
            code=self.code,
            result=self.result,
            origin=origin,
            parent_id=self.id,
            island=island,
            generation=self.generation,
            iteration=iteration,
            description=self.description,
            fingerprint=self.fingerprint,
            code_complexity=self.code_complexity,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the program as plain JSON values: one line of programs.jsonl."""
        return {
            "id": self.id,
            "origin": self.origin.value,
            "parent_id": self.parent_id,
            "island": self.island,
            "generation": self.generation,
            "iteration": self.iteration,
            "result": self.result.to_dict(),
            "llm": self.llm.to_dict() if self.llm else None,
            "description": self.description,
            "fingerprint": self.fingerprint,
            "example_ids": list(self.example_ids),
            "code_complexity": self.code_complexity,
            "created_at": self.created_at,
            "code": self.code,
        }
