"""Checks scripts/run.py from the outside, as a user runs it: arguments, messages, and stopping.

Each test starts the script as a process, with the loop tests' tiny problem, the fake
LLM server and the local sandbox. The Ctrl+C and SIGTERM tests need Linux or macOS.
"""

import os
import queue
import signal
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

from fake_llm_server import FakeLLMServer, serve
from test_loop import LoopTestCase, program_returning, reply_with

from my_evolve.storage import Storage

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "run.py"
# The longest a test waits for the script, in seconds.
PATIENCE = 60


class Script:
    """The script running as a process, its output read line by line as it comes."""

    def __init__(
        self, arguments: list[str], cwd: Path, environment: dict[str, str] | None = None
    ) -> None:
        self.process = subprocess.Popen(
            [sys.executable, str(SCRIPT), *arguments],
            cwd=cwd,
            env={**os.environ, **(environment or {})},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.lines: list[str] = []
        self.new_lines: queue.Queue[str | None] = queue.Queue()
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()

    def read(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self.lines.append(line)
            self.new_lines.put(line)
        self.new_lines.put(None)

    def wait_for(self, text: str, timeout: float = PATIENCE) -> None:
        """Wait until a line holding text has been written; fail if the script ends first."""
        if any(text in line for line in self.lines):
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = self.new_lines.get(timeout=deadline - time.monotonic())
            except queue.Empty:
                break
            if line is None:
                raise AssertionError(f"the script ended without writing {text!r}:\n{self.output}")
            if text in line:
                return
        raise AssertionError(f"no line with {text!r} after {timeout} s:\n{self.output}")

    def finish(self, timeout: float = PATIENCE) -> int:
        """Wait for the script to end and return its exit code."""
        code = self.process.wait(timeout=timeout)
        self.reader.join(timeout=5)
        return code

    def kill(self) -> None:
        """Stop the script if it still runs, and close its output."""
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait()
        self.reader.join(timeout=5)
        if self.process.stdout is not None:
            self.process.stdout.close()

    @property
    def output(self) -> str:
        return "".join(self.lines)


class ScriptTestCase(LoopTestCase):
    def start(self, server: FakeLLMServer, *flags: str, **environment: str) -> Script:
        """Start the script on the test problem."""
        arguments = [
            str(self.folder / "initial_program.py"),
            str(self.folder / "evaluation.py"),
            "--config",
            str(self.write_problem(server)),
            "--unsafe-local-sandbox",
            *flags,
        ]
        script = Script(arguments, self.folder, environment)
        self.addCleanup(script.kill)
        return script

    def run_script(self, server: FakeLLMServer, *flags: str, **environment: str) -> tuple[int, str]:
        script = self.start(server, *flags, **environment)
        return script.finish(), script.output


class TestRunScript(ScriptTestCase):
    def test_runs_the_problem_end_to_end(self) -> None:
        server = serve(self, ["OK", reply_with("2"), reply_with("3")])
        code, output = self.run_script(
            server, "--iterations", "2", "--output", "run", "--seed", "4"
        )
        self.assertEqual(code, 0, output)
        self.assertIn("Iteration 2/2", output)
        self.assertIn("Run finished: 2 iterations completed.", output)
        self.assertEqual(len(Storage(self.folder / "run").load_history()), 2)

    def test_run_folder_defaults_to_runs_name_date_and_time(self) -> None:
        server = serve(self, ["OK", reply_with("2")])
        code, output = self.run_script(server, "--iterations", "1")
        self.assertEqual(code, 0, output)
        (folder,) = (self.folder / "runs").iterdir()
        self.assertRegex(folder.name, r"^test_\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d$")

    def test_wrong_values_are_usage_errors(self) -> None:
        server = serve(self, ["OK"])
        for flags, message in (
            (["--iterations", "0"], "must be at least 1"),
            (["--workers", "two"], "must be a whole number"),
        ):
            with self.subTest(flags=flags):
                code, output = self.run_script(server, *flags)
                self.assertEqual(code, 2)
                self.assertIn(message, output)

    def test_missing_file_is_a_usage_error(self) -> None:
        script = Script(["absent.py", "evaluation.py", "--config", "problem.yaml"], self.folder)
        self.addCleanup(script.kill)
        self.assertEqual(script.finish(), 2)
        self.assertIn("no such file: absent.py", script.output)

    def test_problem_file_error_is_one_message_without_a_traceback(self) -> None:
        server = serve(self, ["OK"])
        problem = self.write_problem(server)
        problem.write_text(problem.read_text(encoding="utf-8") + "grid: {}\n", encoding="utf-8")
        script = Script(
            [
                str(self.folder / "initial_program.py"),
                str(self.folder / "evaluation.py"),
                "--config",
                str(problem),
            ],
            self.folder,
        )
        self.addCleanup(script.kill)
        self.assertEqual(script.finish(), 1)
        self.assertIn("my-evolve:", script.output)
        self.assertIn("unknown key 'grid'", script.output)
        self.assertNotIn("Traceback", script.output)

    def test_initial_program_that_fails_is_one_message(self) -> None:
        (self.folder / "initial_program.py").write_text(program_returning("-1"), encoding="utf-8")
        code, output = self.run_script(serve(self, ["OK"]), "--output", "run")
        self.assertEqual(code, 1)
        self.assertIn("my-evolve: the initial program must work, but it is invalid", output)
        self.assertNotIn("Traceback", output)

    def test_api_key_appears_in_no_output_and_no_file(self) -> None:
        secret = "sk-my-evolve-test-secret"
        server = serve(self, ["OK", reply_with("2")])
        problem = self.write_problem(server)
        text = problem.read_text(encoding="utf-8").replace(
            "  retries: 0\n", "  retries: 0\n  api_key: ${MY_EVOLVE_TEST_KEY}\n"
        )
        problem.write_text(text, encoding="utf-8")
        script = Script(
            [str(self.folder / "initial_program.py"), str(self.folder / "evaluation.py"),
             "--config", str(problem), "--unsafe-local-sandbox", "--iterations", "1",
             "--output", "run", "--verbose"],
            self.folder,
            {"MY_EVOLVE_TEST_KEY": secret},
        )  # fmt: skip
        self.addCleanup(script.kill)
        self.assertEqual(script.finish(), 0, script.output)
        self.assertEqual(server.requests[0]["authorization"], f"Bearer {secret}")
        self.assertNotIn(secret, script.output)
        for path in (self.folder / "run").rglob("*"):
            if path.is_file():
                self.assertNotIn(secret, path.read_text(encoding="utf-8"), path.name)

    def test_characters_outside_the_console_encoding_are_shown(self) -> None:
        reply = reply_with("0").replace("return 0", "raise ValueError('été ✓')")
        server = serve(self, ["OK", reply])
        code, output = self.run_script(
            server, "--iterations", "1", "--output", "run", PYTHONIOENCODING="ascii"
        )
        self.assertEqual(code, 0, output)
        self.assertIn("ValueError: été ✓", output)


@unittest.skipIf(sys.platform == "win32", "sends POSIX signals")
class TestStopping(ScriptTestCase):
    def stop_reason(self) -> str | None:
        info = Storage(self.folder / "run").read_run_info()
        assert info is not None
        return info.sessions[-1].end

    def start_slow_run(self, delay: float, *flags: str) -> Script:
        """Start a long run on a slow LLM, and wait until its first iterations are in flight."""
        server = serve(self, ["OK", reply_with("2")], delay=delay)
        script = self.start(server, "--iterations", "50", "--output", "run", *flags)
        script.wait_for("The model test-model answered")
        # Delay of the start-up check, then the first requests are in flight.
        time.sleep(0.5)
        return script

    def test_first_ctrl_c_finishes_the_iterations_in_progress(self) -> None:
        script = self.start_slow_run(2.0, "--workers", "2")
        script.process.send_signal(signal.SIGINT)
        script.wait_for("Ctrl+C: no new iteration starts; the 2 in progress finish")
        self.assertEqual(script.finish(), 0, script.output)
        self.assertEqual(len(Storage(self.folder / "run").load_history()), 2)
        self.assertEqual(self.stop_reason(), "stopped by the user (Ctrl+C)")

    def test_second_ctrl_c_stops_at_once(self) -> None:
        script = self.start_slow_run(30.0)
        script.process.send_signal(signal.SIGINT)
        script.wait_for("Ctrl+C: no new iteration starts")
        started = time.monotonic()
        script.process.send_signal(signal.SIGINT)
        # The LLM call in progress would take 30 s more: it is not waited for.
        self.assertEqual(script.finish(timeout=10), 130, script.output)
        self.assertLess(time.monotonic() - started, 5)
        self.assertIn("Stopped at once", script.output)
        self.assertEqual(self.stop_reason(), "interrupted")

    def test_sigterm_stops_at_once_and_kills_the_evaluations_in_progress(self) -> None:
        slow_program = reply_with("0").replace("return 0", "__import__('time').sleep(300)")
        server = serve(self, ["OK", slow_program])
        script = self.start(server, "--iterations", "5", "--output", "run")
        script.wait_for("The model test-model answered")
        # Let the slow child's evaluation start.
        time.sleep(2)
        started = time.monotonic()
        script.process.send_signal(signal.SIGTERM)
        self.assertEqual(script.finish(timeout=10), 130, script.output)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(self.stop_reason(), "interrupted")
        leftovers = subprocess.run(
            ["pgrep", "-f", "my_evolve.sandbox_worker"], capture_output=True, text=True, check=False
        ).stdout.split()
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
