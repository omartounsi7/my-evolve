"""The Evaluator class: runs a program and scores it with the problem's evaluation file.

The evaluation file is Python code written for the problem. It defines a function

    from my_evolve.evaluation_api import InvalidProgram, StageResult

    def evaluate(namespace):
        ...
        return StageResult(score=score, metrics={"sum_radii": total}, feedback="...")

which receives the names the program defines (its functions and constants), calls
the program's functions, and returns the program's score (a finite number, higher is
better), with named metrics and feedback for the LLM. When the program's answer breaks
a rule of the problem, evaluate raises InvalidProgram with the reason.

The evaluation file runs here, on the host. The program runs in a worker process of
its own (the sandbox), and the namespace evaluate receives stands in front of it.
Whatever happens becomes a Result with a status:

- ok: evaluate returned a StageResult, with a finite score;
- invalid: evaluate raised InvalidProgram, the program's answer is illegal;
- failed: the program failed (it raised, or its process ended): ProgramFailure;
- timeout: the evaluation ran over its time limit: StageTimeout;
- error: not the program's fault: the sandbox failed, or the evaluation file raised.
"""

import math
import runpy
import sys
import time
import traceback
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from my_evolve.evaluation_api import InvalidProgram, ProgramFailure, StageResult, StageTimeout
from my_evolve.program import Result, Status
from my_evolve.sandbox import ProgramNamespace, Sandbox, SandboxError

# The function every evaluation file must define
EVALUATE_FUNCTION_NAME = "evaluate"

# What an evaluation file's evaluate looks like: the program's names in, a StageResult out
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


def checked_number(value: Any, what: str) -> float:
    """Return value if it is a finite number. Raises ValueError, naming what it is, otherwise."""
    # A bool is a kind of int in Python, but True is not a number here.
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{what} must be a number, got {type(value).__name__}")
    if not math.isfinite(value):
        raise ValueError(f"{what} must be a finite number, got {value}")
    return float(value)


def checked(outcome: Any) -> StageResult:
    """Return what evaluate returned, if it is a StageResult that can be saved as it is.

    Raises ValueError otherwise: a mistake of the evaluation file, not of the program.
    """
    if not isinstance(outcome, StageResult):
        raise ValueError(f"evaluate must return a StageResult, got {type(outcome).__name__}")
    if not isinstance(outcome.metrics, dict) or not all(
        isinstance(name, str) for name in outcome.metrics
    ):
        raise ValueError("the metrics must be a dictionary with text keys")
    if not isinstance(outcome.feedback, str):
        raise ValueError(f"the feedback must be text, got {type(outcome.feedback).__name__}")
    metrics = {
        name: checked_number(value, f"the metric {name!r}")
        for name, value in outcome.metrics.items()
    }
    return StageResult(checked_number(outcome.score, "the score"), metrics, outcome.feedback)


class Evaluator:
    """Scores programs with one problem's evaluation file."""

    def __init__(self, evaluation_path: Path, sandbox: Sandbox, stage_time_limit: float) -> None:
        """Load the evaluation file. Raises EvaluationFileError if it defines no evaluate.

        sandbox runs the programs; an evaluation may last stage_time_limit seconds.
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
        # How long an evaluation may last, in seconds, loading the program included
        self.stage_time_limit: float = stage_time_limit

    def evaluate(self, code: str) -> Result:
        """Load the program in a fresh sandbox session, and score it.

        Never raises: whatever happens becomes a result whose status and error say
        what (see the top of this file). Only Ctrl+C gets through.
        """
        started = time.monotonic()
        result = self.run_stage(code)
        return replace(result, duration=time.monotonic() - started)

    def run_stage(self, code: str) -> Result:
        """Run the evaluation file on the program, in a fresh sandbox session, and return the
        result without its duration."""
        try:
            session = self.sandbox.start(code, self.stage_time_limit)
        except ProgramFailure as failure:
            return Result.failure(Status.FAILED, failure.describe())
        except StageTimeout as timeout:
            return Result.failure(Status.TIMEOUT, str(timeout))
        except SandboxError as error:
            return Result.failure(Status.ERROR, f"sandbox: {error}")
        try:
            outcome = checked(self.evaluate_function(ProgramNamespace(session)))
        except InvalidProgram as invalid:
            result = Result.failure(Status.INVALID, invalid.reason, invalid.feedback or None)
        except ProgramFailure as failure:
            result = Result.failure(Status.FAILED, failure.describe())
        except StageTimeout as timeout:
            result = Result.failure(Status.TIMEOUT, str(timeout))
        except SandboxError as error:
            result = Result.failure(Status.ERROR, f"sandbox: {error}")
        # The evaluation file raised, or returned something that cannot be saved.
        except Exception as error:
            result = Result.failure(
                Status.ERROR, f"evaluator: {describe_error(error)}\n\n{traceback.format_exc()}"
            )
        else:
            result = Result(
                Status.OK,
                score=outcome.score,
                metrics=outcome.metrics,
                feedback=outcome.feedback or None,
            )
        finally:
            session.close()
        # Out of time, whatever the evaluation file made of it (it may catch every exception).
        if session.timed_out:
            limit = f"{self.stage_time_limit:g}"
            return Result.failure(
                Status.TIMEOUT, f"the evaluation ran over its time limit of {limit} s"
            )
        return result
