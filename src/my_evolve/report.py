"""The report of a run (D51, D79): what scripts/report.py draws into RUN_FOLDER/report/.

    progress.png        the best score so far against completed iterations, with every
                        ok child's score as a dot
    output_0010.png     the best program's output after that many iterations, at every
                        snapshot and at the end, drawn by the evaluation file's
                        visualize(output_data, path) if it defines one

The run folder is only read; the report folder is written. A run still in progress can
be reported on: a last line being written is left out.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

# Draw into files, without a screen.
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402 - the backend must be chosen first

from my_evolve.evaluator import load_evaluation_file  # noqa: E402
from my_evolve.problem import Problem, ProblemError  # noqa: E402
from my_evolve.program import Program  # noqa: E402
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
    return written
