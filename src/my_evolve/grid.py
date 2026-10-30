"""The Grid class: one MAP-Elites grid, fixed when the run starts (D16 to D18, D61).

Each working program is described by a few numbers, its features, and each feature's
range is cut into equal bins: a program's cell is its bin on every feature. A cell keeps
one program, its elite: the best program found with those features. An island's
population is its grid's elites, so a program that is good in its own way survives even
when it is worse than programs elsewhere in the grid.

The grid is fixed: the ranges and bins come from the problem file and never change, so
the same features always land in the same cell (openevolve's bins move with a running
minimum and maximum; differences.md, Part D, openevolve item 6).

The built-in feature, code_complexity, is the number of syntax-tree nodes inside the
evolve blocks, as log2 of its ratio to the initial program's: 0 for the initial
program's size, 1 for twice it, -1 for half (D18).
"""

import math
from collections.abc import Sequence

from my_evolve.problem import CODE_COMPLEXITY, FeatureSpec
from my_evolve.program import Program

# A cell: one bin number per feature
Cell = tuple[int, ...]


class Grid:
    """One MAP-Elites grid: for each occupied cell, its elite."""

    def __init__(self, features: Sequence[FeatureSpec], reference_nodes: int) -> None:
        """Create an empty grid.

        reference_nodes is the initial program's code complexity, which normalizes
        every program's.
        """
        # The grid's dimensions
        self.features: tuple[FeatureSpec, ...] = tuple(features)
        # The initial program's syntax-tree nodes inside the evolve blocks
        self.reference_nodes: int = reference_nodes
        # For each occupied cell, its elite
        self.elites: dict[Cell, Program] = {}

    def feature_values(self, program: Program) -> list[float]:
        """Return the program's value for each feature of the grid."""
        values = []
        for feature in self.features:
            if feature.name == CODE_COMPLEXITY:
                if program.code_complexity is None:
                    raise ValueError(f"program {program.id} has no code complexity")
                ratio = max(program.code_complexity, 1) / max(self.reference_nodes, 1)
                values.append(math.log2(ratio))
            else:
                raise ValueError(f"unknown feature {feature.name!r}")
        return values

    def cell_of(self, program: Program) -> Cell:
        """Return the program's cell: for each feature, the bin its value falls in.

        A value outside the feature's range goes to the nearest end bin.
        """
        cell = []
        for feature, value in zip(self.features, self.feature_values(program), strict=True):
            position = (value - feature.low) / (feature.high - feature.low)
            cell.append(min(max(math.floor(position * feature.bins), 0), feature.bins - 1))
        return tuple(cell)

    def place(self, program: Program) -> tuple[bool, Cell, Program | None]:
        """Offer a working program its cell.

        It takes the cell if the cell is empty or its elite scores strictly lower.
        Returns whether it took the cell, the cell, and the elite it displaced, if any.
        """
        cell = self.cell_of(program)
        elite = self.elites.get(cell)
        if elite is not None and (program.result.score or 0.0) <= (elite.result.score or 0.0):
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
        return max(elites, key=lambda elite: elite.result.score or 0.0) if elites else None
