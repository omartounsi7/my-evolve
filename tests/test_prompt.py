"""Checks the exact text of the prompt sent to the LLM."""

import unittest

from my_evolve.problem import LLMSettings, Problem
from my_evolve.program import Program, Result
from my_evolve.prompt import PromptBuilder

PROBLEM = Problem(
    name="toy",
    description="Write solve(), which returns a number up to 10.\n",
    llm=LLMSettings(model="some-model", api_base="http://localhost:11434/v1"),
)


def program(code: str, score: float | None) -> Program:
    """Return a program with that code and score (None for a failed program)."""
    return Program(code, Result(score=score, error=None if score is not None else "Error: x"))


class PromptTest(unittest.TestCase):
    def test_the_system_message(self) -> None:
        """The system message holds the instruction, the problem and the reply format."""
        system = PromptBuilder(PROBLEM).system_message
        self.assertTrue(system.startswith("You are an expert software engineer"))
        self.assertIn("# Problem\nWrite solve(), which returns a number up to 10.\n\n", system)
        self.assertIn("Higher scores are better.", system)
        self.assertTrue(system.endswith("in a single ```python code block.\n"))

    def test_the_user_message_with_examples(self) -> None:
        """The examples come first, in the order given, then the parent, then the request."""
        parent = program("def solve():\n    return 3\n", 3.0)
        examples = [program("def solve():\n    return 1\n", 1.0), program("\n\nA = 2\n", 2.5)]
        prompt = PromptBuilder(PROBLEM).build(parent, examples)
        self.assertEqual(
            prompt.user,
            "# Previous attempts\n\n"
            "## Attempt 1: score 1.0\n```python\ndef solve():\n    return 1\n```\n\n"
            "## Attempt 2: score 2.5\n```python\nA = 2\n```\n\n"
            "# Program to improve (the parent): score 3.0\n"
            "```python\ndef solve():\n    return 3\n```\n\n"
            "Write the improved program.\n",
        )
        self.assertEqual(prompt.system, PromptBuilder(PROBLEM).system_message)

    def test_the_user_message_without_examples(self) -> None:
        """Without examples, there is no "Previous attempts" section."""
        prompt = PromptBuilder(PROBLEM).build(program("x = 1\n", 0.5), [])
        self.assertEqual(
            prompt.user,
            "# Program to improve (the parent): score 0.5\n```python\nx = 1\n```\n\n"
            "Write the improved program.\n",
        )

    def test_braces_are_kept_as_written(self) -> None:
        """Code and descriptions containing braces reach the prompt unchanged."""
        problem = Problem(name="toy", description="Return {a: 1}.", llm=PROBLEM.llm)
        code = "def solve():\n    return len(f'{1}{{}}')\n"
        prompt = PromptBuilder(problem).build(program(code, 1.0), [])
        self.assertIn("Return {a: 1}.", prompt.system)
        self.assertIn(code, prompt.user)

    def test_a_failed_program_cannot_be_shown(self) -> None:
        """Only working programs are shown, for now."""
        with self.assertRaisesRegex(ValueError, "has no score"):
            PromptBuilder(PROBLEM).build(program("x = (\n", None), [])


if __name__ == "__main__":
    unittest.main()
