"""The sandbox: runs a program in a worker process of its own, and lets the host call its functions.

The evaluation file stays on the host. It receives a ProgramNamespace, which stands in
front of the worker: looking up a function gives a RemoteFunction, and calling that
sends a call message to the worker, which runs the program's function and sends back
its value. So the program chooses what its functions return, but never runs in the
same process as the code that computes its score.

A session has a deadline: past it, the worker is killed and StageTimeout raised. A
reader thread collects the worker's messages in a queue, so that waiting for an answer
can stop at the deadline.

For now the worker is a plain subprocess (LocalSandbox), without any isolation: the
program can still read and write your files and use the network. Step 1.8 of the plan
adds the Docker sandbox.
"""

import queue
import subprocess
import sys
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping
from typing import IO, Any

from my_evolve.evaluation_api import ProgramFailure, StageTimeout
from my_evolve.sandbox_protocol import Message, receive, send, to_plain

# How long closing a session waits for the worker to end on its own, in seconds
CLOSE_WAIT_SECONDS = 5.0


class SandboxError(Exception):
    """The sandbox itself failed, not the program: the program's status is error."""


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
                # The program's own output is not kept yet (step 1.5).
                stderr=subprocess.DEVNULL,
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
        answer = self.exchange({"type": "load", "code": self.code})
        if answer["type"] == "load_failed":
            raise ProgramFailure(answer["error"], answer["traceback"])
        self.names = answer["names"]

    def exchange(self, message: Message) -> Message:
        """Send one message and return the worker's answer.

        Raises StageTimeout if the deadline passes first (the worker is then killed),
        ProgramFailure if the worker ends without answering.
        """
        assert self.process is not None and self.process.stdin is not None
        try:
            send(self.process.stdin, message)
        except OSError:
            # The worker has ended: its output tells how, below.
            pass
        try:
            answer = self.messages.get(timeout=max(0.0, self.deadline - time.monotonic()))
        except queue.Empty:
            self.timed_out = True
            self.kill()
            raise StageTimeout(
                f"the evaluation ran over its time limit of {self.stage_limit:g} s"
            ) from None
        if answer is None:
            exit_code = self.process.wait()
            raise ProgramFailure(f"the program's process ended (exit code {exit_code})")
        return answer

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
            "args": to_plain(list(args)),
            "kwargs": to_plain(dict(kwargs or {})),
        }
        return self.value_of(self.exchange(message))

    def get(self, name: str) -> Any:
        """Return the value of one of the program's plain-data globals."""
        self.last_id += 1
        return self.value_of(self.exchange({"type": "get", "id": self.last_id, "name": name}))

    def value_of(self, answer: Message) -> Any:
        """Return the value an answer carries. Raises ProgramFailure if it reports an error."""
        if answer["type"] == "raised":
            raise ProgramFailure(answer["error"], answer["traceback"])
        return answer["value"]

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
