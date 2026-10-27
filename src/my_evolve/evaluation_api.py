"""What evaluation files import: the result of a stage, and the errors of a program (D76).

An evaluation file defines evaluate(namespace), or evaluate_stage1(namespace),
evaluate_stage2(namespace), ... (D9). Each stage function receives the program's
namespace, whose functions run the program's own functions in its sandbox (D8), and:

- returns a StageResult;
- or raises InvalidProgram when the program's answer breaks the problem's rules;
- and lets ProgramFailure, CallTimeout and StageTimeout through, unless it handles
  them itself (for example, to score the trials that did not time out).

Stage functions may run in several threads at once, so they must not keep state
between calls.
"""

from dataclasses import dataclass, field
from typing import Any

from my_evolve.program import JsonValue


@dataclass
class StageResult:
    """What one stage of the evaluation found about a working program."""

    # A finite number, higher is better.
    score: float
    # Named numbers about the run, saved and logged but not shown to the LLM (D27).
    metrics: dict[str, float] = field(default_factory=dict)
    # Stage 1 only: every output feature the problem's grid uses (D17).
    features: dict[str, float] = field(default_factory=dict)
    # What the LLM should know about this program (D10).
    feedback: str | None = None
    # Plain data kept for the report's drawings (D51).
    output_data: JsonValue = None


class InvalidProgram(Exception):
    """The program's answer breaks the problem's rules (D7), such as overlapping circles."""

    def __init__(self, reason: str, feedback: str | None = None) -> None:
        super().__init__(reason)
        # Why the answer is illegal, shown to the LLM as the program's error.
        self.reason: str = reason
        # Anything else the LLM should know.
        self.feedback: str | None = feedback


class ProgramFailure(Exception):
    """The program raised an exception, or its process ended, while loading or in a call."""

    def __init__(
        self, message: str, traceback: str | None = None, error_output: str | None = None
    ) -> None:
        super().__init__(message)
        # What happened, such as "IndexError: list index out of range".
        self.message: str = message
        # The program's traceback, if it raised.
        self.traceback: str | None = traceback
        # The end of what the program wrote to its error output (its prints included).
        self.error_output: str | None = error_output


class CallTimeout(Exception):
    """A call ran over its own time limit (see RemoteFunction.with_timeout)."""


class StageTimeout(Exception):
    """The stage ran out of time (D41).

    Deliberately not a kind of CallTimeout: an evaluator that catches the timeout of
    one trial must not hide that the whole stage is over.
    """


def call_with_timeout(function: Any, seconds: float, *args: Any, **kwargs: Any) -> Any:
    """Call one of the program's functions with a time limit of its own, and return its value.

    A call over the limit raises CallTimeout: the program's process is stopped, and
    the next call starts it again with the program freshly loaded (D8). This is
    OpenEvolve's run_with_timeout, except that the slow call is really stopped.
    """
    with_timeout = getattr(function, "with_timeout", None)
    if with_timeout is None:
        raise TypeError("call_with_timeout needs a function taken from the program's namespace")
    return with_timeout(seconds)(*args, **kwargs)
