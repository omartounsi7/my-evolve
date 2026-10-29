"""Evolve a program: the command line of my-evolve.

Usage:
    python scripts/run.py INITIAL_PROGRAM EVALUATION_FILE --config PROBLEM_FILE
        --iterations N --output FOLDER [--seed S] [--unsafe-local-sandbox]

Programs run in Docker containers, so Docker must be installed and running.

Example, from the repository root:
    python scripts/run.py examples/circle_packing/initial_program.py
        examples/circle_packing/evaluation.py --config examples/circle_packing/problem.yaml
        --iterations 20 --output runs/circle_packing_1
"""

import argparse
import sys
import uuid
from pathlib import Path

from my_evolve.evaluator import EvaluationFileError, Evaluator
from my_evolve.llm import OpenAICompatibleLLM
from my_evolve.loop import RunError, run
from my_evolve.problem import Problem, ProblemError
from my_evolve.sandbox import DockerSandbox, LocalSandbox, Sandbox, SandboxError, ensure_image

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
        "--iterations", type=positive_integer, required=True, help="how many children to ask for"
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="the run folder, where programs are saved"
    )
    parser.add_argument("--seed", type=int, help="fixes the random draws (default: drawn)")
    parser.add_argument(
        "--unsafe-local-sandbox",
        action="store_true",
        help="run programs as plain processes, without Docker or any isolation (tests only)",
    )
    parsed = parser.parse_args(arguments)
    for path in (parsed.initial_program, parsed.evaluation_file, parsed.config):
        if not path.is_file():
            parser.error(f"no such file: {path}")
    return parsed


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
    parsed = parse_arguments(arguments)
    try:
        problem = Problem.load(parsed.config)
        initial_code = parsed.initial_program.read_text(encoding="utf-8")
        # Identifies the run, and labels its containers; saved in run.json.
        run_id = uuid.uuid4().hex
        sandbox = make_sandbox(problem, parsed.unsafe_local_sandbox, run_id)
        evaluator = Evaluator(
            parsed.evaluation_file,
            sandbox,
            problem.evaluation.stage_time_limit,
            problem.evaluation.thresholds,
        )
        llm = OpenAICompatibleLLM(problem.llm.model, problem.llm.api_base)
        sandbox.remove_leftovers()
        try:
            run(
                problem,
                initial_code,
                llm,
                evaluator,
                parsed.iterations,
                parsed.output,
                parsed.seed,
                run_id,
            )
        finally:
            # Whatever happened, no container of the run outlives it.
            sandbox.remove_leftovers()
    except (ProblemError, EvaluationFileError, RunError, SandboxError) as error:
        # A mistake in the user's files, or Docker failing: one clear message, no traceback.
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        # Every program evaluated so far is already saved.
        print(f"\nStopped by Ctrl+C. The programs so far are in {parsed.output}")
        return 130
    print(f"Done. The programs are in {parsed.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
