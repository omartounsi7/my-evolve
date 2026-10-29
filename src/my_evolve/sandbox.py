"""The sandbox: runs a program in a worker process of its own, and lets the host call its functions.

The evaluation file stays on the host. It receives a ProgramNamespace, which stands in
front of the worker: looking up a function gives a RemoteFunction, and calling that
sends a call message to the worker, which runs the program's function and sends back
its value. So the program chooses what its functions return, but never runs in the
same process as the code that computes its score.

A session has a deadline: past it, the worker is killed and StageTimeout raised. A
reader thread collects the worker's messages in a queue, so that waiting for an answer
can stop at the deadline. What the program prints goes to a temporary file, whose end
is added to every failure; a message the host is not waiting for is ignored.

For now the worker is a plain subprocess (LocalSandbox), without any isolation: the
program can still read and write your files and use the network. Step 1.8 of the plan
adds the Docker sandbox.
"""

import queue
import subprocess
import sys
import tempfile
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping
from typing import IO, Any

from my_evolve.evaluation_api import ProgramFailure, StageTimeout
from my_evolve.sandbox_protocol import Message, NotPlainData, decode, encode, receive, send

# How long closing a session waits for the worker to end on its own, in seconds
CLOSE_WAIT_SECONDS = 5.0
# How much of the end of the program's output a failure keeps, in characters
ERROR_TAIL_CHARS = 2000
# The exit codes of a process killed by SIGKILL, which is what running out of memory
# usually brings: in Docker, and as a plain subprocess
KILLED_EXIT_CODES = (137, -9)


class SandboxError(Exception):
    """The sandbox itself failed, not the program: the program's status is error."""


def describe_exit(exit_code: int) -> str:
    """Return how the worker ended, in words."""
    if exit_code in KILLED_EXIT_CODES:
        return (
            f"the program's process was stopped (exit code {exit_code}), "
            "most likely for using too much memory"
        )
    if exit_code < 0:
        return f"the program's process was stopped by signal {-exit_code}"
    return f"the program's process ended (exit code {exit_code})"


def read_messages(stream: IO[str], messages: "queue.Queue[Message | None]") -> None:
    """Put every message the worker sends in the queue, then None when its output ends.

    Runs in the session's reader thread. A line that is not a message is skipped.
    """
    while True:
        try:
            message = receive(stream)
        except ValueError:
            continue
        except (OSError, UnicodeDecodeError):
            message = None
        messages.put(message)
        if message is None:
            return


class SandboxSession:
    """One worker process holding one loaded program, until its deadline."""

    def __init__(self, command: list[str], code: str, stage_limit: float) -> None:
        """Prepare a session; start() starts the worker and loads the program."""
        # How to start the worker
        self.command: list[str] = command
        # The program's code
        self.code: str = code
        # How long the session may last, in seconds, loading included
        self.stage_limit: float = stage_limit
        # When the session must end (time.monotonic), set when it starts
        self.deadline: float = 0.0
        # The worker process, once started
        self.process: subprocess.Popen[str] | None = None
        # The worker's messages, collected by the reader thread; None when its output ended
        self.messages: queue.Queue[Message | None] = queue.Queue()
        # The program's top-level names, each "function", "data" or "other"
        self.names: dict[str, str] = {}
        # The id of the last call or get message sent
        self.last_id: int = 0
        # True once the worker was killed because the deadline passed
        self.timed_out: bool = False
        # Where the program's output goes (what it prints, and Python's own messages)
        self.error_file: IO[bytes] = tempfile.TemporaryFile()

    def start(self) -> None:
        """Start the worker and load the program.

        Raises ProgramFailure if the program fails to load, StageTimeout if loading
        outlasts the deadline, SandboxError if the worker cannot be started.
        """
        self.deadline = time.monotonic() + self.stage_limit
        try:
            self.process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                # A file, not a pipe: a program printing without end fills a file, not memory.
                stderr=self.error_file,
                text=True,
                encoding="utf-8",
            )
        except OSError as error:
            raise SandboxError(f"cannot start the worker: {error}") from error
        assert self.process.stdout is not None
        reader = threading.Thread(
            target=read_messages, args=(self.process.stdout, self.messages), daemon=True
        )
        reader.start()
        answer = self.exchange({"type": "load", "code": self.code}, {"loaded", "load_failed"})
        if answer["type"] == "load_failed":
            raise self.failure(answer["error"], answer["traceback"])
        self.names = answer["names"]

    def exchange(self, message: Message, expected: set[str]) -> Message:
        """Send one message and return the worker's answer: the next message of an expected
        type that carries the message's id.

        Any other message is ignored: a program writing forged answers gains nothing.
        Raises StageTimeout if the deadline passes first (the worker is then killed),
        ProgramFailure if the worker ends without answering.
        """
        assert self.process is not None and self.process.stdin is not None
        try:
            send(self.process.stdin, message)
        except OSError:
            # The worker has ended: its output tells how, below.
            pass
        while True:
            try:
                answer = self.messages.get(timeout=max(0.0, self.deadline - time.monotonic()))
            except queue.Empty:
                self.timed_out = True
                self.kill()
                raise StageTimeout(
                    f"the evaluation ran over its time limit of {self.stage_limit:g} s"
                ) from None
            if answer is None:
                raise self.failure(describe_exit(self.process.wait()))
            if answer.get("type") in expected and answer.get("id") == message.get("id"):
                return answer

    def failure(self, error: str, traceback: str = "") -> ProgramFailure:
        """Return the ProgramFailure to raise, with the end of the program's output."""
        return ProgramFailure(error, traceback, self.error_tail())

    def error_tail(self) -> str:
        """Return the end of what the program printed so far."""
        self.error_file.seek(0, 2)
        size = self.error_file.tell()
        # Four bytes at most per character, in UTF-8.
        self.error_file.seek(max(0, size - 4 * ERROR_TAIL_CHARS))
        text = self.error_file.read().decode("utf-8", errors="replace")
        return text[-ERROR_TAIL_CHARS:]

    def call(
        self, name: str, args: tuple[Any, ...] = (), kwargs: Mapping[str, Any] | None = None
    ) -> Any:
        """Call one of the program's functions in the worker, and return its value.

        Raises ProgramFailure if the function raises or the worker ends, StageTimeout
        if the deadline passes.
        """
        self.last_id += 1
        message = {
            "type": "call",
            "id": self.last_id,
            "name": name,
            "args": encode(list(args)),
            "kwargs": encode(dict(kwargs or {})),
        }
        return self.value_of(self.exchange(message, {"return", "raised"}))

    def get(self, name: str) -> Any:
        """Return the value of one of the program's plain-data globals."""
        self.last_id += 1
        message = {"type": "get", "id": self.last_id, "name": name}
        return self.value_of(self.exchange(message, {"return", "raised"}))

    def value_of(self, answer: Message) -> Any:
        """Return the value an answer carries. Raises ProgramFailure if it reports an error."""
        if answer["type"] == "raised":
            raise self.failure(answer["error"], answer["traceback"])
        try:
            return decode(answer["value"])
        except NotPlainData as error:
            raise self.failure(f"the program's answer cannot be read: {error}") from None

    def kill(self) -> None:
        """Stop the worker at once, if it is still running."""
        if self.process is not None and self.process.poll() is None:
            self.process.kill()
            self.process.wait()

    def close(self) -> None:
        """End the worker: close its input, so that it stops, and kill it if it does not."""
        if self.process is None:
            return
        if self.process.stdin:
            try:
                self.process.stdin.close()
            except OSError:
                pass
        try:
            self.process.wait(timeout=CLOSE_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            self.kill()
        self.error_file.close()


class RemoteFunction:
    """Stands for one of the program's functions: calling it runs the function in the worker."""

    def __init__(self, session: SandboxSession, name: str) -> None:
        self.session: SandboxSession = session
        self.name: str = name

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Call the program's function with these arguments (plain data) and return its value."""
        return self.session.call(self.name, args, kwargs)

    def __repr__(self) -> str:
        return f"<the program's function {self.name}>"


class ProgramNamespace(Mapping[str, Any]):
    """What an evaluation file's evaluate receives: the names the program defines.

    A function's name gives a RemoteFunction; a plain-data global gives its value. A
    missing name, or one that is neither (a module, a class), raises ProgramFailure.
    """

    def __init__(self, session: SandboxSession) -> None:
        self.session: SandboxSession = session

    def __getitem__(self, name: str) -> Any:
        kind = self.session.names.get(name)
        if kind == "function":
            return RemoteFunction(self.session, name)
        if kind == "data":
            return self.session.get(name)
        if kind is None:
            raise ProgramFailure(f"the program defines no {name!r}")
        raise ProgramFailure(f"the program's {name!r} is neither a function nor plain data")

    def __contains__(self, name: object) -> bool:
        return name in self.session.names

    def __iter__(self) -> Iterator[str]:
        return iter(self.session.names)

    def __len__(self) -> int:
        return len(self.session.names)


class Sandbox(ABC):
    """Starts sessions: one worker process per program evaluated."""

    @abstractmethod
    def command(self) -> list[str]:
        """Return the command that starts a worker."""

    def start(self, code: str, stage_limit: float) -> SandboxSession:
        """Start a worker, load the program into it, and give it stage_limit seconds in all.

        The caller must close the session. Raises ProgramFailure if the program fails to
        load, StageTimeout if loading takes too long, SandboxError if the sandbox fails.
        """
        session = SandboxSession(self.command(), code, stage_limit)
        try:
            session.start()
        except BaseException:
            session.close()
            raise
        return session


class LocalSandbox(Sandbox):
    """Runs the worker as a plain subprocess, with this Python: no isolation at all."""

    def command(self) -> list[str]:
        """Return the command that starts a worker with this Python."""
        return [sys.executable, "-m", "my_evolve.sandbox_worker"]
