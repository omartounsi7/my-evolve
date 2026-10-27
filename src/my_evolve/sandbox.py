"""The sandboxes programs run in, and the namespace the evaluator sees them through (D8, D64).

A sandbox starts one session per cascade stage. A session is one worker process
(sandbox_worker) holding one loaded program; the evaluator, which stays on the
host, reaches the program only through a ProgramNamespace: looking a function up
gives a RemoteFunction, and calling it runs the program's function in the worker
and returns its value as plain data.

Time limits: the whole stage has one (D41); a call may have its own as well. A call
over its own limit raises CallTimeout and the worker is killed; the next call
starts a fresh worker with the program loaded again. When the stage's time is up,
StageTimeout.

Two sandboxes exist: LocalSandbox, a plain subprocess without any isolation, for
the tests and trusted code (--unsafe-local-sandbox, D40); and the Docker sandbox,
the default.
"""

import hashlib
import logging
import math
import os
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import IO, Any

from my_evolve.evaluation_api import CallTimeout, ProgramFailure, StageTimeout
from my_evolve.problem import SandboxSettings
from my_evolve.sandbox_protocol import (
    DATA,
    FUNCTION,
    NotPlainData,
    ProtocolError,
    decode,
    encode,
    receive,
    send,
)

logger = logging.getLogger(__name__)

# The environment variables that set how many threads numeric libraries use (D41).
THREAD_VARIABLES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)

# The host's environment variables a local worker keeps: what Python needs to run.
# Everything else, API keys included, stays out.
LOCAL_ENVIRONMENT_VARIABLES = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "TEMP",
    "TMP",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "USERPROFILE",
)

# The folder holding the my_evolve package, from which a local worker imports it.
PACKAGE_PARENT = Path(__file__).resolve().parent.parent

# How much of the end of the program's error output is kept, in characters (D10).
ERROR_TAIL_CHARS = 4000

# How long to wait for a killed process to end, in seconds.
KILL_WAIT_SECONDS = 10

# Exit codes of a process killed by the system, which Docker (137) and the Linux
# memory limit (-9: killed by signal 9) give a program using too much memory.
KILLED_EXIT_CODES = (137, -9)

# What the reader thread puts in the queue when the worker's output ends.
END = object()


class SandboxError(Exception):
    """The sandbox itself failed (Docker missing, a process that cannot start); not the
    program's fault, so the program gets the status error (D7)."""


def describe_end(exit_code: int | None) -> str:
    """Explain why a worker ended without answering."""
    if exit_code in KILLED_EXIT_CODES:
        return "the program was stopped, most likely for using too much memory"
    return f"the program's process ended without answering (exit code {exit_code})"


def read_messages(stream: IO[str], messages: "queue.Queue[Any]") -> None:
    """Put every message the worker writes into the queue, then END. Runs in its own thread.

    Lines that are not messages are skipped: a program may write to the protocol's
    stream, but gains nothing from it (D77).
    """
    try:
        while True:
            try:
                message = receive(stream)
            except ProtocolError:
                continue
            if message is None:
                break
            messages.put(message)
    except (OSError, ValueError):
        # The stream was closed while reading: the session is being killed.
        pass
    finally:
        messages.put(END)


class SandboxSession:
    """One worker process holding one loaded program, for one cascade stage."""

    def __init__(self, sandbox: "Sandbox", code: str, stage_limit: float) -> None:
        """Prepare a session; nothing runs until restart()."""
        self.sandbox: Sandbox = sandbox
        # The program's code, loaded again each time the worker restarts.
        self.code: str = code
        # The stage's time limit, in seconds, and the moment it runs out.
        self.stage_limit: float = stage_limit
        self.deadline: float = time.monotonic() + stage_limit
        # A name for the worker, unique in the run (a container's name, for Docker).
        self.name: str = sandbox.new_session_name()
        # A folder of the session's own: the program's working folder and its error output.
        self.folder: Path = Path(tempfile.mkdtemp(prefix="my-evolve-session-"))
        self.work_folder: Path = self.folder / "work"
        self.work_folder.mkdir()
        # The program's error output, from every worker of the session in turn.
        # Opened in append mode, so each write goes to the end whoever reads the file.
        self.stderr_path: Path = self.folder / "error_output.txt"
        self.stderr_file: IO[bytes] = open(self.stderr_path, "ab")
        # The worker, the thread reading its messages, and those messages.
        self.process: subprocess.Popen[str] | None = None
        self.reader: threading.Thread | None = None
        self.messages: queue.Queue[Any] = queue.Queue()
        # The program's top-level names and their kinds, from its loaded message.
        self.names: dict[str, str] = {}
        # Whether a worker is running with the program loaded.
        self.alive: bool = False
        # The id of the latest request; answers with another id are ignored.
        self.last_id: int = 0
        # Calls from several threads of an evaluator take turns.
        self.lock: threading.Lock = threading.Lock()

    def __enter__(self) -> "SandboxSession":
        return self

    def __exit__(self, *exception_details: object) -> None:
        self.close()

    def stage_time_left(self) -> float:
        """Return the seconds left before the stage's time limit runs out."""
        return self.deadline - time.monotonic()

    def stage_timeout(self, during: str) -> StageTimeout:
        """Kill the worker and return the error saying the stage's time is up."""
        self.kill()
        return StageTimeout(f"the stage ran out of time ({self.stage_limit:g} s) while {during}")

    def restart(self) -> None:
        """Start a fresh worker and load the program into it.

        Raises SandboxError if the worker cannot start, ProgramFailure if the program
        fails to load, and StageTimeout if the stage's time runs out first.
        """
        self.kill()
        self.messages = queue.Queue()
        try:
            self.process = self.sandbox.spawn(self)
        except OSError as error:
            raise SandboxError(f"cannot start the program's process: {error}") from error
        assert self.process.stdout is not None
        self.reader = threading.Thread(
            target=read_messages, args=(self.process.stdout, self.messages), daemon=True
        )
        self.reader.start()

        self.send({"type": "load", "code": self.code})
        answer = self.wait(lambda message: message["type"] in ("loaded", "load_failed"))
        if answer is None:
            raise self.stage_timeout("the program was loading")
        if answer is END:
            raise self.ended()
        if answer["type"] == "load_failed":
            self.kill()
            raise ProgramFailure(
                str(answer.get("error")), answer.get("traceback"), self.error_tail()
            )
        names = answer.get("names")
        if not isinstance(names, dict):
            self.kill()
            raise ProgramFailure("the program's worker sent no list of names")
        self.names = {str(name): str(kind) for name, kind in names.items()}
        self.alive = True

    def send(self, message: dict[str, Any]) -> None:
        """Send one message to the worker; if it has ended, its end shows when waiting."""
        if self.process is None or self.process.stdin is None:
            return
        try:
            send(self.process.stdin, message)
        except (OSError, ValueError):
            pass

    def wait(self, matches: Callable[[dict[str, Any]], bool], until: float | None = None) -> Any:
        """Return the first message that matches, END if the worker ended, or None at until.

        until is a time.monotonic() moment; by default the stage's deadline. Other
        messages are dropped.
        """
        until = self.deadline if until is None else until
        while True:
            remaining = until - time.monotonic()
            if remaining <= 0:
                return None
            try:
                item = self.messages.get(timeout=remaining)
            except queue.Empty:
                return None
            if item is END or matches(item):
                return item

    def ended(self) -> ProgramFailure | SandboxError:
        """Return the error for a worker that ended without answering; the session is dead.

        Usually the program's fault (ProgramFailure); a SandboxError if the sandbox
        finds that it failed itself, for example Docker no longer running.
        """
        exit_code: int | None = None
        if self.process is not None:
            try:
                exit_code = self.process.wait(timeout=KILL_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
                pass
        self.kill()
        error_output = self.error_tail()
        sandbox_failure = self.sandbox.infrastructure_failure(exit_code)
        if sandbox_failure is not None:
            return SandboxError(f"{sandbox_failure}: {error_output.strip()[-500:]}")
        return ProgramFailure(describe_end(exit_code), error_output=error_output)

    def request(self, message: dict[str, Any], what: str, timeout: float | None) -> Any:
        """Send a call or get message and return the decoded value of its answer."""
        with self.lock:
            if self.stage_time_left() <= 0:
                raise self.stage_timeout(f"calling {what}")
            if not self.alive:
                self.restart()
            self.last_id += 1
            request_id = self.last_id
            started = time.monotonic()
            call_end = started + timeout if timeout is not None else math.inf
            until = min(call_end, self.deadline)

            self.send({**message, "id": request_id})
            answer = self.wait(
                lambda reply: (
                    reply.get("id") == request_id and reply["type"] in ("return", "raised")
                ),
                until,
            )
            if answer is None:
                if call_end <= self.deadline:
                    self.kill()
                    raise CallTimeout(f"{what} ran over its time limit of {timeout:g} s")
                raise self.stage_timeout(f"{what} was running")
            if answer is END:
                raise self.ended()
            if answer["type"] == "raised":
                raise ProgramFailure(
                    str(answer.get("error")), answer.get("traceback"), self.error_tail()
                )
            try:
                return decode(answer.get("value"))
            except (ProtocolError, NotPlainData, KeyError, TypeError, ValueError) as error:
                raise ProgramFailure(f"the program's answer could not be read: {error}") from None

    def call(
        self,
        name: str,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Call one of the program's functions and return its value.

        Raises NotPlainData if an argument cannot be sent (the evaluator's mistake),
        ProgramFailure if the program raised or its worker ended, CallTimeout if the
        call ran over timeout, and StageTimeout if the stage's time ran out.
        """
        # Encoded first: an argument that cannot be sent is the evaluator's mistake,
        # and must not cost the program a restart.
        message = {
            "type": "call",
            "name": name,
            "args": encode(list(args)),
            "kwargs": encode(dict(kwargs or {})),
        }
        return self.request(message, name, timeout)

    def get(self, name: str) -> Any:
        """Return the value of one of the program's plain-data globals."""
        return self.request({"type": "get", "name": name}, name, None)

    def kill(self) -> None:
        """Stop the worker, if one is running; the session is no longer alive."""
        process = self.process
        if process is not None:
            if process.poll() is None:
                try:
                    self.sandbox.stop(self)
                except OSError:
                    pass
                try:
                    process.wait(timeout=KILL_WAIT_SECONDS)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if self.reader is not None:
                self.reader.join(timeout=KILL_WAIT_SECONDS)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
        self.process = None
        self.reader = None
        self.alive = False

    def close(self) -> None:
        """Kill the worker and delete the session's folder."""
        self.kill()
        self.stderr_file.close()
        shutil.rmtree(self.folder, ignore_errors=True)
        self.sandbox.forget(self)

    def error_tail(self, max_chars: int = ERROR_TAIL_CHARS) -> str:
        """Return the end of what the program wrote to its error output (D10)."""
        try:
            with open(self.stderr_path, "rb") as error_file:
                error_file.seek(0, os.SEEK_END)
                size = error_file.tell()
                # 4 bytes per character at most in UTF-8.
                error_file.seek(max(0, size - 4 * max_chars))
                text = error_file.read().decode("utf-8", errors="replace")
        except OSError:
            return ""
        return text[-max_chars:]


class RemoteFunction:
    """One of the program's functions: calling it runs the function in the sandbox."""

    def __init__(self, session: SandboxSession, name: str, timeout: float | None = None) -> None:
        self.session: SandboxSession = session
        self.name: str = name
        # This call's own time limit, in seconds; None: only the stage's limit applies.
        self.timeout: float | None = timeout

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Run the program's function with these arguments and return its value."""
        return self.session.call(self.name, args, kwargs, self.timeout)

    def with_timeout(self, seconds: float) -> "RemoteFunction":
        """Return the same function with a time limit of its own (D8)."""
        if not seconds > 0:
            raise ValueError(f"a time limit must be above 0, got {seconds}")
        return RemoteFunction(self.session, self.name, seconds)

    def __repr__(self) -> str:
        return f"RemoteFunction({self.name!r})"


class ProgramNamespace:
    """What a stage function receives: the program's names, reached through its session.

    namespace["run_packing"] gives a RemoteFunction for a function and the value of
    a plain-data global; any other name, or a missing one, raises ProgramFailure, so
    that the program gets the status failed (D7).
    """

    def __init__(self, session: SandboxSession) -> None:
        self.session: SandboxSession = session

    def __getitem__(self, name: str) -> Any:
        kind = self.session.names.get(name)
        if kind is None:
            raise ProgramFailure(f"the program defines no name {name!r}")
        if kind == FUNCTION:
            return RemoteFunction(self.session, name)
        if kind == DATA:
            return self.session.get(name)
        raise ProgramFailure(f"{name} in the program is neither a function nor plain data")

    def get(self, name: str, default: Any = None) -> Any:
        """Return namespace[name] if the program defines name, otherwise default."""
        return self[name] if name in self else default

    def __contains__(self, name: object) -> bool:
        return name in self.session.names

    def __iter__(self) -> Iterator[str]:
        return iter(self.session.names)

    def __len__(self) -> int:
        return len(self.session.names)


class Sandbox(ABC):
    """Where programs run; each cascade stage gets a session of its own (D40, D64)."""

    def __init__(self) -> None:
        # The sessions started and not closed yet, from every worker thread.
        self.live_sessions: set[SandboxSession] = set()
        self.live_sessions_lock: threading.Lock = threading.Lock()

    def start(self, code: str, stage_limit: float) -> SandboxSession:
        """Start a session with the program loaded, for one stage of stage_limit seconds.

        Raises SandboxError, ProgramFailure or StageTimeout as restart() does.
        """
        session = SandboxSession(self, code, stage_limit)
        with self.live_sessions_lock:
            self.live_sessions.add(session)
        try:
            session.restart()
        except BaseException:
            session.close()
            raise
        return session

    def forget(self, session: SandboxSession) -> None:
        """Take a closed session off the live sessions."""
        with self.live_sessions_lock:
            self.live_sessions.discard(session)

    def kill_all(self) -> None:
        """Kill every live session's worker, then remove what is left (D54).

        For a run that stops at once: the evaluations in progress are lost.
        """
        with self.live_sessions_lock:
            sessions = list(self.live_sessions)
        for session in sessions:
            try:
                session.kill()
            except (OSError, ValueError, SandboxError):
                pass
        self.remove_leftovers()

    def new_session_name(self) -> str:
        """Return a name for a new worker, unique in the run."""
        return f"my-evolve-{uuid.uuid4().hex[:12]}"

    @abstractmethod
    def command(self, name: str, stage_limit: float) -> list[str]:
        """Return the command that starts a worker."""

    def environment(self) -> dict[str, str] | None:
        """Return the environment variables of the started command; None: the host's."""
        return None

    def popen_options(self) -> dict[str, Any]:
        """Return extra options for subprocess.Popen."""
        return {}

    def spawn(self, session: SandboxSession) -> "subprocess.Popen[str]":
        """Start a worker for a session; its error output goes to the session's file."""
        return subprocess.Popen(
            self.command(session.name, session.stage_limit),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=session.stderr_file,
            cwd=session.work_folder,
            env=self.environment(),
            text=True,
            encoding="utf-8",
            errors="replace",
            **self.popen_options(),
        )

    @abstractmethod
    def stop(self, session: SandboxSession) -> None:
        """Kill a session's worker and everything it started."""

    def infrastructure_failure(self, exit_code: int | None) -> str | None:
        """Say why the sandbox itself failed, if it did, when a worker ended with exit_code.

        None means the program is to blame.
        """
        return None

    @abstractmethod
    def remove_leftovers(self) -> None:
        """Remove the workers an earlier session of the run left behind (D42)."""


class LocalSandbox(Sandbox):
    """Runs the worker as a plain subprocess of the host, WITHOUT ANY ISOLATION.

    Only for the tests and for trusted code (--unsafe-local-sandbox, D40): the
    program can read and write the user's files and use the network. It does not
    see the host's environment variables, so API keys stay out of its reach.
    """

    def __init__(self, cpus: float = 1.0) -> None:
        super().__init__()
        # Numeric libraries use this many threads (D41).
        self.threads: int = max(1, int(cpus))

    def command(self, name: str, stage_limit: float) -> list[str]:
        """Return the command running the worker with this Python.

        -I keeps the worker away from the current folder and Python's environment
        variables; the package is imported from where this file lives.
        """
        start_worker = (
            "import runpy, sys; "
            f"sys.path.insert(0, {str(PACKAGE_PARENT)!r}); "
            "runpy.run_module('my_evolve.sandbox_worker', run_name='__main__')"
        )
        return [sys.executable, "-I", "-c", start_worker]

    def environment(self) -> dict[str, str]:
        """Return the few host variables Python needs, plus the thread counts."""
        environment = {
            name: os.environ[name] for name in LOCAL_ENVIRONMENT_VARIABLES if name in os.environ
        }
        environment.update({name: str(self.threads) for name in THREAD_VARIABLES})
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return environment

    def popen_options(self) -> dict[str, Any]:
        """On Linux and macOS, start the worker in a process group of its own.

        stop() can then kill everything the program started along with it.
        """
        return {"start_new_session": True} if sys.platform != "win32" else {}

    def stop(self, session: SandboxSession) -> None:
        """Kill the worker, with its whole process group on Linux and macOS."""
        process = session.process
        if process is None:
            return
        if sys.platform != "win32":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()

    def remove_leftovers(self) -> None:
        """Nothing to do: local workers carry no label to be found by (kill_all
        stops the running ones).

        A worker whose host died ends by itself once its current call returns, since
        its input is then closed; only a call that never returns would keep it alive.
        """


# ----------------------------------------------------------------------------------
# The Docker sandbox
# ----------------------------------------------------------------------------------

# The image definition, and the name of the images built from it (D71).
DOCKERFILE_PATH = Path(__file__).resolve().parent / "evaluation.Dockerfile"
IMAGE_NAME = "my-evolve-evaluation"
# The label every container of a run carries, with the run's id as value (D42).
RUN_LABEL = "my-evolve.run"
# Where the my_evolve package is mounted in the container (the image's PYTHONPATH is /app).
CONTAINER_PACKAGE_FOLDER = "/app/my_evolve"
# "nobody": a user without any rights.
NOBODY = "65534:65534"
# The worker's own time limit is this much longer than the stage's, so that a
# container stops by itself even if the host process dies (D42).
CONTAINER_TIME_MARGIN = 10.0
# How long a docker command (other than a build) may take, in seconds.
DOCKER_COMMAND_SECONDS = 60
# The exit codes of "docker run" when the container could not be run at all.
DOCKER_RUN_FAILURE_CODES = (125, 126, 127)


def docker_image_tag(packages: tuple[str, ...]) -> str:
    """Return the image's name, tagged with a hash of the Dockerfile and the package list.

    Changing either changes the tag, so the image is rebuilt (D71).
    """
    content = DOCKERFILE_PATH.read_bytes() + "\n".join(packages).encode("utf-8")
    return f"{IMAGE_NAME}:{hashlib.sha256(content).hexdigest()[:12]}"


def run_docker(
    arguments: list[str], timeout: float = DOCKER_COMMAND_SECONDS
) -> "subprocess.CompletedProcess[str]":
    """Run a docker command and return how it went; SandboxError if it cannot run at all."""
    try:
        return subprocess.run(
            ["docker", *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SandboxError(f"docker {arguments[0]} failed: {error}") from error


def check_docker() -> None:
    """Raise SandboxError unless Docker is installed and running."""
    if shutil.which("docker") is None:
        raise SandboxError("Docker is not installed.")
    if run_docker(["info"]).returncode != 0:
        raise SandboxError("Docker is not running: start it (Docker Desktop on Windows).")


class DockerSandbox(Sandbox):
    """Runs each worker in its own Docker container, removed when it stops (D40-D42).

    Inside, the program has no network, can write only in a temporary /tmp, runs as
    a user without rights, and is limited in memory (without swap), CPUs and
    processes. It sees the my_evolve package, read-only, and nothing of the host's
    files or environment variables.
    """

    def __init__(self, image: str, settings: SandboxSettings, run_id: str) -> None:
        """Prepare to start containers from image; nothing is checked or started yet."""
        super().__init__()
        # The image's tag, from ensure_image.
        self.image: str = image
        # The memory, CPU and process limits (D41).
        self.settings: SandboxSettings = settings
        # The run's id, the value of every container's label.
        self.run_id: str = run_id

    @staticmethod
    def ensure_image(packages: tuple[str, ...]) -> str:
        """Check Docker, build the evaluation image if it does not exist yet, and return its tag.

        The build sees only a folder holding the Dockerfile and the package list. It
        is the only moment with network access (D71). Raises SandboxError if Docker
        is missing or not running, or if the build fails.
        """
        check_docker()
        tag = docker_image_tag(packages)
        if run_docker(["image", "inspect", tag]).returncode == 0:
            return tag
        logger.info("Building the Docker image %s (only once)...", tag)
        with tempfile.TemporaryDirectory() as build_folder:
            shutil.copyfile(DOCKERFILE_PATH, Path(build_folder) / "Dockerfile")
            requirements = "".join(f"{package}\n" for package in packages)
            (Path(build_folder) / "requirements.txt").write_text(requirements, encoding="utf-8")
            # No time limit: downloading Python's image and the packages may be slow.
            try:
                build = subprocess.run(
                    ["docker", "build", "--tag", tag, build_folder],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
            except OSError as error:
                raise SandboxError(f"docker build failed: {error}") from error
        if build.returncode != 0:
            last_lines = "\n".join((build.stdout + build.stderr).strip().splitlines()[-15:])
            raise SandboxError(f"building the image {tag} failed:\n{last_lines}")
        return tag

    def new_session_name(self) -> str:
        """Return a container name, starting with the run's id so it is easy to recognise."""
        return f"my-evolve-{self.run_id[:8]}-{uuid.uuid4().hex[:12]}"

    def command(self, name: str, stage_limit: float) -> list[str]:
        """Return the docker run command of one worker (D41, D42)."""
        threads = str(max(1, int(self.settings.cpus)))
        thread_options = [
            option for variable in THREAD_VARIABLES for option in ("--env", f"{variable}={threads}")
        ]
        package_folder = Path(__file__).resolve().parent
        package_mount = f"type=bind,source={package_folder},target={CONTAINER_PACKAGE_FOLDER}"
        return [
            "docker", "run", "--rm", "--interactive",
            "--name", name,
            "--label", f"{RUN_LABEL}={self.run_id}",
            "--network", "none",
            "--read-only",
            "--tmpfs", "/tmp",
            "--memory", self.settings.memory,
            "--memory-swap", self.settings.memory,
            "--cpus", f"{self.settings.cpus:g}",
            "--pids-limit", str(self.settings.max_processes),
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--user", NOBODY,
            *thread_options,
            "--mount", f"{package_mount},readonly",
            self.image,
            "timeout", "--signal=KILL", f"{stage_limit + CONTAINER_TIME_MARGIN:g}",
            "python", "-m", "my_evolve.sandbox_worker",
        ]  # fmt: skip

    def stop(self, session: SandboxSession) -> None:
        """Kill the session's container, which takes every process inside with it.

        A container still being created cannot be killed yet: it is removed instead.
        The docker client process is killed last.
        """
        try:
            if run_docker(["kill", session.name]).returncode != 0:
                run_docker(["rm", "--force", session.name])
        except SandboxError as error:
            logger.warning("Could not stop the container %s: %s", session.name, error)
        if session.process is not None:
            session.process.kill()

    def infrastructure_failure(self, exit_code: int | None) -> str | None:
        """Tell Docker's failures apart from the program's when a container ends early.

        docker run exits with 125 to 127 when the container could not run at all. A
        program may exit with the same codes, so Docker itself is checked: only if it
        stopped running, or the image is gone, is the sandbox to blame.
        """
        if exit_code not in DOCKER_RUN_FAILURE_CODES:
            return None
        try:
            if run_docker(["info"]).returncode != 0:
                return "Docker stopped running"
            if run_docker(["image", "inspect", self.image]).returncode != 0:
                return f"the image {self.image} no longer exists"
        except SandboxError as error:
            return str(error)
        return None

    def remove_leftovers(self) -> None:
        """Remove every container labelled with the run's id, running or not (D42)."""
        listing = run_docker(
            ["ps", "--all", "--quiet", "--filter", f"label={RUN_LABEL}={self.run_id}"]
        )
        container_ids = listing.stdout.split()
        if container_ids:
            run_docker(["rm", "--force", *container_ids])
