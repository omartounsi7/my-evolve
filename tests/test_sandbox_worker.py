"""Checks the worker that runs a program, driven through its pipes as the host will drive it.

The worker runs here as a plain subprocess, without a container: these tests are
about the protocol, not about isolation.
"""

import subprocess
import sys
import tempfile
import unittest
from typing import Any

from my_evolve.sandbox_protocol import decode, encode, receive, send

# The longest a test waits for the worker to answer or end, in seconds.
WAIT_SECONDS = 30


class Worker:
    """A worker subprocess, with helpers to send messages and read its answers."""

    def __init__(self, test_case: unittest.TestCase) -> None:
        # The error output goes to a file: a pipe nobody reads could fill up and block.
        self.error_output = tempfile.TemporaryFile()
        test_case.addCleanup(self.error_output.close)
        self.process = subprocess.Popen(
            [sys.executable, "-m", "my_evolve.sandbox_worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.error_output,
            text=True,
            encoding="utf-8",
        )
        test_case.addCleanup(self.stop)
        self.next_id = 0

    def send(self, message: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        send(self.process.stdin, message)

    def receive(self) -> dict[str, Any] | None:
        assert self.process.stdout is not None
        return receive(self.process.stdout)

    def load(self, code: str) -> dict[str, Any] | None:
        """Send the program and return the worker's answer."""
        self.send({"type": "load", "code": code})
        return self.receive()

    def call(self, name: str, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
        """Call one of the program's functions and return the worker's answer."""
        self.next_id += 1
        self.send(
            {
                "type": "call",
                "id": self.next_id,
                "name": name,
                "args": encode(list(args)),
                "kwargs": encode(kwargs),
            }
        )
        return self.receive()

    def get(self, name: str) -> dict[str, Any] | None:
        """Ask for one of the program's plain-data globals."""
        self.next_id += 1
        self.send({"type": "get", "id": self.next_id, "name": name})
        return self.receive()

    def errors(self) -> str:
        """Return what the program wrote to its error output so far."""
        self.error_output.seek(0)
        return self.error_output.read().decode("utf-8")

    def finish(self) -> int:
        """Close the worker's input, wait for it to end, and return its exit code."""
        assert self.process.stdin is not None
        self.process.stdin.close()
        return self.process.wait(timeout=WAIT_SECONDS)

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait()
        for stream in (self.process.stdin, self.process.stdout):
            if stream is not None:
                stream.close()


PROGRAM = """\
import math

LIMIT = 26
POINT = (0.5, 0.5)
SETTINGS = {"bins": [10, 5]}
IMPORTED = math


def double(x, factor=2):
    return x * factor


def broken():
    return [][1]


def leave():
    raise SystemExit(3)


def unsendable():
    return {1, 2}


def shout(text):
    print("shouting", text)
    return text.upper()


def ask():
    return input()


if __name__ == "__main__":
    print("MAIN PART RAN")
"""


class TestLoading(unittest.TestCase):
    def test_loaded_lists_the_names_and_their_kinds(self) -> None:
        worker = Worker(self)
        answer = worker.load(PROGRAM)
        assert answer is not None
        self.assertEqual(answer["type"], "loaded")
        names = answer["names"]
        self.assertEqual(names["double"], "function")
        self.assertEqual(names["LIMIT"], "data")
        self.assertEqual(names["POINT"], "data")
        self.assertEqual(names["SETTINGS"], "data")
        self.assertEqual(names["IMPORTED"], "other")
        self.assertEqual(names["math"], "other")
        self.assertNotIn("__builtins__", names)

    def test_main_part_of_the_program_does_not_run(self) -> None:
        worker = Worker(self)
        worker.load(PROGRAM)
        worker.finish()
        self.assertNotIn("MAIN PART RAN", worker.errors())

    def test_program_that_raises_while_loading_fails_to_load(self) -> None:
        worker = Worker(self)
        answer = worker.load("x = 1\ny = x / 0\n")
        assert answer is not None
        self.assertEqual(answer["type"], "load_failed")
        self.assertEqual(answer["error"], "ZeroDivisionError: division by zero")
        self.assertIn('File "program.py", line 2', answer["traceback"])
        self.assertIn("y = x / 0", answer["traceback"])
        self.assertNotIn("sandbox_worker", answer["traceback"])
        self.assertEqual(worker.finish(), 0)

    def test_exit_while_loading_fails_to_load(self) -> None:
        for code in ("import sys\nsys.exit(0)\n", "raise KeyboardInterrupt\n"):
            with self.subTest(code=code):
                worker = Worker(self)
                answer = worker.load(code)
                assert answer is not None
                self.assertEqual(answer["type"], "load_failed")

    def test_missing_package_fails_to_load(self) -> None:
        worker = Worker(self)
        answer = worker.load("import package_that_does_not_exist\n")
        assert answer is not None
        self.assertEqual(answer["type"], "load_failed")
        self.assertIn("ModuleNotFoundError", answer["error"])

    def test_syntax_error_fails_to_load(self) -> None:
        worker = Worker(self)
        answer = worker.load("def broken(:\n")
        assert answer is not None
        self.assertEqual(answer["type"], "load_failed")
        self.assertIn("SyntaxError", answer["error"])


class TestCalls(unittest.TestCase):
    def setUp(self) -> None:
        self.worker = Worker(self)
        self.worker.load(PROGRAM)

    def test_call_returns_the_encoded_value(self) -> None:
        answer = self.worker.call("double", 21)
        assert answer is not None
        self.assertEqual(answer, {"type": "return", "id": 1, "value": 42})

    def test_arguments_by_name_and_tuples_arrive_intact(self) -> None:
        answer = self.worker.call("double", (1, 2), factor=2)
        assert answer is not None
        self.assertEqual(decode(answer["value"]), (1, 2, 1, 2))

    def test_plain_data_globals_can_be_read(self) -> None:
        answer = self.worker.get("POINT")
        assert answer is not None
        self.assertEqual(decode(answer["value"]), (0.5, 0.5))

    def test_exception_in_a_call_is_raised_with_its_traceback(self) -> None:
        answer = self.worker.call("broken")
        assert answer is not None
        self.assertEqual(answer["type"], "raised")
        self.assertEqual(answer["id"], 1)
        self.assertEqual(answer["error"], "IndexError: list index out of range")
        self.assertIn('File "program.py", line 14, in broken', answer["traceback"])

    def test_worker_keeps_answering_after_an_exception(self) -> None:
        self.worker.call("broken")
        answer = self.worker.call("double", 2)
        assert answer is not None
        self.assertEqual(answer["value"], 4)

    def test_exit_request_in_a_call_is_raised(self) -> None:
        answer = self.worker.call("leave")
        assert answer is not None
        self.assertEqual(answer["type"], "raised")
        self.assertEqual(answer["error"], "SystemExit: 3")

    def test_value_that_is_not_plain_data_is_raised(self) -> None:
        answer = self.worker.call("unsendable")
        assert answer is not None
        self.assertEqual(answer["type"], "raised")
        self.assertIn("NotPlainData", answer["error"])

    def test_missing_name_is_raised(self) -> None:
        answer = self.worker.call("run_packing")
        assert answer is not None
        self.assertEqual(answer["type"], "raised")
        self.assertIn("defines no name 'run_packing'", answer["error"])

    def test_calling_data_is_raised(self) -> None:
        answer = self.worker.call("LIMIT")
        assert answer is not None
        self.assertIn("LIMIT is not a function", answer["error"])

    def test_prints_go_to_the_error_output_not_the_protocol(self) -> None:
        answer = self.worker.call("shout", "hello")
        assert answer is not None
        self.assertEqual(answer["value"], "HELLO")
        self.worker.finish()
        self.assertIn("shouting hello", self.worker.errors())

    def test_program_cannot_read_the_protocol(self) -> None:
        answer = self.worker.call("ask")
        assert answer is not None
        self.assertEqual(answer["type"], "raised")
        self.assertIn("EOFError", answer["error"])
        follow_up = self.worker.call("double", 5)
        assert follow_up is not None
        self.assertEqual(follow_up["value"], 10)

    def test_worker_ends_when_its_input_ends(self) -> None:
        self.assertEqual(self.worker.finish(), 0)


class TestArraysThroughTheWorker(unittest.TestCase):
    def test_numpy_arrays_come_back_as_arrays(self) -> None:
        worker = Worker(self)
        worker.load(
            "import numpy as np\n"
            "def run_packing():\n"
            "    centres = np.full((26, 2), 0.5)\n"
            "    radii = np.full(26, 0.1)\n"
            "    return centres, radii, np.sum(radii)\n"
        )
        answer = worker.call("run_packing")
        assert answer is not None
        centres, radii, total = decode(answer["value"])
        self.assertEqual(centres.shape, (26, 2))
        self.assertEqual(radii.shape, (26,))
        self.assertAlmostEqual(total, 2.6)
        self.assertIsInstance(total, float)


if __name__ == "__main__":
    unittest.main()
