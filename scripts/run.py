"""Evolve a program: the command line of my-evolve.

Usage:
    python scripts/run.py INITIAL_PROGRAM EVALUATION_FILE --config PROBLEM_FILE
        --iterations N --output FOLDER [--seed S]

Example, from the repository root:
    python scripts/run.py examples/circle_packing/initial_program.py
        examples/circle_packing/evaluation.py --config examples/circle_packing/problem.yaml
        --iterations 20 --output runs/circle_packing_1
"""

import argparse
import sys
from pathlib import Path

from my_evolve.evaluator import EvaluationFileError, Evaluator
from my_evolve.llm import OpenAICompatibleLLM
from my_evolve.loop import RunError, run
from my_evolve.problem import Problem, ProblemError
from my_evolve.sandbox import LocalSandbox


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
    parsed = parser.parse_args(arguments)
    for path in (parsed.initial_program, parsed.evaluation_file, parsed.config):
        if not path.is_file():
            parser.error(f"no such file: {path}")
    return parsed


def main(arguments: list[str]) -> int:
    """Run my-evolve from the command line; return the exit code."""
    parsed = parse_arguments(arguments)
    try:
        problem = Problem.load(parsed.config)
        initial_code = parsed.initial_program.read_text(encoding="utf-8")
        evaluator = Evaluator(parsed.evaluation_file, LocalSandbox())
        llm = OpenAICompatibleLLM(problem.llm.model, problem.llm.api_base)
        run(problem, initial_code, llm, evaluator, parsed.iterations, parsed.output, parsed.seed)
    except (ProblemError, EvaluationFileError, RunError) as error:
        # A mistake in the user's files: one clear message, without a traceback.
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
