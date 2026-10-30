"""The evaluation of the function minimization problem.

The program must find the global minimum of
    f(x, y) = sin(x) * cos(y) + sin(x * y) + (x^2 + y^2) / 20,
near (-1.704, 0.678), where f = -1.519. Its run_search() returns (x, y) or (x, y, value).

A port of OpenEvolve's examples/function_minimization/evaluator.py (commit da3d701), run as
its config.yaml runs it: a cascade of two stages with a threshold of 1.3.
- Stage 1 calls run_search() once, with a time limit of 5 s, and scores the point found.
- Stage 2 calls it 10 times, 5 s each, skips the trials that fail, and scores the average
  point and how many trials succeeded.
The function's value is always recomputed from (x, y): the value the program reports is
never trusted (OpenEvolve issue #514). Every program OpenEvolve scores above 0 gets
exactly the same score here.

Where OpenEvolve gives a score of 0, this evaluation says why instead: an answer that is
not a tuple of 2 or 3 values raises ProgramFailure; a point where the function is not
finite, or whose coordinates OpenEvolve cannot use, raises InvalidProgram; a stage-1 call
over 5 s lets CallTimeout through (status timeout).
"""

from collections.abc import Mapping
from typing import Any

import numpy as np

from my_evolve.evaluation_api import (
    CallTimeout,
    InvalidProgram,
    ProgramFailure,
    StageResult,
    call_with_timeout,
)

# The function every program must define
ENTRY_FUNCTION = "run_search"
# The known global minimum (approximate), as OpenEvolve gives it
GLOBAL_MIN_X = -1.704
GLOBAL_MIN_Y = 0.678
GLOBAL_MIN_VALUE = -1.519
# Each call of run_search() may take this long, in seconds
TRIAL_TIME_LIMIT = 5.0
# How many times stage 2 calls run_search()
TRIALS = 10
# How many skipped trials stage 2's feedback describes
MAX_TRIAL_NOTES = 3


def objective(x: Any, y: Any) -> Any:
    """The function being minimized."""
    return np.sin(x) * np.cos(y) + np.sin(x * y) + (x**2 + y**2) / 20


def safe_float(value: Any) -> float:
    """Return value as a float, or 0.0 if float() refuses it, as OpenEvolve does."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def read_point(answer: Any) -> tuple[float, float, Any]:
    """Return the (x, y) run_search() found and the function's value there, as OpenEvolve
    reads them.

    Raises ProgramFailure if the answer is not a tuple of 2 or 3 values, InvalidProgram if
    the point cannot be used or the function is not finite there.
    """
    if not isinstance(answer, tuple):
        raise ProgramFailure(
            f"{ENTRY_FUNCTION}() must return a tuple (x, y) or (x, y, value), "
            f"got {type(answer).__name__}"
        )
    if len(answer) == 3:
        x, y, _ = answer
    elif len(answer) == 2:
        x, y = answer
        # OpenEvolve computes the value before converting the coordinates: only numbers pass.
        if not all(isinstance(value, int | float) for value in (x, y)):
            raise InvalidProgram(
                f"{ENTRY_FUNCTION}() returned coordinates that are not numbers: {answer!r:.200}"
            )
    else:
        raise ProgramFailure(
            f"{ENTRY_FUNCTION}() must return 2 or 3 values, (x, y) or (x, y, value), "
            f"got {len(answer)}"
        )
    x = safe_float(x)
    y = safe_float(y)
    # Never the reported value: it is recomputed from (x, y).
    value = objective(x, y)
    if not all(np.isfinite(number) for number in (x, y, value)):
        raise InvalidProgram(
            f"{ENTRY_FUNCTION}() returned a point where the function is not finite: "
            f"x={x}, y={y}, value={value}"
        )
    return x, y, value


def evaluate_stage1(namespace: Mapping[str, Any]) -> StageResult:
    """Stage 1: one call of run_search(), 5 s at most, scored on the point found."""
    answer = call_with_timeout(namespace[ENTRY_FUNCTION], TRIAL_TIME_LIMIT)
    x, y, value = read_point(answer)
    x_diff = float(x) - GLOBAL_MIN_X
    y_diff = float(y) - GLOBAL_MIN_Y
    distance = float(np.sqrt(x_diff**2 + y_diff**2))
    value_score = float(1.0 / (1.0 + abs(value - GLOBAL_MIN_VALUE)))
    distance_score = float(1.0 / (1.0 + distance))
    if distance < 0.5:
        multiplier = 1.4
    elif distance < 1.5:
        multiplier = 1.15
    elif distance < 3.0:
        multiplier = 1.0
    else:
        multiplier = 0.8
    base_score = 0.6 * value_score + 0.4 * distance_score
    return StageResult(
        score=float(base_score * multiplier),
        metrics={
            "runs_successfully": 1.0,
            "value_score": value_score,
            "distance_score": distance_score,
        },
        feedback=(
            f"Stage 1: {ENTRY_FUNCTION}() found x={x:.4f}, y={y:.4f}, where f = {value:.4f}; "
            f"distance to the global minimum: {distance:.4f}."
        ),
    )


def evaluate_stage2(namespace: Mapping[str, Any]) -> StageResult:
    """Stage 2: ten calls of run_search(), 5 s each; trials that fail are skipped.

    Raises InvalidProgram if every trial fails (OpenEvolve then scores the program 0).
    """
    run_search = namespace[ENTRY_FUNCTION]
    values: list[Any] = []
    distances: list[Any] = []
    notes: list[str] = []
    for trial in range(1, TRIALS + 1):
        try:
            x, y, value = read_point(call_with_timeout(run_search, TRIAL_TIME_LIMIT))
        except (CallTimeout, ProgramFailure, InvalidProgram) as error:
            notes.append(f"Trial {trial} of {TRIALS} failed: {str(error).splitlines()[0]}")
            continue
        values.append(value)
        distances.append(np.sqrt((x - GLOBAL_MIN_X) ** 2 + (y - GLOBAL_MIN_Y) ** 2))
    if not values:
        raise InvalidProgram(f"all {TRIALS} trials of {ENTRY_FUNCTION}() failed", "\n".join(notes))
    avg_value = float(np.mean(values))
    avg_distance = float(np.mean(distances))
    value_score = float(1.0 / (1.0 + abs(avg_value - GLOBAL_MIN_VALUE)))
    distance_score = float(1.0 / (1.0 + avg_distance))
    reliability_score = float(len(values) / TRIALS)
    if avg_distance < 0.5:
        multiplier = 1.5
    elif avg_distance < 1.5:
        multiplier = 1.2
    elif avg_distance < 3.0:
        multiplier = 1.0
    else:
        multiplier = 0.7
    base_score = 0.5 * value_score + 0.3 * distance_score + 0.2 * reliability_score
    feedback = [
        f"Stage 2: {len(values)} of {TRIALS} trials succeeded; average value {avg_value:.4f}, "
        f"average distance to the global minimum {avg_distance:.4f}."
    ]
    feedback.extend(notes[:MAX_TRIAL_NOTES])
    if len(notes) > MAX_TRIAL_NOTES:
        feedback.append(f"({len(notes) - MAX_TRIAL_NOTES} more trials failed.)")
    return StageResult(
        score=float(base_score * multiplier),
        metrics={
            "value_score": value_score,
            "distance_score": distance_score,
            "reliability_score": reliability_score,
        },
        feedback="\n".join(feedback),
    )
