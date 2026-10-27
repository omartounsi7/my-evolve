"""Checks the sandbox sessions, the namespace and the time limits, with the local sandbox.

No Docker is needed: these tests are about how the host drives a worker. The
isolation of the Docker sandbox is checked separately.
"""

import os
import time
import unittest
from pathlib import Path

import numpy as np

from my_evolve.evaluation_api import (
    CallTimeout,
    ProgramFailure,
    StageTimeout,
    call_with_timeout,
)
from my_evolve.sandbox import (
    ERROR_TAIL_CHARS,
    LocalSandbox,
    ProgramNamespace,
    RemoteFunction,
    SandboxSession,
    describe_end,
)
from my_evolve.sandbox_protocol import NotPlainData

PROGRAM = """\
import os
import sys
import time

import numpy as np

LIMIT = 26
POINT = (0.5, 0.5)
LOADS = []
LOADS.append(1)


def run_packing():
    centres = np.full((26, 2), 0.5)
    radii = np.full(26, 0.1)
    return centres, radii, float(np.sum(radii))


def add(a, b=10):
    return a + b


def broken():
    print("about to fail", file=sys.stderr)
    return [][1]


def sleep(seconds):
    time.sleep(seconds)
    return "woke up"


def loads():
    return len(LOADS)


def die():
    os._exit(3)


def environment(name):
    return os.environ.get(name)


def working_folder():
    return os.getcwd()


def forge():
    # Write a fake answer to every open file descriptor: the host must ignore it.
    line = b'{"type": "return", "id": 999, "value": 1000000000.0}\\nnot a message\\n'
    for descriptor in range(3, 64):
        try:
            os.write(descriptor, line)
        except OSError:
            pass
    return 42


def shout(times):
    for _ in range(times):
        print("x" * 99)
    return times
"""

# Generous limits for tests that must not time out; short ones for tests that must.
STAGE_LIMIT = 30.0


class SandboxTestCase(unittest.TestCase):
    """Starts a session of the test program, closed after each test."""

    sandbox = LocalSandbox()

    def start(self, code: str = PROGRAM, stage_limit: float = STAGE_LIMIT) -> SandboxSession:
        session = self.sandbox.start(code, stage_limit)
        self.addCleanup(session.close)
        return session

    def namespace(self, stage_limit: float = STAGE_LIMIT) -> ProgramNamespace:
        return ProgramNamespace(self.start(stage_limit=stage_limit))


class TestCalls(SandboxTestCase):
    def test_values_come_back_decoded(self) -> None:
        centres, radii, total = self.namespace()["run_packing"]()
        self.assertIsInstance(centres, np.ndarray)
        self.assertEqual(centres.shape, (26, 2))
        self.assertEqual(radii.shape, (26,))
        self.assertAlmostEqual(total, 2.6)

    def test_arguments_by_position_and_by_name(self) -> None:
        add = self.namespace()["add"]
        self.assertEqual(add(1), 11)
        self.assertEqual(add(1, b=2), 3)
        self.assertEqual(add((1,), (2,)), (1, 2))

    def test_argument_that_is_not_plain_data_is_the_evaluators_mistake(self) -> None:
        add = self.namespace()["add"]
        with self.assertRaises(NotPlainData):
            add({1}, {2})
        # The program was not restarted for it.
        self.assertEqual(self.namespace()["loads"](), 1)

    def test_exception_becomes_a_program_failure_with_its_details(self) -> None:
        with self.assertRaises(ProgramFailure) as caught:
            self.namespace()["broken"]()
        failure = caught.exception
        self.assertEqual(failure.message, "IndexError: list index out of range")
        self.assertIn("in broken", str(failure.traceback))
        self.assertIn("about to fail", str(failure.error_output))

    def test_session_carries_on_after_an_exception(self) -> None:
        namespace = self.namespace()
        with self.assertRaises(ProgramFailure):
            namespace["broken"]()
        self.assertEqual(namespace["add"](1), 11)
        self.assertEqual(namespace["loads"](), 1)

    def test_forged_answers_are_ignored(self) -> None:
        self.assertEqual(self.namespace()["forge"](), 42)

    def test_endless_printing_goes_to_a_file_and_only_its_end_is_kept(self) -> None:
        session = self.start()
        # About 5 MB of output.
        self.assertEqual(ProgramNamespace(session)["shout"](50_000), 50_000)
        tail = session.error_tail()
        self.assertLessEqual(len(tail), ERROR_TAIL_CHARS)
        self.assertTrue(tail.endswith("x" * 99 + "\n"))


class TestNamespace(SandboxTestCase):
    def test_functions_are_remote_and_data_is_read(self) -> None:
        namespace = self.namespace()
        self.assertIsInstance(namespace["add"], RemoteFunction)
        self.assertEqual(namespace["LIMIT"], 26)
        self.assertEqual(namespace["POINT"], (0.5, 0.5))

    def test_names_can_be_tested_and_listed(self) -> None:
        namespace = self.namespace()
        self.assertIn("run_packing", namespace)
        self.assertNotIn("run_search", namespace)
        self.assertIn("LIMIT", list(namespace))
        self.assertEqual(namespace.get("run_search", "absent"), "absent")

    def test_missing_name_is_a_program_failure(self) -> None:
        with self.assertRaisesRegex(ProgramFailure, "defines no name 'run_search'"):
            self.namespace()["run_search"]

    def test_name_that_is_neither_function_nor_data_is_a_program_failure(self) -> None:
        with self.assertRaisesRegex(ProgramFailure, "neither a function nor plain data"):
            self.namespace()["np"]


class TestLoading(SandboxTestCase):
    def test_program_failing_to_load_is_a_program_failure(self) -> None:
        with self.assertRaises(ProgramFailure) as caught:
            self.start("print('loading')\nimport package_that_does_not_exist\n")
        self.assertIn("ModuleNotFoundError", caught.exception.message)
        self.assertIn("loading", str(caught.exception.error_output))

    def test_program_dying_while_loading_is_a_program_failure(self) -> None:
        with self.assertRaisesRegex(ProgramFailure, "exit code 5"):
            self.start("import os\nos._exit(5)\n")

    def test_program_too_slow_to_load_runs_out_of_stage_time(self) -> None:
        started = time.monotonic()
        with self.assertRaisesRegex(StageTimeout, "while the program was loading"):
            self.start("import time\ntime.sleep(30)\n", stage_limit=1)
        self.assertLess(time.monotonic() - started, 10)


class TestTimeLimits(SandboxTestCase):
    def test_call_over_its_own_limit_raises_call_timeout(self) -> None:
        sleep = self.namespace()["sleep"]
        started = time.monotonic()
        with self.assertRaisesRegex(CallTimeout, r"sleep ran over its time limit of 0\.5 s"):
            sleep.with_timeout(0.5)(30)
        self.assertLess(time.monotonic() - started, 10)

    def test_next_call_runs_in_a_fresh_worker_with_the_program_reloaded(self) -> None:
        session = self.start()
        namespace = ProgramNamespace(session)
        first_worker = session.process
        with self.assertRaises(CallTimeout):
            namespace["sleep"].with_timeout(0.5)(30)
        self.assertFalse(session.alive)
        # The program's state was not carried over: it was loaded once more, from scratch.
        self.assertEqual(namespace["loads"](), 1)
        self.assertIsNot(session.process, first_worker)
        self.assertTrue(session.alive)

    def test_call_with_timeout_is_openevolves_run_with_timeout(self) -> None:
        namespace = self.namespace()
        self.assertEqual(call_with_timeout(namespace["sleep"], 10, 0), "woke up")
        with self.assertRaises(CallTimeout):
            call_with_timeout(namespace["sleep"], 0.5, 30)
        self.assertEqual(call_with_timeout(namespace["add"], 10, 1, b=1), 2)

    def test_call_with_timeout_needs_a_function_of_the_program(self) -> None:
        with self.assertRaises(TypeError):
            call_with_timeout(print, 1)

    def test_time_limit_must_be_above_zero(self) -> None:
        with self.assertRaises(ValueError):
            self.namespace()["sleep"].with_timeout(0)

    def test_stage_running_out_raises_stage_timeout(self) -> None:
        sleep = self.namespace(stage_limit=1)["sleep"]
        started = time.monotonic()
        with self.assertRaisesRegex(StageTimeout, r"\(1 s\) while sleep was running"):
            sleep(30)
        self.assertLess(time.monotonic() - started, 10)

    def test_stage_limit_wins_over_a_longer_call_limit(self) -> None:
        sleep = self.namespace(stage_limit=1)["sleep"]
        with self.assertRaises(StageTimeout):
            sleep.with_timeout(20)(30)

    def test_catching_a_call_timeout_does_not_hide_the_stage_timeout(self) -> None:
        sleep = self.namespace(stage_limit=1)["sleep"]
        with self.assertRaises(StageTimeout):
            try:
                sleep(30)
            except CallTimeout:
                self.fail("a stage timeout was taken for a call timeout")

    def test_no_call_starts_once_the_stage_is_over(self) -> None:
        namespace = self.namespace(stage_limit=1)
        with self.assertRaises(StageTimeout):
            namespace["sleep"](30)
        with self.assertRaises(StageTimeout):
            namespace["add"](1)


class TestWorkerEnding(SandboxTestCase):
    def test_worker_that_dies_is_a_program_failure(self) -> None:
        session = self.start()
        with self.assertRaisesRegex(ProgramFailure, "exit code 3"):
            ProgramNamespace(session)["die"]()
        self.assertFalse(session.alive)

    def test_next_call_after_a_death_restarts_the_worker(self) -> None:
        namespace = self.namespace()
        with self.assertRaises(ProgramFailure):
            namespace["die"]()
        self.assertEqual(namespace["add"](1), 11)

    def test_killed_workers_are_explained(self) -> None:
        self.assertIn("too much memory", describe_end(137))
        self.assertIn("too much memory", describe_end(-9))
        self.assertIn("exit code 1", describe_end(1))


class TestSessionLife(SandboxTestCase):
    def test_close_stops_the_worker_and_deletes_the_folder(self) -> None:
        session = self.sandbox.start(PROGRAM, STAGE_LIMIT)
        process = session.process
        folder = session.folder
        session.close()
        assert process is not None
        self.assertIsNotNone(process.poll())
        self.assertFalse(folder.exists())
        self.assertFalse(session.alive)

    def test_session_works_as_a_context_manager(self) -> None:
        with self.sandbox.start(PROGRAM, STAGE_LIMIT) as session:
            folder = session.folder
            self.assertEqual(ProgramNamespace(session)["add"](1), 11)
        self.assertFalse(folder.exists())

    def test_program_runs_in_the_sessions_own_folder(self) -> None:
        session = self.start()
        folder = ProgramNamespace(session)["working_folder"]()
        self.assertEqual(Path(folder).resolve(), session.work_folder.resolve())


class TestLocalEnvironment(SandboxTestCase):
    def test_host_secrets_are_not_passed_to_the_program(self) -> None:
        os.environ["MY_EVOLVE_TEST_SECRET"] = "sk-not-for-programs"
        self.addCleanup(os.environ.pop, "MY_EVOLVE_TEST_SECRET")
        self.assertIsNone(self.namespace()["environment"]("MY_EVOLVE_TEST_SECRET"))

    def test_numeric_libraries_get_the_cpu_count_as_thread_count(self) -> None:
        environment = self.namespace()["environment"]
        self.assertEqual(environment("OMP_NUM_THREADS"), "1")
        self.assertEqual(environment("OPENBLAS_NUM_THREADS"), "1")


if __name__ == "__main__":
    unittest.main()
