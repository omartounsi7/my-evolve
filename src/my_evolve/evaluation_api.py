"""What evaluation files import from my-evolve.

An evaluation file defines evaluate(namespace), which returns the program's score. When
the program's answer breaks a rule of the problem (overlapping circles, a negative
radius), it raises InvalidProgram with the reason, and the program's status is invalid.
"""


class InvalidProgram(Exception):
    """Raised by an evaluation file when the program's answer breaks a rule of the problem."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        # Why the answer is illegal, in words the LLM will read
        self.reason: str = reason
