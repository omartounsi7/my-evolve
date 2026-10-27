"""The records of a run: how an evaluation ended, and the programs themselves.

- Status: how a program's evaluation ended (D7).
- Result: what its evaluation found (D6, D73).
- LLMUsage: the LLM call that wrote a program (D35).
- Program: one program of the run, with its result (D60).

They are plain records: everything about them is fixed once they exist (they are
"frozen"), and what the run derives from them, such as how many children a program
has, lives in the database instead (D63). Each one turns into a dictionary of plain
JSON values and back, for the run folder's files (D47, D48).
"""

import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, TypeAlias

# Plain data, as JSON can hold it: what an evaluator may keep in output_data (D48).
JsonValue: TypeAlias = "None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]"


class Status(StrEnum):
    """How a program's evaluation ended (D7). Saved as its plain name, such as "ok"."""

    # Evaluated, and its answer is legal: the only status with a score.
    OK = "ok"
    # Refused before evaluation by a check (D13); never run.
    REJECTED = "rejected"
    # Raised an exception, or its process died.
    FAILED = "failed"
    # Ran out of time.
    TIMEOUT = "timeout"
    # Gave an answer the evaluator judged illegal.
    INVALID = "invalid"
    # Not the program's fault: the infrastructure failed.
    ERROR = "error"


class Origin(StrEnum):
    """How a program came to exist (D60)."""

    # The initial program, which evolution starts from.
    INITIAL = "initial"
    # Written by the LLM.
    LLM = "llm"
    # Placed by the framework: the initial program on each island, or a copied migrant.
    COPY = "copy"
    # A migrant moved from one island to another.
    MOVE = "move"


def checked_keys(data: Any, keys: tuple[str, ...], where: str) -> dict[str, Any]:
    """Return data if it is a dictionary with exactly the given keys.

    Raises ValueError naming the first missing or unknown key, and where it is
    (for example "program.result"), so that a damaged file is easy to fix.
    """
    if not isinstance(data, dict):
        raise ValueError(f"{where}: expected a dictionary, got {type(data).__name__}")
    for key in keys:
        if key not in data:
            raise ValueError(f"{where}: missing key {key!r}")
    unknown_keys = sorted(set(data) - set(keys))
    if unknown_keys:
        raise ValueError(f"{where}: unknown key {unknown_keys[0]!r}")
    return data


def status_from_name(name: Any, where: str) -> Status:
    """Return the Status with this name; raise ValueError naming where it was read."""
    try:
        return Status(name)
    except ValueError:
        raise ValueError(f"{where}: unknown status {name!r}") from None


@dataclass(frozen=True)
class Result:
    """What the evaluation of one program found (D6, D73).

    Only an ok result has a score; every other status has none, which is saved as
    null. Creating a result that breaks this rule raises ValueError.
    """

    # How the evaluation ended (D7).
    status: Status
    # The score, higher is better; None unless status is ok.
    score: float | None = None
    # Named numbers about the run, saved and logged but not shown to the LLM (D27).
    metrics: dict[str, float] = field(default_factory=dict)
    # The output features for the MAP-Elites grid (D17), from stage 1 only.
    features: dict[str, float] = field(default_factory=dict)
    # What the evaluator wants the LLM to know (D10).
    feedback: str | None = None
    # Why the program failed, or the error of a later stage it did not pass (D9).
    error: str | None = None
    # Plain data kept for the report's drawings (D51).
    output_data: JsonValue = None
    # The last cascade stage completed; 0 if none.
    stage_reached: int = 0
    # Wall-clock time of the evaluation, in seconds.
    duration: float = 0.0

    def __post_init__(self) -> None:
        """Check that the score agrees with the status; store a whole-number score as a float."""
        if self.status is not Status.OK:
            if self.score is not None:
                raise ValueError(f"a {self.status} result has no score, got {self.score!r}")
            return
        score: Any = self.score
        if score is None:
            raise ValueError("an ok result must have a score")
        if isinstance(score, bool) or not isinstance(score, int | float):
            raise ValueError(f"the score must be a number, got {type(score).__name__}")
        if not math.isfinite(score):
            raise ValueError(f"the score must be a finite number, got {score}")
        # The dataclass is frozen, so the field is set through object.__setattr__.
        object.__setattr__(self, "score", float(score))

    @property
    def is_ok(self) -> bool:
        """True when the program was evaluated and its answer is legal: the meaning of "correct"."""
        return self.status is Status.OK

    @classmethod
    def rejected(cls, reason: str) -> "Result":
        """Return the result of a program refused before evaluation (D13)."""
        return cls(status=Status.REJECTED, error=reason)

    @classmethod
    def failure(
        cls,
        status: Status,
        error: str,
        feedback: str | None = None,
        duration: float = 0.0,
        stage_reached: int = 0,
    ) -> "Result":
        """Return a result without a score: any status but ok.

        stage_reached is the last stage the program passed before failing, such as
        1 for a program judged invalid at stage 2.
        """
        if status is Status.OK:
            raise ValueError("a failure cannot have the status ok")
        return cls(
            status=status,
            error=error,
            feedback=feedback,
            duration=duration,
            stage_reached=stage_reached,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return this result as plain JSON values; a missing score is None (null in JSON)."""
        return {
            "status": self.status.value,
            "score": self.score,
            "metrics": dict(self.metrics),
            "features": dict(self.features),
            "feedback": self.feedback,
            "error": self.error,
            "output_data": self.output_data,
            "stage_reached": self.stage_reached,
            "duration": self.duration,
        }

    @classmethod
    def from_dict(cls, data: Any, where: str = "result") -> "Result":
        """Rebuild a result from a dictionary made by to_dict.

        Raises ValueError for a missing or unknown key, or an unknown status.
        """
        fields = checked_keys(data, RESULT_KEYS, where)
        return cls(
            status=status_from_name(fields["status"], where),
            score=fields["score"],
            metrics=dict(fields["metrics"]),
            features=dict(fields["features"]),
            feedback=fields["feedback"],
            error=fields["error"],
            output_data=fields["output_data"],
            stage_reached=fields["stage_reached"],
            duration=fields["duration"],
        )


# The keys of Result.to_dict, in order.
RESULT_KEYS = (
    "status",
    "score",
    "metrics",
    "features",
    "feedback",
    "error",
    "output_data",
    "stage_reached",
    "duration",
)


@dataclass(frozen=True)
class LLMUsage:
    """The LLM call that wrote a program (D35)."""

    # The model's name, as its server knows it.
    model: str
    # Tokens sent and received; 0 when the server does not say.
    input_tokens: int
    output_tokens: int
    # How long the call took, in seconds.
    duration: float

    def to_dict(self) -> dict[str, Any]:
        """Return this usage as plain JSON values."""
        return {
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "duration": self.duration,
        }

    @classmethod
    def from_dict(cls, data: Any, where: str = "llm") -> "LLMUsage":
        """Rebuild a usage from a dictionary made by to_dict."""
        fields = checked_keys(data, LLM_USAGE_KEYS, where)
        return cls(
            model=fields["model"],
            input_tokens=fields["input_tokens"],
            output_tokens=fields["output_tokens"],
            duration=fields["duration"],
        )


# The keys of LLMUsage.to_dict, in order.
LLM_USAGE_KEYS = ("model", "input_tokens", "output_tokens", "duration")


def new_id() -> str:
    """Return a new identifier for a program: a random UUID."""
    return str(uuid.uuid4())


def now() -> datetime:
    """Return the current time, in UTC."""
    return datetime.now(UTC)


@dataclass(frozen=True)
class Program:
    """One program of the run: its code, its result and where it comes from (D60).

    The facts here never change once the program exists. Database state, such as
    the grid cell it holds or its number of children, is kept by the database.
    """

    # A UUID, identifying the program everywhere.
    id: str
    # The full file.
    code: str
    # What its evaluation found.
    result: Result
    # How it came to exist (initial, llm, copy, move).
    origin: Origin
    # The parent; for a copy or a move, the program copied; None for the initial program.
    parent_id: str | None
    # The island it was made on; None for the initial program, which lives on the
    # islands through its copies.
    island: int | None
    # The iteration that produced it: 0 for the initial program and its copies; for a
    # migrant, the number of completed iterations at its migration.
    iteration: int
    # Its distance from the initial program; a copy keeps the generation it copies.
    generation: int
    # The LLM's self-contained description of the program (D15); may be None.
    description: str | None
    # The hash of its syntax tree (D13); None if it does not compile.
    fingerprint: str | None
    # Its number of syntax-tree nodes inside the evolve blocks (D17); None if it does
    # not compile.
    code_complexity: int | None
    # The example programs shown in its prompt (D26).
    example_ids: tuple[str, ...]
    # The LLM call that wrote it; None for the initial program and copies.
    llm: LLMUsage | None
    # When it was made, in UTC.
    created_at: datetime

    def __repr__(self) -> str:
        """Return a one-line summary, leaving out the code.

        Example: Program(id=3f2a9c1e, origin=llm, status=ok, score=0.364, generation=1)
        """
        return (
            f"Program(id={self.id[:8]}, origin={self.origin}, status={self.result.status}, "
            f"score={self.result.score}, generation={self.generation})"
        )

    @classmethod
    def initial(
        cls,
        code: str,
        result: Result,
        fingerprint: str | None,
        code_complexity: int | None,
    ) -> "Program":
        """Return the initial program: no parent, no island, iteration 0, generation 0."""
        return cls(
            id=new_id(),
            code=code,
            result=result,
            origin=Origin.INITIAL,
            parent_id=None,
            island=None,
            iteration=0,
            generation=0,
            description=None,
            fingerprint=fingerprint,
            code_complexity=code_complexity,
            example_ids=(),
            llm=None,
            created_at=now(),
        )

    @classmethod
    def new_child(
        cls,
        parent: "Program",
        *,
        code: str,
        result: Result,
        island: int,
        iteration: int,
        description: str | None,
        fingerprint: str | None,
        code_complexity: int | None,
        example_ids: tuple[str, ...],
        llm: LLMUsage,
    ) -> "Program":
        """Return a program the LLM wrote from this parent, one generation after it."""
        return cls(
            id=new_id(),
            code=code,
            result=result,
            origin=Origin.LLM,
            parent_id=parent.id,
            island=island,
            iteration=iteration,
            generation=parent.generation + 1,
            description=description,
            fingerprint=fingerprint,
            code_complexity=code_complexity,
            example_ids=tuple(example_ids),
            llm=llm,
            created_at=now(),
        )

    def copy_to(self, island: int, iteration: int, mode: Origin) -> "Program":
        """Return a copy or a move of this program onto an island (D23).

        mode is Origin.COPY or Origin.MOVE. The new record has its own id, this
        program as parent, and the same code, result, generation, description,
        fingerprint and code complexity; it has no LLM usage and no example programs.
        """
        if mode not in (Origin.COPY, Origin.MOVE):
            raise ValueError(f"mode must be copy or move, got {mode}")
        return Program(
            id=new_id(),
            code=self.code,
            result=self.result,
            origin=mode,
            parent_id=self.id,
            island=island,
            iteration=iteration,
            generation=self.generation,
            description=self.description,
            fingerprint=self.fingerprint,
            code_complexity=self.code_complexity,
            example_ids=(),
            llm=None,
            created_at=now(),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return this program as plain JSON values: one line of programs.jsonl (D48)."""
        return {
            "id": self.id,
            "code": self.code,
            "result": self.result.to_dict(),
            "origin": self.origin.value,
            "parent_id": self.parent_id,
            "island": self.island,
            "iteration": self.iteration,
            "generation": self.generation,
            "description": self.description,
            "fingerprint": self.fingerprint,
            "code_complexity": self.code_complexity,
            "example_ids": list(self.example_ids),
            "llm": self.llm.to_dict() if self.llm is not None else None,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Program":
        """Rebuild a program from a dictionary made by to_dict, keeping its id.

        Raises ValueError naming any missing or unknown key, unknown status or
        origin, or a time without a time zone.
        """
        fields = checked_keys(data, PROGRAM_KEYS, "program")
        try:
            origin = Origin(fields["origin"])
        except ValueError:
            raise ValueError(f"program: unknown origin {fields['origin']!r}") from None
        created_at = datetime.fromisoformat(fields["created_at"])
        if created_at.tzinfo is None:
            raise ValueError("program: created_at has no time zone")
        llm = fields["llm"]
        return cls(
            id=fields["id"],
            code=fields["code"],
            result=Result.from_dict(fields["result"], "program.result"),
            origin=origin,
            parent_id=fields["parent_id"],
            island=fields["island"],
            iteration=fields["iteration"],
            generation=fields["generation"],
            description=fields["description"],
            fingerprint=fields["fingerprint"],
            code_complexity=fields["code_complexity"],
            example_ids=tuple(fields["example_ids"]),
            llm=LLMUsage.from_dict(llm, "program.llm") if llm is not None else None,
            created_at=created_at,
        )


# The keys of Program.to_dict, in order.
PROGRAM_KEYS = (
    "id",
    "code",
    "result",
    "origin",
    "parent_id",
    "island",
    "iteration",
    "generation",
    "description",
    "fingerprint",
    "code_complexity",
    "example_ids",
    "llm",
    "created_at",
)
