"""The Evaluator class: runs the evaluation cascade on a program and returns its Result (D9, D65).

The evaluation file is trusted code, loaded on the host. Each of its stage
functions receives the program's namespace, whose functions run in a fresh
sandbox session for that stage (D8). Whatever happens, the program, its
evaluation file or the sandbox failing, evaluate() returns a Result with a
status (D7); it never raises because of a program.
"""

import math
import runpy
import sys
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from my_evolve.evaluation_api import (
    CallTimeout,
    InvalidProgram,
    ProgramFailure,
    StageResult,
    StageTimeout,
)
from my_evolve.problem import Problem
from my_evolve.program import JsonValue, Result, Status
from my_evolve.sandbox import ProgramNamespace, Sandbox, SandboxError

# A stage function of an evaluation file: evaluate_stage1(namespace), or evaluate(namespace).
StageFunction = Callable[[ProgramNamespace], Any]
# The evaluation file's optional drawing of a program's output (D51).
VisualizeFunction = Callable[[JsonValue, Path], None]

SINGLE_STAGE_NAME = "evaluate"
STAGE_NAME_PREFIX = "evaluate_stage"
VISUALIZE_NAME = "visualize"

# How many of the last lines of a failure's traceback and error output are kept.
TRACEBACK_LINES = 15
ERROR_OUTPUT_LINES = 20


class EvaluationFileError(ValueError):
    """An evaluation file that cannot be used; the message says why."""


class EvaluatorMistake(Exception):
    """A stage function returned something the framework cannot use (P5): the evaluation
    file's fault, not the program's, so the program gets the status error."""


def load_evaluation_file(evaluation_path: Path) -> dict[str, Any]:
    """Run the evaluation file on the host and return the names it defines.

    Helper files next to it can be imported; they are forgotten afterwards, so that
    two problems can each have a utils.py (v1's loader). Raises EvaluationFileError
    if the file is missing or raises while loading.
    """
    if not evaluation_path.is_file():
        raise EvaluationFileError(f"no such file: {evaluation_path}")
    evaluation_folder = evaluation_path.resolve().parent
    # Remember the modules imported so far, to spot the new ones afterwards.
    names_imported_before = set(sys.modules)
    # Let the evaluation file import helper files that sit next to it.
    sys.path.insert(0, str(evaluation_folder))
    try:
        return runpy.run_path(str(evaluation_path))
    except Exception as error:
        details = "".join(traceback.format_exception(error)[-TRACEBACK_LINES:])
        raise EvaluationFileError(
            f"{evaluation_path} raised an error while loading:\n{details}"
        ) from error
    finally:
        sys.path.remove(str(evaluation_folder))
        # Forget the helpers the file imported.
        for name in set(sys.modules) - names_imported_before:
            module_file = getattr(sys.modules[name], "__file__", None)
            if module_file and Path(module_file).resolve().is_relative_to(evaluation_folder):
                del sys.modules[name]


def find_stages(names: dict[str, Any], evaluation_path: Path) -> list[StageFunction]:
    """Return the stage functions of an evaluation file, in order (D9).

    evaluate_stage1, evaluate_stage2, ... as long as they exist; otherwise evaluate
    alone. Raises EvaluationFileError if there is neither.
    """
    stages: list[StageFunction] = []
    while f"{STAGE_NAME_PREFIX}{len(stages) + 1}" in names:
        name = f"{STAGE_NAME_PREFIX}{len(stages) + 1}"
        if not callable(names[name]):
            raise EvaluationFileError(f"{evaluation_path}: {name} is not a function")
        stages.append(names[name])
    if stages:
        return stages
    if callable(names.get(SINGLE_STAGE_NAME)):
        return [names[SINGLE_STAGE_NAME]]
    raise EvaluationFileError(
        f"{evaluation_path} must define evaluate(namespace), "
        "or evaluate_stage1(namespace), evaluate_stage2(namespace), ..."
    )


def is_finite_number(value: Any) -> bool:
    """Tell whether value is an int or a float, not a boolean, and finite."""
    return not isinstance(value, bool) and isinstance(value, int | float) and math.isfinite(value)


def plain_json_problem(value: Any, where: str) -> str | None:
    """Return what keeps value from being saved as JSON unchanged, or None if nothing does.

    Allowed: None, booleans, finite numbers, text, lists, dictionaries with text keys.
    Tuples are refused, since they would come back from the file as lists.
    """
    if value is None or isinstance(value, bool | str):
        return None
    if isinstance(value, int | float):
        return None if math.isfinite(value) else f"{where} is not a finite number ({value})"
    if isinstance(value, list):
        for index, item in enumerate(value):
            problem = plain_json_problem(item, f"{where}[{index}]")
            if problem is not None:
                return problem
        return None
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                return f"{where} has a key that is not text ({key!r})"
            problem = plain_json_problem(item, f"{where}[{key!r}]")
            if problem is not None:
                return problem
        return None
    hint = " (use a list)" if isinstance(value, tuple) else ""
    if type(value).__module__ == "numpy":
        hint = " (use .tolist())"
    return f"{where} is a {type(value).__name__}, not plain JSON data{hint}"


def describe_failure(failure: ProgramFailure | CallTimeout | StageTimeout) -> str:
    """Return a failure as text: what happened, then the end of the traceback and error output."""
    if not isinstance(failure, ProgramFailure):
        return str(failure)
    parts = [failure.message]
    if failure.traceback:
        lines = failure.traceback.strip().splitlines()[-TRACEBACK_LINES:]
        parts.append("\n".join(lines))
    if failure.error_output and failure.error_output.strip():
        lines = failure.error_output.strip().splitlines()[-ERROR_OUTPUT_LINES:]
        parts.append("Error output (end):\n" + "\n".join(lines))
    return "\n".join(parts)


def joined_feedback(feedbacks: list[str | None]) -> str | None:
    """Return the stages' feedback texts one after the other, or None if there is none."""
    texts = [feedback.strip() for feedback in feedbacks if feedback and feedback.strip()]
    return "\n".join(texts) if texts else None


class Evaluator:
    """Runs the evaluation cascade of one problem (D9, D65)."""

    def __init__(
        self,
        evaluation_path: Path,
        problem: Problem,
        sandbox: Sandbox,
        output_features: tuple[str, ...] = (),
    ) -> None:
        """Load the evaluation file and check that it fits the problem file.

        output_features are the grid's features the evaluator must provide at stage 1
        (D17). Raises EvaluationFileError if the file cannot be used, or if the problem
        file does not give exactly one threshold per stage after the first.
        """
        names = load_evaluation_file(evaluation_path)
        # The stage functions, in order.
        self.stages: list[StageFunction] = find_stages(names, evaluation_path)
        thresholds = problem.evaluation.thresholds
        if len(thresholds) != len(self.stages) - 1:
            raise EvaluationFileError(
                f"{evaluation_path} defines {len(self.stages)} stage(s), so the problem file "
                f"needs {len(self.stages) - 1} threshold(s) in evaluation.thresholds "
                f"(one per stage after the first), but it gives {len(thresholds)}"
            )
        # Stage k+1 runs only if stage k's score reaches thresholds[k-1].
        self.thresholds: tuple[float, ...] = thresholds
        # Seconds each stage may take (D41).
        self.stage_limit: float = problem.evaluation.stage_time_limit
        self.output_features: tuple[str, ...] = output_features
        self.sandbox: Sandbox = sandbox
        visualize = names.get(VISUALIZE_NAME)
        # The evaluation file's drawing of a program's output (D51), or None.
        self.visualize: VisualizeFunction | None = visualize if callable(visualize) else None

    def evaluate(self, code: str) -> Result:
        """Run the cascade on a program and return its Result; never raises because of it."""
        started = time.monotonic()
        merged: StageResult | None = None
        feedbacks: list[str | None] = []
        later_error: str | None = None
        stage_reached = 0

        def failure(status: Status, error: str, *extra_feedback: str | None) -> Result:
            return Result.failure(
                status,
                error,
                feedback=joined_feedback([*feedbacks, *extra_feedback]),
                duration=time.monotonic() - started,
                stage_reached=stage_reached,
            )

        for number, stage in enumerate(self.stages, start=1):
            try:
                outcome = self.checked(self.run_stage(stage, code), number)
            except InvalidProgram as invalid:
                # An illegal answer at any stage makes the whole program invalid (D9).
                return failure(Status.INVALID, invalid.reason, invalid.feedback)
            except (ProgramFailure, CallTimeout, StageTimeout) as program_error:
                status = (
                    Status.FAILED if isinstance(program_error, ProgramFailure) else Status.TIMEOUT
                )
                if number == 1:
                    return failure(status, describe_failure(program_error))
                # A later stage that fails keeps the earlier stages' result (D9).
                later_error = f"stage {number}: {describe_failure(program_error)}"
                break
            except SandboxError as sandbox_error:
                return failure(Status.ERROR, f"sandbox: {sandbox_error}")
            except EvaluatorMistake as mistake:
                return failure(Status.ERROR, f"evaluator: {mistake}")
            except Exception as evaluator_error:
                # The evaluation file raised, or returned something unusable: not the
                # program's fault.
                details = "".join(traceback.format_exception(evaluator_error)[-TRACEBACK_LINES:])
                return failure(Status.ERROR, f"evaluator: {details.strip()}")

            merged = self.merge(merged, outcome, number)
            feedbacks.append(outcome.feedback)
            stage_reached = number
            if number < len(self.stages) and outcome.score < self.thresholds[number - 1]:
                break

        assert merged is not None
        return Result(
            status=Status.OK,
            score=merged.score,
            metrics=merged.metrics,
            features=merged.features,
            feedback=joined_feedback(feedbacks),
            error=later_error,
            output_data=merged.output_data,
            stage_reached=stage_reached,
            duration=time.monotonic() - started,
        )

    def run_stage(self, stage: StageFunction, code: str) -> Any:
        """Run one stage function on a freshly loaded program, and always close its session.

        Loading the program may raise ProgramFailure or StageTimeout, as calls do.
        """
        session = self.sandbox.start(code, self.stage_limit)
        try:
            return stage(ProgramNamespace(session))
        finally:
            session.close()

    def checked(self, outcome: Any, number: int) -> StageResult:
        """Return what a stage function returned, if the framework can use it.

        Raises EvaluatorMistake otherwise: not a StageResult, a score that is a boolean
        or not a finite number, metrics or features that are not finite numbers, an
        output feature missing at stage 1, feedback that is not text, or output data
        that cannot be saved as JSON (P5).
        """
        stage = f"stage {number}"
        if not isinstance(outcome, StageResult):
            raise EvaluatorMistake(
                f"{stage} returned a {type(outcome).__name__}, not a StageResult"
            )
        if not is_finite_number(outcome.score):
            raise EvaluatorMistake(
                f"{stage}: the score must be a finite number, got {outcome.score!r}"
            )
        for field_name in ("metrics", "features"):
            values = getattr(outcome, field_name)
            if not isinstance(values, dict):
                raise EvaluatorMistake(f"{stage}: {field_name} must be a dictionary")
            for name, value in values.items():
                if not isinstance(name, str) or not is_finite_number(value):
                    raise EvaluatorMistake(
                        f"{stage}: {field_name}[{name!r}] must be a finite number, got {value!r}"
                    )
        if number == 1:
            for name in self.output_features:
                if name not in outcome.features:
                    raise EvaluatorMistake(f"stage 1 did not give the output feature {name!r}")
        if outcome.feedback is not None and not isinstance(outcome.feedback, str):
            raise EvaluatorMistake(f"{stage}: feedback must be text or None")
        problem = plain_json_problem(outcome.output_data, "output_data")
        if problem is not None:
            raise EvaluatorMistake(f"{stage}: {problem}")
        return outcome

    @staticmethod
    def merge(previous: StageResult | None, outcome: StageResult, number: int) -> StageResult:
        """Return the result so far after one more stage (D9).

        The new score replaces the earlier one; the new metrics are added to the
        earlier ones, replacing those with the same name; features stay stage 1's; the
        new output data replaces the earlier one if the stage gave any. Feedback is
        gathered separately.
        """
        if previous is None or number == 1:
            return StageResult(
                score=float(outcome.score),
                metrics={name: float(value) for name, value in outcome.metrics.items()},
                features={name: float(value) for name, value in outcome.features.items()},
                output_data=outcome.output_data,
            )
        return StageResult(
            score=float(outcome.score),
            metrics={
                **previous.metrics,
                **{name: float(value) for name, value in outcome.metrics.items()},
            },
            features=previous.features,
            output_data=(
                outcome.output_data if outcome.output_data is not None else previous.output_data
            ),
        )
