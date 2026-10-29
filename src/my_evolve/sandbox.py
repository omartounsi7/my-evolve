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
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import IO, Any

from my_evolve.evaluation_api import ProgramFailure, StageTimeout
from my_evolve.problem import SandboxSettings
from my_evolve.sandbox_protocol import Message, NotPlainData, decode, encode, receive, send

# How long closing a session waits for the worker to end on its own, in seconds
CLOSE_WAIT_SECONDS = 5.0
# How much of the end of the program's output a failure keeps, in characters
ERROR_TAIL_CHARS = 2000
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

    def __init__(
        self,
        command: list[str],
        code: str,
        stage_limit: float,
        environment: dict[str, str] | None = None,
        stop: Callable[[], None] | None = None,
        startup_exit_codes: tuple[int, ...] = (),
    ) -> None:
        """Prepare a session; start() starts the worker and loads the program.

        environment is the worker's environment variables (None: this process's own);
        stop stops what runs the worker besides its process (a container); a worker
        ending with one of startup_exit_codes before loading means the sandbox failed.
        """
        # How to start the worker
        self.command: list[str] = command
        # The worker's environment variables; None for this process's own
        self.environment: dict[str, str] | None = environment
        # Stops what runs the worker besides its process, such as its container
        self.stop: Callable[[], None] | None = stop
        # Exit codes meaning the worker could not start: the sandbox's fault, not the program's
        self.startup_exit_codes: tuple[int, ...] = startup_exit_codes
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
                env=self.environment,
            )
        except OSError as error:
            raise SandboxError(f"cannot start the worker: {error}") from error
        assert self.process.stdout is not None
        reader = threading.Thread(
            target=read_messages, args=(self.process.stdout, self.messages), daemon=True
        )
        reader.start()
        try:
            answer = self.exchange({"type": "load", "code": self.code}, {"loaded", "load_failed"})
        except ProgramFailure:
            if self.process.returncode in self.startup_exit_codes:
                raise SandboxError(
                    f"the worker could not start (exit code {self.process.returncode}): "
                    f"{self.error_tail().strip()}"
                ) from None
            raise
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
                    f"the stage ran over its time limit of {self.stage_limit:g} s"
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
            if self.stop is not None:
                self.stop()
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
        name = f"my-evolve-{uuid.uuid4().hex[:12]}"
        session = SandboxSession(
            self.command(name, stage_limit),
            code,
            stage_limit,
            environment=self.environment(),
            stop=lambda: self.stop(name),
            startup_exit_codes=self.startup_exit_codes(),
        )
        try:
            session.start()
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
