"""The evaluation of the circle packing problem: 26 circles in the unit square.

A port of OpenEvolve's examples/circle_packing/evaluator.py, at commit da3d701
(D3, D9). Every working program gets exactly the score OpenEvolve gives it: the sum
of its radii divided by 2.635, the sum the AlphaEvolve paper reached. What differs:

- the evaluation runs on the host and calls run_packing() through the program's
  namespace, in the sandbox (D8);
- a packing that breaks the rules is invalid, with the reason, instead of scoring 0;
  an answer that cannot be read at all is failed (D7);
- every check writes feedback for the LLM (D10);
- stage 1 also measures two output features for the MAP-Elites grid (D17), and keeps
  the circles as output data for the report's drawings (D51).

The cascade is OpenEvolve's: stage 1 builds the packing once and scores it; a
packing scoring at least 0.5 (the problem file's threshold) is built and scored
again by stage 2, OpenEvolve's full evaluation, whose score replaces the first.
"""

from typing import Any

import numpy as np

from my_evolve.evaluation_api import InvalidProgram, ProgramFailure, StageResult

# The function every program must define (it lies outside the evolve block).
ENTRY_FUNCTION = "run_packing"
NUMBER_OF_CIRCLES = 26
# The sum of the radii the AlphaEvolve paper reached, which sums are divided by.
TARGET_VALUE = 2.635
# The numerical error tolerated at the square's sides and between circles, as in OpenEvolve.
TOLERANCE = 1e-6
# The centre of the square, from which the distance of each circle is measured (D17).
SQUARE_CENTRE = np.array([0.5, 0.5])
# How many of the rules a packing breaks are named in its feedback.
MAX_PROBLEMS_SHOWN = 5


def read_answer(result: Any) -> tuple[np.ndarray, np.ndarray, Any]:
    """Return the centres and radii run_packing returned, as numpy arrays, and the sum it reported.

    Raises ProgramFailure if the answer is not three values, or not numbers: OpenEvolve
    scores such answers 0, and here they are failed (D7).
    """
    try:
        centres, radii, reported_sum = result
    except (TypeError, ValueError):
        raise ProgramFailure(
            f"{ENTRY_FUNCTION} must return (centers, radii, sum_of_radii), "
            f"got {type(result).__name__}"
        ) from None
    # The arrays keep the type the program gave them (float32 sums differ from float64
    # ones), so that the score is exactly OpenEvolve's.
    try:
        centres = np.asarray(centres)
        radii = np.asarray(radii)
    except (TypeError, ValueError) as error:
        raise ProgramFailure(f"the centers and radii must be arrays of numbers: {error}") from None
    for name, array in (("centers", centres), ("radii", radii)):
        if array.dtype.kind not in "biuf":
            raise ProgramFailure(f"the {name} must be numbers, got an array of {array.dtype}")
    return centres, radii, reported_sum


def packing_problems(centres: np.ndarray, radii: np.ndarray) -> list[str]:
    """Return every rule the packing breaks, in OpenEvolve's order of checks; empty if valid."""
    if centres.shape != (NUMBER_OF_CIRCLES, 2) or radii.shape != (NUMBER_OF_CIRCLES,):
        return [
            f"expected centers of shape ({NUMBER_OF_CIRCLES}, 2) and radii of shape "
            f"({NUMBER_OF_CIRCLES},), got {centres.shape} and {radii.shape}"
        ]
    if np.isnan(centres).any() or np.isnan(radii).any():
        return ["the centers or the radii hold NaN values"]
    problems = []
    for i in range(NUMBER_OF_CIRCLES):
        if radii[i] < 0:
            problems.append(f"circle {i} has a negative radius ({radii[i]:.6f})")
    for i in range(NUMBER_OF_CIRCLES):
        x, y = centres[i]
        r = radii[i]
        if (
            x - r < -TOLERANCE
            or x + r > 1 + TOLERANCE
            or y - r < -TOLERANCE
            or y + r > 1 + TOLERANCE
        ):
            problems.append(
                f"circle {i} at ({x:.6f}, {y:.6f}) with radius {r:.6f} is outside the unit square"
            )
    for i in range(NUMBER_OF_CIRCLES):
        for j in range(i + 1, NUMBER_OF_CIRCLES):
            distance = np.sqrt(np.sum((centres[i] - centres[j]) ** 2))
            if distance < radii[i] + radii[j] - TOLERANCE:
                problems.append(
                    f"circles {i} and {j} overlap (distance between centres {distance:.6f}, "
                    f"radii sum {radii[i] + radii[j]:.6f})"
                )
    return problems


def output_features(centres: np.ndarray, radii: np.ndarray) -> dict[str, float]:
    """Return the two output features of a valid packing (D17).

    - radii_spread: std(radii) / mean(radii); 0 when all circles have the same size,
      or when the mean is 0.
    - radius_centre_correlation: the correlation of each circle's radius with the
      distance from its centre to the square's centre; -1 means big circles in the
      middle, +1 big circles at the edges; 0 when it is undefined (all radii, or all
      distances, equal).
    """
    mean = float(np.mean(radii))
    spread = float(np.std(radii)) / mean if mean > 0 else 0.0
    distances = np.sqrt(np.sum((centres - SQUARE_CENTRE) ** 2, axis=1))
    if np.std(radii) == 0 or np.std(distances) == 0:
        correlation = 0.0
    else:
        correlation = float(np.corrcoef(radii, distances)[0, 1])
    return {"radii_spread": spread, "radius_centre_correlation": correlation}


def score_packing(namespace: Any, with_features: bool) -> StageResult:
    """Build the packing once, check it, and score it as OpenEvolve does."""
    result = namespace[ENTRY_FUNCTION]()
    centres, radii, reported_sum = read_answer(result)

    problems = packing_problems(centres, radii)
    if problems:
        shown = "\n".join(f"- {problem}" for problem in problems[:MAX_PROBLEMS_SHOWN])
        more = len(problems) - MAX_PROBLEMS_SHOWN
        if more > 0:
            shown += f"\n- ... and {more} more"
        raise InvalidProgram(
            problems[0],
            feedback=f"The packing breaks {len(problems)} rule(s):\n{shown}",
        )

    sum_radii = np.sum(radii)
    target_ratio = float(sum_radii / TARGET_VALUE)
    feedback = [
        f"{ENTRY_FUNCTION} returned {NUMBER_OF_CIRCLES} circles: all are inside the unit "
        "square and none overlap.",
        f"Sum of the radii: {float(sum_radii):.6f}, which is {target_ratio:.4%} of {TARGET_VALUE}.",
    ]
    try:
        if abs(float(reported_sum) - float(sum_radii)) > TOLERANCE:
            feedback.append(
                f"The sum {ENTRY_FUNCTION} reported, {float(reported_sum):.6f}, is not the sum "
                f"of the radii, {float(sum_radii):.6f}; the score uses the radii."
            )
    except (TypeError, ValueError):
        feedback.append(f"The sum {ENTRY_FUNCTION} reported is not a number.")

    return StageResult(
        score=target_ratio,
        metrics={"sum_radii": float(sum_radii), "target_ratio": target_ratio},
        features=output_features(centres, radii) if with_features else {},
        feedback="\n".join(feedback),
        output_data={"centers": centres.tolist(), "radii": radii.tolist()},
    )


def evaluate_stage1(namespace: Any) -> StageResult:
    """Stage 1: build the packing once and score it (OpenEvolve's evaluate_stage1)."""
    return score_packing(namespace, with_features=True)


def evaluate_stage2(namespace: Any) -> StageResult:
    """Stage 2: build and score it again, freshly loaded (OpenEvolve's evaluate)."""
    return score_packing(namespace, with_features=False)
