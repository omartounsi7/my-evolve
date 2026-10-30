"""The best circle packing of the claude_3d_1 run (iteration 11): a legal sum of radii of
2.6359830849, the best found so far. Written by Claude Sonnet 5.5 through my-evolve;
the starting point of circle_packing_precise. Only its docstring is new."""

# EVOLVE-BLOCK-START
"""Constructor-based circle packing for n=26 circles"""
import time
import numpy as np
from scipy.optimize import linprog, minimize

N = 26
_IU, _JU = np.triu_indices(N, 1)


def _row_layout(counts):
    pts = []
    for k, c in enumerate(counts):
        y = (k + 0.5) / len(counts)
        for j in range(c):
            x = (j + 0.5) / c
            pts.append([x, y])
    return np.array(pts, dtype=float)


def _lp_radii(centers):
    """Maximum-sum radii for fixed centers, via linear programming."""
    n = centers.shape[0]
    bounds = []
    for x, y in centers:
        m = min(x, y, 1 - x, 1 - y)
        bounds.append((0.0, max(m, 0.0)))
    m = len(_IU)
    A = np.zeros((m, n))
    A[np.arange(m), _IU] = 1.0
    A[np.arange(m), _JU] = 1.0
    d = np.linalg.norm(centers[_IU] - centers[_JU], axis=1)
    try:
        res = linprog(-np.ones(n), A_ub=A, b_ub=d, bounds=bounds, method="highs")
    except Exception:
        return None
    if not res.success:
        return None
    return np.maximum(res.x, 0.0)


def _slsqp(centers, radii, maxiter=150):
    n = N
    iu, ju = _IU, _JU
    m = len(iu)
    idx = np.arange(n)
    rows = 4 * n + np.arange(m)

    def obj(z):
        return -np.sum(z[2 * n:])

    def grad(z):
        g = np.zeros(3 * n)
        g[2 * n:] = -1.0
        return g

    def cons(z):
        x = z[:n]; y = z[n:2 * n]; r = z[2 * n:]
        dx = x[iu] - x[ju]; dy = y[iu] - y[ju]; rs = r[iu] + r[ju]
        border = np.concatenate([x - r, 1 - x - r, y - r, 1 - y - r])
        return np.concatenate([border, dx * dx + dy * dy - rs * rs])

    J0 = np.zeros((4 * n + m, 3 * n))
    J0[idx, idx] = 1.0
    J0[idx, 2 * n + idx] = -1.0
    J0[n + idx, idx] = -1.0
    J0[n + idx, 2 * n + idx] = -1.0
    J0[2 * n + idx, n + idx] = 1.0
    J0[2 * n + idx, 2 * n + idx] = -1.0
    J0[3 * n + idx, n + idx] = -1.0
    J0[3 * n + idx, 2 * n + idx] = -1.0

    def jac(z):
        x = z[:n]; y = z[n:2 * n]; r = z[2 * n:]
        J = J0.copy()
        dx = x[iu] - x[ju]; dy = y[iu] - y[ju]; rs = r[iu] + r[ju]
        J[rows, iu] = 2 * dx
        J[rows, ju] = -2 * dx
        J[rows, n + iu] = 2 * dy
        J[rows, n + ju] = -2 * dy
        J[rows, 2 * n + iu] = -2 * rs
        J[rows, 2 * n + ju] = -2 * rs
        return J

    z0 = np.concatenate([centers[:, 0], centers[:, 1], radii])
    bounds = [(0.0, 1.0)] * (2 * n) + [(0.0, 0.5)] * n
    try:
        res = minimize(obj, z0, jac=grad, method="SLSQP", bounds=bounds,
                       constraints=[{"type": "ineq", "fun": cons, "jac": jac}],
                       options={"maxiter": maxiter, "ftol": 1e-11})
        z = res.x
    except Exception:
        z = z0
    c = np.clip(np.stack([z[:n], z[n:2 * n]], axis=1), 0.0, 1.0)
    return c


def _refine(centers):
    """LP radii -> SLSQP -> LP radii. Returns (centers, radii, sum)."""
    centers = np.clip(centers, 0.01, 0.99)
    r0 = _lp_radii(centers)
    if r0 is None:
        r0 = compute_max_radii(centers)
    c1 = _slsqp(centers, r0)
    r1 = _lp_radii(c1)
    if r1 is None:
        r1 = compute_max_radii(c1)
    s1 = float(np.sum(r1))
    s0 = float(np.sum(r0))
    if s0 > s1:
        return centers, r0, s0
    return c1, r1, s1


def construct_packing():
    """
    Construct a packing of 26 circles in the unit square.

    Returns:
        Tuple of (centers, radii, sum_of_radii)
    """
    t0 = time.time()
    budget = 45.0
    rng = np.random.default_rng(7)

    layouts = [[5, 5, 6, 5, 5], [6, 5, 5, 5, 5], [5, 6, 5, 5, 5],
               [4, 5, 4, 5, 4, 4], [5, 4, 5, 4, 4, 4], [6, 5, 4, 5, 6]]
    starts = []
    for L in layouts:
        base = _row_layout(L)
        for sig in (0.0, 0.03):
            starts.append(base + rng.normal(0, sig, base.shape))
    for _ in range(4):
        starts.append(rng.uniform(0.05, 0.95, size=(N, 2)))

    best_c, best_r, best_s = None, None, -1.0
    for c0 in starts:
        if time.time() - t0 > budget * 0.5 and best_c is not None:
            break
        c, r, s = _refine(c0)
        if s > best_s:
            best_c, best_r, best_s = c, r, s

    # Basin hopping around the best
    while time.time() - t0 < budget:
        cand = best_c.copy()
        mode = rng.integers(3)
        if mode == 0:
            cand += rng.normal(0, 0.03, cand.shape)
        elif mode == 1:
            k = rng.integers(1, 4)
            ids = rng.choice(N, k, replace=False)
            cand[ids] = rng.uniform(0.05, 0.95, size=(k, 2))
        else:
            i, j = rng.choice(N, 2, replace=False)
            cand[i] += rng.normal(0, 0.1, 2)
            cand += rng.normal(0, 0.01, cand.shape)
        c, r, s = _refine(cand)
        if s > best_s + 1e-10:
            best_c, best_r, best_s = c, r, s

    # Final safety pass: only shrinks radii
    radii = np.minimum(best_r, np.minimum.reduce(
        [best_c[:, 0], best_c[:, 1], 1 - best_c[:, 0], 1 - best_c[:, 1]]))
    radii = np.maximum(radii, 0.0)
    for i in range(N):
        for j in range(i + 1, N):
            d = np.linalg.norm(best_c[i] - best_c[j])
            if radii[i] + radii[j] > d:
                sc = d / (radii[i] + radii[j])
                radii[i] *= sc
                radii[j] *= sc
    return best_c, radii, float(np.sum(radii))


def compute_max_radii(centers):
    """
    Greedy fallback: maximum radii for each centre, avoiding overlaps.

    Args:
        centers: np.array of shape (n, 2) with (x, y) coordinates

    Returns:
        np.array of shape (n) with radius of each circle
    """
    n = centers.shape[0]
    radii = np.ones(n)
    for i in range(n):
        x, y = centers[i]
        radii[i] = max(0.0, min(x, y, 1 - x, 1 - y))
    for i in range(n):
        for j in range(i + 1, n):
            dist = np.sqrt(np.sum((centers[i] - centers[j]) ** 2))
            if radii[i] + radii[j] > dist and radii[i] + radii[j] > 0:
                scale = dist / (radii[i] + radii[j])
                radii[i] *= scale
                radii[j] *= scale
    return radii


# EVOLVE-BLOCK-END


# This part remains fixed (not evolved)
def run_packing():
    """Run the circle packing constructor for n=26"""
    centers, radii, sum_radii = construct_packing()
    return centers, radii, sum_radii


def visualize(centers, radii):
    """
    Visualize the circle packing

    Args:
        centers: np.array of shape (n, 2) with (x, y) coordinates
        radii: np.array of shape (n) with radius of each circle
    """
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle

    fig, ax = plt.subplots(figsize=(8, 8))

    # Draw unit square
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_aspect("equal")
    ax.grid(True)

    # Draw circles
    for i, (center, radius) in enumerate(zip(centers, radii)):
        circle = Circle(center, radius, alpha=0.5)
        ax.add_patch(circle)
        ax.text(center[0], center[1], str(i), ha="center", va="center")

    plt.title(f"Circle Packing (n={len(centers)}, sum={sum(radii):.6f})")
    plt.show()


if __name__ == "__main__":
    centers, radii, sum_radii = run_packing()
    print(f"Sum of radii: {sum_radii}")
    # AlphaEvolve improved this to 2.635

    # Uncomment to visualize:
    visualize(centers, radii)
