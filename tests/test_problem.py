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
