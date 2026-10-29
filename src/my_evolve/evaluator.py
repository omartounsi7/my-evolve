"""The Evaluator class: runs a program and scores it with the problem's evaluation file.

The evaluation file is Python code written for the problem. It defines a function
(or several stages: evaluate_stage1, evaluate_stage2, ..., the cascade)

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
- timeout: the first stage ran over its time limit (StageTimeout), or a call over its own
  limit that the evaluation file did not catch (CallTimeout);
- error: not the program's fault: the sandbox failed, or the evaluation file raised.
"""

import math
import runpy
import sys
import time
import traceback
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from my_evolve.evaluation_api import (
    CallTimeout,
    InvalidProgram,
    ProgramFailure,
    StageResult,
    StageTimeout,
)
from my_evolve.program import Result, Status
from my_evolve.sandbox import ProgramNamespace, Sandbox, SandboxError

# The function an evaluation file with a single stage defines
EVALUATE_FUNCTION_NAME = "evaluate"
# The beginning of the names of the stage functions: evaluate_stage1, evaluate_stage2, ...
STAGE_FUNCTION_PREFIX = "evaluate_stage"

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


def join_feedback(*parts: str | None) -> str | None:
    """Return the non-empty pieces of feedback, one paragraph each; None if there is none."""
    kept = [part.strip() for part in parts if part and part.strip()]
    return "\n\n".join(kept) or None


def find_stages(names: Mapping[str, Any], path: Path) -> list[EvaluateFunction]:
    """Return an evaluation file's stage functions, in order.

    evaluate_stage1, evaluate_stage2, ... as long as they exist; otherwise evaluate alone,
    a single stage. Raises EvaluationFileError if there is neither.
    """
    stages: list[EvaluateFunction] = []
    while callable(names.get(f"{STAGE_FUNCTION_PREFIX}{len(stages) + 1}")):
        stages.append(names[f"{STAGE_FUNCTION_PREFIX}{len(stages) + 1}"])
    if not stages and callable(names.get(EVALUATE_FUNCTION_NAME)):
        stages.append(names[EVALUATE_FUNCTION_NAME])
    if not stages:
        raise EvaluationFileError(
            f"{path} must define a function called {EVALUATE_FUNCTION_NAME}, "
            f"or {STAGE_FUNCTION_PREFIX}1, {STAGE_FUNCTION_PREFIX}2, ..."
        )
    return stages


class Evaluator:
    """Scores programs with one problem's evaluation file, stage after stage (the cascade)."""

    def __init__(
        self,
        evaluation_path: Path,
        sandbox: Sandbox,
        stage_time_limit: float,
        thresholds: Sequence[float] = (),
    ) -> None:
        """Load the evaluation file and find its stages.

        sandbox runs the programs; each stage may last stage_time_limit seconds; stage
        k + 1 runs only if stage k's score reaches thresholds[k - 1]. Raises
        EvaluationFileError if the file has no stage, or if the thresholds are not one
        per stage after the first.
        """
        # The evaluation file's stage functions, in order
        self.stages: list[EvaluateFunction] = find_stages(
            load_evaluation_file(evaluation_path), evaluation_path
        )
        if len(thresholds) != len(self.stages) - 1:
            raise EvaluationFileError(
                f"{evaluation_path} has {len(self.stages)} stage(s), so the problem file needs "
                f"{len(self.stages) - 1} threshold(s), one per stage after the first; "
                f"it lists {len(thresholds)}"
            )
        # The score stage k must reach for stage k + 1 to run, at index k - 1
        self.thresholds: list[float] = list(thresholds)
        # Where the programs run
        self.sandbox: Sandbox = sandbox
        # How long one stage may last, in seconds, loading the program included
        self.stage_time_limit: float = stage_time_limit

    def evaluate(self, code: str) -> Result:
        """Run the program through the cascade, each stage in a fresh sandbox session.

        Never raises: whatever happens becomes a result whose status and error say
        what (see the top of this file). Only Ctrl+C gets through.
        """
        started = time.monotonic()
        result = self.run_cascade(code)
        return replace(result, duration=time.monotonic() - started)

    def run_cascade(self, code: str) -> Result:
        """Run the stages in order, and merge what they return (D9); no duration yet.

        - A later stage's score replaces the earlier one; its metrics are added to the
          earlier ones, replacing those with the same name; feedback is gathered.
        - The next stage runs only if this stage's score reaches its threshold.
        - An illegal answer at any stage makes the program invalid, and an error at any
          stage (not the program's fault) makes the result an error.
        - A later stage that fails or times out keeps the earlier stages' result: the
          program stays ok, with "stage k:" and the failure as its error.
        """
        merged: StageResult | None = None
        feedback: str | None = None
        stage_reached = 0
        for number, stage in enumerate(self.stages, start=1):
            outcome = self.run_stage(stage, code)
            if isinstance(outcome, Result):
                # The stage did not give a score.
                gathered = join_feedback(feedback, outcome.feedback)
                if merged is None or outcome.status in (Status.INVALID, Status.ERROR):
                    return replace(outcome, feedback=gathered, stage_reached=stage_reached)
                return Result(
                    Status.OK,
                    score=merged.score,
                    error=f"stage {number}: {outcome.error}",
                    metrics=merged.metrics,
                    feedback=gathered,
                    stage_reached=stage_reached,
                )
            metrics = {**merged.metrics, **outcome.metrics} if merged else outcome.metrics
            merged = StageResult(outcome.score, metrics)
            feedback = join_feedback(feedback, outcome.feedback)
            stage_reached = number
            if number < len(self.stages) and outcome.score < self.thresholds[number - 1]:
                break
        assert merged is not None
        return Result(
            Status.OK,
            score=merged.score,
            metrics=merged.metrics,
            feedback=feedback,
            stage_reached=stage_reached,
        )

    def run_stage(self, stage: EvaluateFunction, code: str) -> StageResult | Result:
        """Run one stage on the program in a fresh sandbox session, with its own time limit.

        Returns what the stage returned, checked, or the Result of a program that gave no
        score at this stage.
        """
        try:
            session = self.sandbox.start(code, self.stage_time_limit)
        except ProgramFailure as failure:
            return Result.failure(Status.FAILED, failure.describe())
        except StageTimeout as timeout:
            return Result.failure(Status.TIMEOUT, str(timeout))
        except SandboxError as error:
            return Result.failure(Status.ERROR, f"sandbox: {error}")
        outcome: StageResult | Result
        try:
            outcome = checked(stage(ProgramNamespace(session)))
        except InvalidProgram as invalid:
            outcome = Result.failure(Status.INVALID, invalid.reason, invalid.feedback or None)
        except ProgramFailure as failure:
            outcome = Result.failure(Status.FAILED, failure.describe())
        except (StageTimeout, CallTimeout) as timeout:
            outcome = Result.failure(Status.TIMEOUT, str(timeout))
        except SandboxError as error:
            outcome = Result.failure(Status.ERROR, f"sandbox: {error}")
        # The evaluation file raised, or returned something that cannot be saved.
        except Exception as error:
            outcome = Result.failure(
                Status.ERROR, f"evaluator: {describe_error(error)}\n\n{traceback.format_exc()}"
            )
        finally:
            session.close()
        # Out of time, whatever the evaluation file made of it (it may catch every exception).
        if session.timed_out:
            limit = f"{self.stage_time_limit:g}"
            return Result.failure(Status.TIMEOUT, f"the stage ran over its time limit of {limit} s")
        return outcome
