"""The records of a run: how an evaluation ended (Result), and one program (Program)."""

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Result:
    """How a program's evaluation ended: a score, or the error that stopped it."""

    # How good the program is, higher is better; None when the program failed
    score: float | None = None
    # Why the program failed, such as "ZeroDivisionError: division by zero"; None when it worked
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return the result as plain JSON values; a missing score is None (null in JSON)."""
        return {"score": self.score, "error": self.error}


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
    # Identifies the program everywhere: in the database and in the saved files
    id: str = field(default_factory=new_id)

    @classmethod
    def new_child(cls, parent: "Program", code: str, result: Result, iteration: int) -> "Program":
        """Return a program the LLM wrote from parent, one generation further."""
        return cls(
            code=code,
            result=result,
            parent_id=parent.id,
            generation=parent.generation + 1,
            iteration=iteration,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the program as plain JSON values: one line of programs.jsonl."""
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "generation": self.generation,
            "iteration": self.iteration,
            "result": self.result.to_dict(),
            "code": self.code,
        }
