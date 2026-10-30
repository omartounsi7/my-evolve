"""The loop: AlphaEvolve's controller, which evolves the problem's program.

Each iteration runs the six steps of the AlphaEvolve diagram:

    island = database.sample_island()
    parent, examples = database.sample(island, example_count)
    prompt = prompt_builder.build(parent, examples, best_score)
    reply = ensemble.draw(rng).complete(prompt)
    parsed = parse_reply(reply)          # the program and its description
    result = evaluator.evaluate(parsed.code)
    database.add(Program.new_child(parent, parsed.code, result, iteration))

For now iterations run one after another, and the run folder holds:
- programs.jsonl: one line per program, appended as it is stored;
- llm_calls.jsonl: one line per LLM call, failed ones included: the user message, the
  reply, the tokens and the duration;
- run.json: the run's id, its seed and the system message, written once;
- best_program.py: the best program so far;
- log.txt: everything logged, with the time (logs.py).
The run ends with a summary: iterations done and why the run stopped, the best score,
the children by status, and the tokens and cost of each model (D51).
"""

import json
import logging
import random
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from my_evolve.checks import MarkerError, check_child, split_evolve_blocks
from my_evolve.database import Database
from my_evolve.evaluator import Evaluator
from my_evolve.llm import Ensemble, LLMError, NoModelLeft
from my_evolve.logs import setup_logging, stop_logging
from my_evolve.problem import ModelSettings, Problem
from my_evolve.program import LLMUsage, Origin, Program, Result
from my_evolve.prompt import PromptBuilder
from my_evolve.reply_parser import parse_reply

# The files of the run folder
PROGRAMS_FILE = "programs.jsonl"
LLM_CALLS_FILE = "llm_calls.jsonl"
RUN_FILE = "run.json"
BEST_PROGRAM_FILE = "best_program.py"

# The longest error shown on the console, in characters (programs.jsonl keeps it whole)
MAX_CONSOLE_ERROR = 200

logger = logging.getLogger(__name__)


class RunError(Exception):
    """Raised when a run cannot start; the message says why."""


def append_line(path: Path, record: dict[str, Any]) -> None:
    """Add one record to a JSON-lines file."""
    # allow_nan=False: scores are finite numbers or null, so the file is plain JSON.
    line = json.dumps(record, allow_nan=False)
    with path.open("a", encoding="utf-8") as file:
        file.write(line + "\n")


def append_program(folder: Path, program: Program) -> None:
    """Add the program to programs.jsonl, as one line of JSON."""
    append_line(folder / PROGRAMS_FILE, program.to_dict())


def write_run_info(folder: Path, run_id: str, seed: int, system_message: str) -> None:
    """Write run.json: what identifies the run, and the system message of every prompt."""
    info = {"run_id": run_id, "seed": seed, "system_message": system_message}
    (folder / RUN_FILE).write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")


def write_best_program(folder: Path, program: Program) -> None:
    """Rewrite best_program.py: the program's code, under a comment saying what it is."""
    header = (
        f"# Best program of the run: score {program.result.score}, "
        f"iteration {program.iteration}, id {program.id}\n\n"
    )
    (folder / BEST_PROGRAM_FILE).write_text(header + program.code, encoding="utf-8")


def describe(program: Program) -> str:
    """Return the program's score, or its status and error in one short line, for the console."""
    if program.result.score is not None:
        return f"score {program.result.score:.6f}"
    lines = (program.result.error or "").splitlines()
    error = lines[0] if lines else "no error message"
    if len(error) > MAX_CONSOLE_ERROR:
        error = error[:MAX_CONSOLE_ERROR] + "…"
    return f"{program.result.status.value}: {error}"


def best_score_text(database: Database) -> str:
    """Return the best score so far, for the console."""
    best_score = database.best_score()
    return f"{best_score:.6f}" if best_score is not None else "none"


def model_cost(model: ModelSettings | None, input_tokens: int, output_tokens: int) -> str:
    """Return what a model's tokens cost, as text; empty when its prices are not given."""
    if model is None or model.price_input is None or model.price_output is None:
        return ""
    dollars = (input_tokens * model.price_input + output_tokens * model.price_output) / 1e6
    return f", ${dollars:.4f}"


def summary(problem: Problem, database: Database, completed: int, reason: str) -> list[str]:
    """Return the lines of the end-of-run summary (D51).

    The iterations done and why the run stopped, the best score and the iteration that
    found it, the LLM's children by status, and the tokens (and cost, when prices are
    given) of each model.
    """
    lines = [f"Run finished: {completed} iterations done, {reason}."]
    best = database.best()
    if best is not None:
        lines.append(
            f"Best score: {best_score_text(database)}, found at iteration {best.iteration}."
        )
    children = [program for program in database.programs.values() if program.origin is Origin.LLM]
    statuses = Counter(child.result.status.value for child in children)
    counts = ", ".join(f"{count} {status}" for status, count in sorted(statuses.items()))
    lines.append(f"Children: {len(children)} ({counts or 'none'}).")
    models = {model.name: model for model in problem.llm.models}
    usage: dict[str, list[int]] = {}
    for child in children:
        if child.llm is not None:
            totals = usage.setdefault(child.llm.model, [0, 0, 0])
            totals[0] += 1
            totals[1] += child.llm.input_tokens
            totals[2] += child.llm.output_tokens
    for name, (calls, input_tokens, output_tokens) in usage.items():
        cost = model_cost(models.get(name), input_tokens, output_tokens)
        lines.append(
            f"{name}: {calls} replies, {input_tokens:,} input and {output_tokens:,} output "
            f"tokens{cost}."
        )
    return lines


def run(
    problem: Problem,
    initial_code: str,
    ensemble: Ensemble,
    evaluator: Evaluator,
    iterations: int,
    output: Path,
    seed: int | None = None,
    run_id: str | None = None,
    verbose: bool = False,
) -> Database:
    """Evolve the initial program for that many iterations, and return the database.

    Every program and every LLM call is saved in the output folder as soon as it
    exists. seed fixes the random draws (with the same LLM replies, a run repeats
    exactly); without one, a seed is drawn and printed. run_id identifies the run (its
    containers are labelled with it); without one, an id is made. Each iteration draws
    one model of the ensemble; an iteration whose LLM call fails is skipped, and the run
    stops when every model has been dropped. Every model is checked before the run.
    Messages go to the console (details too with verbose) and to log.txt in the output
    folder.

    A child that fails a check (it does not compile, changes code outside the evolve
    blocks, lacks an entry function, or repeats an earlier program) is rejected, and
    costs no evaluation.

    Raises RunError if the output folder already holds a run, if a model does not
    answer its check, if the initial program fails the checks, or if it does not work:
    evolution needs a working start.
    """
    if (output / PROGRAMS_FILE).exists():
        raise RunError(f"{output} already holds a run; choose another output folder")
    setup_logging(output, verbose)
    try:
        return evolve(problem, initial_code, ensemble, evaluator, iterations, output, seed, run_id)
    finally:
        stop_logging()


def evolve(
    problem: Problem,
    initial_code: str,
    ensemble: Ensemble,
    evaluator: Evaluator,
    iterations: int,
    output: Path,
    seed: int | None,
    run_id: str | None,
) -> Database:
    """Run the loop, once logging is set up (see run)."""
    if seed is None:
        seed = random.SystemRandom().randrange(2**32)
    if run_id is None:
        run_id = uuid.uuid4().hex
    try:
        split_evolve_blocks(initial_code)
    except MarkerError as error:
        raise RunError(f"the initial program's evolve blocks are broken: {error}") from None
    initial_checks = check_child(initial_code, initial_code, problem.entry_functions, {})
    if initial_checks.reason is not None:
        raise RunError(f"the initial program fails the checks: {initial_checks.reason}")
    logger.info("Seed: %d", seed)

    try:
        ensemble.check_all()
    except LLMError as error:
        raise RunError(f"a model did not answer its check: {error}") from None
    # The run's random generator: every draw of the run comes from it (D39)
    rng = random.Random(seed)
    database = Database(
        rng,
        problem.parents,
        problem.islands,
        problem.grid_features,
        reference_nodes=initial_checks.code_complexity or 1,
    )
    prompt_builder = PromptBuilder(problem)

    def store(program: Program) -> None:
        """Add the program to the database and the run folder."""
        database.add(program)
        append_program(output, program)
        if database.best_id == program.id:
            write_best_program(output, program)

    def after_completion(completed: int) -> None:
        """Migrate between islands when due: every migration_interval completed iterations,
        skipped ones included (D23)."""
        if completed % problem.islands.migration_interval != 0:
            return
        arrivals = database.migrate(completed)
        for arrival in arrivals:
            store(arrival)
        if arrivals:
            verb = "moved" if problem.islands.mode == "move" else "copied"
            logger.info(
                "Migration after iteration %d: %d programs %s", completed, len(arrivals), verb
            )

    initial = Program(
        initial_code,
        evaluator.evaluate(initial_code),
        fingerprint=initial_checks.fingerprint,
        code_complexity=initial_checks.code_complexity,
    )
    if not initial.result.is_ok:
        raise RunError(
            f"the initial program does not work ({initial.result.status.value}): "
            f"{initial.result.error}"
        )
    output.mkdir(parents=True, exist_ok=True)
    write_run_info(output, run_id, seed, prompt_builder.system_message)
    store(initial)
    for copy in database.seed_islands(initial):
        store(copy)
    logger.info(
        "Initial program: %s, copied to %d islands", describe(initial), len(database.islands)
    )

    completed = 0
    reason = "every iteration done"
    for iteration in range(1, iterations + 1):
        island = database.sample_island()
        parent, examples = database.sample(island, problem.prompt.example_programs)
        try:
            llm = ensemble.draw(rng)
        except NoModelLeft as error:
            logger.info("Stopping: %s", error)
            reason = "no LLM model left"
            break
        logger.debug(
            "Iteration %d: island %d, parent %s (%s), examples %s, model %s",
            iteration,
            island,
            parent.id,
            describe(parent),
            [example.id for example in examples],
            llm.name,
        )
        prompt = prompt_builder.build(parent, examples, database.best_score())
        call: dict[str, Any] = {"iteration": iteration, "user_message": prompt.user}
        try:
            reply = llm.complete(prompt)
        except LLMError as error:
            ensemble.record_failure(llm.name)
            call.update(program_id=None, model=llm.name, reply=None, error=str(error))
            append_line(output / LLM_CALLS_FILE, call)
            logger.info(
                "Iteration %d/%d, island %d, %s: skipped, no reply (%s)",
                iteration,
                iterations,
                island,
                llm.name,
                error,
            )
            completed = iteration
            after_completion(iteration)
            continue
        ensemble.record_success(llm.name)
        parsed = parse_reply(reply.text, parent.code)
        checks = check_child(
            parsed.code, initial_code, problem.entry_functions, database.fingerprints
        )
        if checks.reason is not None:
            result = Result.rejected(checks.reason)
        else:
            result = evaluator.evaluate(parsed.code)
            logger.debug(
                "Iteration %d: LLM %.1f s, evaluation %.1f s (stage %d reached)",
                iteration,
                reply.duration,
                result.duration,
                result.stage_reached,
            )
        usage = LLMUsage(reply.model, reply.input_tokens, reply.output_tokens, reply.duration)
        child = Program.new_child(
            parent,
            parsed.code,
            result,
            iteration,
            island=island,
            llm=usage,
            description=parsed.description,
            fingerprint=checks.fingerprint,
            example_ids=prompt.example_ids,
            code_complexity=checks.code_complexity,
        )
        store(child)
        call.update(program_id=child.id, reply=reply.text, error=None, **usage.to_dict())
        append_line(output / LLM_CALLS_FILE, call)
        logger.info(
            "Iteration %d/%d, island %d, %s: %s (best %s)",
            iteration,
            iterations,
            island,
            llm.name,
            describe(child),
            best_score_text(database),
        )
        completed = iteration
        after_completion(iteration)
    for line in summary(problem, database, completed, reason):
        logger.info(line)
    return database
