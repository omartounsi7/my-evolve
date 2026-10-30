"""Checks the Docker sandbox: its image, and the isolation of its containers.

Skipped when Docker is not installed or not running.
"""

import os
import sys
import time
import unittest
import uuid
from pathlib import Path

from docker_check import docker_is_available
from test_sandbox import POOL_PROGRAM, POOL_TOTAL, interrupt_the_group

from my_evolve.evaluation_api import ProgramFailure, StageTimeout
from my_evolve.evaluator import Evaluator
from my_evolve.problem import Problem, SandboxSettings
from my_evolve.program import Status
from my_evolve.sandbox import (
    DockerSandbox,
    SandboxError,
    SandboxSession,
    ensure_image,
    image_tag,
    run_docker,
)
from my_evolve.sandbox_protocol import send

REPOSITORY_FOLDER = Path(__file__).parent.parent
CIRCLE_PACKING_FOLDER = REPOSITORY_FOLDER / "examples" / "circle_packing"
TOY_FOLDER = Path(__file__).parent / "toy"


class ImageTagTest(unittest.TestCase):
    def test_the_tag_changes_with_the_packages(self) -> None:
        """A different package list means a different image."""
        self.assertTrue(image_tag([]).startswith("my-evolve-evaluation:"))
        self.assertEqual(image_tag(["numpy==2.5.4"]), image_tag(["numpy==2.5.4"]))
        self.assertNotEqual(image_tag(["numpy==2.5.4"]), image_tag(["numpy==2.5.3"]))
        self.assertNotEqual(image_tag([]), image_tag(["numpy==2.5.4"]))


@unittest.skipUnless(docker_is_available(), "Docker is not available")
class ImageTest(unittest.TestCase):
    def test_the_image_is_built_once_then_reused(self) -> None:
        """ensure_image builds the image if needed; afterwards Docker has it."""
        tag = ensure_image([])
        self.assertEqual(tag, image_tag([]))
        self.assertEqual(run_docker(["image", "inspect", tag]).returncode, 0)
        self.assertEqual(ensure_image([]), tag)


@unittest.skipUnless(docker_is_available(), "Docker is not available")
class IsolationTest(unittest.TestCase):
    """Programs run in containers built without packages, except where numpy is needed."""

    def start(self, code: str, settings: SandboxSettings | None = None) -> SandboxSession:
        """Start a session in a container without packages, closed at the end of the test."""
        sandbox = DockerSandbox(ensure_image([]), settings or SandboxSettings(), "test")
        session = sandbox.start(code, stage_limit=30.0)
        self.addCleanup(session.close)
        return session

    def test_there_is_no_network(self) -> None:
        """A connection to the outside fails."""
        session = self.start(
            "import socket\n"
            "def connect():\n"
            "    socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
        )
        with self.assertRaisesRegex(ProgramFailure, "OSError|gaierror|unreachable"):
            session.call("connect")

    def test_only_tmp_is_writable(self) -> None:
        """Writing to /tmp works; writing anywhere else, the package folder included, fails."""
        session = self.start(
            "def write(path):\n"
            "    with open(path, 'w') as file:\n"
            "        file.write('x')\n"
            "    return path\n"
        )
        self.assertEqual(session.call("write", ("/tmp/note.txt",)), "/tmp/note.txt")
        for path in ["/note.txt", "/app/my_evolve/note.txt", "/usr/note.txt"]:
            with self.subTest(path=path), self.assertRaises(ProgramFailure):
                session.call("write", (path,))

    def test_the_program_runs_as_nobody_without_the_host_environment(self) -> None:
        """The user is nobody, the host's variables are absent, threads are limited."""
        os.environ["MY_EVOLVE_TEST_SECRET"] = "do-not-leak"
        self.addCleanup(os.environ.pop, "MY_EVOLVE_TEST_SECRET")
        session = self.start(
            "import os\n"
            "def who():\n"
            "    variables = os.environ\n"
            "    return os.getuid(), variables.get('MY_EVOLVE_TEST_SECRET'), "
            "variables.get('OMP_NUM_THREADS')\n"
        )
        self.assertEqual(session.call("who"), (65534, None, "1"))

    def test_process_pools_work(self) -> None:
        """A program may spread its work over processes, on the read-only file system."""
        session = self.start(POOL_PROGRAM, SandboxSettings(cpus=2))
        for method in ("fork", "spawn", "forkserver"):
            with self.subTest(method=method):
                self.assertEqual(session.call("with_pool", (method,)), POOL_TOTAL)
        self.assertEqual(session.call("with_executor"), POOL_TOTAL)

    def test_the_memory_limit(self) -> None:
        """A program using more memory than allowed is stopped, and the failure says why."""
        session = self.start(
            "def grow():\n    blocks = [bytearray(50_000_000) for _ in range(20)]\n",
            SandboxSettings(memory="256m"),
        )
        with self.assertRaisesRegex(ProgramFailure, "most likely for using too much memory"):
            session.call("grow")

    def test_packages_not_listed_cannot_be_imported(self) -> None:
        """The image without packages has no numpy."""
        session = self.start("def check():\n    import numpy\n")
        with self.assertRaisesRegex(ProgramFailure, "ModuleNotFoundError: No module named 'numpy'"):
            session.call("check")

    def test_a_timeout_kills_the_container(self) -> None:
        """At the deadline the container is stopped and removed, with everything it started."""
        sandbox = DockerSandbox(ensure_image([]), SandboxSettings(), "test")
        session = sandbox.start("import time\ndef wait():\n    time.sleep(60)\n", stage_limit=5.0)
        self.addCleanup(session.close)
        started = time.monotonic()
        with self.assertRaises(StageTimeout):
            session.call("wait")
        self.assertLess(time.monotonic() - started, 20.0)
        listed = run_docker(["ps", "--all", "--quiet", "--filter", f"name={session.name}"]).stdout
        self.assertEqual(listed.strip(), "")

    def test_a_missing_image_is_the_sandbox_fault(self) -> None:
        """docker run failing to start the worker is a SandboxError, not a program failure."""
        sandbox = DockerSandbox("my-evolve-evaluation:no-such-tag", SandboxSettings(), "test")
        with self.assertRaisesRegex(SandboxError, "the worker could not start"):
            sandbox.start("x = 1\n", stage_limit=60.0)


@unittest.skipUnless(docker_is_available(), "Docker is not available")
class LeftoverTest(unittest.TestCase):
    def containers_of(self, run_id: str) -> list[str]:
        """Return the ids of the containers labelled with that run id."""
        filter_ = f"label=my-evolve.run={run_id}"
        return run_docker(["ps", "--all", "--quiet", "--filter", filter_]).stdout.split()

    def test_leftovers_of_the_run_are_removed_and_no_others(self) -> None:
        """remove_leftovers removes the run's containers, still running or not, and only those."""
        ours = DockerSandbox(ensure_image([]), SandboxSettings(), uuid.uuid4().hex)
        theirs = DockerSandbox(ensure_image([]), SandboxSettings(), uuid.uuid4().hex)
        program = "import time\ndef wait():\n    time.sleep(60)\n"
        sessions = [ours.start(program, 60.0), theirs.start(program, 60.0)]
        for session in sessions:
            self.addCleanup(session.close)
        self.addCleanup(theirs.remove_leftovers)
        self.assertEqual(len(self.containers_of(ours.run_id)), 1)
        ours.remove_leftovers()
        self.assertEqual(self.containers_of(ours.run_id), [])
        self.assertEqual(len(self.containers_of(theirs.run_id)), 1)

    def test_a_container_stops_on_its_own_when_its_host_process_dies(self) -> None:
        """Killing only the docker client leaves a busy container, which stops at its own limit.

        The worker is kept busy, so that it does not notice its input closing: only its
        own time limit, 1 + 10 s, stops it.
        """
        sandbox = DockerSandbox(ensure_image([]), SandboxSettings(), uuid.uuid4().hex)
        self.addCleanup(sandbox.remove_leftovers)
        program = "def spin():\n    print('spinning')\n    while True:\n        pass\n"
        session = sandbox.start(program, stage_limit=1.0)
        assert session.process is not None and session.process.stdin is not None
        started = time.monotonic()
        send(
            session.process.stdin,
            {"type": "call", "id": 1, "name": "spin", "args": [], "kwargs": {"__dict__": {}}},
        )
        # Kill the client only once the worker is busy: killed earlier, the client could
        # lose the call, and the idle worker would end as soon as its input closes.
        while "spinning" not in session.error_tail() and time.monotonic() < started + 10:
            time.sleep(0.05)
        session.process.kill()
        session.process.wait()
        session.close()
        time.sleep(3)
        self.assertEqual(len(self.containers_of(sandbox.run_id)), 1)
        while self.containers_of(sandbox.run_id) and time.monotonic() < started + 30:
            time.sleep(1)
        self.assertEqual(self.containers_of(sandbox.run_id), [])
        self.assertGreater(time.monotonic() - started, 8)


@unittest.skipUnless(docker_is_available(), "Docker is not available")
@unittest.skipIf(sys.platform == "win32", "process groups and SIGINT are Linux and macOS ones")
class CtrlCInDockerTest(unittest.TestCase):
    def test_ctrl_c_in_the_terminal_does_not_reach_the_container(self) -> None:
        """Neither the docker client nor the container gets the terminal's Ctrl+C."""
        sandbox = DockerSandbox(ensure_image([]), SandboxSettings(), uuid.uuid4().hex)
        self.addCleanup(sandbox.remove_leftovers)
        self.assertIn("returned 42", interrupt_the_group("docker", sandbox.run_id))


@unittest.skipUnless(docker_is_available(), "Docker is not available")
class EvaluationInDockerTest(unittest.TestCase):
    def test_the_initial_programs_score_as_before(self) -> None:
        """Circle packing (with its packages) and the toy problem score the same in Docker."""
        problem = Problem.load(CIRCLE_PACKING_FOLDER / "problem.yaml")
        sandbox = DockerSandbox(ensure_image(problem.packages), problem.sandbox, "test")
        evaluator = Evaluator(
            CIRCLE_PACKING_FOLDER / "evaluation.py", sandbox, 60.0, problem.evaluation.thresholds
        )
        result = evaluator.evaluate((CIRCLE_PACKING_FOLDER / "initial_program.py").read_text())
        self.assertEqual(result.status, Status.OK, result.error)
        self.assertAlmostEqual(result.score or 0.0, 0.3642, places=3)
        evaluator = Evaluator(
            TOY_FOLDER / "evaluation.py",
            DockerSandbox(ensure_image([]), SandboxSettings(), "test"),
            60.0,
        )
        result = evaluator.evaluate((TOY_FOLDER / "initial_program.py").read_text())
        self.assertEqual((result.status, result.score), (Status.OK, 1.0))


if __name__ == "__main__":
    unittest.main()
