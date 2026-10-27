"""Checks the Docker sandbox: the image, the container's limits, and that nothing is left behind.

The tests that start containers are skipped when Docker is not available. The
first run builds a small test image with numpy, which needs network access once.
"""

import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

import numpy as np
from docker_check import docker_is_available

from my_evolve.evaluation_api import CallTimeout, ProgramFailure, StageTimeout
from my_evolve.problem import SandboxSettings
from my_evolve.sandbox import (
    RUN_LABEL,
    DockerSandbox,
    ProgramNamespace,
    SandboxError,
    SandboxSession,
    docker_image_tag,
)

SETTINGS = SandboxSettings(memory="1g", cpus=1.0, max_processes=64)
TEST_PACKAGES = ("numpy==2.5.4",)
STAGE_LIMIT = 60.0

PROGRAM = """\
import os
import socket
import subprocess
import sys
import time

import numpy as np

LOADS = []
LOADS.append(1)


def run_packing():
    centres = np.full((26, 2), 0.5)
    radii = np.full(26, 0.1)
    return centres, radii, float(np.sum(radii))


def connect():
    socket.create_connection(("1.1.1.1", 53), timeout=3)
    return "connected"


def write(path):
    with open(path, "w") as file:
        file.write("x")
    return "written"


def allocate(gigabytes):
    data = bytearray(int(gigabytes * 1024**3))
    return len(data)


def run_forever():
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
    while True:
        pass


def sleep(seconds):
    time.sleep(seconds)
    return "woke up"


def loads():
    return len(LOADS)


def echo(text):
    print(text)
    return text


def environment(name):
    return os.environ.get(name)


def user_id():
    return os.getuid()
"""


def containers_labelled(run_id: str) -> list[str]:
    """Return the ids of the containers, running or not, carrying the run's label."""
    listing = subprocess.run(
        ["docker", "ps", "--all", "--quiet", "--filter", f"label={RUN_LABEL}={run_id}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return listing.stdout.split()


class TestImageAndCommand(unittest.TestCase):
    """Checks that need no container."""

    def test_same_packages_give_the_same_image(self) -> None:
        self.assertEqual(docker_image_tag(("numpy==2.5.4",)), docker_image_tag(("numpy==2.5.4",)))

    def test_different_packages_give_a_different_image(self) -> None:
        self.assertNotEqual(docker_image_tag(()), docker_image_tag(("numpy==2.5.4",)))

    def test_command_applies_every_limit(self) -> None:
        sandbox = DockerSandbox("my-evolve-evaluation:test", SETTINGS, "run-1234")
        command = sandbox.command("my-evolve-run-1234-abc", 60.0)
        text = " ".join(command)
        for expected in (
            "--rm",
            "--network none",
            "--read-only",
            "--tmpfs /tmp",
            "--memory 1g",
            "--memory-swap 1g",
            "--cpus 1",
            "--pids-limit 64",
            "--cap-drop ALL",
            "--security-opt no-new-privileges",
            "--user 65534:65534",
            f"--label {RUN_LABEL}=run-1234",
            "--env OMP_NUM_THREADS=1",
            "target=/app/my_evolve,readonly",
            "timeout --signal=KILL 70 python -m my_evolve.sandbox_worker",
        ):
            self.assertIn(expected, text)
        self.assertNotIn("--env ANTHROPIC_API_KEY", text)

    def test_container_names_start_with_the_run_id(self) -> None:
        sandbox = DockerSandbox("my-evolve-evaluation:test", SETTINGS, "abcdef12-3456")
        self.assertTrue(sandbox.new_session_name().startswith("my-evolve-abcdef12-"))


@unittest.skipUnless(docker_is_available(), "Docker is not available")
class DockerTestCase(unittest.TestCase):
    """Builds the test image once; every test gets a run id of its own."""

    image: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.image = DockerSandbox.ensure_image(TEST_PACKAGES)

    def setUp(self) -> None:
        self.run_id = uuid.uuid4().hex
        self.sandbox = DockerSandbox(self.image, SETTINGS, self.run_id)
        self.addCleanup(self.sandbox.remove_leftovers)

    def start(self, code: str = PROGRAM, stage_limit: float = STAGE_LIMIT) -> SandboxSession:
        session = self.sandbox.start(code, stage_limit)
        self.addCleanup(session.close)
        return session

    def namespace(self, stage_limit: float = STAGE_LIMIT) -> ProgramNamespace:
        return ProgramNamespace(self.start(stage_limit=stage_limit))


class TestDockerSandbox(DockerTestCase):
    def test_values_come_back_from_the_container(self) -> None:
        centres, radii, total = self.namespace()["run_packing"]()
        self.assertIsInstance(centres, np.ndarray)
        self.assertEqual(centres.shape, (26, 2))
        self.assertAlmostEqual(total, 2.6)

    def test_program_has_no_network(self) -> None:
        with self.assertRaises(ProgramFailure) as caught:
            self.namespace()["connect"]()
        self.assertIn("OSError", caught.exception.message)

    def test_program_cannot_write_outside_its_temporary_folder(self) -> None:
        namespace = self.namespace()
        for path in ("/app/my_evolve/planted.py", "/home/planted.txt", "/planted.txt"):
            with self.subTest(path=path), self.assertRaises(ProgramFailure):
                namespace["write"](path)
        self.assertFalse((Path(__file__).parent.parent / "src/my_evolve/planted.py").exists())

    def test_program_may_write_in_its_temporary_folder(self) -> None:
        self.assertEqual(self.namespace()["write"]("/tmp/notes.txt"), "written")

    def test_program_runs_as_a_user_without_rights(self) -> None:
        self.assertEqual(self.namespace()["user_id"](), 65534)

    def test_program_sees_no_host_environment_variable(self) -> None:
        os.environ["MY_EVOLVE_TEST_SECRET"] = "sk-not-for-programs"
        self.addCleanup(os.environ.pop, "MY_EVOLVE_TEST_SECRET")
        environment = self.namespace()["environment"]
        self.assertIsNone(environment("MY_EVOLVE_TEST_SECRET"))
        self.assertEqual(environment("OMP_NUM_THREADS"), "1")

    def test_listed_package_is_importable_and_others_are_not(self) -> None:
        self.start("import numpy\n")
        with self.assertRaises(ProgramFailure) as caught:
            self.start("import scipy\n")
        self.assertIn("ModuleNotFoundError", caught.exception.message)

    def test_program_using_too_much_memory_is_stopped(self) -> None:
        with self.assertRaisesRegex(ProgramFailure, "too much memory"):
            self.namespace()["allocate"](3)

    def test_text_outside_plain_english_survives(self) -> None:
        session = self.start()
        self.assertEqual(ProgramNamespace(session)["echo"]("été → ✓"), "été → ✓")
        self.assertIn("été → ✓", session.error_tail())

    def test_program_that_never_ends_is_stopped_with_everything_it_started(self) -> None:
        session = self.start(stage_limit=5)
        with self.assertRaises(StageTimeout):
            ProgramNamespace(session)["run_forever"]()
        self.assertEqual(containers_labelled(self.run_id), [])

    def test_call_timeout_restarts_in_a_fresh_container(self) -> None:
        session = self.start()
        namespace = ProgramNamespace(session)
        with self.assertRaises(CallTimeout):
            namespace["sleep"].with_timeout(1)(60)
        self.assertEqual(containers_labelled(self.run_id), [])
        self.assertEqual(namespace["loads"](), 1)

    def test_closing_a_session_leaves_no_container(self) -> None:
        session = self.sandbox.start(PROGRAM, STAGE_LIMIT)
        self.assertEqual(len(containers_labelled(self.run_id)), 1)
        session.close()
        self.assertEqual(containers_labelled(self.run_id), [])

    def test_leftovers_of_the_run_are_removed_and_others_kept(self) -> None:
        other_sandbox = DockerSandbox(self.image, SETTINGS, uuid.uuid4().hex)
        self.addCleanup(other_sandbox.remove_leftovers)
        mine = self.sandbox.start(PROGRAM, STAGE_LIMIT)
        theirs = other_sandbox.start(PROGRAM, STAGE_LIMIT)
        self.addCleanup(mine.close)
        self.addCleanup(theirs.close)
        self.sandbox.remove_leftovers()
        self.assertEqual(containers_labelled(self.run_id), [])
        self.assertEqual(len(containers_labelled(other_sandbox.run_id)), 1)

    def test_missing_image_is_the_sandboxs_failure(self) -> None:
        sandbox = DockerSandbox("my-evolve-evaluation:no-such-image", SETTINGS, self.run_id)
        with self.assertRaisesRegex(SandboxError, "no longer exists"):
            sandbox.start(PROGRAM, STAGE_LIMIT)


HOST_SCRIPT = """\
import sys
from my_evolve.problem import SandboxSettings
from my_evolve.sandbox import DockerSandbox, ProgramNamespace

image, run_id, code = sys.argv[1], sys.argv[2], open(sys.argv[3]).read()
sandbox = DockerSandbox(image, SandboxSettings("1g", 1.0, 64), run_id)
session = sandbox.start(code, 5.0)
print("started", flush=True)
ProgramNamespace(session)["sleep"](1000)
"""


class TestHostDying(DockerTestCase):
    def test_container_stops_by_itself_when_the_host_dies(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        script = Path(folder.name) / "host.py"
        script.write_text(HOST_SCRIPT, encoding="utf-8")
        program = Path(folder.name) / "program.py"
        program.write_text(PROGRAM, encoding="utf-8")

        host = subprocess.Popen(
            [sys.executable, str(script), self.image, self.run_id, str(program)],
            stdout=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        assert host.stdout is not None
        self.assertEqual(host.stdout.readline().strip(), "started")
        # The host dies without cleaning anything up, as after a crash.
        host.send_signal(signal.SIGKILL)
        host.wait()
        host.stdout.close()
        self.assertEqual(len(containers_labelled(self.run_id)), 1)

        # The worker's own limit is 5 s + 10 s.
        deadline = time.monotonic() + 40
        while containers_labelled(self.run_id) and time.monotonic() < deadline:
            time.sleep(1)
        self.assertEqual(containers_labelled(self.run_id), [])


if __name__ == "__main__":
    unittest.main()
