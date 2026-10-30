"""The evaluation of circle packing at full precision: 26 circles in the unit square.

A variant of ../circle_packing/evaluation.py for going past the best known packing,
where gains are in the sixth decimal or beyond. That evaluation, a port of OpenEvolve's,
lets circles overlap, or stick out of the square, by up to 1e-6: across 26 circles, that
slack is worth more than any real gain left. Here only legal geometry counts:

- the packing's worst violation (the most two circles overlap, or one sticks out of the
  square) is measured; every radius is then shrunk by it, which makes the packing legal,
  and the score is the sum of the shrunk radii (a radius smaller than the shrink becomes
  0). Using the tolerance thus costs up to 26 times what it brings;
- a violation above 1e-6, a wrong shape, a NaN or a negative radius is still an illegal
  packing (InvalidProgram), and an answer that breaks the contract a failure;
- the score is that legal sum divided by 2.6359830849, the best legal sum found so far:
  a score above 1 is a better packing than any found before. The sum is computed in
  64-bit floats, whatever type the program returns.

One stage: the program is called once. Its output features are those of the original
evaluation, for the MAP-Elites grid, and its centres and radii are kept for the report.
"""

import math
from collections.abc import Mapping
from typing import Any

import numpy as np

from my_evolve.evaluation_api import InvalidProgram, ProgramFailure, StageResult

# The function every program must define, and how many circles it must place
ENTRY_FUNCTION = "run_packing"
NUMBER_OF_CIRCLES = 26
# The best legal sum of radii found so far, which scores 1.0: claude_3d_1's best packing,
# whose worst violation is 2.8e-17 (round-off)
BEST_KNOWN_SUM = 2.6359830849
# The largest violation that is shrunk away rather than refused
MAX_VIOLATION = 1e-6
# The largest violation that floating-point round-off explains: still shrunk away, but the
# feedback does not send the LLM after it
ROUND_OFF = 1e-14
# The kinds of numpy arrays accepted: booleans, integers, unsigned integers, floats
NUMBER_KINDS = "biuf"


def call_run_packing(namespace: Mapping[str, Any]) -> tuple[Any, Any]:
    """Call run_packing(); return its centres and radii as arrays of 64-bit floats.

    Raises ProgramFailure if the answer breaks the contract.
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
    return centers.astype(np.float64), radii.astype(np.float64)


def check_shape(centers: Any, radii: Any) -> None:
    """Raise InvalidProgram for a wrong shape, a NaN or a negative radius."""
    if centers.shape != (NUMBER_OF_CIRCLES, 2) or radii.shape != (NUMBER_OF_CIRCLES,):
        raise InvalidProgram(
            f"expected centers of shape ({NUMBER_OF_CIRCLES}, 2) and radii of shape "
            f"({NUMBER_OF_CIRCLES},), got {centers.shape} and {radii.shape}"
        )
    if not (np.isfinite(centers).all() and np.isfinite(radii).all()):
        raise InvalidProgram("the centers or the radii contain NaN or infinite values")
    if (radii < 0).any():
        i = int(np.argmin(radii))
        raise InvalidProgram(f"circle {i} has a negative radius, {radii[i]}")


def worst_violation(centers: Any, radii: Any) -> tuple[float, str]:
    """Return the packing's worst violation, and where it is.

    The most two circles overlap (the sum of their radii minus the distance between
    their centres), or the most a circle sticks out of the square; 0 or less for a legal
    packing.
    """
    i, j = np.triu_indices(NUMBER_OF_CIRCLES, 1)
    overlaps = radii[i] + radii[j] - np.linalg.norm(centers[i] - centers[j], axis=1)
    k = int(np.argmax(overlaps))
    worst, where = float(overlaps[k]), f"circles {i[k]} and {j[k]} overlap"
    walls = np.stack(
        [radii - centers[:, 0], centers[:, 0] + radii - 1, radii - centers[:, 1],
         centers[:, 1] + radii - 1]
    )  # fmt: skip
    side, circle = np.unravel_index(int(np.argmax(walls)), walls.shape)
    if walls[side, circle] > worst:
        worst = float(walls[side, circle])
        where = f"circle {circle} sticks out of the square"
    return worst, where


def output_features(centers: Any, radii: Any) -> dict[str, float]:
    """Return the packing's two output features for the grid (D17), as the original
    evaluation computes them: radii_spread and radius_centre_correlation."""
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


def evaluate(namespace: Mapping[str, Any]) -> StageResult:
    """Call run_packing() once, make its packing legal, and score the legal sum."""
    centers, radii = call_run_packing(namespace)
    check_shape(centers, radii)
    violation, where = worst_violation(centers, radii)
    if violation > MAX_VIOLATION:
        raise InvalidProgram(
            f"{where} by {violation:.3e}, more than the {MAX_VIOLATION:g} that is shrunk away"
        )
    shrink = max(violation, 0.0)
    legal_radii = np.maximum(radii - shrink, 0.0)
    legal_sum = float(np.sum(legal_radii))
    raw_sum = float(np.sum(radii))
    feedback = [
        f"Legal sum of radii: {legal_sum:.12f} (the best found so far, {BEST_KNOWN_SUM}, "
        f"scores 1; the difference is {legal_sum - BEST_KNOWN_SUM:+.3e})."
    ]
    if 0 < shrink <= ROUND_OFF:
        feedback.append(
            f"The contacts touch within floating-point round-off (worst overlap {shrink:.1e})."
        )
    elif shrink > 0:
        feedback.append(
            f"Worst violation: {where} by {shrink:.3e}. Every radius was shrunk by that much "
            f"to make the packing legal, which cost {raw_sum - legal_sum:.3e} of the sum."
        )
    else:
        feedback.append(f"No violation: the closest contact leaves a gap of {-violation:.3e}.")
    return StageResult(
        score=legal_sum / BEST_KNOWN_SUM,
        metrics={
            "sum_radii": legal_sum,
            "raw_sum_radii": raw_sum,
            "worst_violation": violation,
        },
        feedback=" ".join(feedback),
        features=output_features(centers, legal_radii),
        output_data={"centers": centers.tolist(), "radii": legal_radii.tolist()},
    )


def visualize(output_data: dict[str, Any], path: Any) -> None:
    """Draw a packing into an image file: the unit square, each circle with its number,
    and n and the legal sum of the radii as the title. Called by the report."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle

    centers, radii = output_data["centers"], output_data["radii"]
    figure, axes = plt.subplots(figsize=(8, 8))
    axes.set_xlim(0, 1)
    axes.set_ylim(0, 1)
    axes.set_aspect("equal")
    axes.grid(True)
    for i, (center, radius) in enumerate(zip(centers, radii, strict=True)):
        axes.add_patch(Circle(center, radius, alpha=0.5))
        axes.text(center[0], center[1], str(i), ha="center", va="center")
    axes.set_title(f"Circle Packing (n={len(centers)}, legal sum={sum(radii):.10f})")
    figure.savefig(path)
    plt.close(figure)
