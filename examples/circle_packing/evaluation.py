"""The evaluation of the circle packing problem: 26 circles in the unit square.

A port of OpenEvolve's examples/circle_packing/evaluator.py (commit da3d701), run as its
config_phase_1.yaml runs it: a cascade of two stages, with a threshold of 0.5 (OpenEvolve's
second threshold, 0.75, has no stage to gate). Both stages call run_packing() once and score
it the same way, as OpenEvolve's do: the sum of the radii divided by 2.635, if the packing
is legal. Every program OpenEvolve scores above 0 gets exactly the same score here.

Stage 1 also gives two output features for the MAP-Elites grid (D17): radii_spread, how
much the radii vary, and radius_centre_correlation, whether the big circles are in the
middle (-1) or at the edges (+1). A problem file's grid may use either, or both.

Where OpenEvolve gives a score of 0, this evaluation says why instead:
- a packing that breaks a rule of the problem (wrong number of circles, NaN, a negative
  radius, a circle outside the square, two circles overlapping) raises InvalidProgram;
- an answer that is not (centers, radii, sum_of_radii) with arrays of numbers raises
  ProgramFailure: the program does not keep its contract.
"""

import math
from collections.abc import Mapping
from typing import Any

import numpy as np

from my_evolve.evaluation_api import InvalidProgram, ProgramFailure, StageResult

# The function every program must define, and how many circles it must place
ENTRY_FUNCTION = "run_packing"
NUMBER_OF_CIRCLES = 26
# The sum of the radii the AlphaEvolve paper reached, which scores 1.0
TARGET_VALUE = 2.635
# How far a circle may stick out of the square, or into another circle: numerical error
TOLERANCE = 1e-6
# The kinds of numpy arrays accepted: booleans, integers, unsigned integers, floats
NUMBER_KINDS = "biuf"


def call_run_packing(namespace: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    """Call run_packing(); return its centers and radii as numpy arrays, and its reported sum.

    The arrays keep the type the program chose (float32 included), as in OpenEvolve, where
    the score is computed in that type. Raises ProgramFailure if the answer breaks the
    contract.
    """
    answer = namespace[ENTRY_FUNCTION]()
    if not isinstance(answer, tuple | list) or len(answer) != 3:
        raise ProgramFailure(
            f"{ENTRY_FUNCTION}() must return (centers, radii, sum_of_radii), "
            f"got {type(answer).__name__} {answer!r:.200}"
        )
    try:
        centers = np.array(answer[0])
        radii = np.array(answer[1])
    except ValueError as error:
        raise ProgramFailure(f"the centers and radii must be arrays of numbers: {error}") from None
    for name, array in (("centers", centers), ("radii", radii)):
        if array.dtype.kind not in NUMBER_KINDS:
            raise ProgramFailure(f"the {name} must be numbers, got an array of {array.dtype}")
    return centers, radii, answer[2]


def check_packing(centers: Any, radii: Any) -> None:
    """Raise InvalidProgram, with the reason, if the packing breaks a rule of the problem.

    OpenEvolve's checks (validate_packing and the shapes), in an order that never fails
    on a wrong shape: shapes, NaN values, negative radii, circles outside the square,
    overlaps.
    """
    if centers.shape != (NUMBER_OF_CIRCLES, 2) or radii.shape != (NUMBER_OF_CIRCLES,):
        raise InvalidProgram(
            f"expected centers of shape ({NUMBER_OF_CIRCLES}, 2) and radii of shape "
            f"({NUMBER_OF_CIRCLES},), got {centers.shape} and {radii.shape}"
        )
    if np.isnan(centers).any() or np.isnan(radii).any():
        raise InvalidProgram("the centers or the radii contain NaN values")
    for i in range(NUMBER_OF_CIRCLES):
        if radii[i] < 0:
            raise InvalidProgram(f"circle {i} has a negative radius, {radii[i]}")
    for i in range(NUMBER_OF_CIRCLES):
        x, y = centers[i]
        r = radii[i]
        outside = (
            x - r < -TOLERANCE
            or x + r > 1 + TOLERANCE
            or y - r < -TOLERANCE
            or y + r > 1 + TOLERANCE
        )
        if outside:
            raise InvalidProgram(
                f"circle {i} at ({x}, {y}) with radius {r} is outside the unit square"
            )
    for i in range(NUMBER_OF_CIRCLES):
        for j in range(i + 1, NUMBER_OF_CIRCLES):
            distance = np.sqrt(np.sum((centers[i] - centers[j]) ** 2))
            if distance < radii[i] + radii[j] - TOLERANCE:
                raise InvalidProgram(
                    f"circles {i} and {j} overlap: their centres are {distance:.6f} apart, "
                    f"but their radii add up to {radii[i] + radii[j]:.6f}"
                )


def score_packing(radii: Any) -> StageResult:
    """Return a legal packing's score: the sum of its radii divided by 2.635.

    The sum is computed in the array's own type, as OpenEvolve computes it.
    """
    sum_radii = np.sum(radii)
    score = float(sum_radii / TARGET_VALUE)
    return StageResult(score=score, metrics={"sum_radii": float(sum_radii), "target_ratio": score})


def output_features(centers: Any, radii: Any) -> dict[str, float]:
    """Return the packing's two output features for the grid (D17).

    - radii_spread: std(radii) / mean(radii); 0 when every circle has the same size, and
      when the mean is 0.
    - radius_centre_correlation: the Pearson correlation between each circle's radius and
      the distance from its centre to (0.5, 0.5): -1 means big circles in the middle, +1
      big circles at the edges; 0 when the radii or the distances are all equal, where the
      correlation is undefined.
    """
    radii = np.asarray(radii, dtype=float)
    centers = np.asarray(centers, dtype=float)
    mean = float(np.mean(radii))
    spread = float(np.std(radii)) / mean if mean > 0 else 0.0
    distances = np.sqrt(np.sum((centers - 0.5) ** 2, axis=1))
    if np.ptp(radii) == 0 or np.ptp(distances) == 0:
        correlation = 0.0
    else:
        correlation = float(np.corrcoef(radii, distances)[0, 1])
    return {
        "radii_spread": spread,
        "radius_centre_correlation": correlation if math.isfinite(correlation) else 0.0,
    }


def evaluate_stage1(namespace: Mapping[str, Any]) -> StageResult:
    """Stage 1: call run_packing() once, check the packing and score it (OpenEvolve's stage 1).

    Also gives the packing's output features.
    """
    centers, radii, _ = call_run_packing(namespace)
    check_packing(centers, radii)
    result = score_packing(radii)
    feedback = (
        f"Valid packing: all {NUMBER_OF_CIRCLES} circles lie in the unit square without "
        f"overlapping. Sum of radii: {result.metrics['sum_radii']:.6f} "
        f"(the target, {TARGET_VALUE}, scores 1)."
    )
    return StageResult(result.score, result.metrics, feedback, output_features(centers, radii))


def evaluate_stage2(namespace: Mapping[str, Any]) -> StageResult:
    """Stage 2: a second call, scored the same way (OpenEvolve's full evaluate).

    As in OpenEvolve, the sum the program reports must be a number; one that differs
    from the sum of the radii only earns a warning.
    """
    centers, radii, reported_sum = call_run_packing(namespace)
    check_packing(centers, radii)
    result = score_packing(radii)
    if isinstance(reported_sum, bool) or not isinstance(reported_sum, int | float):
        raise InvalidProgram(f"sum_of_radii must be a number, got {type(reported_sum).__name__}")
    feedback = ""
    if abs(result.metrics["sum_radii"] - reported_sum) > TOLERANCE:
        feedback = (
            f"Warning: run_packing() reports a sum of radii of {reported_sum}, but its radii "
            f"add up to {result.metrics['sum_radii']:.6f}."
        )
    return StageResult(result.score, result.metrics, feedback)
