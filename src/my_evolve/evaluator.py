"""The Evaluator class: runs a program and scores it with the problem's evaluation file.

The evaluation file is Python code written for the problem. It defines a function

    def evaluate(namespace):
        ...
        return score

which receives the names the program defines (its functions and constants), calls
the program's functions, and returns the program's score: a number, higher is better.
When the program's answer breaks a rule of the problem, evaluate raises InvalidProgram
(from my_evolve.evaluation_api) with the reason.

The evaluation file runs here, on the host. The program runs in a worker process of
its own (the sandbox), and the namespace evaluate receives stands in front of it.
Whatever happens becomes a Result with a status:

- ok: evaluate returned a finite number, the score;
- invalid: evaluate raised InvalidProgram, the program's answer is illegal;
- failed: the program failed (it raised, or its process ended): ProgramFailure;
- error: not the program's fault: the sandbox failed, or the evaluation file raised.
"""

import math
import runpy
import sys
import traceback
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from my_evolve.evaluation_api import InvalidProgram, ProgramFailure
from my_evolve.program import Result, Status
from my_evolve.sandbox import ProgramNamespace, Sandbox, SandboxError

# The function every evaluation file must define
EVALUATE_FUNCTION_NAME = "evaluate"

# What an evaluation file's evaluate looks like: the program's names in, a score out
EvaluateFunction = Callable[[Mapping[str, Any]], Any]


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


class Evaluator:
    """Scores programs with one problem's evaluation file."""

    def __init__(self, evaluation_path: Path, sandbox: Sandbox) -> None:
        """Load the evaluation file. Raises EvaluationFileError if it defines no evaluate.

        sandbox runs the programs.
        """
        names = load_evaluation_file(evaluation_path)
        function = names.get(EVALUATE_FUNCTION_NAME)
        if not callable(function):
            raise EvaluationFileError(
                f"{evaluation_path} must define a function called {EVALUATE_FUNCTION_NAME}"
            )
        # The evaluation file's evaluate function
        self.evaluate_function: EvaluateFunction = function
        # Where the programs run
        self.sandbox: Sandbox = sandbox

    def evaluate(self, code: str) -> Result:
        """Load the program in a fresh sandbox session, and score it.

        Never raises: whatever happens becomes a result whose status and error say
        what (see the top of this file). Only Ctrl+C gets through.
        """
        try:
            session = self.sandbox.start(code)
        except ProgramFailure as failure:
            return Result.failure(Status.FAILED, failure.describe())
        except SandboxError as error:
            return Result.failure(Status.ERROR, f"sandbox: {error}")
        try:
            score = checked_score(self.evaluate_function(ProgramNamespace(session)))
        except InvalidProgram as invalid:
            return Result.failure(Status.INVALID, invalid.reason)
        except ProgramFailure as failure:
            return Result.failure(Status.FAILED, failure.describe())
        except SandboxError as error:
            return Result.failure(Status.ERROR, f"sandbox: {error}")
        # The evaluation file raised, or returned something that is not a score.
        except Exception as error:
            return Result.failure(
                Status.ERROR, f"evaluator: {describe_error(error)}\n\n{traceback.format_exc()}"
            )
        finally:
            session.close()
        return Result(Status.OK, score=score)
