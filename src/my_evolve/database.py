"""The Database class: every program of the run, and the choice of parents (D16 to D23, D63).

Everything here is derived from the programs: adding the saved programs again, in
order, rebuilds the database exactly (D49), so none of it is saved on its own. Only
the main thread uses it (D36).

For now the run has one island, and an island's population is every working
program made on it; MAP-Elites grids and several islands come in later steps.
"""

import math
import random
import statistics
from abc import ABC, abstractmethod
from collections.abc import Iterable

from my_evolve.problem import Problem
from my_evolve.program import Origin, Program, Status

# The statuses whose programs count for the duplicate check (D13): the ones that ran.
FINGERPRINTED_STATUSES = (Status.OK, Status.FAILED, Status.TIMEOUT, Status.INVALID)


def stable_sigmoid(x: float) -> float:
    """Return 1 / (1 + e^-x) without overflowing for large |x|."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    exp_x = math.exp(x)
    return exp_x / (1.0 + exp_x)


class Island:
    """One island: its number, its population, and every program made on it (D23, D62)."""

    def __init__(self, index: int) -> None:
        self.index: int = index
        # Every program made on the island, in order, failed ones included: where
        # example programs are drawn from (D26).
        self.program_ids: list[str] = []
        # The island's working programs, which parents are drawn from.
        self.population: list[Program] = []

    def elites(self) -> list[Program]:
        """Return the island's population, in a fixed order so that draws can be repeated."""
        return list(self.population)

    def best(self) -> Program | None:
        """Return the island's best program; the earliest on a tie."""
        best: Program | None = None
        for program in self.population:
            if best is None or score_of(program) > score_of(best):
                best = program
        return best


def score_of(program: Program) -> float:
    """Return a working program's score."""
    assert program.result.score is not None
    return program.result.score


class ParentSelector(ABC):
    """A strategy for choosing a parent among an island's elites (D19, D75)."""

    @abstractmethod
    def choose(self, island: Island, database: "Database", rng: random.Random) -> Program:
        """Return the parent of the next child made on the island."""


class WeightedSelector(ParentSelector):
    """ShinkaEvolve's weighted rule, adapted to my-evolve (D19, D75).

    An elite is drawn with probability proportional to
    sigmoid(λ × (score − median) / spread) × 1 / (1 + children):
    good programs are favoured, and so are programs that have had few children.
    """

    def __init__(self, lam: float) -> None:
        # λ: how strongly higher scores are favoured; 0 ignores scores (D19).
        self.lam: float = lam

    def weights(self, elites: list[Program], database: "Database") -> list[float]:
        """Return each elite's weight, in the order given.

        The median and the spread are those of the elites' scores; the spread is their
        median absolute deviation, or their standard deviation if that is 0; if both
        are 0, every elite's performance term is 0.5 (D19).
        """
        scores = [score_of(elite) for elite in elites]
        median = statistics.median(scores)
        spread = statistics.median(abs(score - median) for score in scores)
        if spread == 0:
            spread = statistics.pstdev(scores)
        weights = []
        for elite, score in zip(elites, scores, strict=True):
            performance = (
                0.5 if spread == 0 else stable_sigmoid(self.lam * (score - median) / spread)
            )
            novelty = 1.0 / (1.0 + database.children_count(elite.id))
            weights.append(performance * novelty)
        return weights

    def choose(self, island: Island, database: "Database", rng: random.Random) -> Program:
        """Draw one of the island's elites in proportion to its weight."""
        elites = island.elites()
        if not elites:
            raise ValueError(f"island {island.index} has no working program to choose from")
        return rng.choices(elites, weights=self.weights(elites, database))[0]


def make_selector(problem: Problem) -> ParentSelector:
    """Return the parent selector the problem file names (D19)."""
    if problem.parents.strategy == "weighted":
        return WeightedSelector(problem.parents.lam)
    raise ValueError(f"unknown parent strategy {problem.parents.strategy!r}")


class Database:
    """All of the run's state that is derived from its programs (D63)."""

    def __init__(self, problem: Problem, initial_program: Program, rng: random.Random) -> None:
        """Create an empty database for a run starting from initial_program.

        The initial program itself is not added: the loop adds it, then seeds the islands.
        """
        self.problem: Problem = problem
        # The initial program's code complexity, the grid's reference (D18).
        self.reference_complexity: int | None = initial_program.code_complexity
        # Every program of the run, by id, in the order added (D22).
        self.programs: dict[str, Program] = {}
        self.islands: list[Island] = [Island(0)]
        # For each fingerprint, the id of the first program that had it (D13).
        self.fingerprints: dict[str, str] = {}
        # For each program, its number of llm children, error ones excluded (D19).
        self.children: dict[str, int] = {}
        # The best ok program so far; the earliest on a tie.
        self.best_id: str | None = None
        # The number of completed iterations when the best last improved (for --patience).
        self.best_changed_at: int = 0
        self.selector: ParentSelector = make_selector(problem)
        # The run's random generator (D39).
        self.rng: random.Random = rng

    def add(self, program: Program, completed: int | None = None) -> None:
        """Record a program and everything derived from it (D63).

        completed is the number of completed iterations when it was made, if known.
        Raises ValueError for an id already recorded, or a parent never recorded.
        """
        if program.id in self.programs:
            raise ValueError(f"the program {program.id} was already added")
        if program.parent_id is not None and program.parent_id not in self.programs:
            raise ValueError(f"the program {program.id} has an unknown parent {program.parent_id}")
        self.programs[program.id] = program
        if program.island is not None:
            self.islands[program.island].program_ids.append(program.id)

        status = program.result.status
        if program.fingerprint is not None and status in FINGERPRINTED_STATUSES:
            self.fingerprints.setdefault(program.fingerprint, program.id)

        if program.origin is Origin.LLM and status is not Status.ERROR:
            assert program.parent_id is not None
            self.children[program.parent_id] = self.children_count(program.parent_id) + 1

        if program.result.is_ok:
            if program.island is not None:
                self.islands[program.island].population.append(program)
            best = self.best_or_none()
            if best is None or score_of(program) > score_of(best):
                self.best_id = program.id
                if completed is not None:
                    self.best_changed_at = completed

    def seed_islands(self, initial_program: Program) -> list[Program]:
        """Put one copy of the initial program on every island, and return the copies (D23)."""
        copies = [
            initial_program.copy_to(island.index, iteration=0, mode=Origin.COPY)
            for island in self.islands
        ]
        for copy in copies:
            self.add(copy)
        return copies

    def best_or_none(self) -> Program | None:
        """Return the best ok program so far, or None before any."""
        return self.programs[self.best_id] if self.best_id is not None else None

    def best(self) -> Program:
        """Return the best ok program so far."""
        best = self.best_or_none()
        if best is None:
            raise ValueError("the database holds no working program yet")
        return best

    def children_count(self, program_id: str) -> int:
        """Return how many children a program has had, error ones excluded (D19)."""
        return self.children.get(program_id, 0)

    def sample_island(self) -> Island:
        """Draw the iteration's island, uniformly (D23)."""
        return self.islands[self.rng.randrange(len(self.islands))]

    def sample_parent(self, island: Island) -> Program:
        """Return the parent selector's choice on that island (D19)."""
        return self.selector.choose(island, self, self.rng)

    def replay(self, programs: Iterable[Program]) -> None:
        """Add saved programs again, in order, to rebuild the database (D49)."""
        for program in programs:
            self.add(program)
