"""The loop: AlphaEvolve's controller, which evolves the problem's program.

Each iteration runs the six steps of the AlphaEvolve diagram:

    island = database.sample_island()
    parent, examples = database.sample(island, example_count)
    prompt = prompt_builder.build(parent, examples, best_score)
    reply = ensemble.draw(rng).complete(prompt)
    parsed = parse_reply(reply)          # the program and its description
    result = evaluator.evaluate(parsed.code)
    database.add(Program.new_child(parent, parsed.code, result, iteration))

Up to `workers` iterations are in flight at once (D36). Each alternates between the main
thread, which does all the bookkeeping, and a worker thread, which does the waiting:

1. main: draw the island, the parent, the examples and the model; build the prompt;
2. worker: ask the model, and parse its reply;
3. main: run the checks, so that the duplicate check sees every stored program;
4. worker: evaluate the child;
5. main: store the child; snapshot the best program, or migrate, when due.

Only the main thread uses the database and the run folder. Everything is saved as it
happens (storage.py), and logged to the console and log.txt (logs.py).

Errors are recorded and the run goes on (D38): an unexpected exception that is not the
program's fault (in a worker, in the checks, in the evaluation) gives the child the
status error, or, before a child exists, records the iteration as an error; too many
in a row stop the run. An exception in the main thread's own bookkeeping (the disk
refusing a write) stops the run at once.

Stopping (D53, D54): the first Ctrl+C lets the iterations in flight finish and be saved,
then the run ends as usual. A second Ctrl+C, or SIGTERM (Linux, macOS), stops at once:
the worker threads are not waited for, and the iterations in flight are lost;
everything finished is already saved.

The run ends with a summary: iterations done and why the run stopped, the best score,
the children by status, and the tokens and cost of each model (D51).
"""

import logging
import queue
import random
import signal
import subprocess
import sys
import threading
import uuid
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from my_evolve.checks import ChildChecks, MarkerError, check_child, split_evolve_blocks
from my_evolve.database import Database
from my_evolve.evaluator import Evaluator
from my_evolve.llm import LLM, Ensemble, LLMError, LLMReply, NoModelLeft
from my_evolve.logs import setup_logging, stop_logging
from my_evolve.problem import ModelSettings, Problem
from my_evolve.program import LLMUsage, Origin, Program, Result, Status, new_id
from my_evolve.prompt import Prompt, PromptBuilder
from my_evolve.reply_parser import ParsedReply, parse_reply
from my_evolve.storage import HistoryRow, RunInfo, Storage

# The longest error shown on the console, in characters (programs.jsonl keeps it whole)
MAX_CONSOLE_ERROR = 200
# How long the main thread waits for a finished task at a time, in seconds: short, so that
# Ctrl+C reaches it promptly, Windows included (D53)
WAIT_STEP_SECONDS = 0.2

logger = logging.getLogger(__name__)


class RunError(Exception):
    """Raised when a run cannot start; the message says why."""


class StopNow(KeyboardInterrupt):
    """Stops a run at once: a second Ctrl+C, or SIGTERM (D54)."""


def stop_on_sigterm() -> Any:
    """Make SIGTERM stop a run at once, as a second Ctrl+C does; return the previous handler.

    SIGTERM exists on Linux and macOS only: on Windows, nothing changes and None is
    returned. Call it from the main thread.
    """
    if sys.platform == "win32" or not hasattr(signal, "SIGTERM"):
        return None

    def handler(signal_number: int, frame: Any) -> None:
        raise StopNow("SIGTERM")

    return signal.signal(signal.SIGTERM, handler)


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


def now() -> str:
    """Return the current time, in UTC, as ISO 8601 text."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def git_commit() -> str | None:
    """Return the commit of the my-evolve code that runs, or None if it is not known."""
    try:
        found = subprocess.run(
            ["git", "-C", str(Path(__file__).parent), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return found.stdout.strip() or None if found.returncode == 0 else None


@dataclass
class TaskResult:
    """A task a worker finished: what it was, and its value or the exception it raised."""

    # "propose" (ask the LLM and parse its reply) or "evaluate"
    kind: str
    # The iteration it belongs to
    iteration: int
    # What the task returned; None if it raised
    value: Any
    # What it raised; None if it returned
    error: BaseException | None


class WorkerPool:
    """Daemon threads taking tasks from one queue and putting their results on another (D70).

    Being daemon threads, they are never waited for when the program ends, so stopping a
    run at once cannot hang on an LLM call in progress (differences.md, Part D, v1 item 1).
    """

    def __init__(self, workers: int) -> None:
        """Start that many worker threads."""
        # The tasks waiting for a worker
        self.tasks: queue.Queue[tuple[str, int, Callable[..., Any], tuple[Any, ...]]] = (
            queue.Queue()
        )
        # The tasks finished, waiting for the main thread
        self.results: queue.Queue[TaskResult] = queue.Queue()
        for number in range(workers):
            threading.Thread(target=self.work, name=f"worker-{number}", daemon=True).start()

    def work(self) -> None:
        """Run tasks, one after another, for as long as the program lives."""
        while True:
            kind, iteration, function, arguments = self.tasks.get()
            try:
                value = function(*arguments)
            except BaseException as error:
                self.results.put(TaskResult(kind, iteration, None, error))
            else:
                self.results.put(TaskResult(kind, iteration, value, None))

    def submit(
        self, kind: str, iteration: int, function: Callable[..., Any], *arguments: Any
    ) -> None:
        """Hand a task to the workers."""
        self.tasks.put((kind, iteration, function, arguments))

    def next_result(self, timeout: float) -> TaskResult | None:
        """Return the next finished task, or None if none finishes within timeout seconds."""
        try:
            return self.results.get(timeout=timeout)
        except queue.Empty:
            return None


def propose(llm: LLM, prompt: Prompt, parent_code: str) -> tuple[LLMReply, ParsedReply]:
    """Ask the model and parse its reply: an iteration's first task for a worker."""
    reply = llm.complete(prompt)
    return reply, parse_reply(reply.text, parent_code)


@dataclass
class IterationState:
    """What the main thread knows about one iteration in flight."""

    # Its number
    number: int
    # The island, the parent and the examples drawn for it
    island: int
    parent: Program
    examples: list[Program]
    # The model drawn for it, and the prompt it was sent
    llm: LLM
    prompt: Prompt
    # The id its child will have, so that the duplicate check can name it while in flight
    child_id: str = field(default_factory=new_id)
    # Once the model replied: its reply, the parsed reply, and what the checks found
    reply: LLMReply | None = None
    parsed: ParsedReply | None = None
    checks: ChildChecks | None = None


class Loop:
    """One session of a run: its state, and the steps of its iterations (D70's Context)."""

    def __init__(
        self,
        problem: Problem,
        initial_code: str,
        ensemble: Ensemble,
        evaluator: Evaluator,
        iterations: int,
        storage: Storage,
        seed: int,
        workers: int,
    ) -> None:
        """Gather what the run needs; prepare() then checks the start."""
        self.problem: Problem = problem
        self.initial_code: str = initial_code
        self.ensemble: Ensemble = ensemble
        self.evaluator: Evaluator = evaluator
        # The number of iterations to complete
        self.iterations: int = iterations
        self.storage: Storage = storage
        # How many iterations may be in flight at once
        self.workers: int = workers
        # The run's random generator: every draw of the run comes from it (D39)
        self.rng: random.Random = random.Random(seed)
        self.prompt_builder: PromptBuilder = PromptBuilder(problem)
        # Set by prepare
        self.database: Database | None = None
        # Iterations started and completed (failed and skipped ones included)
        self.started: int = 0
        self.completed: int = 0
        # Why the run stopped, once it stops starting new iterations
        self.stop_reason: str | None = None
        # The fingerprints of the children being evaluated, each with its future id: the
        # duplicate check also sees them, so two identical children in flight are not
        # both evaluated
        self.pending: dict[str, str] = {}
        # Iterations in a row that ended in an error, not the program's fault (D38)
        self.errors_in_a_row: int = 0
        # True once Ctrl+C was pressed: no new iteration starts
        self.interrupted: bool = False

    @property
    def db(self) -> Database:
        """Return the database, which prepare() creates."""
        assert self.database is not None
        return self.database

    def prepare(self) -> Program:
        """Check the initial program and the models, evaluate the initial program, and fill the
        database; return the initial program. Raises RunError if the run cannot start."""
        try:
            split_evolve_blocks(self.initial_code)
        except MarkerError as error:
            raise RunError(f"the initial program's evolve blocks are broken: {error}") from None
        checks = check_child(self.initial_code, self.initial_code, self.problem.entry_functions, {})
        if checks.reason is not None:
            raise RunError(f"the initial program fails the checks: {checks.reason}")
        try:
            self.ensemble.check_all()
        except LLMError as error:
            raise RunError(f"a model did not answer its check: {error}") from None
        self.database = Database(
            self.rng,
            self.problem.parents,
            self.problem.islands,
            self.problem.grid_features,
            reference_nodes=checks.code_complexity or 1,
        )
        initial = Program(
            self.initial_code,
            self.evaluator.evaluate(self.initial_code),
            fingerprint=checks.fingerprint,
            code_complexity=checks.code_complexity,
        )
        if not initial.result.is_ok:
            raise RunError(
                f"the initial program does not work ({initial.result.status.value}): "
                f"{initial.result.error}"
            )
        return initial

    def seed(self, initial: Program) -> None:
        """Store the initial program and its copy on every island, and snapshot 0."""
        self.store(initial)
        for copy in self.db.seed_islands(initial):
            self.store(copy)
        self.storage.write_snapshot(initial, 0)
        logger.info(
            "Initial program: %s, copied to %d islands", describe(initial), len(self.db.islands)
        )

    def store(self, program: Program) -> None:
        """Add a program to the database and the run folder."""
        self.db.add(program)
        self.storage.append_program(program)
        if self.db.best_id == program.id:
            self.storage.write_best(program)

    def start_iteration(self) -> IterationState | None:
        """Start the next iteration (main thread): draw its island, parent, examples and model,
        and build its prompt. Returns None, and stops the run, if no model is left."""
        number = self.started + 1
        island = self.db.sample_island()
        parent, examples = self.db.sample(island, self.problem.prompt.example_programs)
        try:
            llm = self.ensemble.draw(self.rng)
        except NoModelLeft as error:
            logger.info("Stopping: %s", error)
            self.stop_reason = "no LLM model left"
            return None
        self.started = number
        logger.debug(
            "Iteration %d: island %d, parent %s (%s), examples %s, model %s",
            number,
            island,
            parent.id,
            describe(parent),
            [example.id for example in examples],
            llm.name,
        )
        prompt = self.prompt_builder.build(parent, examples, self.db.best_score())
        return IterationState(number, island, parent, examples, llm, prompt)

    def after_proposal(self, state: IterationState, task: TaskResult) -> bool:
        """Handle the model's reply (main thread); return True if the child must be evaluated.

        A failed call skips the iteration; any other exception in the worker records the
        iteration as an error. A child that fails the checks is stored as rejected, and
        one the checks themselves fail on gets the status error; otherwise its fingerprint
        joins those in flight, and it is evaluated.
        """
        if isinstance(task.error, LLMError):
            self.ensemble.record_failure(state.llm.name)
            self.skip(state, task.error)
            return False
        if task.error is not None:
            self.fail(state, task.error)
            return False
        state.reply, state.parsed = task.value
        self.ensemble.record_success(state.llm.name)
        known = {**self.db.fingerprints, **self.pending}
        try:
            state.checks = check_child(
                state.parsed.code, self.initial_code, self.problem.entry_functions, known
            )
        except Exception as error:
            state.checks = ChildChecks(None, None)
            self.finish(state, Result.failure(Status.ERROR, f"checks: {error!r}"))
            return False
        if state.checks.reason is not None:
            self.finish(state, Result.rejected(state.checks.reason))
            return False
        if state.checks.fingerprint is not None:
            self.pending[state.checks.fingerprint] = state.child_id
        return True

    def finish(self, state: IterationState, result: Result) -> None:
        """Store an iteration's child, its LLM call and its history row (main thread)."""
        assert state.reply is not None and state.parsed is not None and state.checks is not None
        if state.checks.fingerprint is not None:
            self.pending.pop(state.checks.fingerprint, None)
        reply = state.reply
        usage = LLMUsage(reply.model, reply.input_tokens, reply.output_tokens, reply.duration)
        child = Program.new_child(
            state.parent,
            state.parsed.code,
            result,
            state.number,
            island=state.island,
            llm=usage,
            description=state.parsed.description,
            fingerprint=state.checks.fingerprint,
            example_ids=state.prompt.example_ids,
            code_complexity=state.checks.code_complexity,
            program_id=state.child_id,
        )
        self.store(child)
        self.completed += 1
        self.count_error(result.status is Status.ERROR)
        self.storage.append_llm_call(
            {
                "iteration": state.number,
                "user_message": state.prompt.user,
                "program_id": child.id,
                "reply": reply.text,
                "error": None,
                **usage.to_dict(),
            }
        )
        self.storage.append_history(self.history_row(state, child))
        logger.debug(
            "Iteration %d: LLM %.1f s, evaluation %.1f s (stage %d reached)",
            state.number,
            reply.duration,
            result.duration,
            result.stage_reached,
        )
        logger.info(
            "Iteration %d/%d, island %d, %s: %s (best %s)",
            state.number,
            self.iterations,
            state.island,
            state.llm.name,
            describe(child),
            best_score_text(self.db),
        )
        self.after_completion()

    def fail(self, state: IterationState, error: BaseException) -> None:
        """Record an iteration that failed before having a child, not through the program's
        fault (main thread): it counts as completed, and as an error in a row (D38)."""
        self.completed += 1
        self.count_error(True)
        self.storage.append_llm_call(
            {
                "iteration": state.number,
                "user_message": state.prompt.user,
                "program_id": None,
                "model": state.llm.name,
                "reply": None,
                "error": repr(error),
            }
        )
        self.storage.append_history(self.history_row(state, None, "error"))
        logger.info(
            "Iteration %d/%d, island %d, %s: error: %r",
            state.number,
            self.iterations,
            state.island,
            state.llm.name,
            error,
        )
        self.after_completion()

    def count_error(self, is_error: bool) -> None:
        """Count an error in a row, or start the count again; stop the run at the limit."""
        self.errors_in_a_row = self.errors_in_a_row + 1 if is_error else 0
        if self.errors_in_a_row >= self.problem.max_errors_in_a_row and self.stop_reason is None:
            logger.info("Stopping: %d errors in a row", self.errors_in_a_row)
            self.stop_reason = "too many errors in a row"

    def skip(self, state: IterationState, error: BaseException) -> None:
        """Record an iteration that produced no child (main thread): it still counts (D34)."""
        self.completed += 1
        self.storage.append_llm_call(
            {
                "iteration": state.number,
                "user_message": state.prompt.user,
                "program_id": None,
                "model": state.llm.name,
                "reply": None,
                "error": str(error),
            }
        )
        self.storage.append_history(self.history_row(state, None, "skipped"))
        logger.info(
            "Iteration %d/%d, island %d, %s: skipped, no reply (%s)",
            state.number,
            self.iterations,
            state.island,
            state.llm.name,
            error,
        )
        self.after_completion()

    def history_row(
        self, state: IterationState, child: Program | None, outcome: str = ""
    ) -> HistoryRow:
        """Return the history row of a completed iteration; without a child, its outcome:
        "skipped" (no reply) or "error"."""
        best = self.db.best()
        return HistoryRow(
            iteration=state.number,
            completed=self.completed,
            program_id=child.id if child else "",
            status=child.result.status.value if child else outcome,
            score=child.result.score if child else None,
            best_score=self.db.best_score(),
            best_id=best.id if best else "",
            model=state.llm.name,
        )

    def after_completion(self) -> None:
        """Every snapshot_every completed iterations, skipped ones included, save the best
        program (D47); every migration_interval, migrate between islands (D23)."""
        completed = self.completed
        best = self.db.best()
        if completed % self.problem.snapshot_every == 0 and best is not None:
            self.storage.write_snapshot(best, completed)
        if completed % self.problem.islands.migration_interval != 0:
            return
        arrivals = self.db.migrate(completed)
        for arrival in arrivals:
            self.store(arrival)
        if arrivals:
            verb = "moved" if self.problem.islands.mode == "move" else "copied"
            logger.info(
                "Migration after iteration %d: %d programs %s", completed, len(arrivals), verb
            )

    def run_iterations(self) -> str:
        """Run iterations until enough have completed or the run stops; return why it stopped.

        The first Ctrl+C stops new iterations from starting, and the run ends once those
        in flight are done (D53). A second Ctrl+C, or SIGTERM, raises StopNow (D54).
        """
        pool = WorkerPool(self.workers)
        in_flight: dict[int, IterationState] = {}
        while True:
            try:
                if not self.step(pool, in_flight):
                    break
            except StopNow:
                raise
            except KeyboardInterrupt:
                if self.interrupted:
                    raise StopNow("a second Ctrl+C") from None
                self.interrupted = True
                self.stop_reason = self.stop_reason or "stopped by Ctrl+C"
                logger.info(
                    "Ctrl+C: no new iteration starts; the %d in progress finish and are saved. "
                    "Press Ctrl+C again to stop at once.",
                    len(in_flight),
                )
        return self.stop_reason or "every iteration done"

    def step(self, pool: WorkerPool, in_flight: dict[int, IterationState]) -> bool:
        """Start iterations while fewer than `workers` are in flight, then wait a short while
        for a finished task and handle it. Return False once nothing is left to do.

        The wait is short, so that Ctrl+C reaches the main thread promptly (D53).
        """
        while (
            self.stop_reason is None
            and len(in_flight) < self.workers
            and self.started < self.iterations
        ):
            state = self.start_iteration()
            if state is None:
                break
            in_flight[state.number] = state
            pool.submit(
                "propose", state.number, propose, state.llm, state.prompt, state.parent.code
            )
        if not in_flight:
            return False
        task = pool.next_result(WAIT_STEP_SECONDS)
        if task is None:
            return True
        state = in_flight[task.iteration]
        if task.kind == "propose":
            if self.after_proposal(state, task):
                assert state.parsed is not None
                pool.submit("evaluate", state.number, self.evaluator.evaluate, state.parsed.code)
                return True
        elif task.error is not None:
            # The evaluator never raises because of a program: this is not its fault.
            self.finish(state, Result.failure(Status.ERROR, f"evaluation: {task.error!r}"))
        else:
            self.finish(state, task.value)
        del in_flight[task.iteration]
        return True


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
    problem_file: Path | None = None,
    command: Sequence[str] = (),
    workers: int = 1,
) -> Database:
    """Evolve the initial program for that many iterations, and return the database.

    Everything is saved in the output folder as soon as it exists (storage.py), with a
    copy of problem_file, if given, and the command line in the session's record. seed
    fixes the random draws (with one worker and the same LLM replies, a run repeats
    exactly); without one, a seed is drawn. run_id identifies the run (its containers are
    labelled with it); without one, an id is made. Up to `workers` iterations are in
    flight at once. Each iteration draws one model of the ensemble; an iteration whose
    LLM call fails is skipped, and the run stops when every model has been dropped. Every
    model is checked before the run. Messages go to the console (details too with
    verbose) and to log.txt in the output folder.

    A child that fails a check (it does not compile, changes code outside the evolve
    blocks, lacks an entry function, or repeats an earlier program or one in flight) is
    rejected, and costs no evaluation.

    Raises RunError if the output folder already holds a run, if a model does not
    answer its check, if the initial program fails the checks, or if it does not work:
    evolution needs a working start.
    """
    storage = Storage(output)
    if storage.holds_a_run():
        raise RunError(f"{output} already holds a run; choose another output folder")
    setup_logging(output, verbose)
    try:
        seed = seed if seed is not None else random.SystemRandom().randrange(2**32)
        loop = Loop(problem, initial_code, ensemble, evaluator, iterations, storage, seed, workers)
        logger.info("Seed: %d", seed)
        initial = loop.prepare()
        info = RunInfo(run_id=run_id or uuid.uuid4().hex, seed=seed)
        session: dict[str, Any] = {
            "started_at": now(),
            "ended_at": None,
            "end": None,
            "command": list(command),
            "git_commit": git_commit(),
            "flags": {"iterations": iterations, "workers": workers, "verbose": verbose},
            "llm": asdict(problem.llm),
            "system_message": loop.prompt_builder.system_message,
        }
        info.sessions.append(session)
        storage.write_run_info(info)
        if problem_file is not None:
            storage.save_problem(problem_file)
        loop.seed(initial)
        reason = "interrupted"
        try:
            reason = loop.run_iterations()
        except BaseException as error:
            if not isinstance(error, KeyboardInterrupt):
                reason = f"failed: {error!r}"
            raise
        finally:
            session.update(ended_at=now(), end=reason)
            storage.write_run_info(info)
        for line in summary(problem, loop.db, loop.completed, reason):
            logger.info(line)
        return loop.db
    finally:
        stop_logging()
