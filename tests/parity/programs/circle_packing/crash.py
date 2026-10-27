import numpy as np


def grid(radius=0.1):
    """Return a valid packing: a 5 x 5 grid of equal circles, and a 26th of radius 0 in a corner."""
    centers = [(0.1 + 0.2 * i, 0.1 + 0.2 * j) for i in range(5) for j in range(5)]
    centers.append((0.0, 0.0))
    radii = [radius] * 25 + [0.0]
    return np.array(centers), np.array(radii)


def run_packing():
    centers, radii = grid()
    return centers[30], radii, 0.0
