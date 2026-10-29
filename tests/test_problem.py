"""Checks that problem files are read, and every mistake in them reported clearly."""

import tempfile
import unittest
from pathlib import Path
from typing import Any

from my_evolve.problem import Problem, ProblemError

REPOSITORY_FOLDER = Path(__file__).parent.parent


def valid_data() -> dict[str, Any]:
    """Return the parsed content of a correct problem file."""
    return {
        "name": "toy",
        "description": "Return a number.",
        "llm": {"model": "some-model", "api_base": "http://localhost:11434/v1"},
    }


class ProblemTest(unittest.TestCase):
    def test_a_correct_problem(self) -> None:
        """Every value of a correct file reaches the Problem."""
        problem = Problem.from_dict(valid_data())
        self.assertEqual(problem.name, "toy")
        self.assertEqual(problem.description, "Return a number.")
        self.assertEqual(problem.llm.model, "some-model")
        self.assertEqual(problem.llm.api_base, "http://localhost:11434/v1")

    def test_the_example_problem_files_load(self) -> None:
        """The repository's problem files are correct."""
        for path in [
            REPOSITORY_FOLDER / "examples" / "circle_packing" / "problem.yaml",
            Path(__file__).parent / "toy" / "problem.yaml",
        ]:
            with self.subTest(path=path.name):
                self.assertTrue(Problem.load(path).description)

    def test_an_unknown_key_is_refused_with_its_location(self) -> None:
        """A misspelt key is an error, not silently ignored."""
        data = valid_data()
        data["descripton"] = "typo"
        with self.assertRaisesRegex(ProblemError, "unknown key 'descripton' in the problem file"):
            Problem.from_dict(data)
        data = valid_data()
        data["llm"]["temperature"] = 0.7
        with self.assertRaisesRegex(ProblemError, "unknown key 'temperature' in the llm section"):
            Problem.from_dict(data)

    def test_the_stage_time_limit(self) -> None:
        """60 s by default; any number above 0 may be set."""
        self.assertEqual(Problem.from_dict(valid_data()).evaluation.stage_time_limit, 60.0)
        data = valid_data()
        data["evaluation"] = {"stage_time_limit": 5}
        self.assertEqual(Problem.from_dict(data).evaluation.stage_time_limit, 5.0)
        for wrong in [0, -1, "60", True]:
            data["evaluation"] = {"stage_time_limit": wrong}
            with self.subTest(value=wrong), self.assertRaisesRegex(ProblemError, "above 0"):
                Problem.from_dict(data)
        data["evaluation"] = {"thresholds": [0.5, 1]}
        self.assertEqual(Problem.from_dict(data).evaluation.thresholds, (0.5, 1.0))
        data["evaluation"] = {"thresholds": [0.5, "high"]}
        with self.assertRaisesRegex(ProblemError, "list of numbers"):
            Problem.from_dict(data)
        data["evaluation"] = {"time_limit": 5}
        with self.assertRaisesRegex(ProblemError, "unknown key 'time_limit' in the evaluation"):
            Problem.from_dict(data)

    def test_the_prompt_and_sandbox_sections(self) -> None:
        """Their defaults, and values that are refused."""
        problem = Problem.from_dict(valid_data())
        self.assertEqual(problem.prompt.max_feedback_chars, 2000)
        self.assertEqual(
            (problem.sandbox.memory, problem.sandbox.cpus, problem.sandbox.max_processes),
            ("1g", 1.0, 64),
        )
        data = valid_data()
        data["prompt"] = {"max_feedback_chars": 500}
        data["sandbox"] = {"memory": "512m", "cpus": 2, "max_processes": 32}
        problem = Problem.from_dict(data)
        self.assertEqual(problem.prompt.max_feedback_chars, 500)
        self.assertEqual(problem.sandbox.memory, "512m")
        for section, wrong in [
            ("prompt", {"max_feedback_chars": 0}),
            ("sandbox", {"memory": "lots"}),
            ("sandbox", {"cpus": -1}),
            ("sandbox", {"max_processes": 1.5}),
            ("sandbox", {"network": "none"}),
        ]:
            data = valid_data()
            data[section] = wrong
            with self.subTest(section=section, value=wrong), self.assertRaises(ProblemError):
                Problem.from_dict(data)

    def test_packages_need_exact_versions(self) -> None:
        """Only name==version entries: no ranges, no pip options, no duplicates."""
        data = valid_data()
        self.assertEqual(Problem.from_dict(data).packages, ())
        data["packages"] = ["numpy==2.5.4", "scikit-learn==1.8.0"]
        self.assertEqual(Problem.from_dict(data).packages, ("numpy==2.5.4", "scikit-learn==1.8.0"))
        for wrong in [["numpy"], ["numpy>=2"], ["--index-url=http://x"], ["-e ."], [3], "numpy"]:
            data["packages"] = wrong
            with self.subTest(packages=wrong), self.assertRaises(ProblemError):
                Problem.from_dict(data)
        data["packages"] = ["numpy==2.5.4", "NumPy==2.5.3"]
        with self.assertRaisesRegex(ProblemError, "listed twice"):
            Problem.from_dict(data)

    def test_a_missing_key_is_refused(self) -> None:
        """Each required key must be there."""
        data = valid_data()
        del data["llm"]["model"]
        with self.assertRaisesRegex(ProblemError, "missing key 'model' in the llm section"):
            Problem.from_dict(data)

    def test_values_must_be_text(self) -> None:
        """An empty description, or a section that is not a mapping, is refused."""
        data = valid_data()
        data["description"] = "  "
        with self.assertRaisesRegex(ProblemError, "'description' .* must be some text"):
            Problem.from_dict(data)
        data = valid_data()
        data["llm"] = "qwen3-coder:30b"
        with self.assertRaisesRegex(ProblemError, "the llm section must be a mapping"):
            Problem.from_dict(data)

    def test_errors_name_the_file(self) -> None:
        """Errors from load name the file; a file that is not a mapping is refused."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "problem.yaml"
            path.write_text("- just\n- a list\n", encoding="utf-8")
            with self.assertRaisesRegex(ProblemError, "problem.yaml: the problem file must be"):
                Problem.load(path)
            with self.assertRaisesRegex(ProblemError, "cannot be read"):
                Problem.load(Path(folder) / "missing.yaml")


if __name__ == "__main__":
    unittest.main()
