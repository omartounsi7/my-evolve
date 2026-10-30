"""The report of a run (D51, D79): what scripts/report.py draws into RUN_FOLDER/report/.

    progress.png        the best score so far against completed iterations, with every
                        ok child's score as a dot
    output_0010.png     the best program's output after that many iterations, at every
                        snapshot and at the end, drawn by the evaluation file's
                        visualize(output_data, path) if it defines one
    grids_0010.png      every island's MAP-Elites grid after that many iterations, at
                        every snapshot and at the end, on one colour scale
    grids.gif           the grid images, one after another

The run folder is only read; the report folder is written. A run still in progress can
be reported on: a last line being written is left out.
"""

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
from matplotlib.cm import ScalarMappable
from matplotlib.colors import LinearSegmentedColormap, Normalize
from PIL import Image

# Draw into files, without a screen.
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402 - the backend must be chosen first

from my_evolve.database import Database  # noqa: E402
from my_evolve.evaluator import load_evaluation_file  # noqa: E402
from my_evolve.grid import Cell  # noqa: E402
from my_evolve.problem import FeatureSpec, Problem, ProblemError  # noqa: E402
from my_evolve.program import Origin, Program  # noqa: E402
from my_evolve.storage import (  # noqa: E402
    PROBLEM_COPY,
    HistoryRow,
    RunFolderError,
    Storage,
    saved_run_info,
)

# The report's folder, inside the run folder
REPORT_FOLDER = "report"
# The function of an evaluation file that draws a program's output data
VISUALIZE_FUNCTION = "visualize"
# The colours of the drawings: the reference palette's first two series, its surface and
# its inks (the dataviz guidance)
BEST_COLOUR = "#2a78d6"
CHILD_COLOUR = "#eb6834"
SURFACE_COLOUR = "#fcfcfb"
TEXT_COLOUR = "#0b0b0b"
MUTED_COLOUR = "#52514e"
GRID_COLOUR = "#e4e3df"
# An empty cell of a MAP-Elites grid
EMPTY_COLOUR = "#ffffff"
# Occupied cells go from light (the run's lowest score) to deep blue (its highest): the
# Blues colour map without its near-white end, which an empty cell could be taken for
SCORE_COLOURS = LinearSegmentedColormap.from_list(
    "scores", plt.get_cmap("Blues")(np.linspace(0.25, 1.0, 256))
)
# How long each grid image shows in the animation, in milliseconds
FRAME_MILLISECONDS = 700


class ReportError(Exception):
    """Raised when a run folder cannot be reported on; the message says why."""


@dataclass
class RunData:
    """What a run folder holds, read back."""

    # The problem, from the folder's copy of the problem file
    problem: Problem
    # Every program, in the order stored; the first is the initial program
    programs: list[Program]
    # One row per completed iteration, in the order completed
    history: list[HistoryRow]
    # The evaluation file the last session used; None if run.json does not say
    evaluation_file: Path | None


def load_run(folder: Path) -> RunData:
    """Read a run folder back, without changing it. Raises ReportError if it cannot be read."""
    if not (folder / PROBLEM_COPY).is_file():
        raise ReportError(f"{folder} has no {PROBLEM_COPY}: it is not a run folder")
    try:
        problem = Problem.load(folder / PROBLEM_COPY)
        storage = Storage(folder)
        programs = storage.load_programs(repair=False)
        history = storage.load_history(repair=False)
    except (ProblemError, RunFolderError) as error:
        raise ReportError(str(error)) from None
    if not programs:
        raise ReportError(f"{folder} holds no program yet")
    info = saved_run_info(folder)
    sessions = info.sessions if info is not None else []
    path = sessions[-1].get("evaluation_file") if sessions else None
    return RunData(problem, programs, history, Path(path) if path else None)


def snapshot_counts(snapshot_every: int, completed: int) -> list[int]:
    """Return the completed counts at which the run took a snapshot: 0, every
    snapshot_every, and the last count, if it is not one of them."""
    counts = list(range(0, completed + 1, snapshot_every))
    if counts[-1] != completed:
        counts.append(completed)
    return counts


def best_at_snapshots(run: RunData) -> list[tuple[int, Program]]:
    """Return the best program at every snapshot and at the end, with its completed count.

    The initial program at 0; afterwards, the best that the history row of that count names.
    """
    by_id = {program.id: program for program in run.programs}
    best_by_count = {row.completed: row.best_id for row in run.history}
    snapshots = [(0, run.programs[0])]
    for count in snapshot_counts(run.problem.snapshot_every, len(run.history))[1:]:
        best = by_id.get(best_by_count.get(count, ""))
        if best is not None:
            snapshots.append((count, best))
    return snapshots


def style(axes: Any) -> None:
    """Give a plot's axes the report's look: a light surface, a recessive grid, muted axes."""
    axes.set_facecolor(SURFACE_COLOUR)
    axes.grid(True, color=GRID_COLOUR, linewidth=0.8)
    axes.set_axisbelow(True)
    for side in ("top", "right"):
        axes.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        axes.spines[side].set_color(MUTED_COLOUR)
    axes.tick_params(colors=MUTED_COLOUR, labelcolor=MUTED_COLOUR)


def plot_progress(run: RunData, path: Path) -> None:
    """Draw the best score so far against completed iterations, as a step line from the
    initial program's score, with every ok child's score as a dot (D51)."""
    counts = [0] + [row.completed for row in run.history]
    initial_score = run.programs[0].result.score
    best = [initial_score] + [row.best_score for row in run.history]
    ok = [
        (row.completed, row.score)
        for row in run.history
        if row.status == "ok" and row.score is not None
    ]
    figure, axes = plt.subplots(figsize=(9, 5), facecolor=SURFACE_COLOUR)
    style(axes)
    if ok:
        axes.scatter(
            [count for count, _ in ok],
            [score for _, score in ok],
            s=36,
            color=CHILD_COLOUR,
            alpha=0.6,
            edgecolors=SURFACE_COLOUR,
            linewidths=1,
            label="ok child",
            zorder=2,
        )
    axes.step(
        counts,
        [float("nan") if score is None else score for score in best],
        where="post",
        color=BEST_COLOUR,
        linewidth=2,
        label="best score so far",
        zorder=3,
    )
    axes.set_xlabel("completed iterations", color=TEXT_COLOUR)
    axes.set_ylabel("score", color=TEXT_COLOUR)
    axes.set_title(f"{run.problem.name}: progress", color=TEXT_COLOUR, loc="left")
    axes.legend(frameon=False, labelcolor=TEXT_COLOUR)
    figure.tight_layout()
    figure.savefig(path, facecolor=SURFACE_COLOUR)
    plt.close(figure)


def find_visualize(evaluation_file: Path | None) -> Callable[[Any, Path], Any] | None:
    """Return the evaluation file's visualize function, or None if it defines none.

    The file is loaded on this machine: it is the problem's own code, as during the run.
    """
    if evaluation_file is None or not evaluation_file.is_file():
        return None
    visualize = load_evaluation_file(evaluation_file).get(VISUALIZE_FUNCTION)
    return visualize if callable(visualize) else None


def draw_outputs(
    visualize: Callable[[Any, Path], Any], snapshots: Sequence[tuple[int, Program]], folder: Path
) -> list[Path]:
    """Draw each snapshot's program output into output_NNNN.png; return the files written.

    A program without output data is left out. Raises ReportError if visualize fails.
    """
    written = []
    for count, program in snapshots:
        if program.result.output_data is None:
            continue
        path = folder / f"output_{count:04d}.png"
        try:
            visualize(program.result.output_data, path)
        except Exception as error:
            raise ReportError(
                f"visualize failed on the best program after {count} iterations "
                f"({program.id}): {type(error).__name__}: {error}"
            ) from error
        plt.close("all")
        written.append(path)
    return written


@dataclass
class GridSnapshot:
    """Every island's grid at one moment of the run: each occupied cell's score."""

    # The number of completed iterations
    count: int
    # For each island, the score of each occupied cell's elite
    islands: list[dict[Cell, float]]


def take_snapshot(database: Database, count: int) -> GridSnapshot:
    """Return a copy of every island's grid, with the completed count."""
    return GridSnapshot(
        count,
        [
            {cell: elite.result.score or 0.0 for cell, elite in island.grid.elites.items()}
            for island in database.islands
        ],
    )


def grid_snapshots(run: RunData) -> list[GridSnapshot]:
    """Replay the run, and take its grids at every snapshot and at the end (D79).

    Each child's completed count comes from the history. A snapshot due at a count is
    taken once that count's child is added, before the migrants of that count, as the run
    took its own; one due after an iteration without a child is taken before the next
    program that comes later. A replay draws nothing at random.
    """
    database = Database(
        random.Random(0),
        run.problem.parents,
        run.problem.islands,
        run.problem.grid_features,
        reference_nodes=run.programs[0].code_complexity or 1,
    )
    counts = {row.program_id: row.completed for row in run.history if row.program_id}
    due = snapshot_counts(run.problem.snapshot_every, len(run.history))
    snapshots: list[GridSnapshot] = []

    def take_due(up_to: float) -> None:
        """Take the snapshots due at counts up to this one, included."""
        while due and due[0] <= up_to:
            snapshots.append(take_snapshot(database, due.pop(0)))

    for program in run.programs:
        if program.origin is Origin.LLM:
            count = counts.get(program.id)
            if count is None:
                # A child whose iteration was never finished: the run left it out too.
                continue
            take_due(count - 1)
            database.add(program, count)
            take_due(count)
        else:
            # A migrant carries the completed count of its migration; the initial program
            # and its island copies carry 0, and belong to the first snapshot.
            if program.iteration > 0:
                take_due(program.iteration)
            database.add(program)
    take_due(math.inf)
    return snapshots


def colour_scale(programs: Sequence[Program]) -> tuple[float, float]:
    """Return the lowest and the highest score of the run's working programs: one scale
    for every grid image. A run with a single score gets a scale around it."""
    scores = [program.result.score for program in programs if program.result.score is not None]
    low, high = (min(scores), max(scores)) if scores else (0.0, 1.0)
    return (low, high) if low < high else (low - 0.5, high + 0.5)


def grid_array(cells: dict[Cell, float], features: Sequence[FeatureSpec]) -> Any:
    """Return a grid as an array of scores, one axis per feature; NaN for an empty cell."""
    array = np.full(tuple(feature.bins for feature in features), np.nan)
    for cell, score in cells.items():
        array[cell] = score
    return array


def bin_edges(feature: FeatureSpec) -> Any:
    """Return the edges of a feature's bins, from low to high."""
    return np.linspace(feature.low, feature.high, feature.bins + 1)


def draw_panel(
    axes: Any,
    array: Any,
    features: Sequence[FeatureSpec],
    norm: Normalize,
    x_label: bool = True,
    y_label: bool = True,
) -> None:
    """Draw a 1D or 2D grid: a 1D grid as a row of cells, a 2D grid as a square, the first
    feature across and the second up; thin lines between the cells, so that empty ones
    show. x_label and y_label say whether to name the features along the axes."""
    colours = SCORE_COLOURS.with_extremes(bad=EMPTY_COLOUR)
    first = features[0]
    if len(features) == 1:
        axes.imshow(
            array[np.newaxis, :],
            cmap=colours,
            norm=norm,
            extent=(first.low, first.high, 0, 1),
            aspect="auto",
            interpolation="nearest",
        )
        axes.set_yticks([])
    else:
        second = features[1]
        axes.imshow(
            array.T,
            cmap=colours,
            norm=norm,
            origin="lower",
            extent=(first.low, first.high, second.low, second.high),
            aspect="auto",
            interpolation="nearest",
        )
        axes.set_yticks(bin_edges(second), minor=True)
        if y_label:
            axes.set_ylabel(second.name, color=MUTED_COLOUR)
    axes.set_xticks(bin_edges(first), minor=True)
    if x_label:
        axes.set_xlabel(first.name, color=MUTED_COLOUR)
    axes.grid(which="minor", color=GRID_COLOUR, linewidth=0.8)
    axes.tick_params(which="minor", length=0)
    axes.tick_params(colors=MUTED_COLOUR, labelcolor=MUTED_COLOUR, labelsize=8)
    for spine in axes.spines.values():
        spine.set_color(GRID_COLOUR)


def draw_grids(
    snapshot: GridSnapshot,
    features: Sequence[FeatureSpec],
    scale: tuple[float, float],
    path: Path,
    title: str = "",
) -> None:
    """Draw every island's grid at one snapshot (D51).

    An empty cell is white, an occupied one blue, from light for the scale's lowest score
    to deep for its highest. A 1D grid is a row of cells, one island under another; a 2D
    grid a square, the islands side by side; a 3D grid one square per bin of its third
    feature, each island a row. A colour bar gives the scale; the title says after how
    many iterations.
    """
    norm = Normalize(*scale)
    islands = len(snapshot.islands)
    arrays = [grid_array(cells, features) for cells in snapshot.islands]
    if len(features) == 1:
        rows, columns, size = islands, 1, (9.0, 1.2 + 0.9 * islands)
    elif len(features) == 2:
        rows, columns, size = 1, islands, (1.0 + 3.6 * islands, 4.2)
    else:
        rows, columns = islands, features[2].bins
        size = (1.2 + 2.9 * columns, 0.8 + 2.7 * rows)
    figure, axes = plt.subplots(
        rows, columns, figsize=size, squeeze=False, layout="constrained", facecolor=SURFACE_COLOUR
    )
    for island, array in enumerate(arrays):
        if len(features) < 3:
            panel = axes[island][0] if len(features) == 1 else axes[0][island]
            # Each axis is named once: under the last strip, left of the first square.
            draw_panel(
                panel,
                array,
                features,
                norm,
                x_label=len(features) == 2 or island == islands - 1,
                y_label=island == 0,
            )
            panel.set_title(f"island {island}", color=TEXT_COLOUR, fontsize=10, loc="left")
            continue
        third = features[2]
        width = (third.high - third.low) / third.bins
        for bin_number in range(third.bins):
            panel = axes[island][bin_number]
            draw_panel(
                panel,
                array[:, :, bin_number],
                features[:2],
                norm,
                x_label=island == islands - 1,
                y_label=bin_number == 0,
            )
            low = third.low + bin_number * width
            panel.set_title(
                f"island {island}, {third.name}\n{low:.3g} to {low + width:.3g}",
                color=TEXT_COLOUR,
                fontsize=8,
                loc="left",
            )
    colour_bar = figure.colorbar(
        ScalarMappable(norm=norm, cmap=SCORE_COLOURS), ax=axes, shrink=0.9, label="score"
    )
    colour_bar.outline.set_visible(False)
    colour_bar.ax.tick_params(colors=MUTED_COLOUR, labelcolor=MUTED_COLOUR)
    heading = f"{title}: " if title else ""
    figure.suptitle(
        f"{heading}grids after {snapshot.count} iterations", color=TEXT_COLOUR, x=0.02, ha="left"
    )
    figure.savefig(path, facecolor=SURFACE_COLOUR)
    plt.close(figure)


def animate(images: Sequence[Path], path: Path) -> None:
    """Join images of one size into an animated GIF, each shown FRAME_MILLISECONDS."""
    frames = [Image.open(image).convert("RGB") for image in images]
    frames[0].save(
        path, save_all=True, append_images=frames[1:], duration=FRAME_MILLISECONDS, loop=0
    )


def write_report(folder: Path) -> list[Path]:
    """Draw a run folder's report into its report folder; return the files written.

    Raises ReportError if the folder cannot be read, or if visualize fails.
    """
    run = load_run(folder)
    report = folder / REPORT_FOLDER
    report.mkdir(exist_ok=True)
    written = [report / "progress.png"]
    plot_progress(run, written[0])
    visualize = find_visualize(run.evaluation_file)
    if visualize is not None:
        written.extend(draw_outputs(visualize, best_at_snapshots(run), report))
    scale = colour_scale(run.programs)
    grid_images = []
    for snapshot in grid_snapshots(run):
        path = report / f"grids_{snapshot.count:04d}.png"
        draw_grids(snapshot, run.problem.grid_features, scale, path, run.problem.name)
        grid_images.append(path)
    animate(grid_images, report / "grids.gif")
    return [*written, *grid_images, report / "grids.gif"]
