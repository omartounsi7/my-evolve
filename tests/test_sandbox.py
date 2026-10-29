"""Checks sandbox sessions directly: calls, the deadline, and the worker process."""

import time
import unittest

from my_evolve.evaluation_api import ProgramFailure, StageTimeout
from my_evolve.sandbox import LocalSandbox, ProgramNamespace, RemoteFunction

PROGRAM = """\
import time

LIMIT = 10


def add(a, b):
    return a + b


def wait(seconds):
    time.sleep(seconds)
    return seconds
"""


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


if __name__ == "__main__":
    unittest.main()
