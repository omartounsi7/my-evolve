"""The loop: AlphaEvolve's controller, which evolves the problem's program.

Each iteration runs the six steps of the AlphaEvolve diagram:

    parent, examples = database.sample(example_count)
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
- best_program.py: the best program so far.
"""

import json
import random
import uuid
from pathlib import Path
from typing import Any

from my_evolve.checks import MarkerError, check_child, split_evolve_blocks
from my_evolve.database import Database
from my_evolve.evaluator import Evaluator
from my_evolve.llm import Ensemble, LLMError, NoModelLeft
from my_evolve.problem import Problem
from my_evolve.program import LLMUsage, Program, Result
from my_evolve.prompt import PromptBuilder
from my_evolve.reply_parser import parse_reply

# The files of the run folder
PROGRAMS_FILE = "programs.jsonl"
LLM_CALLS_FILE = "llm_calls.jsonl"
RUN_FILE = "run.json"
BEST_PROGRAM_FILE = "best_program.py"

# The longest error shown on the console, in characters (programs.jsonl keeps it whole)
MAX_CONSOLE_ERROR = 200


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


def run(
    problem: Problem,
    initial_code: str,
    ensemble: Ensemble,
    evaluator: Evaluator,
    iterations: int,
    output: Path,
    seed: int | None = None,
    run_id: str | None = None,
) -> Database:
    """Evolve the initial program for that many iterations, and return the database.

    Every program and every LLM call is saved in the output folder as soon as it
    exists. seed fixes the random draws (with the same LLM replies, a run repeats
    exactly); without one, a seed is drawn and printed. run_id identifies the run (its
    containers are labelled with it); without one, an id is made. Each iteration draws
    one model of the ensemble; an iteration whose LLM call fails is skipped, and the run
    stops when every model has been dropped. Every model is checked before the run.

    A child that fails a check (it does not compile, changes code outside the evolve
    blocks, lacks an entry function, or repeats an earlier program) is rejected, and
    costs no evaluation.

    Raises RunError if the output folder already holds a run, if a model does not
    answer its check, if the initial program fails the checks, or if it does not work:
    evolution needs a working start.
    """
    if (output / PROGRAMS_FILE).exists():
        raise RunError(f"{output} already holds a run; choose another output folder")
    if seed is None:
        seed = random.SystemRandom().randrange(2**32)
    if run_id is None:
        run_id = uuid.uuid4().hex
    try:
        split_evolve_blocks(initial_code)
    except MarkerError as error:
        raise RunError(f"the initial program's evolve blocks are broken: {error}") from None
    checks = check_child(initial_code, initial_code, problem.entry_functions, {})
    if checks.reason is not None:
        raise RunError(f"the initial program fails the checks: {checks.reason}")
    print(f"Seed: {seed}")

    try:
        ensemble.check_all()
    except LLMError as error:
        raise RunError(f"a model did not answer its check: {error}") from None
    # The run's random generator: every draw of the run comes from it (D39)
    rng = random.Random(seed)
    database = Database(rng, problem.parents)
    prompt_builder = PromptBuilder(problem)

    def store(program: Program) -> None:
        """Add the program to the database and the run folder."""
        database.add(program)
        append_program(output, program)
        if database.best_id == program.id:
            write_best_program(output, program)

    initial = Program(
        initial_code, evaluator.evaluate(initial_code), fingerprint=checks.fingerprint
    )
    if not initial.result.is_ok:
        raise RunError(
            f"the initial program does not work ({initial.result.status.value}): "
            f"{initial.result.error}"
        )
    output.mkdir(parents=True, exist_ok=True)
    write_run_info(output, run_id, seed, prompt_builder.system_message)
    store(initial)
    print(f"Initial program: {describe(initial)}")

    for iteration in range(1, iterations + 1):
        parent, examples = database.sample(problem.prompt.example_programs)
        try:
            llm = ensemble.draw(rng)
        except NoModelLeft as error:
            print(f"Stopping: {error}")
            break
        prompt = prompt_builder.build(parent, examples, database.best_score())
        call: dict[str, Any] = {"iteration": iteration, "user_message": prompt.user}
        try:
            reply = llm.complete(prompt)
        except LLMError as error:
            ensemble.record_failure(llm.name)
            call.update(program_id=None, model=llm.name, reply=None, error=str(error))
            append_line(output / LLM_CALLS_FILE, call)
            print(f"Iteration {iteration}/{iterations}, {llm.name}: skipped, no reply ({error})")
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
        usage = LLMUsage(reply.model, reply.input_tokens, reply.output_tokens, reply.duration)
        child = Program.new_child(
            parent,
            parsed.code,
            result,
            iteration,
            usage,
            parsed.description,
            checks.fingerprint,
        )
        store(child)
        call.update(program_id=child.id, reply=reply.text, error=None, **usage.to_dict())
        append_line(output / LLM_CALLS_FILE, call)
        print(
            f"Iteration {iteration}/{iterations}, {llm.name}: {describe(child)} "
            f"(best {best_score_text(database)})"
        )
    return database
