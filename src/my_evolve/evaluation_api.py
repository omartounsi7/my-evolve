"""What evaluation files import from my-evolve.

An evaluation file defines evaluate(namespace), which returns a StageResult: the
program's score, and optionally named metrics and feedback for the LLM. The namespace
gives the program's names: calling one of its functions runs that function in the
program's own process (the sandbox), and returns its value as plain data.

- When the program's answer breaks a rule of the problem (overlapping circles, a
  negative radius), evaluate raises InvalidProgram with the reason: status invalid.
- When the program itself fails (it raises, its process ends, a name is missing), the
  namespace raises ProgramFailure, which evaluate lets through: status failed.
- When the stage runs out of time, the namespace raises StageTimeout, which evaluate
  lets through too: status timeout.
- A single call may get a time limit of its own, with call_with_timeout; a call over
  it raises CallTimeout, which evaluate may catch (to skip one trial of several, say).
  If it does not, the status is timeout.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StageResult:
    """What an evaluation file's evaluate returns for a program whose answer is legal."""

    # How good the program is: a finite number, higher is better
    score: float
    # Named numbers about the run, saved but not shown to the LLM, such as the sum of radii
    metrics: dict[str, float] = field(default_factory=dict)
    # What the LLM should know about the program, such as "Circles 3 and 7 nearly touch"
    feedback: str = ""
    # Named numbers describing the program's output, for the MAP-Elites grid (D17), such as
    # the spread of the radii; read from stage 1 only, which must give every output feature
    # the problem's grid names
    features: dict[str, float] = field(default_factory=dict)
    # Plain data about the program's output, kept for the report's drawings (D6, D51), such
    # as the centres and radii of a packing: numbers, text, lists, dictionaries with text
    # keys. The evaluation file's visualize(output_data, path), if it defines one, draws it
    output_data: Any = None


class InvalidProgram(Exception):
    """Raised by an evaluation file when the program's answer breaks a rule of the problem."""

    def __init__(self, reason: str, feedback: str = "") -> None:
        super().__init__(reason)
        # Why the answer is illegal, in words the LLM will read
        self.reason: str = reason
        # Anything else the LLM should know about the program
        self.feedback: str = feedback


class ProgramFailure(Exception):
    """Raised by the namespace when the program failed: it raised, or its process ended."""

    def __init__(self, error: str, traceback: str = "", error_output: str = "") -> None:
        super().__init__(error)
        # What went wrong, in one line, such as "ZeroDivisionError: division by zero"
        self.error: str = error
        # Where in the program it went wrong, when known
        self.traceback: str = traceback
        # The end of what the program printed, when it printed anything
        self.error_output: str = error_output

    def describe(self) -> str:
        """Return the error, then the traceback and the end of the program's output, if any."""
        parts = [self.error, self.traceback.rstrip()]
        if self.error_output.strip():
            parts.append("The end of the program's output:\n" + self.error_output.rstrip())
        return "\n\n".join(part for part in parts if part)


class StageTimeout(Exception):
    """Raised by the namespace when the evaluation ran out of time; the program is stopped."""


class CallTimeout(Exception):
    """Raised when one call ran over the time limit call_with_timeout gave it.

    Deliberately not related to StageTimeout: catching a call's timeout never hides the
    stage's.
    """


def call_with_timeout(function: Any, seconds: float, *args: Any, **kwargs: Any) -> Any:
    """Call one of the program's functions, with a time limit of its own (OpenEvolve's
    run_with_timeout, ported).

    function comes from the namespace. Raises CallTimeout if the call takes longer than
    seconds; the program is then stopped, and loaded again in a fresh process for the
    next call. The stage's own limit still applies.
    """
    with_timeout = getattr(function, "with_timeout", None)
    if with_timeout is None:
        raise TypeError(
            "call_with_timeout needs one of the program's functions, from the namespace"
        )
    return with_timeout(seconds)(*args, **kwargs)
