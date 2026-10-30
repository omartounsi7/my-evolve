"""The Database class: every program of the run, and the choice of what to build on next.

The programs live on islands, populations that evolve apart (D23): each starts with a
copy of the initial program, each iteration draws an island uniformly, and the child
lives on that island. Each island has its own MAP-Elites grid (D16, D61), and its
population is the grid's elites: every working program made on the island is offered
its cell as it is added. The parent is chosen among the island's elites by ShinkaEvolve's
weighted rule (D19): programs score above or below the median, and programs already
tried often are tried less. openevolve's rule is the other choice: it mixes uniform and
score-proportional draws among the elites with draws from an archive of the run's best
programs (D21). The examples are other programs made on the island, drawn
at random, failed ones and displaced elites included (D26): the LLM sees them as previous
attempts, unlabelled.

Every so often, islands exchange some of their elites (migration, D23): copies, or
moves, that take a cell of their new island's grid only if it is empty or holds a
lower score. Migrants are programs of their own, stored like any other, so a run can
be rebuilt by adding its saved programs again, in order.
"""

import math
import random
import statistics
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from my_evolve.grid import Grid
from my_evolve.problem import DEFAULT_GRID, FeatureSpec, IslandSettings, ParentSettings
from my_evolve.program import Origin, Program, Status

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
    """A rule choosing the parent of an island's next child (D75)."""

    @abstractmethod
    def choose(self, island: int, database: "Database", rng: random.Random) -> Program:
        """Return the parent of the island's next child; the island has an elite or more."""


class WeightedSelector(ParentSelector):
    """ShinkaEvolve's weighted rule (D19), from its database/parents.py, over grid elites.

    Each of the island's elites is drawn with probability proportional to
        sigmoid(lam * (score - median) / spread) * 1 / (1 + children)
    where the median and the spread are those of the elites' scores. The first term
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

    def choose(self, island: int, database: "Database", rng: random.Random) -> Program:
        """Draw one of the island's elites in proportion to its weight."""
        elites = database.islands[island].elites()
        return rng.choices(elites, weights=self.weights(elites, database))[0]


class OpenEvolveSelector(ParentSelector):
    """openevolve's rule (database.py, sample_from_island), adapted to grids (D19, D75).

    - 20% of the time, a uniform draw among the island's elites;
    - 70%, a uniform draw among the archive's programs made on this island, or among the
      whole archive if none was: the parent may then come from another island (or be the
      initial program, which belongs to none), as in openevolve;
    - 10%, a draw among the island's elites in proportion to their scores, each counted
      as at least 0.001.
    """

    # Where the draw switches from one branch to the next
    UNIFORM_SHARE = 0.2
    ARCHIVE_SHARE = 0.7
    # The least weight a score counts for, in the fitness-proportional branch
    MINIMUM_WEIGHT = 0.001

    def __init__(self, archive_size: int) -> None:
        # How many of the run's best programs the archive holds (D21)
        self.archive_size: int = archive_size

    def choose(self, island: int, database: "Database", rng: random.Random) -> Program:
        """Draw the branch, then the parent."""
        elites = database.islands[island].elites()
        draw = rng.random()
        if draw < self.UNIFORM_SHARE:
            return rng.choice(elites)
        if draw < self.UNIFORM_SHARE + self.ARCHIVE_SHARE:
            archive = database.archive(self.archive_size)
            made_here = [program for program in archive if program.island == island]
            return rng.choice(made_here or archive)
        weights = [max(elite.result.score or 0.0, self.MINIMUM_WEIGHT) for elite in elites]
        return rng.choices(elites, weights=weights)[0]


@dataclass
class Island:
    """One island: its number, its grid, and every program made on it, in order (D62)."""

    # Its number, from 0
    index: int
    # Its MAP-Elites grid, whose elites are its population (D23)
    grid: Grid
    # The ids of every program made on it, whatever its status: where examples come from
    program_ids: list[str] = field(default_factory=list)

    def elites(self) -> list[Program]:
        """Return the island's population: its grid's elites, in cell order."""
        return self.grid.elite_list()

    def best(self) -> Program | None:
        """Return the island's best elite."""
        return self.grid.best()


def make_selector(settings: ParentSettings) -> ParentSelector:
    """Return the parent selector the problem file names."""
    if settings.strategy == "openevolve":
        return OpenEvolveSelector(settings.archive_size)
    return WeightedSelector(settings.lam)


class Database:
    """Keeps every program of the run, failed ones included, and draws parents and examples."""

    def __init__(
        self,
        rng: random.Random,
        parents: ParentSettings | None = None,
        islands: IslandSettings | None = None,
        grid_features: Sequence[FeatureSpec] = DEFAULT_GRID,
        reference_nodes: int = 1,
    ) -> None:
        """Create an empty database.

        rng makes every random draw, so that a run with the same seed draws the same;
        parents says how parents are chosen (the weighted rule with lambda 1 by default);
        islands how many islands there are (3 by default). Each island's grid has the
        dimensions grid_features (code complexity alone by default), measured against
        reference_nodes, the initial program's code complexity.
        """
        # Every program of the run, by id, in the order added
        self.programs: dict[str, Program] = {}
        # For each fingerprint of a program run so far, the id of the first that had it
        self.fingerprints: dict[str, str] = {}
        # For each program, how many children the LLM wrote from it, error ones excluded
        self.children: dict[str, int] = {}
        # The id of the program with the highest score; the earliest one on a tie
        self.best_id: str | None = None
        # The number of completed iterations when the best last improved (for --patience)
        self.best_changed_at: int = 0
        # How many islands there are, and how they exchange programs
        self.island_settings: IslandSettings = islands or IslandSettings()
        # The islands
        self.islands: list[Island] = [
            Island(index, Grid(grid_features, reference_nodes))
            for index in range(self.island_settings.count)
        ]
        # The rule choosing parents
        self.selector: ParentSelector = make_selector(parents or ParentSettings())
        # The run's random generator
        self.rng: random.Random = rng

    def add(self, program: Program, completed: int = 0) -> None:
        """Store a program; if it works and beats the best score, it becomes the best.

        completed is the number of iterations completed once the program is added: the
        best's, for --patience (D37).

        A program made on an island joins that island's list, and, if it works, is
        offered its cell of the island's grid. An LLM child counts for its parent whatever
        its status (each cost an LLM call), unless it is an error, which is not the
        program's fault (D19). A moved migrant takes the program it moves out of its old
        island's grid, and keeps its children count; a copy starts at 0 (D23).
        """
        self.programs[program.id] = program
        if program.island is not None:
            self.islands[program.island].program_ids.append(program.id)
        if program.fingerprint is not None and program.result.status in FINGERPRINTED_STATUSES:
            self.fingerprints.setdefault(program.fingerprint, program.id)
        if (
            program.origin is Origin.LLM
            and program.parent_id is not None
            and program.result.status is not Status.ERROR
        ):
            self.children[program.parent_id] = self.children.get(program.parent_id, 0) + 1
        if program.origin is Origin.MOVE and program.parent_id is not None:
            moved = self.programs[program.parent_id]
            if moved.island is not None:
                self.islands[moved.island].grid.remove(moved.id)
            self.children[program.id] = self.children_count(moved.id)
        score = program.result.score
        if not program.result.is_ok or score is None:
            return
        if program.island is not None:
            self.islands[program.island].grid.place(program)
        best_score = self.best_score()
        # Strictly higher: on a tie, the earlier program stays the best.
        if best_score is None or score > best_score:
            self.best_id = program.id
            self.best_changed_at = completed

    def replay(self, programs: Sequence[Program], completed: Mapping[str, int]) -> None:
        """Add saved programs again, in the order they were stored, to rebuild a run (D49).

        completed gives each child's number of completed iterations, from history.csv
        (the first plan's P4); a program it lacks (the initial program, a copy, a migrant)
        has that of the child before it. Migrations were stored as their records, so they
        replay too; nothing is drawn.
        """
        count = 0
        for program in programs:
            count = completed.get(program.id, count)
            self.add(program, count)

    def best(self) -> Program | None:
        """Return the program with the highest score (None while no program works)."""
        return self.programs[self.best_id] if self.best_id is not None else None

    def best_score(self) -> float | None:
        """Return the highest score so far (None while no program works)."""
        best = self.best()
        return best.result.score if best is not None else None

    def archive(self, size: int) -> list[Program]:
        """Return the run's size best working programs, best first (D21).

        Computed when needed, never stored. On a tie, the earlier program comes first;
        copies of one program (one fingerprint) count once, as their earliest.
        """
        ranked = sorted(
            (program for program in self.programs.values() if program.result.is_ok),
            key=lambda program: -(program.result.score or 0.0),
        )
        archive: list[Program] = []
        seen: set[str] = set()
        for program in ranked:
            key = program.fingerprint or program.id
            if key not in seen:
                seen.add(key)
                archive.append(program)
            if len(archive) == size:
                break
        return archive

    def children_count(self, program_id: str) -> int:
        """Return how many children the program has had, error ones excluded."""
        return self.children.get(program_id, 0)

    def seed_islands(self, initial: Program) -> list[Program]:
        """Return one copy of the initial program per island, iteration 0, for the run to store.

        The initial program itself belongs to no island (D23).
        """
        return [initial.copy_to(island.index, iteration=0) for island in self.islands]

    def choose_migrants(self, island: Island) -> list[Program]:
        """Return the elites of an island that migrate this time (D23).

        Its best for "best"; otherwise migration_share of its elites, rounded down but at
        least one, drawn among all its elites ("random") or all but its best
        ("random_non_best"); fewer if there are not that many. Moves always leave the
        island one elite at least, so that it keeps a parent to draw.
        """
        settings = self.island_settings
        elites = island.elites()
        best = island.best()
        if settings.migrants == "best":
            candidates = [best] if best is not None else []
        elif settings.migrants == "random":
            candidates = elites
        else:
            candidates = [elite for elite in elites if elite is not best]
        count = min(max(1, math.floor(settings.migration_share * len(elites))), len(candidates))
        if settings.mode == "move":
            count = min(count, len(elites) - 1)
        return self.rng.sample(candidates, max(count, 0))

    def destinations(self, island: int) -> list[int]:
        """Return the islands an island's migrants go to.

        The next island for "ring", every other island for "all_others"; a moved program
        can be in one place only, so it goes to the first of them alone.
        """
        count = len(self.islands)
        if self.island_settings.destinations == "ring":
            targets = [(island + 1) % count]
        else:
            targets = [other for other in range(count) if other != island]
        targets = [target for target in targets if target != island]
        return targets[:1] if self.island_settings.mode == "move" else targets

    def migrate(self, iteration: int) -> list[Program]:
        """Return this migration's new records, for the run to add and store (D23, D63).

        Every island's migrants are chosen first, then their copies (or moves) made, so
        that an arrival never migrates again in the same round. Adding a record offers
        the migrant its cell on the new island, which it takes only if the cell is empty
        or holds a lower score. iteration is the number of completed iterations.
        """
        origin = Origin.MOVE if self.island_settings.mode == "move" else Origin.COPY
        chosen = [(island.index, self.choose_migrants(island)) for island in self.islands]
        return [
            migrant.copy_to(destination, iteration, origin)
            for index, migrants in chosen
            for migrant in migrants
            for destination in self.destinations(index)
        ]

    def island_programs(self, island: int) -> list[Program]:
        """Return every program made on an island, in the order added."""
        return [self.programs[program_id] for program_id in self.islands[island].program_ids]

    def working_programs(self, island: int) -> list[Program]:
        """Return the programs of an island whose status is ok, in the order they were added."""
        return [program for program in self.island_programs(island) if program.result.is_ok]

    def sample_island(self) -> int:
        """Draw an island uniformly (D23)."""
        return self.rng.randrange(len(self.islands))

    def sample_parent(self, island: int) -> Program:
        """Choose the parent of the next child among the island's elites (D19, D23).

        Failed programs never enter a grid, so they are never parents. Raises ValueError
        if the island has no elite.
        """
        if not self.islands[island].elites():
            raise ValueError(f"no working program on island {island} to build on")
        return self.selector.choose(island, self, self.rng)

    def sample_examples(self, island: int, parent: Program, count: int) -> list[Program]:
        """Draw up to count example programs to show beside the parent (D26).

        They are drawn uniformly, without replacement, among every program made on the
        island, failed ones included, except the parent, error programs (not the program's
        fault) and children without code; they come in the order drawn.
        """
        candidates = [
            program
            for program in self.island_programs(island)
            if program.id != parent.id
            and program.result.status is not Status.ERROR
            and program.code.strip()
        ]
        return self.rng.sample(candidates, min(count, len(candidates)))

    def sample(self, island: int, example_count: int) -> tuple[Program, list[Program]]:
        """Draw the parent of the next child on an island, then the examples shown beside it."""
        parent = self.sample_parent(island)
        return parent, self.sample_examples(island, parent, example_count)
