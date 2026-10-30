"""Checks sandbox sessions directly: calls, the deadline, and the worker process."""

import subprocess
import sys
import time
import unittest

from my_evolve.evaluation_api import (
    CallTimeout,
    ProgramFailure,
    StageTimeout,
    call_with_timeout,
)
from my_evolve.sandbox import LocalSandbox, ProgramNamespace, RemoteFunction, SandboxSession

PROGRAM = """\
import time

LIMIT = 10


def add(a, b):
    return a + b


def wait(seconds):
    time.sleep(seconds)
    return seconds
"""

# A program whose count() counts its calls since the program was loaded
COUNTER_PROGRAM = """\
import os
import time

calls = []


def count(seconds=0):
    time.sleep(seconds)
    calls.append(1)
    return len(calls)


def end():
    os._exit(7)
"""

# A program that hands its own functions to other processes, as searches over several
# CPUs do: the processes must find them in the program's module
POOL_PROGRAM = """\
import multiprocessing
from concurrent.futures import ProcessPoolExecutor

OFFSET = 1000


def square(x):
    return x * x + OFFSET


def with_pool(method):
    with multiprocessing.get_context(method).Pool(2) as pool:
        return sum(pool.map(square, range(4)))


def with_executor():
    with ProcessPoolExecutor(2) as executor:
        return sum(executor.map(square, range(4)))
"""
# What both functions return: 0 + 1 + 4 + 9, plus OFFSET four times
POOL_TOTAL = 4014


class SessionTest(unittest.TestCase):
    def test_calls_and_globals(self) -> None:
        """The namespace gives functions as stand-ins and plain data as values."""
        session = LocalSandbox().start(PROGRAM, stage_limit=30.0)
        self.addCleanup(session.close)
        namespace = ProgramNamespace(session)
        self.assertIsInstance(namespace["add"], RemoteFunction)
        self.assertEqual(namespace["add"](2, b=3), 5)
        self.assertEqual(namespace["LIMIT"], 10)
        self.assertEqual(sorted(namespace), ["LIMIT", "add", "time", "wait"])
        with self.assertRaisesRegex(ProgramFailure, "the program defines no 'missing'"):
            namespace["missing"]

    def test_the_deadline_stops_the_worker(self) -> None:
        """A call still running at the deadline raises StageTimeout, and the worker is killed."""
        session = LocalSandbox().start(PROGRAM, stage_limit=1.0)
        self.addCleanup(session.close)
        started = time.monotonic()
        with self.assertRaisesRegex(StageTimeout, "time limit of 1 s"):
            session.call("wait", (30,))
        self.assertLess(time.monotonic() - started, 5.0)
        self.assertTrue(session.timed_out)
        assert session.process is not None
        self.assertIsNotNone(session.process.poll())

    def test_calls_within_the_deadline_are_unaffected(self) -> None:
        """The deadline covers the whole session: short calls all get their answer."""
        session = LocalSandbox().start(PROGRAM, stage_limit=5.0)
        self.addCleanup(session.close)
        for _ in range(3):
            self.assertEqual(session.call("wait", (0.1,)), 0.1)
        self.assertFalse(session.timed_out)


class CallTimeLimitTest(unittest.TestCase):
    def test_a_call_over_its_own_limit_raises_call_timeout(self) -> None:
        """The worker is killed; the next call gets a fresh one, with the program reloaded."""
        session = LocalSandbox().start(COUNTER_PROGRAM, stage_limit=30.0)
        self.addCleanup(session.close)
        count = ProgramNamespace(session)["count"]
        self.assertEqual((count(), count()), (1, 2))
        started = time.monotonic()
        with self.assertRaisesRegex(CallTimeout, r"count\(\) ran over its time limit of 0.5 s"):
            count.with_timeout(0.5)(30)
        self.assertLess(time.monotonic() - started, 5.0)
        self.assertFalse(session.alive)
        # A fresh worker: the program's state starts over.
        self.assertEqual(call_with_timeout(count, 5.0), 1)
        self.assertFalse(session.timed_out)

    def test_the_stage_limit_still_applies_and_is_not_a_call_timeout(self) -> None:
        """A call's limit past the stage's deadline gives StageTimeout, which is no CallTimeout."""
        self.assertFalse(issubclass(StageTimeout, CallTimeout))
        session = LocalSandbox().start(COUNTER_PROGRAM, stage_limit=1.0)
        self.addCleanup(session.close)
        with self.assertRaises(StageTimeout):
            call_with_timeout(ProgramNamespace(session)["count"], 10.0, 30)
        self.assertTrue(session.timed_out)

    def test_a_worker_that_died_is_replaced_at_the_next_call(self) -> None:
        """After the process ends, the next call loads the program again."""
        session = LocalSandbox().start(COUNTER_PROGRAM, stage_limit=30.0)
        self.addCleanup(session.close)
        self.assertEqual(session.call("count"), 1)
        with self.assertRaisesRegex(ProgramFailure, "exit code 7"):
            session.call("end")
        self.assertEqual(session.call("count"), 1)

    def test_call_with_timeout_needs_a_function_of_the_program(self) -> None:
        """A plain Python function has no sandbox to limit."""
        with self.assertRaisesRegex(TypeError, "one of the program's functions"):
            call_with_timeout(print, 1.0)


class MisbehavingProgramTest(unittest.TestCase):
    def start(self, code: str) -> SandboxSession:
        """Start a session for the program, closed at the end of the test."""
        session = LocalSandbox().start(code, stage_limit=30.0)
        self.addCleanup(session.close)
        return session

    def test_a_failure_carries_the_end_of_the_program_output(self) -> None:
        """What the program printed before failing is kept, after the error and traceback."""
        session = self.start("def f():\n    print('step 42 reached')\n    raise ValueError('x')\n")
        with self.assertRaises(ProgramFailure) as caught:
            session.call("f")
        self.assertIn("step 42 reached", caught.exception.error_output)
        description = caught.exception.describe()
        self.assertTrue(description.startswith("ValueError: x\n\nTraceback"))
        self.assertTrue(description.endswith("The end of the program's output:\nstep 42 reached"))

    def test_endless_printing_is_kept_neither_on_disk_nor_in_memory(self) -> None:
        """A program printing without end until the stage's deadline: only the end of its
        output is kept (it once went to a file, which grew by about 1 GB a second)."""
        session = LocalSandbox().start(
            "import sys\ndef f():\n    while True:\n        sys.stdout.write('x' * 9999 + '\\n')\n",
            stage_limit=2.0,
        )
        self.addCleanup(session.close)
        with self.assertRaises(StageTimeout):
            session.call("f")
        self.assertLessEqual(len(session.output.data), 4 * 2000)

    def test_endless_printing_keeps_only_the_end(self) -> None:
        """A program printing a lot keeps working, and only the end of its output is kept."""
        session = self.start(
            "def f():\n    for i in range(200_000):\n        print('line', i)\n    return 1 / 0\n"
        )
        with self.assertRaises(ProgramFailure) as caught:
            session.call("f")
        self.assertLessEqual(len(caught.exception.error_output), 2000)
        self.assertTrue(caught.exception.error_output.endswith("line 199999\n"))

    def test_a_worker_that_dies_says_how(self) -> None:
        """A process that ends during a call, or is killed, is described."""
        session = self.start("import os, signal\ndef end():\n    os._exit(3)\n")
        with self.assertRaisesRegex(ProgramFailure, r"process ended \(exit code 3\)"):
            session.call("end")
        session = self.start("import os, signal\ndef die():\n    os.kill(os.getpid(), 9)\n")
        with self.assertRaisesRegex(ProgramFailure, "most likely for using too much memory"):
            session.call("die")

    def test_forged_answers_are_ignored(self) -> None:
        """A program writing an answer with an id the host is not waiting for gains nothing."""
        session = self.start(
            "import os\n"
            "def f():\n"
            '    forged = b\'{"type": "return", "id": 99, "value": 1000000000.0}\\n\'\n'
            "    for fd in range(3, 20):\n"
            "        try:\n            os.write(fd, forged)\n"
            "        except OSError:\n            pass\n"
            "    return 5\n"
        )
        self.assertEqual(session.call("f"), 5)
        self.assertEqual(session.call("f"), 5)


class ProcessPoolTest(unittest.TestCase):
    def test_programs_can_hand_their_functions_to_other_processes(self) -> None:
        """Pools work, whichever way they start processes: the program is a module others
        can import (pickling its functions once failed, and programs fell back to one CPU
        without saying so)."""
        session = LocalSandbox().start(POOL_PROGRAM, stage_limit=60.0)
        self.addCleanup(session.close)
        for method in ("fork", "spawn", "forkserver"):
            with self.subTest(method=method):
                self.assertEqual(session.call("with_pool", (method,)), POOL_TOTAL)
        self.assertEqual(session.call("with_executor"), POOL_TOTAL)

    def test_the_program_is_the_module_program(self) -> None:
        """Its __name__ is "program", its main part does not run, and tracebacks still name
        the program's lines."""
        session = LocalSandbox().start(
            "NAME = __name__\nif __name__ == '__main__':\n    NAME = 'main'\n"
            "def f():\n    return [][1]\n",
            stage_limit=30.0,
        )
        self.addCleanup(session.close)
        self.assertEqual(session.get("NAME"), "program")
        with self.assertRaises(ProgramFailure) as caught:
            session.call("f")
        self.assertIn(
            'File "<program>", line 5, in f\n    return [][1]', caught.exception.describe()
        )


# Run in a process group of its own, as a terminal runs my-evolve: it starts a session,
# then, while the program is in the middle of a call, interrupts its whole group as Ctrl+C
# does, ignoring the signal itself. It prints what the call returned, or the failure.
CTRL_C_SCRIPT = """
import os, signal, sys, threading
from my_evolve.evaluation_api import ProgramFailure
from my_evolve.sandbox import DockerSandbox, LocalSandbox, ensure_image
from my_evolve.problem import SandboxSettings
if sys.argv[1] == "docker":
    sandbox = DockerSandbox(ensure_image([]), SandboxSettings(), sys.argv[2])
else:
    sandbox = LocalSandbox()
session = sandbox.start("import time\\ndef f():\\n    time.sleep(3)\\n    return 42\\n", 60.0)
# Ignored only now: a worker started while it was ignored would ignore it too.
signal.signal(signal.SIGINT, signal.SIG_IGN)
threading.Timer(1.5, os.killpg, (os.getpgrp(), signal.SIGINT)).start()
try:
    print("returned", session.call("f"))
except ProgramFailure as failure:
    print("failed", failure.error)
session.close()
"""


def interrupt_the_group(sandbox: str, run_id: str = "") -> str:
    """Run CTRL_C_SCRIPT with that sandbox, in a group of its own; return what it printed."""
    finished = subprocess.run(
        [sys.executable, "-c", CTRL_C_SCRIPT, sandbox, run_id],
        capture_output=True,
        text=True,
        timeout=120,
        start_new_session=True,
    )
    return finished.stdout + finished.stderr


@unittest.skipIf(sys.platform == "win32", "process groups and SIGINT are Linux and macOS ones")
class CtrlCTest(unittest.TestCase):
    def test_ctrl_c_in_the_terminal_does_not_reach_the_program(self) -> None:
        """Only my-evolve decides what Ctrl+C stops: the program's call goes on (it was once
        interrupted, and the program recorded as failed)."""
        self.assertIn("returned 42", interrupt_the_group("local"))


if __name__ == "__main__":
    unittest.main()
