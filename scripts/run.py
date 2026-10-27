"""The command line of my-evolve: evolve a problem's program (D45, D79).

Usage:
    python scripts/run.py INITIAL_PROGRAM EVALUATION_FILE --config PROBLEM_FILE
        [--iterations N] [--output FOLDER] [--workers N] [--seed N]
        [--unsafe-local-sandbox] [--verbose]

Ctrl+C once: no new iteration starts, and those in progress finish and are saved.
Ctrl+C twice (or SIGTERM, on Linux and macOS): the run stops at once.
"""

import argparse
import io
import sys
from datetime import datetime
from pathlib import Path

from my_evolve.checks import MarkerError
from my_evolve.evaluator import EvaluationFileError
from my_evolve.llm import LLMError, ModelSetupError
from my_evolve.loop import RunError, RunInterrupted, RunSettings, run
from my_evolve.problem import Problem, ProblemError
from my_evolve.sandbox import SandboxError
from my_evolve.storage import StorageError

DEFAULT_ITERATIONS = 100
DEFAULT_WORKERS = 1
# Where run folders go when --output is not given (D45).
RUNS_FOLDER = Path("runs")

# The errors that mean "this run cannot start or go on": shown as one message.
RUN_ERRORS = (
    ProblemError,
    RunError,
    SandboxError,
    EvaluationFileError,
    ModelSetupError,
    LLMError,
    StorageError,
    MarkerError,
)

# The exit code of a program stopped by Ctrl+C, by convention.
INTERRUPTED_EXIT_CODE = 130


def positive_integer(text: str) -> int:
    """Read a whole number of at least 1, for argparse."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be a whole number, got {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {value}")
    return value


def make_parser() -> argparse.ArgumentParser:
    """Return the parser of the command line."""
    parser = argparse.ArgumentParser(prog="run.py", description="Evolve a program with my-evolve.")
    parser.add_argument("initial_program", type=Path, help="the program evolution starts from")
    parser.add_argument(
        "evaluation_file", type=Path, help="the Python file defining the evaluation's stages"
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="the problem file (YAML): the problem and its settings",
    )
    parser.add_argument(
        "--iterations",
        type=positive_integer,
        default=DEFAULT_ITERATIONS,
        help=(
            "completed iterations in all; running the same command again on the same "
            f"--output finishes an interrupted run (default: {DEFAULT_ITERATIONS})"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="the run folder (default: runs/<problem name>_<date>_<time>)",
    )
    parser.add_argument(
        "--workers",
        type=positive_integer,
        default=DEFAULT_WORKERS,
        help=f"iterations in progress at once (default: {DEFAULT_WORKERS})",
    )
    parser.add_argument(
        "--seed", type=int, default=None, help="the seed of the run's random draws (default: drawn)"
    )
    parser.add_argument(
        "--unsafe-local-sandbox",
        action="store_true",
        help="run programs WITHOUT ANY ISOLATION: for tests and trusted code only",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="show the details of each iteration on the console"
    )
    return parser


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    """Read the command line; a wrong value is reported as a usage error (exit code 2)."""
    parser = make_parser()
    arguments = parser.parse_args(argv)
    for name in ("initial_program", "evaluation_file", "config"):
        path: Path = getattr(arguments, name)
        if not path.is_file():
            parser.error(f"no such file: {path}")
    return arguments


def default_output(problem_name: str, now: datetime | None = None) -> Path:
    """Return runs/<problem name>_<date>_<time>, with characters every system accepts."""
    moment = now or datetime.now()
    return RUNS_FOLDER / f"{problem_name}_{moment:%Y-%m-%d_%H-%M-%S}"


def use_utf8_console() -> None:
    """Let the console show any character, even where its encoding cannot (D55)."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Run my-evolve from the command line, and return the exit code."""
    use_utf8_console()
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    try:
        output = arguments.output
        if output is None:
            output = default_output(Problem.load(arguments.config).name)
        settings = RunSettings(
            initial_program=arguments.initial_program,
            evaluation_file=arguments.evaluation_file,
            problem_file=arguments.config,
            output=output,
            iterations=arguments.iterations,
            workers=arguments.workers,
            seed=arguments.seed,
            unsafe_local_sandbox=arguments.unsafe_local_sandbox,
            verbose=arguments.verbose,
        )
        run(settings)
    except RUN_ERRORS as error:
        print(f"my-evolve: {error}", file=sys.stderr)
        return 1
    except (RunInterrupted, KeyboardInterrupt):
        return INTERRUPTED_EXIT_CODE
    return 0


if __name__ == "__main__":
    sys.exit(main())
