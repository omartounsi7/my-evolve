"""The Grid class: one MAP-Elites grid, fixed when the run starts (D16 to D18, D61).

Each working program is described by a few numbers, its features. Each feature's range
is cut into equal bins, and a program's cell is its bin on every feature. A cell keeps
one program, its elite: the best program found with those features. An island's
population is its grid's elites, so a program that is good in its own way survives even
when programs elsewhere in the grid score higher.

The grid is fixed: ranges and bins come from the problem file and never change, so the
same features always land in the same cell (openevolve's bins follow a running minimum
and maximum, so its cells drift: differences.md, Part D, openevolve item 6).

The built-in feature, code_complexity, is the number of syntax-tree nodes inside the
evolve blocks, written as log2 of its ratio to the initial program's: 0 for the initial
program's size, 1 for twice it, -1 for half (D18).
"""

import math
from collections.abc import Sequence

from my_evolve.problem import CODE_COMPLEXITY, FeatureSpec
from my_evolve.program import Program

# A cell of the grid: one bin number per feature
Cell = tuple[int, ...]


class Grid:
    """One MAP-Elites grid: for each occupied cell, its elite."""

    def __init__(self, features: Sequence[FeatureSpec], reference_nodes: int) -> None:
        """Create an empty grid with these dimensions.

        reference_nodes is the initial program's code complexity: every program's is
        measured against it.
        """
        # The grid's dimensions
        self.features: tuple[FeatureSpec, ...] = tuple(features)
        # The initial program's syntax-tree nodes inside the evolve blocks
        self.reference_nodes: int = reference_nodes
        # For each occupied cell, its elite
        self.elites: dict[Cell, Program] = {}

    def feature_values(self, program: Program) -> list[float]:
        """Return the program's value for each feature of the grid, in order.

        Raises ValueError for a program whose code complexity was not measured.
        """
        values = []
        for feature in self.features:
            if feature.name != CODE_COMPLEXITY:
                raise ValueError(f"the grid does not know the feature {feature.name!r}")
            if program.code_complexity is None:
                raise ValueError(f"program {program.id} has no code complexity")
            # Each count taken as at least 1, so that the logarithm exists.
            ratio = max(program.code_complexity, 1) / max(self.reference_nodes, 1)
            values.append(math.log2(ratio))
        return values

    def cell_of(self, program: Program) -> Cell:
        """Return the program's cell: for each feature, the bin its value falls in.

        The bin is the value's position between low and high, times the number of bins,
        rounded down; a value outside the range goes to the nearest end bin.
        """
        cell = []
        for feature, value in zip(self.features, self.feature_values(program), strict=True):
            position = (value - feature.low) / (feature.high - feature.low)
            cell.append(min(max(math.floor(position * feature.bins), 0), feature.bins - 1))
        return tuple(cell)

    def place(self, program: Program) -> tuple[bool, Cell, Program | None]:
        """Offer a working program its cell.

        It becomes the cell's elite if the cell is empty, or if its elite scores strictly
        lower: on a tie, the earlier program stays. Returns whether it took the cell, the
        cell, and the elite it displaced, if any. Raises ValueError for a program that does
        not work: only ok programs enter a grid (D7).
        """
        if not program.result.is_ok or program.result.score is None:
            raise ValueError(f"program {program.id} does not work: it cannot enter a grid")
        cell = self.cell_of(program)
        elite = self.elites.get(cell)
        if elite is not None and program.result.score <= (elite.result.score or 0.0):
            return False, cell, None
        self.elites[cell] = program
        return True, cell, elite

    def remove(self, program_id: str) -> None:
        """Empty the cell this program holds, if it holds one (a migrant moving away)."""
        for cell, elite in list(self.elites.items()):
            if elite.id == program_id:
                del self.elites[cell]

    def elite_list(self) -> list[Program]:
        """Return the elites in the order of their cells, so that draws can be repeated."""
        return [self.elites[cell] for cell in sorted(self.elites)]

    def best(self) -> Program | None:
        """Return the elite with the highest score; the first in cell order on a tie."""
        elites = self.elite_list()
        # max keeps the first of equal values.
        return max(elites, key=lambda elite: elite.result.score or 0.0) if elites else None
