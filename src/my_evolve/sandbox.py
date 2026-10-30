"""The sandbox: runs a program in a worker process of its own, and lets the host call its functions.

The evaluation file stays on the host. It receives a ProgramNamespace, which stands in
front of the worker: looking up a function gives a RemoteFunction, and calling that
sends a call message to the worker, which runs the program's function and sends back
its value. So the program chooses what its functions return, but never runs in the
same process as the code that computes its score.

A session has a deadline: past it, the worker is killed and StageTimeout raised. A
reader thread collects the worker's messages in a queue, so that waiting for an answer
can stop at the deadline. What the program prints is read by a thread of its own, which
keeps only its end, added to every failure: a program printing without end costs neither
memory nor disk. A message the host is not waiting for is ignored.

Two sandboxes start workers:
- DockerSandbox, the default: a fresh container for each session, without network, with
  a read-only file system except /tmp, and limited memory, CPUs and processes;
- LocalSandbox: a plain subprocess without any isolation, for the tests and trusted code
  only (--unsafe-local-sandbox).
"""

import hashlib
import math
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import IO, Any

from my_evolve.evaluation_api import CallTimeout, ProgramFailure, StageTimeout
from my_evolve.problem import SandboxSettings
from my_evolve.sandbox_protocol import Message, NotPlainData, decode, encode, receive, send

# How long closing a session waits for the worker to end on its own, in seconds
CLOSE_WAIT_SECONDS = 5.0
# How much of the end of the program's output a failure keeps, in characters
ERROR_TAIL_CHARS = 2000
# How much of the program's output is kept, in bytes: four at most per character in UTF-8
OUTPUT_KEPT_BYTES = 4 * ERROR_TAIL_CHARS
# How many bytes the output's reader takes at a time
OUTPUT_CHUNK_BYTES = 65536
# Before the output's end is read, how long its reader must have been waiting for more,
# with nothing left to read, in seconds; and how long to wait for that at most (a program
# printing without pause never lets its reader wait)
OUTPUT_SETTLE_SECONDS = 0.02
OUTPUT_SETTLE_LIMIT_SECONDS = 0.5
# The exit codes of a process killed by SIGKILL, which is what running out of memory
# usually brings: in Docker, and as a plain subprocess
KILLED_EXIT_CODES = (137, -9)

# The image definition the Docker sandbox builds from, and the name of its images
DOCKERFILE_PATH = Path(__file__).parent / "evaluation.Dockerfile"
IMAGE_NAME = "my-evolve-evaluation"
# How much of a failed docker command's output an error message keeps, in characters
DOCKER_ERROR_CHARS = 2000
# The label every container of a run carries, with the run's id as its value
RUN_LABEL = "my-evolve.run"
# How much longer than its stage a worker may live in its container, in seconds: it then
# stops on its own, even if the host process that started it died
CONTAINER_GRACE_SECONDS = 10
# The exit codes of `docker run` itself failing before the worker started: the daemon
# refused (125), or the command could not be run (126, 127)
DOCKER_RUN_EXIT_CODES = (125, 126, 127)
# The variables that limit the threads of numeric libraries (numpy, scipy)
THREAD_VARIABLES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)


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


def apart_from_the_terminal() -> dict[str, Any]:
    """Return the Popen options that start a worker in a process group of its own.

    Ctrl+C in a terminal interrupts every process of the terminal's foreground group: a
    worker left in it would raise KeyboardInterrupt in the program it is evaluating, and
    the program would be recorded as failed, though only my-evolve was meant to stop.
    """
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def read_messages(stream: IO[str], messages: "queue.Queue[Message | None]") -> None:
    """Put every message the worker sends in the queue, then None when its output ends.

    Runs in the session's reader thread. A line that is not a message is skipped.
    """
    while True:
        try:
            message = receive(stream)
        except ValueError:
            if stream.closed:
                message = None
            else:
                continue
        except (OSError, UnicodeDecodeError):
            message = None
        messages.put(message)
        if message is None:
            return


class OutputTail:
    """The end of what a session's workers printed, read by a thread of its own.

    Only the last OUTPUT_KEPT_BYTES are kept, however much the program prints. The
    worker writes its output before the answer that follows it, so once the reader has
    caught up with the pipe (it waits for more), the end includes everything printed
    before that answer.
    """

    def __init__(self) -> None:
        # The end of the output, as bytes
        self.data: bytearray = bytearray()
        self.lock: threading.Lock = threading.Lock()
        # The thread reading the current worker's output
        self.reader: threading.Thread | None = None
        # Since when the reader has been waiting for more output (time.monotonic); None
        # while it is busy
        self.waiting_since: float | None = None

    def follow(self, stream: IO[Any]) -> None:
        """Start reading a new worker's output; it ends when the stream does."""
        self.reader = threading.Thread(target=self.read_all, args=(stream,), daemon=True)
        self.reader.start()

    def read_all(self, stream: IO[Any]) -> None:
        """Read the stream to its end, keeping its last bytes. Runs in the reader thread."""
        descriptor = stream.fileno()
        while True:
            self.waiting_since = time.monotonic()
            try:
                chunk = os.read(descriptor, OUTPUT_CHUNK_BYTES)
            except OSError:
                chunk = b""
            self.waiting_since = None
            if not chunk:
                return
            with self.lock:
                self.data += chunk
                del self.data[: max(0, len(self.data) - OUTPUT_KEPT_BYTES)]

    def settle(self) -> None:
        """Wait, briefly, until the reader has read everything printed so far."""
        limit = time.monotonic() + OUTPUT_SETTLE_LIMIT_SECONDS
        while time.monotonic() < limit and self.reader is not None and self.reader.is_alive():
            since = self.waiting_since
            if since is not None and time.monotonic() - since >= OUTPUT_SETTLE_SECONDS:
                return
            time.sleep(OUTPUT_SETTLE_SECONDS / 4)

    def text(self) -> str:
        """Return the end of the output, at most ERROR_TAIL_CHARS characters."""
        self.settle()
        with self.lock:
            text = self.data.decode("utf-8", errors="replace")
        return text[-ERROR_TAIL_CHARS:]

    def finish(self, timeout: float) -> None:
        """Wait for the reader of a worker that has ended to read the rest of its output."""
        if self.reader is not None:
            self.reader.join(timeout)


class SandboxSession:
    """One loaded program, in one worker process at a time, until the stage's deadline.

    A call that runs over its own time limit kills the worker; the next call starts a
    fresh one, with the program loaded again (D8). The same happens after the worker dies.
    """

    def __init__(self, sandbox: "Sandbox", code: str, stage_limit: float) -> None:
        """Prepare a session; restart() starts its first worker and loads the program."""
        # Starts the workers, and stops them
        self.sandbox: Sandbox = sandbox
        # The program's code
        self.code: str = code
        # How long the session may last, in seconds, loading included
        self.stage_limit: float = stage_limit
        # When the session must end (time.monotonic)
        self.deadline: float = time.monotonic() + stage_limit
        # The current worker's name (its container's, in Docker)
        self.name: str = ""
        # The current worker process
        self.process: subprocess.Popen[str] | None = None
        # The thread collecting the current worker's messages
        self.reader: threading.Thread | None = None
        # The current worker's messages; None when its output ended
        self.messages: queue.Queue[Message | None] = queue.Queue()
        # The program's top-level names, each "function", "data" or "other"
        self.names: dict[str, str] = {}
        # The id of the last call or get message sent
        self.last_id: int = 0
        # True while a worker holds the loaded program and can answer
        self.alive: bool = False
        # True once a worker was killed because the deadline passed
        self.timed_out: bool = False
        # The end of the program's output (what it prints, and Python's own messages)
        self.output: OutputTail = OutputTail()

    def restart(self) -> None:
        """Start a fresh worker and load the program into it, ending any worker still running.

        Raises ProgramFailure if the program fails to load, StageTimeout if the deadline
        passes first, SandboxError if the worker cannot be started.
        """
        self.kill()
        self.release()
        if time.monotonic() >= self.deadline:
            self.timed_out = True
            raise StageTimeout(f"the stage ran over its time limit of {self.stage_limit:g} s")
        self.name = f"my-evolve-{uuid.uuid4().hex[:12]}"
        try:
            self.process = subprocess.Popen(
                self.sandbox.command(self.name, self.stage_limit),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=self.sandbox.environment(),
                **apart_from_the_terminal(),
            )
        except OSError as error:
            raise SandboxError(f"cannot start the worker: {error}") from error
        assert self.process.stdout is not None and self.process.stderr is not None
        self.output.follow(self.process.stderr)
        self.messages = queue.Queue()
        self.reader = threading.Thread(
            target=read_messages, args=(self.process.stdout, self.messages), daemon=True
        )
        self.reader.start()
        try:
            answer = self.exchange({"type": "load", "code": self.code}, {"loaded", "load_failed"})
        except ProgramFailure:
            if self.process.returncode in self.sandbox.startup_exit_codes():
                raise SandboxError(
                    f"the worker could not start (exit code {self.process.returncode}): "
                    f"{self.error_tail().strip()}"
                ) from None
            raise
        if answer["type"] == "load_failed":
            raise self.failure(answer["error"], answer["traceback"])
        self.names = answer["names"]
        self.alive = True

    def exchange(
        self, message: Message, expected: set[str], timeout: float | None = None
    ) -> Message:
        """Send one message and return the worker's answer: the next message of an expected
        type that carries the message's id.

        Any other message is ignored: a program writing forged answers gains nothing.
        timeout, if given, is the call's own limit in seconds. Raises CallTimeout if that
        limit passes first, StageTimeout if the stage's deadline does (the worker is
        killed either way), ProgramFailure if the worker ends without answering.
        """
        assert self.process is not None and self.process.stdin is not None
        try:
            send(self.process.stdin, message)
        except OSError:
            # The worker has ended: its output tells how, below.
            pass
        own_limit = time.monotonic() + timeout if timeout is not None else None
        call_deadline = min(self.deadline, own_limit) if own_limit is not None else self.deadline
        while True:
            try:
                answer = self.messages.get(timeout=max(0.0, call_deadline - time.monotonic()))
            except queue.Empty:
                self.kill()
                if own_limit is not None and own_limit < self.deadline:
                    raise CallTimeout(
                        f"{message.get('name')}() ran over its time limit of {timeout:g} s"
                    ) from None
                self.timed_out = True
                raise StageTimeout(
                    f"the stage ran over its time limit of {self.stage_limit:g} s"
                ) from None
            if answer is None:
                self.alive = False
                exit_code = self.process.wait()
                self.output.finish(CLOSE_WAIT_SECONDS)
                raise self.failure(describe_exit(exit_code))
            if answer.get("type") in expected and answer.get("id") == message.get("id"):
                return answer

    def failure(self, error: str, traceback: str = "") -> ProgramFailure:
        """Return the ProgramFailure to raise, with the end of the program's output."""
        return ProgramFailure(error, traceback, self.error_tail())

    def error_tail(self) -> str:
        """Return the end of what the program printed so far."""
        return self.output.text()

    def call(
        self,
        name: str,
        args: tuple[Any, ...] = (),
        kwargs: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Call one of the program's functions in the worker, and return its value.

        timeout, if given, is the call's own limit in seconds. A worker killed by an
        earlier call is replaced first. Raises ProgramFailure if the function raises or
        the worker ends, CallTimeout or StageTimeout if a limit passes.
        """
        if not self.alive:
            self.restart()
        self.last_id += 1
        message = {
            "type": "call",
            "id": self.last_id,
            "name": name,
            "args": encode(list(args)),
            "kwargs": encode(dict(kwargs or {})),
        }
        return self.value_of(self.exchange(message, {"return", "raised"}, timeout))

    def get(self, name: str) -> Any:
        """Return the value of one of the program's plain-data globals."""
        if not self.alive:
            self.restart()
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
        """Stop the current worker at once, if it is still running."""
        self.alive = False
        if self.process is not None and self.process.poll() is None:
            self.sandbox.stop(self.name)
            self.process.kill()
            self.process.wait()

    def release(self) -> None:
        """Close the pipes of a worker that has ended, once its reader thread is done."""
        if self.process is None:
            return
        if self.process.stdin:
            try:
                self.process.stdin.close()
            except OSError:
                pass
        if self.reader is not None:
            self.reader.join(timeout=CLOSE_WAIT_SECONDS)
        self.output.finish(CLOSE_WAIT_SECONDS)
        for stream in (self.process.stdout, self.process.stderr):
            if stream:
                stream.close()

    def close(self) -> None:
        """End the session: close the worker's input, so that it stops, and kill it if it
        does not; then release everything the session holds."""
        if self.process is not None:
            if self.process.stdin:
                try:
                    self.process.stdin.close()
                except OSError:
                    pass
            try:
                self.process.wait(timeout=CLOSE_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
                self.kill()
            self.release()
        self.alive = False


class RemoteFunction:
    """Stands for one of the program's functions: calling it runs the function in the worker."""

    def __init__(self, session: SandboxSession, name: str, timeout: float | None = None) -> None:
        self.session: SandboxSession = session
        self.name: str = name
        # The call's own time limit, in seconds; None for the stage's alone
        self.timeout: float | None = timeout

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Call the program's function with these arguments (plain data) and return its value."""
        return self.session.call(self.name, args, kwargs, self.timeout)

    def with_timeout(self, seconds: float) -> "RemoteFunction":
        """Return the same function, whose calls are limited to that many seconds each.

        A call over the limit raises CallTimeout, and the next call starts a fresh worker.
        """
        return RemoteFunction(self.session, self.name, seconds)

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


def thread_variables(cpus: float) -> dict[str, str]:
    """Return the variables that limit numeric libraries to as many threads as there are CPUs."""
    threads = str(max(1, math.floor(cpus)))
    return {name: threads for name in THREAD_VARIABLES}


class Sandbox(ABC):
    """Starts sessions: one worker process per program evaluated."""

    @abstractmethod
    def command(self, name: str, stage_limit: float) -> list[str]:
        """Return the command that starts a worker; name identifies it (a container's name)."""

    def environment(self) -> dict[str, str] | None:
        """Return the worker process's environment variables; None for this process's own."""
        return None

    def image_name(self) -> str:
        """Return the image programs run in: its tag, or "none" without one (D50)."""
        return "none"

    def stop(self, name: str) -> None:  # noqa: B027 - most sandboxes have nothing to stop
        """Stop what runs the worker besides its process, such as its container."""

    def startup_exit_codes(self) -> tuple[int, ...]:
        """Return the exit codes meaning the worker could not start: not the program's fault."""
        return ()

    def remove_leftovers(self) -> None:  # noqa: B027 - most sandboxes leave nothing behind
        """Remove whatever the run's workers left behind, such as containers still running."""

    def start(self, code: str, stage_limit: float) -> SandboxSession:
        """Start a worker, load the program into it, and give it stage_limit seconds in all.

        The caller must close the session. Raises ProgramFailure if the program fails to
        load, StageTimeout if loading takes too long, SandboxError if the sandbox fails.
        """
        session = SandboxSession(self, code, stage_limit)
        try:
            session.restart()
        except BaseException:
            session.close()
            raise
        return session


class LocalSandbox(Sandbox):
    """Runs the worker as a plain subprocess, with this Python: no isolation at all.

    The program can read and write your files, use the network, and read every
    environment variable, API keys included. For the tests and trusted code only.
    """

    def __init__(self, cpus: float = 1.0) -> None:
        # How many threads numeric libraries may use
        self.cpus: float = cpus

    def command(self, name: str, stage_limit: float) -> list[str]:
        """Return the command that starts a worker with this Python."""
        return [sys.executable, "-m", "my_evolve.sandbox_worker"]

    def environment(self) -> dict[str, str]:
        """Return this process's environment, with the numeric libraries' threads limited."""
        return {**os.environ, **thread_variables(self.cpus)}


class DockerSandbox(Sandbox):
    """Runs each worker in a fresh Docker container, isolated from the host (D41).

    The container has no network; its file system is read-only except a temporary
    /tmp; its memory (without swap), CPUs and processes are limited; it runs as the
    user nobody, without any capability; it sees no environment variable of the host.
    The my_evolve package is mounted read-only: the worker needs nothing else.

    No container outlives the run (D42): each is labelled with the run's id, so that
    remove_leftovers finds them, and its worker runs under a time limit of its own, a
    little longer than the stage's, so that it stops even if this process dies.
    """

    def __init__(self, image: str, settings: SandboxSettings, run_id: str) -> None:
        """Prepare to run workers in containers of image (see ensure_image) for one run."""
        # The evaluation image, with the problem's packages
        self.image: str = image
        # The containers' limits
        self.settings: SandboxSettings = settings
        # The run's id, the value of every container's label
        self.run_id: str = run_id

    def image_name(self) -> str:
        """Return the evaluation image's tag, a hash of its Dockerfile and packages."""
        return self.image

    def command(self, name: str, stage_limit: float) -> list[str]:
        """Return the docker run command of a worker in a new container called name."""
        package_folder = Path(__file__).resolve().parent
        memory = self.settings.memory
        environment = [
            option
            for variable, value in thread_variables(self.settings.cpus).items()
            for option in ("--env", f"{variable}={value}")
        ]
        return [
            "docker", "run", "--rm", "--interactive",
            # A signal the docker client receives is not passed on to the container.
            "--sig-proxy=false",
            "--name", name,
            "--label", f"{RUN_LABEL}={self.run_id}",
            "--network", "none",
            "--read-only",
            "--tmpfs", "/tmp",
            "--memory", memory,
            "--memory-swap", memory,
            "--cpus", f"{self.settings.cpus:g}",
            "--pids-limit", str(self.settings.max_processes),
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--user", "65534:65534",
            *environment,
            "--mount", f"type=bind,source={package_folder},target=/app/my_evolve,readonly",
            self.image,
            "timeout", "--signal=KILL", f"{math.ceil(stage_limit) + CONTAINER_GRACE_SECONDS}",
            "python", "-m", "my_evolve.sandbox_worker",
        ]  # fmt: skip

    def stop(self, name: str) -> None:
        """Kill the container: killing the docker client alone would leave it running."""
        run_docker(["kill", name], timeout=30)

    def startup_exit_codes(self) -> tuple[int, ...]:
        """Return the exit codes of docker run failing before the worker started."""
        return DOCKER_RUN_EXIT_CODES

    def remove_leftovers(self) -> None:
        """Remove every container labelled with this run's id, running or not.

        Called when the run starts and when it stops, so that nothing outlives it.
        """
        listed = run_docker(
            ["ps", "--all", "--quiet", "--filter", f"label={RUN_LABEL}={self.run_id}"], timeout=60
        )
        containers = listed.stdout.split()
        if containers:
            run_docker(["rm", "--force", *containers], timeout=60)


def run_docker(
    arguments: Sequence[str], timeout: float | None = None
) -> "subprocess.CompletedProcess[str]":
    """Run a docker command and return how it went. Raises SandboxError if Docker is missing."""
    if shutil.which("docker") is None:
        raise SandboxError("Docker is not installed")
    try:
        return subprocess.run(
            ["docker", *arguments], capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SandboxError(f"docker {arguments[0]} failed: {error}") from error


def image_tag(packages: Sequence[str]) -> str:
    """Return the evaluation image's name and tag: a hash of the Dockerfile and the packages.

    Changing either changes the tag, so that the image is rebuilt.
    """
    content = DOCKERFILE_PATH.read_bytes() + "\n".join(packages).encode("utf-8")
    return f"{IMAGE_NAME}:{hashlib.sha256(content).hexdigest()[:12]}"


def ensure_image(packages: Sequence[str]) -> str:
    """Build the evaluation image with these packages unless it exists; return its tag.

    The build sees a folder holding only the Dockerfile and the package list. Raises
    SandboxError if Docker is missing or stopped, or if the build fails.
    """
    tag = image_tag(packages)
    if run_docker(["image", "inspect", tag]).returncode == 0:
        return tag
    info = run_docker(["info"])
    if info.returncode != 0:
        raise SandboxError(f"Docker is not running: {info.stderr.strip()[-DOCKER_ERROR_CHARS:]}")
    with tempfile.TemporaryDirectory() as folder:
        shutil.copyfile(DOCKERFILE_PATH, Path(folder) / "Dockerfile")
        requirements = "".join(f"{package}\n" for package in packages)
        (Path(folder) / "requirements.txt").write_text(requirements, encoding="utf-8")
        build = run_docker(["build", "--tag", tag, folder])
    if build.returncode != 0:
        output = (build.stdout + build.stderr).strip()[-DOCKER_ERROR_CHARS:]
        raise SandboxError(f"building the image {tag} failed:\n{output}")
    return tag
