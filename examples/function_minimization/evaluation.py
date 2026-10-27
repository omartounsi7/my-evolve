"""The evaluation of the function minimization problem.

A port of OpenEvolve's examples/function_minimization/evaluator.py, at commit
da3d701 (D3, D9). Programs look for the global minimum of
f(x, y) = sin(x) cos(y) + sin(xy) + (x² + y²) / 20, which has many local minima;
every working program gets exactly the score OpenEvolve gives it. As in that
commit, the value of f is always recomputed from the (x, y) the program returns,
never taken from it (Part D, v1 item 4). What differs:

- the evaluation runs on the host and calls run_search() through the program's
  namespace, in the sandbox (D8); a call over 5 s is really stopped (D8);
- an answer that breaks the rules is invalid, and one that cannot be read at all
  is failed, instead of scoring 0 (D7);
- the checks write feedback for the LLM, like OpenEvolve's artifacts (D10).

The cascade is OpenEvolve's: stage 1 calls run_search once and scores its answer;
a program scoring at least 1.3 (the problem file's threshold) goes on to stage 2,
which calls it 10 times, scores the average answer and how often it succeeded, and
replaces the stage 1 score.
"""

from typing import Any

import numpy as np

from my_evolve.evaluation_api import (
    CallTimeout,
    InvalidProgram,
    ProgramFailure,
    StageResult,
    call_with_timeout,
)

# The function every program must define (it lies outside the evolve block).
ENTRY_FUNCTION = "run_search"
# OpenEvolve's approximation of the global minimum.
GLOBAL_MIN_X = -1.704
GLOBAL_MIN_Y = 0.678
GLOBAL_MIN_VALUE = -1.519
# Each call of run_search may take this long, in seconds.
CALL_TIME_LIMIT = 5
NUMBER_OF_TRIALS = 10


def objective(x: Any, y: Any) -> Any:
    """Return f(x, y), computed as OpenEvolve's evaluator computes it."""
    return np.sin(x) * np.cos(y) + np.sin(x * y) + (x**2 + y**2) / 20


def safe_float(value: Any) -> float:
    """Return value as a float, or 0.0 if it cannot be converted, as OpenEvolve does."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def read_point(result: Any) -> tuple[float, float, Any]:
    """Return the x and y of run_search's answer, and f recomputed there.

    Raises ProgramFailure for an answer that is not a tuple of 2 or 3 values, and
    InvalidProgram for one that is not a finite point; OpenEvolve scores both 0.
    """
    if not isinstance(result, tuple):
        raise ProgramFailure(
            f"{ENTRY_FUNCTION} must return a tuple (x, y) or (x, y, value), "
            f"got {type(result).__name__}"
        )
    if len(result) not in (2, 3):
        raise ProgramFailure(
            f"{ENTRY_FUNCTION} must return a tuple of 2 or 3 values, got {len(result)}"
        )
    if len(result) == 2:
        # OpenEvolve computes f on the two values as they come, before converting them:
        # values f cannot take, such as text, score 0 there.
        try:
            objective(result[0], result[1])
        except Exception as error:
            raise InvalidProgram(
                f"f cannot be computed at the point {ENTRY_FUNCTION} returned: {error}"
            ) from None
    # A third value is never trusted: f is recomputed from (x, y).
    x = safe_float(result[0])
    y = safe_float(result[1])
    try:
        value = objective(x, y)
        finite = bool(np.isfinite(x) and np.isfinite(y) and np.isfinite(value))
    except (ArithmeticError, TypeError, ValueError):
        finite = False
        value = float("nan")
    if not finite:
        raise InvalidProgram(
            f"{ENTRY_FUNCTION} returned a point that is not finite: x={x}, y={y}, f={value}"
        )
    return x, y, value


def quality_multiplier(distance: float, limits_and_multipliers: tuple[float, ...]) -> float:
    """Return OpenEvolve's bonus or penalty for a distance to the global minimum.

    limits_and_multipliers holds the multipliers for distances below 0.5, 1.5, 3.0,
    and beyond, in that order.
    """
    close, region, closer, beyond = limits_and_multipliers
    if distance < 0.5:
        return close
    if distance < 1.5:
        return region
    if distance < 3.0:
        return closer
    return beyond


def describe_quality(distance: float) -> str:
    """Return OpenEvolve's words for a distance to the global minimum."""
    if distance < 0.5:
        return "Distance < 0.5: very close"
    if distance < 1.5:
        return "Distance < 1.5: good region"
    return "Could be improved"


def evaluate_stage1(namespace: Any) -> StageResult:
    """Stage 1: call run_search once, within 5 s, and score its answer.

    An answer that does not come in time is a timeout: the only call gave no answer (D7).
    """
    result = call_with_timeout(namespace[ENTRY_FUNCTION], CALL_TIME_LIMIT)
    x, y, value = read_point(result)

    # The same arithmetic as OpenEvolve's, step by step, so that scores are identical.
    x_diff = float(x) - GLOBAL_MIN_X
    y_diff = float(y) - GLOBAL_MIN_Y
    distance = float(np.sqrt(x_diff**2 + y_diff**2))
    value_score = float(1.0 / (1.0 + abs(value - GLOBAL_MIN_VALUE)))
    distance_score = float(1.0 / (1.0 + distance))
    multiplier = quality_multiplier(distance, (1.4, 1.15, 1.0, 0.8))
    base_score = 0.6 * value_score + 0.4 * distance_score
    combined_score = float(base_score * multiplier)

    return StageResult(
        score=combined_score,
        metrics={
            "runs_successfully": 1.0,
            "value_score": value_score,
            "distance_score": distance_score,
        },
        feedback="\n".join(
            [
                f"Found a solution at x={x:.4f}, y={y:.4f} with value={float(value):.4f}.",
                f"Distance to the global minimum: {distance:.4f}.",
                describe_quality(distance),
            ]
        ),
    )


def evaluate_stage2(namespace: Any) -> StageResult:
    """Stage 2: call run_search 10 times, 5 s each, and score the average answer.

    A call that fails or times out is skipped and counts against reliability, as in
    OpenEvolve. If all of them fail, the program is invalid: OpenEvolve then scores
    it 0, which replaces the stage 1 score (D9).
    """
    run_search = namespace[ENTRY_FUNCTION]
    values: list[Any] = []
    distances: list[Any] = []
    failures: list[str] = []
    last_point = (0.0, 0.0)

    for trial in range(1, NUMBER_OF_TRIALS + 1):
        try:
            x, y, value = read_point(call_with_timeout(run_search, CALL_TIME_LIMIT))
        except CallTimeout:
            failures.append(f"call {trial}: {ENTRY_FUNCTION} took more than {CALL_TIME_LIMIT} s")
            continue
        except ProgramFailure as failure:
            failures.append(f"call {trial}: {failure.message}")
            continue
        except InvalidProgram as invalid:
            failures.append(f"call {trial}: {invalid.reason}")
            continue
        x_diff = x - GLOBAL_MIN_X
        y_diff = y - GLOBAL_MIN_Y
        distances.append(np.sqrt(x_diff**2 + y_diff**2))
        values.append(value)
        last_point = (x, y)

    successes = len(values)
    if successes == 0:
        raise InvalidProgram(
            f"all {NUMBER_OF_TRIALS} calls of {ENTRY_FUNCTION} failed",
            feedback="\n".join(failures),
        )

    average_value = float(np.mean(values))
    average_distance = float(np.mean(distances))
    value_score = float(1.0 / (1.0 + abs(average_value - GLOBAL_MIN_VALUE)))
    distance_score = float(1.0 / (1.0 + average_distance))
    reliability_score = float(successes / NUMBER_OF_TRIALS)
    multiplier = quality_multiplier(average_distance, (1.5, 1.2, 1.0, 0.7))
    base_score = 0.5 * value_score + 0.3 * distance_score + 0.2 * reliability_score
    combined_score = float(base_score * multiplier)

    feedback = [
        f"{successes} of {NUMBER_OF_TRIALS} calls succeeded.",
        f"Last position found: x={last_point[0]:.4f}, y={last_point[1]:.4f}.",
        f"Average distance to the global minimum: {average_distance:.4f}.",
        *failures,
    ]
    return StageResult(
        score=combined_score,
        metrics={
            "value_score": value_score,
            "distance_score": distance_score,
            "reliability_score": reliability_score,
        },
        feedback="\n".join(feedback),
    )
