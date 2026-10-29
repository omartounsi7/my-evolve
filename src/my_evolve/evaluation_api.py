"""What evaluation files import from my-evolve.

An evaluation file defines evaluate(namespace), which returns a StageResult: the
program's score, and optionally named metrics and feedback for the LLM. The namespace
gives the program's names: calling one of its functions runs that function in the
program's own process (the sandbox), and returns its value as plain data.

- When the program's answer breaks a rule of the problem (overlapping circles, a
  negative radius), evaluate raises InvalidProgram with the reason: status invalid.
- When the program itself fails (it raises, its process ends, a name is missing), the
  namespace raises ProgramFailure, which evaluate lets through: status failed.
- When the evaluation runs out of time, the namespace raises StageTimeout, which
  evaluate lets through too: status timeout.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StageResult:
    """What an evaluation file's evaluate returns for a program whose answer is legal."""

    # How good the program is: a finite number, higher is better
    score: float
    # Named numbers about the run, saved but not shown to the LLM, such as the sum of radii
    metrics: dict[str, float] = field(default_factory=dict)
    # What the LLM should know about the program, such as "Circles 3 and 7 nearly touch"
    feedback: str = ""


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
