"""What evaluation files import from my-evolve.

An evaluation file defines evaluate(namespace), which returns the program's score. The
namespace gives the program's names: calling one of its functions runs that function
in the program's own process (the sandbox), and returns its value as plain data.

- When the program's answer breaks a rule of the problem (overlapping circles, a
  negative radius), evaluate raises InvalidProgram with the reason: status invalid.
- When the program itself fails (it raises, its process ends, a name is missing), the
  namespace raises ProgramFailure, which evaluate lets through: status failed.
"""


class InvalidProgram(Exception):
    """Raised by an evaluation file when the program's answer breaks a rule of the problem."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        # Why the answer is illegal, in words the LLM will read
        self.reason: str = reason


class ProgramFailure(Exception):
    """Raised by the namespace when the program failed: it raised, or its process ended."""

    def __init__(self, error: str, traceback: str = "") -> None:
        super().__init__(error)
        # What went wrong, in one line, such as "ZeroDivisionError: division by zero"
        self.error: str = error
        # Where in the program it went wrong, when known
        self.traceback: str = traceback

    def describe(self) -> str:
        """Return the error, then the traceback if there is one."""
        return f"{self.error}\n\n{self.traceback}".rstrip() if self.traceback else self.error
