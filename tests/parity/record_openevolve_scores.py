"""Record the scores OpenEvolve's own evaluators give the parity programs (step 9 of the plan).

Usage: python tests/parity/record_openevolve_scores.py [OPENEVOLVE_CHECKOUT]

The checkout defaults to the openevolve folder next to this repository. The scores
are written to tests/parity/openevolve_scores.json, which test_examples.py compares
my-evolve's scores with; the tests themselves never need OpenEvolve. Run it again
only if the programs or OpenEvolve's evaluators change.

Each program goes through OpenEvolve's cascade as OpenEvolve runs it: stage 1, then,
if its combined_score reaches the threshold, stage 2, whose metrics replace stage 1's.
The recorded score is the final combined_score: what OpenEvolve would select on.

Numeric libraries get one thread, as in my-evolve's sandbox (D41): some programs,
OpenEvolve's best circle packing among them, give another answer with more threads.
The best program is therefore recorded with 1 thread and with 8.
"""

import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PROGRAMS = HERE / "programs"
REPOSITORY = HERE.parent.parent
OUTPUT = HERE / "openevolve_scores.json"
THREAD_VARIABLES = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")

# The programs each problem is checked on, besides the initial program.
PROBLEMS: dict[str, dict[str, Any]] = {
    "circle_packing": {"evaluator": "examples/circle_packing/evaluator.py", "threshold": 0.5},
    "function_minimization": {
        "evaluator": "examples/function_minimization/evaluator.py",
        "threshold": 1.3,
    },
}


def set_threads(count: int) -> None:
    """Set how many threads numeric libraries use, here and in subprocesses."""
    for variable in THREAD_VARIABLES:
        os.environ[variable] = str(count)


def load_evaluator(openevolve: Path, relative_path: str) -> Any:
    """Load one of OpenEvolve's evaluator files as a module.

    The function-minimization evaluator imports openevolve.evaluation_result; that one
    file is loaded on its own, so that OpenEvolve's other dependencies are not needed.
    """
    package = types.ModuleType("openevolve")
    package.__path__ = [str(openevolve / "openevolve")]
    sys.modules.setdefault("openevolve", package)
    result_spec = importlib.util.spec_from_file_location(
        "openevolve.evaluation_result", openevolve / "openevolve" / "evaluation_result.py"
    )
    assert result_spec is not None and result_spec.loader is not None
    result_module = importlib.util.module_from_spec(result_spec)
    sys.modules["openevolve.evaluation_result"] = result_module
    result_spec.loader.exec_module(result_module)

    spec = importlib.util.spec_from_file_location("evaluator", openevolve / relative_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def metrics_of(outcome: Any) -> dict[str, Any]:
    """Return the metrics of a dict or an EvaluationResult."""
    return dict(outcome) if isinstance(outcome, dict) else dict(outcome.metrics)


def fitness(metrics: dict[str, Any]) -> float:
    """Return what OpenEvolve selects on: combined_score, or the average of the numbers."""
    score = metrics.get("combined_score")
    if isinstance(score, int | float) and not isinstance(score, bool):
        return float(score)
    numbers = [
        float(value)
        for name, value in metrics.items()
        if name != "error" and isinstance(value, int | float) and not isinstance(value, bool)
    ]
    return sum(numbers) / len(numbers) if numbers else 0.0


def cascade_score(evaluator: Any, program: Path, threshold: float) -> float:
    """Return the score OpenEvolve's cascade gives a program."""
    metrics = metrics_of(evaluator.evaluate_stage1(str(program)))
    if fitness(metrics) < threshold:
        return fitness(metrics)
    merged = {
        name: value
        for name, value in metrics.items()
        if name != "error" and not isinstance(value, str)
    }
    merged.update(
        {
            name: value
            for name, value in metrics_of(evaluator.evaluate_stage2(str(program))).items()
            if name != "error" and not isinstance(value, str)
        }
    )
    return fitness(merged)


def main(arguments: list[str]) -> None:
    openevolve = Path(arguments[0]) if arguments else REPOSITORY.parent / "openevolve"
    commit = subprocess.run(
        ["git", "-C", str(openevolve), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    recorded: dict[str, Any] = {"openevolve_commit": commit}

    for problem, settings in PROBLEMS.items():
        evaluator = load_evaluator(openevolve, str(settings["evaluator"]))
        threshold = float(settings["threshold"])
        programs = {"initial_program": REPOSITORY / "examples" / problem / "initial_program.py"}
        programs.update({path.stem: path for path in sorted((PROGRAMS / problem).glob("*.py"))})
        scores: dict[str, float] = {}
        for name, path in programs.items():
            # The function-minimization initial program searches at random: not comparable.
            if problem == "function_minimization" and name == "initial_program":
                continue
            thread_counts = (1, 8) if name == "best_program" else (1,)
            for threads in thread_counts:
                set_threads(threads)
                key = name if len(thread_counts) == 1 else f"{name}_{threads}_threads"
                scores[key] = cascade_score(evaluator, path, threshold)
                print(f"{problem} / {key}: {scores[key]!r}", file=sys.__stderr__, flush=True)
        recorded[problem] = scores

    OUTPUT.write_text(json.dumps(recorded, indent=2) + "\n", encoding="utf-8")
    print(f"Written: {OUTPUT}", file=sys.__stderr__)


if __name__ == "__main__":
    main(sys.argv[1:])
