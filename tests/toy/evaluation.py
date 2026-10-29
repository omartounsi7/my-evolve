"""The evaluation of the tests' toy problem: a program scores the number its solve() returns.

The problem evaluates in milliseconds, so the tests can run the whole loop quickly.
"""

from collections.abc import Mapping
from typing import Any

from my_evolve.evaluation_api import InvalidProgram, StageResult

# The largest number a program may return
LIMIT = 10.0


def evaluate(namespace: Mapping[str, Any]) -> StageResult:
    """Return the number solve() returns. Raises InvalidProgram if it is not a number up to 10."""
    value = namespace["solve"]()
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidProgram(f"solve() must return a number, got {type(value).__name__}")
    if value > LIMIT:
        raise InvalidProgram(f"solve() returned {value}, more than {LIMIT}")
    return StageResult(score=float(value), feedback=f"solve() returned {value}.")
