"""The loop: run(settings) evolves a problem's program from start to finish (D36 to D39, D70).

The main thread does all the bookkeeping (drawing, checks, the database, the run
folder); a small pool of daemon worker threads does the waiting (LLM calls and
evaluations). Each iteration alternates between them (D36):

1. main: draw an island, a parent and a model; build the prompt;
2. worker: ask the model; extract the description and the code from its reply;
3. main: run the checks before evaluation (D13);
4. worker: evaluate the child through the cascade;
5. main: store the child; update the best program, the history, the snapshots.
"""

import dataclasses
import hashlib
import logging
import queue
import random
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from my_evolve.checks import CheckResult, check_child, split_evolve_blocks
from my_evolve.database import Database, Island
from my_evolve.evaluator import Evaluator
from my_evolve.llm import LLM, Ensemble, LLMError, LLMReply, NoModelLeft
from my_evolve.logs import setup_logging, stop_logging
from my_evolve.problem import Problem
from my_evolve.program import LLMUsage, Origin, Program, Result, Status
from my_evolve.prompt import Prompt, PromptBuilder, format_score
from my_evolve.reply_parser import ParsedReply, parse_reply
from my_evolve.sandbox import DockerSandbox, LocalSandbox, Sandbox, docker_image_tag
from my_evolve.storage import HistoryRow, LLMCallRecord, RunInfo, SessionRecord, Storage

logger = logging.getLogger(__name__)

# How often the main thread wakes up while waiting for workers, in seconds: on
# Windows, Ctrl+C only reaches a thread that is awake (D53).
WAKE_UP_SECONDS = 0.2

# The longest part of an error shown in an iteration's console line.
CONSOLE_ERROR_CHARS = 100

# Why a run stopped, after a first Ctrl+C, and after a second one or a SIGTERM.
USER_STOP = "stopped by the user (Ctrl+C)"
INTERRUPTED = "interrupted"

# The fingerprints of run.json, and what they stand for in messages (D50).
FINGERPRINTS = {
    "initial_program": "the initial program",
    "evaluation_file": "the evaluation file",
    "problem": "the problem file (its settings other than the llm section)",
    "image": "the sandbox's image (or the choice of the local sandbox)",
}

# History statuses of iterations without a child (D47).
SKIPPED = "skipped"
ERROR = "error"


class RunError(Exception):
    """A run that cannot start or go on, such as an initial program that does not work."""


class RunInterrupted(Exception):
    """The run was stopped at once, by a second Ctrl+C or a SIGTERM (D54)."""


@dataclass
class RunSettings:
    """The choices about one run, given on the command line (D45, D70)."""

    initial_program: Path
    evaluation_file: Path
    problem_file: Path
    # The run folder.
    output: Path
    # Completed iterations in all (D49).
    iterations: int = 100
    # Iterations in flight at once (D36).
    workers: int = 1
    # The seed of the run's random generator; None draws one (D39).
    seed: int | None = None
    # Run programs without any isolation (D40).
    unsafe_local_sandbox: bool = False
    # Show the details on the console (D52).
    verbose: bool = False


@dataclass(frozen=True)
class TaskResult:
    """A finished task of the worker pool."""

    kind: str
    iteration: int
    value: Any = None
    # What the task raised, if it did.
    error: BaseException | None = None


class WorkerPool:
    """Daemon threads taking tasks from one queue and putting their results on another.

    Being daemon threads, they are never waited for when the program ends, so a
    second Ctrl+C cannot hang on an LLM call in progress (Part D, v1 item 1).
    """

    def __init__(self, workers: int) -> None:
        self.tasks: queue.Queue[tuple[str, int, Callable[..., Any], tuple[Any, ...]] | None] = (
            queue.Queue()
        )
        self.results: queue.Queue[TaskResult] = queue.Queue()
        self.threads = [
            threading.Thread(target=self.work, name=f"my-evolve-worker-{number}", daemon=True)
            for number in range(1, workers + 1)
        ]
        for thread in self.threads:
            thread.start()

    def work(self) -> None:
        """Run tasks until told to stop. Runs in each worker thread."""
        while (task := self.tasks.get()) is not None:
            kind, iteration, function, arguments = task
            try:
                self.results.put(TaskResult(kind, iteration, value=function(*arguments)))
            except BaseException as error:  # the main thread decides what it means
                self.results.put(TaskResult(kind, iteration, error=error))

    def submit(
        self, kind: str, iteration: int, function: Callable[..., Any], *arguments: Any
    ) -> None:
        """Queue a task: function(*arguments), for one iteration."""
        self.tasks.put((kind, iteration, function, arguments))

    def next_result(self, timeout: float) -> TaskResult | None:
        """Return the next finished task, or None if none finished within timeout seconds."""
        try:
            return self.results.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        """Tell the threads to stop once their current task is done; does not wait."""
        for _ in self.threads:
            self.tasks.put(None)


@dataclass(frozen=True)
class Proposal:
    """What came back from the LLM in one iteration."""

    reply: LLMReply | None
    parsed: ParsedReply | None
    # Why there is no reply, if there is none.
    error: LLMError | None
    duration: float


@dataclass
class IterationState:
    """One iteration in flight."""

    number: int
    island: Island
    parent: Program
    examples: list[Program]
    model: LLM
    prompt: Prompt
    # Once the reply is back:
    proposal: Proposal | None = None
    checks: CheckResult | None = None


@dataclass
class Context:
    """Everything a run works with."""

    settings: RunSettings
    problem: Problem
    storage: Storage
    run_info: RunInfo
    session: SessionRecord
    database: Database
    evaluator: Evaluator
    sandbox: Sandbox
    ensemble: Ensemble
    prompt_builder: PromptBuilder
    initial_code: str
    # Iterations started and completed so far, counting those of earlier sessions;
    # an iteration lost by a crash counts in neither.
    started: int = 0
    completed: int = 0
    # The number of the next iteration started.
    next_number: int = 1
    # Infrastructure errors in a row (D38).
    errors_in_a_row: int = 0
    # Fingerprints of the children being evaluated, and their iterations (P2).
    pending_fingerprints: dict[str, int] = field(default_factory=dict)


def now_text() -> str:
    """Return the current time in ISO 8601, in UTC."""
    return datetime.now(UTC).isoformat()


def file_fingerprint(path: Path) -> str:
    """Return the SHA-256 hash of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_commit() -> str | None:
    """Return the git commit of my-evolve's code, or None if it is not a git checkout."""
    try:
        result = subprocess.run(
            ["git", "-C", str(Path(__file__).resolve().parent), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def plain_flags(settings: RunSettings) -> dict[str, Any]:
    """Return the settings as plain JSON values, for run.json."""
    return {
        name: str(value) if isinstance(value, Path) else value
        for name, value in dataclasses.asdict(settings).items()
    }


def first_line(text: str | None, limit: int = CONSOLE_ERROR_CHARS) -> str:
    """Return the first line of a text, cut to limit characters."""
    lines = (text or "").strip().splitlines()
    line = lines[0] if lines else ""
    return line if len(line) <= limit else line[: limit - 3] + "..."


# ----------------------------------------------------------------------------------
# Starting a run
# ----------------------------------------------------------------------------------


def evaluate_initial(code: str, problem: Problem, evaluator: Evaluator) -> Program:
    """Check and evaluate the initial program; anything but ok stops the run (D20).

    Raises RunError saying why.
    """
    try:
        split_evolve_blocks(code)
    except ValueError as error:
        raise RunError(f"the initial program's evolve blocks are broken: {error}") from error
    checks = check_child(code, code, problem.entry_functions, {})
    if checks.reason is not None:
        raise RunError(f"the initial program does not pass the checks: {checks.reason}")
    logger.info("Evaluating the initial program...")
    result = evaluator.evaluate(code)
    if not result.is_ok:
        raise RunError(f"the initial program must work, but it is {result.status}: {result.error}")
    logger.info("Initial program: score %s.", format_score(result.score))
    return Program.initial(code, result, checks.fingerprint, checks.code_complexity)


def run_generator(seed: int, programs_stored: int) -> random.Random:
    """Return the run's random generator, which makes every draw (D39).

    A new run seeds it with the seed alone; a continued run with the seed and the
    number of programs already stored, so that its draws go on instead of repeating
    those of the run's start (Part D, v1 item 9).
    """
    if programs_stored == 0:
        return random.Random(seed)
    return random.Random(f"{seed}:{programs_stored}")


def expected_image(settings: RunSettings, problem: Problem) -> str:
    """Return the image programs will run in, without building it ("local" without Docker)."""
    return "local" if settings.unsafe_local_sandbox else docker_image_tag(problem.packages)


def current_fingerprints(settings: RunSettings, problem: Problem) -> dict[str, str]:
    """Return the fingerprints that must stay the same for a run to be continued (D50)."""
    return {
        "initial_program": file_fingerprint(settings.initial_program),
        "evaluation_file": file_fingerprint(settings.evaluation_file),
        "problem": problem.fingerprint_without_llm(),
        "image": expected_image(settings, problem),
    }


def check_fingerprints(saved: dict[str, str], current: dict[str, str], folder: Path) -> None:
    """Raise RunError, saying what changed, unless the run folder's fingerprints are the same."""
    changed = [
        description
        for name, description in FINGERPRINTS.items()
        if saved.get(name) != current[name]
    ]
    if changed:
        raise RunError(
            f"{folder} holds a run that cannot be continued: {'; '.join(changed)} changed since "
            "it started. Put back what changed, or give another --output to start a new run."
        )


def make_sandbox(settings: RunSettings, problem: Problem, run_id: str) -> Sandbox:
    """Return the run's sandbox, after removing what an earlier session left (D40, D42)."""
    if settings.unsafe_local_sandbox:
        logger.warning(
            "Programs run WITHOUT ANY ISOLATION (--unsafe-local-sandbox): use it only for "
            "trusted code and tests."
        )
        return LocalSandbox(problem.sandbox.cpus)
    image = DockerSandbox.ensure_image(problem.packages)
    sandbox = DockerSandbox(image, problem.sandbox, run_id)
    sandbox.remove_leftovers()
    return sandbox


def drop_unfinished(
    storage: Storage, programs: list[Program], history: list[HistoryRow]
) -> list[Program]:
    """Drop what was saved for an iteration a crash left without its history row (P3).

    A child is saved before its history row: a crash between the two leaves, at the
    end of programs.jsonl, a child whose iteration is not done. It is dropped, with its
    LLM call, as a cut-off line is, and the iteration is done again.
    """
    done = {row.iteration for row in history}
    kept = list(programs)
    while kept and kept[-1].origin is Origin.LLM and kept[-1].iteration not in done:
        dropped = kept.pop()
        logger.warning(
            "Dropped the child of iteration %d, saved without its history row: the run "
            "stopped while saving it.",
            dropped.iteration,
        )
    if len(kept) != len(programs):
        storage.rewrite_programs(kept)
    calls = storage.load_llm_calls()
    kept_calls = list(calls)
    while kept_calls and kept_calls[-1].iteration not in done:
        kept_calls.pop()
    if len(kept_calls) != len(calls):
        storage.rewrite_llm_calls(kept_calls)
    return kept


def prepare(settings: RunSettings, problem: Problem, storage: Storage) -> Context:
    """Set everything up for a new run or for continuing one (D49, D50, D70).

    A new run evaluates and stores the initial program. A continued run checks that
    nothing but the llm section and the flags changed, rebuilds the database from the
    saved programs, and goes on from the iterations completed. Raises RunError, and
    the sandbox's, evaluator's or models' errors, if the run cannot start.
    """
    initial_code = settings.initial_program.read_text(encoding="utf-8-sig")
    fingerprints = current_fingerprints(settings, problem)
    resuming = not storage.is_new()
    history: list[HistoryRow] = []
    programs: list[Program] = []
    if resuming:
        saved_info = storage.read_run_info()
        if saved_info is None:
            raise RunError(
                f"{storage.folder} holds programs but no run.json: it cannot be continued"
            )
        run_info = saved_info
        check_fingerprints(run_info.fingerprints, fingerprints, storage.folder)
        if settings.seed is not None and settings.seed != run_info.seed:
            logger.warning(
                "--seed %d is ignored: a continued run keeps its seed, %d.",
                settings.seed,
                run_info.seed,
            )
        history = storage.load_history()
        programs = drop_unfinished(storage, storage.load_programs(), history)
        if not programs or programs[0].origin is not Origin.INITIAL:
            raise RunError(
                f"{storage.folder}: the saved programs do not start with the initial program"
            )
        logger.info(
            "Continuing the run %s in %s: %d iterations completed, %d programs saved.",
            run_info.run_id[:8],
            storage.folder,
            len(history),
            len(programs),
        )
    else:
        seed = (
            settings.seed if settings.seed is not None else random.SystemRandom().randrange(2**32)
        )
        run_info = RunInfo(run_id=uuid.uuid4().hex, seed=seed, fingerprints=fingerprints)
        logger.info("Run %s in %s, seed %d.", run_info.run_id[:8], storage.folder, seed)
    rng = run_generator(run_info.seed, len(programs))

    sandbox = make_sandbox(settings, problem, run_info.run_id)
    evaluator = Evaluator(settings.evaluation_file, problem, sandbox)
    ensemble = Ensemble.from_settings(problem.llm, rng)
    prompt_builder = PromptBuilder(problem)
    session = SessionRecord(
        started_at=now_text(),
        ended_at=None,
        git_commit=git_commit(),
        command_line=list(sys.argv),
        llm=dataclasses.asdict(problem.llm),
        flags=plain_flags(settings),
        system_message=prompt_builder.system_message,
    )

    if resuming:
        database = Database(problem, programs[0], rng)
        database.replay(programs)
        run_info.sessions.append(session)
        storage.write_run_info(run_info)
        storage.save_problem(settings.problem_file)
        # A crash right after the initial program was stored may have left islands
        # without their copy of it.
        for copy in database.seed_islands(programs[0], only_empty=True):
            storage.append_program(copy)
        storage.write_best(database.best())
    else:
        initial = evaluate_initial(initial_code, problem, evaluator)
        database = Database(problem, initial, rng)
        run_info.sessions.append(session)
        storage.write_run_info(run_info)
        storage.save_problem(settings.problem_file)
        database.add(initial)
        storage.append_program(initial)
        for copy in database.seed_islands(initial):
            storage.append_program(copy)
        storage.write_best(initial)
        storage.write_snapshot(initial, 0)

    logger.info("Checking the models...")
    ensemble.check_all()

    completed = len(history)
    # Iteration numbers are never reused, even those of iterations a crash lost.
    numbers = [row.iteration for row in history]
    numbers += [program.iteration for program in programs if program.origin is Origin.LLM]
    if resuming and completed >= settings.iterations:
        logger.info(
            "The run already has %d completed iterations (--iterations %d): nothing more to do.",
            completed,
            settings.iterations,
        )
    return Context(
        settings=settings,
        problem=problem,
        storage=storage,
        run_info=run_info,
        session=session,
        database=database,
        evaluator=evaluator,
        sandbox=sandbox,
        ensemble=ensemble,
        prompt_builder=prompt_builder,
        initial_code=initial_code,
        started=completed,
        completed=completed,
        next_number=max(numbers, default=0) + 1,
    )


# ----------------------------------------------------------------------------------
# One iteration
# ----------------------------------------------------------------------------------


def start_iteration(context: Context, number: int) -> IterationState:
    """Draw the island, the parent and the model, and build the prompt (main thread).

    Raises NoModelLeft if every model has been dropped.
    """
    database = context.database
    island = database.sample_island()
    parent = database.sample_parent(island)
    model = context.ensemble.draw()
    prompt = context.prompt_builder.build(parent, database.best().result.score or 0.0)
    logger.debug(
        "Iteration %d: island %d, parent %s (score %s, %d children), model %s.",
        number,
        island.index,
        parent.id[:8],
        format_score(parent.result.score),
        database.children_count(parent.id),
        model.name,
    )
    return IterationState(number, island, parent, [], model, prompt)


def propose(model: LLM, prompt: Prompt, parent_code: str) -> Proposal:
    """Ask the model and parse its reply (worker thread)."""
    started = time.monotonic()
    try:
        reply = model.complete(prompt)
    except LLMError as error:
        return Proposal(None, None, error, time.monotonic() - started)
    return Proposal(reply, parse_reply(reply.text, parent_code), None, reply.duration)


def evaluate_child(evaluator: Evaluator, code: str) -> Result:
    """Evaluate a child (worker thread); a failure of the framework itself gives error."""
    try:
        return evaluator.evaluate(code)
    except Exception as error:
        return Result.failure(Status.ERROR, f"evaluation: {type(error).__name__}: {error}")


def known_fingerprints(context: Context) -> dict[str, str]:
    """Return the fingerprints a child must not repeat: stored programs, then children in flight."""
    known = dict(context.database.fingerprints)
    for fingerprint, iteration in context.pending_fingerprints.items():
        known.setdefault(fingerprint, f"the child of iteration {iteration}, still being evaluated")
    return known


def after_proposal(context: Context, state: IterationState, task: TaskResult) -> bool:
    """Handle the reply of an iteration; return True if its child is to be evaluated."""
    if task.error is not None:
        skip(context, state, ERROR, f"{type(task.error).__name__}: {task.error}")
        return False
    proposal: Proposal = task.value
    state.proposal = proposal
    if proposal.error is not None:
        context.ensemble.record_failure(state.model.name)
        context.storage.append_llm_call(llm_call_record(state, None))
        skip(context, state, SKIPPED, str(proposal.error))
        return False

    context.ensemble.record_success(state.model.name)
    assert proposal.parsed is not None
    state.checks = check_child(
        proposal.parsed.code or "",
        context.initial_code,
        context.problem.entry_functions,
        known_fingerprints(context),
    )
    if state.checks.reason is not None:
        logger.debug("Iteration %d: rejected: %s", state.number, state.checks.reason)
        finish(context, state, child_program(state, Result.rejected(state.checks.reason)))
        return False
    assert state.checks.fingerprint is not None
    context.pending_fingerprints[state.checks.fingerprint] = state.number
    return True


def child_program(state: IterationState, result: Result) -> Program:
    """Return the iteration's child, with its result."""
    proposal, checks = state.proposal, state.checks
    assert proposal is not None and proposal.reply is not None and proposal.parsed is not None
    assert checks is not None
    reply = proposal.reply
    return Program.new_child(
        state.parent,
        code=proposal.parsed.code or "",
        result=result,
        island=state.island.index,
        iteration=state.number,
        description=proposal.parsed.description,
        fingerprint=checks.fingerprint,
        code_complexity=checks.code_complexity,
        example_ids=tuple(example.id for example in state.examples),
        llm=LLMUsage(reply.model, reply.input_tokens, reply.output_tokens, reply.duration),
    )


def llm_call_record(state: IterationState, program_id: str | None) -> LLMCallRecord:
    """Return the record of the iteration's LLM call, for llm_calls.jsonl."""
    proposal = state.proposal
    assert proposal is not None
    reply = proposal.reply
    return LLMCallRecord(
        iteration=state.number,
        program_id=program_id,
        model=state.model.name,
        user_message=state.prompt.user,
        reply=reply.text if reply is not None else None,
        input_tokens=reply.input_tokens if reply is not None else 0,
        output_tokens=reply.output_tokens if reply is not None else 0,
        duration=proposal.duration,
        error=str(proposal.error) if proposal.error is not None else None,
    )


def finish(context: Context, state: IterationState, child: Program) -> None:
    """Store an iteration's child and everything that follows from it (main thread)."""
    context.completed += 1
    if child.fingerprint is not None:
        context.pending_fingerprints.pop(child.fingerprint, None)
    database, storage = context.database, context.storage
    database.add(child, context.completed)
    storage.append_program(child)
    storage.append_llm_call(llm_call_record(state, child.id))
    context.errors_in_a_row = (
        context.errors_in_a_row + 1 if child.result.status is Status.ERROR else 0
    )
    if database.best_id == child.id:
        storage.write_best(child)
    record_history(context, state, child.id, str(child.result.status), child.result.score)
    log_iteration(context, state, child.result.status, child.result.score, child.result.error)
    after_completion(context)


def skip(context: Context, state: IterationState, status: str, error: str) -> None:
    """Complete an iteration without a child: its LLM call failed, or it failed first (D34, D38)."""
    context.completed += 1
    if status == ERROR:
        context.errors_in_a_row += 1
    record_history(context, state, None, status, None)
    log_iteration(context, state, status, None, error)
    after_completion(context)


def record_history(
    context: Context,
    state: IterationState,
    program_id: str | None,
    status: str,
    score: float | None,
) -> None:
    """Append the iteration's line to history.csv."""
    best = context.database.best()
    context.storage.append_history(
        HistoryRow(
            iteration=state.number,
            completed=context.completed,
            program_id=program_id,
            status=status,
            score=score,
            best_score=best.result.score or 0.0,
            best_id=best.id,
            model=state.model.name,
        )
    )


def log_iteration(
    context: Context, state: IterationState, status: str, score: float | None, error: str | None
) -> None:
    """Log the iteration's one console line (D52, D78)."""
    outcome = f"{status} {format_score(score)}" if score is not None else status
    if error and score is None:
        outcome += f" ({first_line(error)})"
    best = context.database.best().result.score
    logger.info(
        # The iteration's number, then the completed iterations and their total: after a
        # crash lost some iterations, numbers run ahead of the completed count.
        "Iteration %d [%d/%d]: island %d, %s: %s; best %s",
        state.number,
        context.completed,
        context.settings.iterations,
        state.island.index,
        state.model.name,
        outcome,
        format_score(best),
    )


def after_completion(context: Context) -> None:
    """Write a snapshot of the best program when one is due (D47)."""
    if context.completed % context.problem.snapshot_every == 0:
        context.storage.write_snapshot(context.database.best(), context.completed)


def should_stop(context: Context) -> str | None:
    """Return why the run must stop, or None (D37); the iteration total is the loop's own test."""
    if context.errors_in_a_row >= context.problem.max_errors_in_a_row:
        return f"too many errors in a row ({context.errors_in_a_row})"
    if not context.ensemble.active:
        return "no LLM model left"
    return None


# ----------------------------------------------------------------------------------
# The run
# ----------------------------------------------------------------------------------


class StopRequests:
    """Turns Ctrl+C and SIGTERM into what the loop does about them (D53, D54).

    Before the iterations start, and for a second Ctrl+C or a SIGTERM, they raise
    KeyboardInterrupt: the run stops at once. During the iterations, a first Ctrl+C
    only sets requested, which the loop acts on between two of its steps, so that it
    never interrupts the bookkeeping.
    """

    def __init__(self) -> None:
        # Whether a first Ctrl+C means "finish what is in progress".
        self.graceful: bool = False
        # Whether a first Ctrl+C has come.
        self.requested: bool = False
        self.previous: dict[int, Any] = {}

    def install(self) -> None:
        """Handle Ctrl+C, and SIGTERM on Linux and macOS; only the main thread can."""
        if threading.current_thread() is not threading.main_thread():
            return
        self.previous[signal.SIGINT] = signal.signal(signal.SIGINT, self.on_interrupt)
        if sys.platform != "win32":
            self.previous[signal.SIGTERM] = signal.signal(signal.SIGTERM, self.on_terminate)

    def ignore(self) -> None:
        """Ignore Ctrl+C and SIGTERM while the run records its end."""
        for number in self.previous:
            signal.signal(number, signal.SIG_IGN)

    def restore(self) -> None:
        """Put back the handlers there were before install()."""
        for number, handler in self.previous.items():
            signal.signal(number, handler)
        self.previous.clear()

    def on_interrupt(self, signal_number: int, frame: Any) -> None:
        """Ctrl+C: the first one during the iterations asks to finish; any other stops at once."""
        if self.graceful and not self.requested:
            self.requested = True
            return
        raise KeyboardInterrupt

    def on_terminate(self, signal_number: int, frame: Any) -> None:
        """SIGTERM: stop at once, as a second Ctrl+C does (D54)."""
        raise KeyboardInterrupt


def run_iterations(context: Context, stops: StopRequests | None = None) -> str:
    """Run iterations until the total is reached or the run must stop; return why it stopped.

    After a first Ctrl+C (stops.requested), no new iteration starts, and those in
    progress finish and are saved (D53).
    """
    settings = context.settings
    pool = WorkerPool(settings.workers)
    in_flight: dict[int, IterationState] = {}
    reason: str | None = None
    announced = False
    try:
        while True:
            if stops is not None and stops.requested and not announced:
                announced = True
                reason = reason or USER_STOP
                logger.warning(
                    "Ctrl+C: no new iteration starts; the %d in progress finish and are saved. "
                    "Press Ctrl+C again to stop at once.",
                    len(in_flight),
                )
            # Keep every worker busy: parents are drawn when an iteration starts, so
            # each one can build on everything stored so far.
            while (
                reason is None
                and len(in_flight) < settings.workers
                and context.started < settings.iterations
            ):
                try:
                    state = start_iteration(context, context.next_number)
                except NoModelLeft:
                    reason = "no LLM model left"
                    break
                context.started += 1
                context.next_number += 1
                in_flight[state.number] = state
                pool.submit(
                    "proposal", state.number, propose, state.model, state.prompt, state.parent.code
                )
            if not in_flight:
                break

            task = pool.next_result(WAKE_UP_SECONDS)
            if task is None:
                continue
            state = in_flight[task.iteration]
            if task.kind == "proposal":
                if after_proposal(context, state, task):
                    assert state.proposal is not None and state.proposal.parsed is not None
                    code = state.proposal.parsed.code or ""
                    pool.submit("evaluation", state.number, evaluate_child, context.evaluator, code)
                    continue
            else:
                result: Result = (
                    task.value
                    if task.error is None
                    else Result.failure(
                        Status.ERROR, f"evaluation: {type(task.error).__name__}: {task.error}"
                    )
                )
                finish(context, state, child_program(state, result))
            del in_flight[task.iteration]
            if reason is None:
                reason = should_stop(context)
    finally:
        pool.close()
    return reason or f"{settings.iterations} iterations completed"


def summary(context: Context, reason: str) -> None:
    """Log the run's summary (D51): why it stopped, the best program, counts, tokens and cost."""
    database = context.database
    best = database.best()
    children = [program for program in database.programs.values() if program.llm is not None]
    statuses = Counter(str(child.result.status) for child in children)
    logger.info("Run finished: %s.", reason)
    logger.info("Iterations completed: %d.", context.completed)
    logger.info(
        "Best score: %s, found at iteration %d (program %s).",
        format_score(best.result.score),
        best.iteration,
        best.id[:8],
    )
    if statuses:
        counts = ", ".join(f"{status} {count}" for status, count in sorted(statuses.items()))
        logger.info("Children by status: %s.", counts)
    prices = {model.name: model for model in context.problem.llm.models}
    for name in context.ensemble.models:
        calls = [
            child.llm for child in children if child.llm is not None and child.llm.model == name
        ]
        tokens_in = sum(call.input_tokens for call in calls)
        tokens_out = sum(call.output_tokens for call in calls)
        line = f"Model {name}: {len(calls)} children, {tokens_in} tokens in, {tokens_out} out"
        settings = prices[name]
        if settings.price_input is not None and settings.price_output is not None:
            cost = (tokens_in * settings.price_input + tokens_out * settings.price_output) / 1e6
            line += f", cost {cost:.4f}"
        logger.info("%s.", line)


def run(settings: RunSettings) -> Database:
    """Evolve the problem's program from start to finish, and return the database (D70).

    Raises the problem file's, the sandbox's, the evaluator's or the models' errors,
    or RunError, if the run cannot start; RunInterrupted if it was stopped at once by
    a second Ctrl+C or a SIGTERM, after removing its containers and recording it (D54).
    """
    problem = Problem.load(settings.problem_file)
    storage = Storage(settings.output)
    setup_logging(storage.folder, settings.verbose)
    stops = StopRequests()
    stops.install()
    context: Context | None = None
    reason = "stopped by an error"
    try:
        context = prepare(settings, problem, storage)
        stops.graceful = True
        reason = run_iterations(context, stops)
        return context.database
    except KeyboardInterrupt:
        reason = INTERRUPTED
        logger.warning(
            "Stopped at once: the iterations in progress are lost; they are done again when "
            "the run is continued."
        )
        raise RunInterrupted("the run was stopped at once") from None
    finally:
        stops.ignore()
        try:
            if context is not None:
                if reason == INTERRUPTED:
                    context.sandbox.kill_all()
                else:
                    context.sandbox.remove_leftovers()
                context.session.ended_at = now_text()
                context.session.end = reason
                storage.write_run_info(context.run_info)
                summary(context, reason)
        finally:
            stop_logging()
            stops.restore()
