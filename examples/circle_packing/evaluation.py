"""The evaluation of the circle packing problem: 26 circles in the unit square.

A program's score is OpenEvolve's: the sum of the radii of its packing divided by
2.635, the sum the AlphaEvolve paper reached. This is a first, simplified version of
OpenEvolve's evaluator (examples/circle_packing/evaluator.py): a single stage, and an
illegal packing raises an error where OpenEvolve gives it a score of 0. Step 1.12 of
the implementation plan turns it into a faithful port.
"""

from collections.abc import Mapping
from typing import Any

import numpy as np

# The function every program must define, and how many circles it must place
ENTRY_FUNCTION = "run_packing"
NUMBER_OF_CIRCLES = 26
# The sum of the radii that scores 1.0
TARGET_VALUE = 2.635
# How far a circle may stick out of the square, or into another circle: numerical error
TOLERANCE = 1e-6


def check_packing(centers: np.ndarray[Any, Any], radii: np.ndarray[Any, Any]) -> None:
    """Raise ValueError naming the first rule of the problem the packing breaks."""
    if centers.shape != (NUMBER_OF_CIRCLES, 2) or radii.shape != (NUMBER_OF_CIRCLES,):
        raise ValueError(
            f"expected centers of shape ({NUMBER_OF_CIRCLES}, 2) and radii of shape "
            f"({NUMBER_OF_CIRCLES},), got {centers.shape} and {radii.shape}"
        )
    if np.isnan(centers).any() or np.isnan(radii).any():
        raise ValueError("the centers or the radii contain NaN values")
    for i in range(NUMBER_OF_CIRCLES):
        x, y = centers[i]
        r = radii[i]
        if r < 0:
            raise ValueError(f"circle {i} has a negative radius, {r}")
        if (
            x - r < -TOLERANCE
            or x + r > 1 + TOLERANCE
            or y - r < -TOLERANCE
            or y + r > 1 + TOLERANCE
        ):
            raise ValueError(f"circle {i} at ({x}, {y}) with radius {r} leaves the unit square")
    for i in range(NUMBER_OF_CIRCLES):
        for j in range(i + 1, NUMBER_OF_CIRCLES):
            distance = np.sqrt(np.sum((centers[i] - centers[j]) ** 2))
            if distance < radii[i] + radii[j] - TOLERANCE:
                raise ValueError(
                    f"circles {i} and {j} overlap (distance {distance:.6f}, "
                    f"radii sum {radii[i] + radii[j]:.6f})"
                )


def evaluate(namespace: Mapping[str, Any]) -> float:
    """Return the program's score: the sum of its radii divided by 2.635 (higher is better).

    namespace gives the names the program defines. Raises ValueError if the packing
    breaks a rule of the problem.
    """
    centers, radii, _ = namespace[ENTRY_FUNCTION]()
    centers = np.asarray(centers, dtype=float)
    radii = np.asarray(radii, dtype=float)
    check_packing(centers, radii)
    # The sum the program reports is ignored: it is recomputed from the radii.
    return float(np.sum(radii)) / TARGET_VALUE
