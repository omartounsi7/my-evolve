"""The records of a run: how an evaluation ended (Status, Result), and one program (Program)."""

import enum
import uuid
from dataclasses import dataclass, field
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


def new_id() -> str:
    """Return a new, unique program id."""
    return str(uuid.uuid4())


@dataclass(frozen=True)
class Program:
    """One program of the run: its code, its result, and where it came from.

    A program never changes once it exists: everything here is a fact about it.
    """

    # The full source code of the program
    code: str
    # How its evaluation ended
    result: Result
    # The program it was made from; None for the initial program
    parent_id: str | None = None
    # How many LLM rewrites separate it from the initial program
    generation: int = 0
    # The iteration of the run that produced it; 0 for the initial program
    iteration: int = 0
    # The LLM call that wrote it; None for the initial program
    llm: LLMUsage | None = None
    # How it solves the problem, in the words of the LLM that wrote it; None if unknown
    description: str | None = None
    # The hash of its syntax tree (D13); None if it does not compile
    fingerprint: str | None = None
    # Identifies the program everywhere: in the database and in the saved files
    id: str = field(default_factory=new_id)

    @classmethod
    def new_child(
        cls,
        parent: "Program",
        code: str,
        result: Result,
        iteration: int,
        llm: LLMUsage | None = None,
        description: str | None = None,
        fingerprint: str | None = None,
    ) -> "Program":
        """Return a program the LLM wrote from parent, one generation further."""
        return cls(
            code=code,
            result=result,
            parent_id=parent.id,
            generation=parent.generation + 1,
            iteration=iteration,
            llm=llm,
            description=description,
            fingerprint=fingerprint,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the program as plain JSON values: one line of programs.jsonl."""
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "generation": self.generation,
            "iteration": self.iteration,
            "result": self.result.to_dict(),
            "llm": self.llm.to_dict() if self.llm else None,
            "description": self.description,
            "fingerprint": self.fingerprint,
            "code": self.code,
        }
