"""The Evaluator class: runs a program and scores it with the problem's evaluation file.

The evaluation file is Python code written for the problem. It defines a function

    def evaluate(namespace):
        ...
        return score

which receives the names the program defines (its functions and constants), calls
the program's functions, and returns the program's score: a number, higher is better.

For now the program runs inside this very process, with exec: it has no time limit
and no isolation, so it can read and write your files and use the network. Phase 1
of the implementation plan moves it into a sandbox.
"""

import math
import runpy
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from my_evolve.program import Result

# The function every evaluation file must define
EVALUATE_FUNCTION_NAME = "evaluate"

# What an evaluation file's evaluate looks like: the program's names in, a score out
EvaluateFunction = Callable[[dict[str, Any]], Any]


class EvaluationFileError(ValueError):
    """Raised when an evaluation file cannot be loaded; the message says why."""


def load_evaluation_file(path: Path) -> dict[str, Any]:
    """Run an evaluation file and return the names it defines.

    The file may import helper files that sit next to it. They are forgotten
    afterwards, so that two problems can each have a helper of the same name.
    """
    if not path.is_file():
        raise EvaluationFileError(f"no such evaluation file: {path}")
    folder = path.resolve().parent
    # Remember the modules imported so far, to spot the new ones afterwards.
    modules_before = set(sys.modules)
    sys.path.insert(0, str(folder))
    try:
        return runpy.run_path(str(path))
    finally:
        sys.path.remove(str(folder))
        # Forget the helpers the file imported from its own folder.
        for name in set(sys.modules) - modules_before:
            module_file = getattr(sys.modules[name], "__file__", None)
            if module_file and Path(module_file).resolve().is_relative_to(folder):
                del sys.modules[name]


def describe_error(error: BaseException) -> str:
    """Return what went wrong in one line, such as "ZeroDivisionError: division by zero"."""
    return f"{type(error).__name__}: {error}"


def checked_score(score: Any) -> float:
    """Return the score evaluate gave, if it is a finite number. Raises ValueError otherwise."""
    # A bool is a kind of int in Python, but True is not a score.
    if isinstance(score, bool) or not isinstance(score, int | float):
        raise ValueError(f"the score must be a number, got {type(score).__name__}")
    if not math.isfinite(score):
        raise ValueError(f"the score must be a finite number, got {score}")
    return float(score)


def run_program(code: str) -> dict[str, Any]:
    """Run a program's code and return the names it defines.

    Its __name__ is "program", so its `if __name__ == "__main__":` part does not run.
    """
    namespace: dict[str, Any] = {"__name__": "program"}
    exec(code, namespace)
    return namespace


class Evaluator:
    """Scores programs with one problem's evaluation file."""

    def __init__(self, evaluation_path: Path) -> None:
        """Load the evaluation file. Raises EvaluationFileError if it defines no evaluate."""
        names = load_evaluation_file(evaluation_path)
        function = names.get(EVALUATE_FUNCTION_NAME)
        if not callable(function):
            raise EvaluationFileError(
                f"{evaluation_path} must define a function called {EVALUATE_FUNCTION_NAME}"
            )
        # The evaluation file's evaluate function
        self.evaluate_function: EvaluateFunction = function

    def evaluate(self, code: str) -> Result:
        """Run the program's code and score it.

        Never raises because of the program: whatever goes wrong becomes a result
        without a score, whose error says what happened. Only Ctrl+C gets through.
        """
        try:
            namespace = run_program(code)
            return Result(score=checked_score(self.evaluate_function(namespace)))
        # SystemExit too: a program calling exit() must not end the run.
        except (Exception, SystemExit) as error:
            return Result(error=describe_error(error))
