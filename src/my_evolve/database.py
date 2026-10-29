"""The Database class: every program of the run, and the choice of what to build on next.

For now the choice is as simple as it gets: a parent drawn at random among the working
programs, and a few other working programs, drawn at random too, shown to the LLM as
examples. Phase 3 of the implementation plan brings ShinkaEvolve's parent rule,
islands and MAP-Elites grids.
"""

import random

from my_evolve.program import Program

# How many example programs the prompt shows besides the parent (fewer if there are fewer)
EXAMPLE_PROGRAMS = 2


class Database:
    """Keeps every program of the run, failed ones included, and draws parents and examples."""

    def __init__(self, rng: random.Random) -> None:
        """Create an empty database.

        rng makes every random draw, so that a run with the same seed draws the same.
        """
        # Every program of the run, by id, in the order added
        self.programs: dict[str, Program] = {}
        # The id of the program with the highest score; the earliest one on a tie
        self.best_id: str | None = None
        # The run's random generator
        self.rng: random.Random = rng

    def add(self, program: Program) -> None:
        """Store a program; if it works and beats the best score, it becomes the best."""
        self.programs[program.id] = program
        score = program.result.score
        if score is None:
            return
        best_score = self.best_score()
        # Strictly higher: on a tie, the earlier program stays the best.
        if best_score is None or score > best_score:
            self.best_id = program.id

    def best(self) -> Program | None:
        """Return the program with the highest score (None while no program works)."""
        return self.programs[self.best_id] if self.best_id is not None else None

    def best_score(self) -> float | None:
        """Return the highest score so far (None while no program works)."""
        best = self.best()
        return best.result.score if best is not None else None

    def working_programs(self) -> list[Program]:
        """Return the programs that have a score, in the order they were added."""
        return [program for program in self.programs.values() if program.result.score is not None]

    def sample(self) -> tuple[Program, list[Program]]:
        """Draw the parent of the next child, and the example programs shown beside it.

        The parent is drawn uniformly among the working programs; the examples are up
        to EXAMPLE_PROGRAMS other working programs, drawn uniformly, in the order drawn.
        Failed programs are never drawn. Raises ValueError if no program works.
        """
        candidates = self.working_programs()
        if not candidates:
            raise ValueError("no working program to build on")
        parent = self.rng.choice(candidates)
        others = [program for program in candidates if program.id != parent.id]
        examples = self.rng.sample(others, min(EXAMPLE_PROGRAMS, len(others)))
        return parent, examples
