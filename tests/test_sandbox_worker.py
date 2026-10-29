"""Checks the sandbox worker, driven through its pipes as the host drives it."""

import subprocess
import sys
import unittest
from typing import Any

import numpy as np

from my_evolve.sandbox_protocol import Message, NotPlainData, receive, send, to_plain

PROGRAM = """\
import math
import sys

import numpy as np

N = 3
SETTINGS = {"size": (2, 3)}


def add(a, b=10):
    return a + b


def packing():
    return np.zeros((2, 2)), np.array([0.5, 0.25]), np.float64(0.75)


def broken():
    return {"key": 1} / 2


def leave():
    sys.exit(4)


def unusual():
    return object()


def chatty():
    print("hello from the program")
    return len(sys.stdin.read())


if __name__ == "__main__":
    raise RuntimeError("the main part must not run")
"""


class Worker:
    """A worker process, started for one test, and the messages to and from it."""

    def __init__(self) -> None:
        self.process = subprocess.Popen(
            [sys.executable, "-m", "my_evolve.sandbox_worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        self.next_id = 0
        # What the worker wrote on its error output, once it has ended
        self.error_output = ""

    def exchange(self, message: Message) -> Message | None:
        """Send one message and return the answer."""
        assert self.process.stdin is not None and self.process.stdout is not None
        send(self.process.stdin, message)
        return receive(self.process.stdout)

    def load(self, code: str) -> Message | None:
        """Send the program; return the answer, loaded or load_failed."""
        return self.exchange({"type": "load", "code": code})

    def call(self, name: str, *args: Any, **kwargs: Any) -> Message | None:
        """Call one of the program's functions; return the answer, return or raised."""
        self.next_id += 1
        message = {"type": "call", "id": self.next_id, "name": name, "args": list(args)}
        return self.exchange({**message, "kwargs": kwargs})

    def close(self) -> str:
        """End the worker by closing its input, and return what it wrote on its error output.

        Safe to call twice: the second call returns the same text.
        """
        assert self.process.stdin and self.process.stdout and self.process.stderr
        if not self.process.stderr.closed:
            self.process.stdin.close()
            self.process.wait(timeout=10)
            self.error_output = self.process.stderr.read()
            self.process.stdout.close()
            self.process.stderr.close()
        return self.error_output


class ToPlainTest(unittest.TestCase):
    def test_plain_data(self) -> None:
        """Numbers, text, lists, tuples, dicts and numpy values become plain JSON data."""
        value = {"a": (1, 2.5), "b": [None, True, "x"], "c": np.array([[1, 2]]), "d": np.int64(3)}
        self.assertEqual(
            to_plain(value), {"a": [1, 2.5], "b": [None, True, "x"], "c": [[1, 2]], "d": 3}
        )

    def test_other_values_are_refused(self) -> None:
        """Objects, and dictionaries with keys that are not text, cannot travel."""
        for value in [object(), {1: "one"}, [print]]:
            with self.subTest(value=value), self.assertRaises(NotPlainData):
                to_plain(value)


class SandboxWorkerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.worker = Worker()
        self.addCleanup(self.worker.close)

    def test_loaded_lists_the_names_and_their_kinds(self) -> None:
        """Functions, plain data, and anything else (modules) are told apart."""
        loaded = self.worker.load(PROGRAM)
        assert loaded is not None
        self.assertEqual(loaded["type"], "loaded")
        names = loaded["names"]
        self.assertEqual(
            (names["add"], names["N"], names["SETTINGS"]), ("function", "data", "data")
        )
        self.assertEqual((names["math"], names["np"]), ("other", "other"))
        self.assertNotIn("__name__", names)

    def test_a_call_returns_its_value(self) -> None:
        """Arguments go in, the value comes back, numpy values as lists and numbers."""
        self.worker.load(PROGRAM)
        self.assertEqual(self.worker.call("add", 1, b=2), {"type": "return", "id": 1, "value": 3})
        answer = self.worker.call("packing")
        assert answer is not None
        self.assertEqual(answer["value"], [[[0.0, 0.0], [0.0, 0.0]], [0.5, 0.25], 0.75])

    def test_get_returns_a_global(self) -> None:
        """A plain-data global can be read."""
        self.worker.load(PROGRAM)
        answer = self.worker.exchange({"type": "get", "id": 7, "name": "SETTINGS"})
        self.assertEqual(answer, {"type": "return", "id": 7, "value": {"size": [2, 3]}})

    def test_an_exception_is_raised_with_its_traceback(self) -> None:
        """The error, and a traceback that shows the program's line."""
        self.worker.load(PROGRAM)
        answer = self.worker.call("broken")
        assert answer is not None
        self.assertEqual(answer["type"], "raised")
        self.assertIn("TypeError: unsupported operand", answer["error"])
        self.assertIn('File "<program>", line 19, in broken', answer["traceback"])
        self.assertIn('return {"key": 1} / 2', answer["traceback"])
        self.assertNotIn("sandbox_worker", answer["traceback"])

    def test_exit_missing_names_and_unusual_values_are_raised(self) -> None:
        """sys.exit in a function, a missing name, and a value that is not plain data."""
        self.worker.load(PROGRAM)
        for name, error in [
            ("leave", "SystemExit: 4"),
            ("missing", "NameError: the program defines no 'missing'"),
            ("unusual", "NotPlainData: a value of type object is not plain data"),
        ]:
            with self.subTest(name=name):
                answer = self.worker.call(name)
                assert answer is not None
                self.assertEqual((answer["type"], answer["error"]), ("raised", error))
        # The worker still answers afterwards.
        answer = self.worker.call("add", 1)
        self.assertEqual(answer and answer["value"], 11)

    def test_prints_and_reads_do_not_touch_the_messages(self) -> None:
        """The program prints to the error output and reads an empty input."""
        self.worker.load(PROGRAM)
        answer = self.worker.call("chatty")
        self.assertEqual(answer and answer["value"], 0)
        self.assertEqual(self.worker.call("add", 2, 2), {"type": "return", "id": 2, "value": 4})
        self.assertIn("hello from the program", self.worker.close())

    def test_a_program_that_fails_to_load(self) -> None:
        """An error while loading, exit requests included, gives load_failed."""
        for code, error in [
            ("import sys\nsys.exit(2)\n", "SystemExit: 2"),
            ("x = 1 / 0\n", "ZeroDivisionError: division by zero"),
            ("def f(:\n", "SyntaxError"),
        ]:
            with self.subTest(error=error):
                worker = Worker()
                answer = worker.load(code)
                worker.close()
                assert answer is not None
                self.assertEqual(answer["type"], "load_failed")
                self.assertIn(error, answer["error"])


if __name__ == "__main__":
    unittest.main()
