"""The Database class: every program of the run, and the choice of what to build on next.

The parent is chosen by ShinkaEvolve's weighted rule (D19): programs score above or
below the median, and programs already tried often are tried less. The examples are
other working programs drawn at random. Islands and MAP-Elites grids come in the next
steps of the plan.
"""

import math
import random
import statistics
from abc import ABC, abstractmethod
from collections.abc import Sequence

from my_evolve.problem import ParentSettings
from my_evolve.program import Program, Status

# The statuses whose programs count for the duplicate check: they were run. Rejected ones
# never were, and an error is not the program's fault: an identical child may be tried.
FINGERPRINTED_STATUSES = (Status.OK, Status.FAILED, Status.TIMEOUT, Status.INVALID)


def sigmoid(x: float) -> float:
    """Return 1 / (1 + e^-x), computed without overflow for large x of either sign."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    exponential = math.exp(x)
    return exponential / (1.0 + exponential)


class ParentSelector(ABC):
    """A rule choosing the parent of the next child among candidate programs (D75)."""

    @abstractmethod
    def choose(
        self, candidates: Sequence[Program], database: "Database", rng: random.Random
    ) -> Program:
        """Return one of the candidates, which are working programs (never empty)."""


class WeightedSelector(ParentSelector):
    """ShinkaEvolve's weighted rule (D19), from its database/parents.py.

    Each candidate is drawn with probability proportional to
        sigmoid(lam * (score - median) / spread) * 1 / (1 + children)
    where the median and the spread are those of the candidates' scores. The first term
    favours good programs, the second programs that have had few children. The spread
    is the median absolute deviation, or the standard deviation if that is 0; if both
    are 0 (every score equal), every sigmoid term is 0.5.
    """

    def __init__(self, lam: float) -> None:
        # How sharply the rule favours programs above the median (ShinkaEvolve uses 10)
        self.lam: float = lam

    def weights(self, candidates: Sequence[Program], database: "Database") -> list[float]:
        """Return each candidate's weight, in order."""
        scores = [program.result.score or 0.0 for program in candidates]
        median = statistics.median(scores)
        spread = statistics.median(abs(score - median) for score in scores)
        if spread == 0:
            spread = statistics.pstdev(scores)
        weights = []
        for program, score in zip(candidates, scores, strict=True):
            performance = 0.5 if spread == 0 else sigmoid(self.lam * (score - median) / spread)
            novelty = 1.0 / (1.0 + database.children_count(program.id))
            weights.append(performance * novelty)
        return weights

    def choose(
        self, candidates: Sequence[Program], database: "Database", rng: random.Random
    ) -> Program:
        """Draw one candidate in proportion to its weight."""
        return rng.choices(candidates, weights=self.weights(candidates, database))[0]


def make_selector(settings: ParentSettings) -> ParentSelector:
    """Return the parent selector the problem file names."""
    return WeightedSelector(settings.lam)


class Database:
    """Keeps every program of the run, failed ones included, and draws parents and examples."""

    def __init__(self, rng: random.Random, parents: ParentSettings | None = None) -> None:
        """Create an empty database.

        rng makes every random draw, so that a run with the same seed draws the same;
        parents says how parents are chosen (the weighted rule with lambda 1 by default).
        """
        # Every program of the run, by id, in the order added
        self.programs: dict[str, Program] = {}
        # For each fingerprint of a program run so far, the id of the first that had it
        self.fingerprints: dict[str, str] = {}
        # For each program, how many children the LLM wrote from it, error ones excluded
        self.children: dict[str, int] = {}
        # The id of the program with the highest score; the earliest one on a tie
        self.best_id: str | None = None
        # The rule choosing parents
        self.selector: ParentSelector = make_selector(parents or ParentSettings())
        # The run's random generator
        self.rng: random.Random = rng

    def add(self, program: Program) -> None:
        """Store a program; if it works and beats the best score, it becomes the best.

        A child counts for its parent whatever its status (each cost an LLM call), unless
        it is an error, which is not the program's fault (D19).
        """
        self.programs[program.id] = program
        if program.fingerprint is not None and program.result.status in FINGERPRINTED_STATUSES:
            self.fingerprints.setdefault(program.fingerprint, program.id)
        if program.parent_id is not None and program.result.status is not Status.ERROR:
            self.children[program.parent_id] = self.children.get(program.parent_id, 0) + 1
        score = program.result.score
        if not program.result.is_ok or score is None:
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

    def children_count(self, program_id: str) -> int:
        """Return how many children the program has had, error ones excluded."""
        return self.children.get(program_id, 0)

    def working_programs(self) -> list[Program]:
        """Return the programs whose status is ok, in the order they were added."""
        return [program for program in self.programs.values() if program.result.is_ok]

    def sample(self, example_count: int) -> tuple[Program, list[Program]]:
        """Draw the parent of the next child, and the example programs shown beside it.

        The parent is chosen among the working programs by the parent selector; the
        examples are up to example_count other working programs, drawn uniformly, in the
        order drawn. Failed programs are never drawn. Raises ValueError if no program works.
        """
        candidates = self.working_programs()
        if not candidates:
            raise ValueError("no working program to build on")
        parent = self.selector.choose(candidates, self, self.rng)
        others = [program for program in candidates if program.id != parent.id]
        examples = self.rng.sample(others, min(example_count, len(others)))
        return parent, examples
