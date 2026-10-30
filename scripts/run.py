"""Evolve a program: the command line of my-evolve.

Usage:
    python scripts/run.py INITIAL_PROGRAM EVALUATION_FILE --config PROBLEM_FILE
        --iterations N [--output FOLDER] [--workers W] [--seed S] [--unsafe-local-sandbox]
        [--verbose]

The run folder defaults to runs/<problem name>_<date>_<time>. Running the same command
with --output naming an existing run folder continues that run: --iterations is the total,
the iterations already done included.

Programs run in Docker containers, so Docker must be installed and running.

Example, from the repository root:
    python scripts/run.py examples/circle_packing/initial_program.py
        examples/circle_packing/evaluation.py --config examples/circle_packing/problem.yaml
        --iterations 20 --output runs/circle_packing_1
"""

import argparse
import io
import sys
import uuid
from datetime import datetime
from pathlib import Path

from my_evolve.evaluator import EvaluationFileError, Evaluator
from my_evolve.llm import Ensemble, MissingKeyError
from my_evolve.loop import RunError, StopNow, run, stop_on_sigterm
from my_evolve.problem import Problem, ProblemError
from my_evolve.sandbox import DockerSandbox, LocalSandbox, Sandbox, SandboxError, ensure_image
from my_evolve.storage import saved_run_info

# Shown when programs run without the Docker sandbox
UNSAFE_WARNING = (
    "WARNING: --unsafe-local-sandbox: the programs the LLM writes run as plain processes, "
    "with your files, your network and your environment variables (API keys included). "
    "Use it for tests and trusted code only."
)


def positive_integer(text: str) -> int:
    """Read a whole number of at least 1, for argparse."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be 1 or more, got {value}")
    return value


def parse_arguments(arguments: list[str]) -> argparse.Namespace:
    """Read the command line; a wrong value stops the script with a usage message."""
    parser = argparse.ArgumentParser(description="Evolve a program with an LLM (AlphaEvolve).")
    parser.add_argument("initial_program", type=Path, help="the program evolution starts from")
    parser.add_argument("evaluation_file", type=Path, help="the file that scores programs")
    parser.add_argument(
        "--config", type=Path, required=True, help="the problem file (YAML): the problem and LLM"
    )
    parser.add_argument(
        "--iterations",
        type=positive_integer,
        required=True,
        help="how many iterations in all (a continued run counts those it did)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="the run folder, where everything is saved (default: runs/<problem>_<date>_<time>);"
        " an existing run folder is continued",
    )
    parser.add_argument(
        "--workers",
        type=positive_integer,
        default=1,
        help="how many iterations may be in flight at once (default 1)",
    )
    parser.add_argument("--seed", type=int, help="fixes the random draws (default: drawn)")
    parser.add_argument(
        "--unsafe-local-sandbox",
        action="store_true",
        help="run programs as plain processes, without Docker or any isolation (tests only)",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="show each iteration's details on the console"
    )
    parsed = parser.parse_args(arguments)
    for path in (parsed.initial_program, parsed.evaluation_file, parsed.config):
        if not path.is_file():
            parser.error(f"no such file: {path}")
    return parsed


def default_output(problem_name: str) -> Path:
    """Return the default run folder: runs/, the problem's name, the date and the time (D45)."""
    return Path("runs") / f"{problem_name}_{datetime.now():%Y-%m-%d_%H-%M-%S}"


def make_sandbox(problem: Problem, unsafe_local: bool, run_id: str) -> Sandbox:
    """Return the sandbox programs run in: Docker, unless the unsafe local one is asked for.

    Builds the evaluation image on first use. Raises SandboxError if Docker fails.
    """
    if unsafe_local:
        print(UNSAFE_WARNING, file=sys.stderr)
        return LocalSandbox(problem.sandbox.cpus)
    print("Preparing the Docker sandbox (the first time, its image is built)...")
    return DockerSandbox(ensure_image(problem.packages), problem.sandbox, run_id)


def main(arguments: list[str]) -> int:
    """Run my-evolve from the command line; return the exit code."""
    # Text beyond plain English must reach a Windows console too (D55).
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    parsed = parse_arguments(arguments)
    output = parsed.output
    stop_on_sigterm()
    try:
        problem = Problem.load(parsed.config)
        output = parsed.output or default_output(problem.name)
        initial_code = parsed.initial_program.read_text(encoding="utf-8")
        # Identifies the run, and labels its containers; saved in run.json. A run being
        # continued keeps its own.
        saved = saved_run_info(output)
        run_id = saved.run_id if saved is not None else uuid.uuid4().hex
        sandbox = make_sandbox(problem, parsed.unsafe_local_sandbox, run_id)
        evaluator = Evaluator(
            parsed.evaluation_file,
            sandbox,
            problem.evaluation.stage_time_limit,
            problem.evaluation.thresholds,
            problem.output_feature_names,
        )
        ensemble = Ensemble.from_settings(problem.llm)
        sandbox.remove_leftovers()
        try:
            run(
                problem,
                initial_code,
                ensemble,
                evaluator,
                parsed.iterations,
                output,
                parsed.seed,
                run_id,
                parsed.verbose,
                parsed.config,
                ["scripts/run.py", *arguments],
                parsed.workers,
            )
        finally:
            # Whatever happened, no container of the run outlives it.
            sandbox.remove_leftovers()
    except (ProblemError, EvaluationFileError, RunError, SandboxError, MissingKeyError) as error:
        # A mistake in the user's files, or Docker failing: one clear message, no traceback.
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except StopNow as stop:
        # Every program evaluated so far is already saved; the containers are removed.
        print(f"\nStopped at once ({stop}). Everything finished is in {output}")
        print(f"To continue the run, run the same command with --output {output}")
        return 130
    except KeyboardInterrupt:
        # Ctrl+C before the iterations started.
        print("\nStopped by Ctrl+C before the run started.")
        return 130
    print(f"Done. The run folder is {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
