"""Checks the exact text of the prompt sent to the LLM."""

import unittest

from my_evolve.problem import LLMSettings, Problem, PromptSettings
from my_evolve.program import Program, Result, Status
from my_evolve.prompt import PromptBuilder

PROBLEM = Problem(
    name="toy",
    description="Write solve(), which returns a number up to 10.\n",
    llm=LLMSettings(model="some-model", api_base="http://localhost:11434/v1"),
)


def program(code: str, score: float | None) -> Program:
    """Return a program with that code and score (None for a failed program)."""
    if score is None:
        return Program(code, Result.failure(Status.FAILED, "Error: x"))
    return Program(code, Result(Status.OK, score=score))


class PromptTest(unittest.TestCase):
    def test_the_system_message(self) -> None:
        """The system message holds the instruction, the problem and the reply format."""
        system = PromptBuilder(PROBLEM).system_message
        self.assertTrue(system.startswith("You are an expert software engineer"))
        self.assertIn("# Problem\nWrite solve(), which returns a number up to 10.\n\n", system)
        self.assertIn(
            "# Rules\n- Change only the code between `# EVOLVE-BLOCK-START` and "
            "`# EVOLVE-BLOCK-END`. Leave everything else, the markers included, exactly as it "
            "is. Return the whole file.\n"
            "- You may import Python's standard library only. Nothing else is installed.\n"
            "- Higher scores are better.\n",
            system,
        )
        self.assertTrue(system.endswith("```python\nthe complete program\n```\n"))

    def test_the_allowed_packages_are_named_without_versions(self) -> None:
        """The rules name each package the program may import."""
        problem = Problem(
            PROBLEM.name, PROBLEM.description, PROBLEM.llm, ("numpy==2.5.4", "scipy==1")
        )
        self.assertIn(
            "- You may import Python's standard library and: numpy, scipy. "
            "Nothing else is installed.",
            PromptBuilder(problem).system_message,
        )

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

    def test_feedback_is_shown_and_truncated(self) -> None:
        """Each program's feedback follows its heading, cut to the size limit."""
        problem = Problem(
            PROBLEM.name,
            PROBLEM.description,
            PROBLEM.llm,
            prompt=PromptSettings(max_feedback_chars=10),
        )
        parent = Program("x = 1\n", Result(Status.OK, score=0.5, feedback="  Short.  "))
        example = Program("x = 2\n", Result(Status.OK, score=0.4, feedback="A" * 11))
        user = PromptBuilder(problem).build(parent, [example]).user
        self.assertIn("## Attempt 1: score 0.4\nFeedback: AAAAAAAAAA… (truncated)\n```python", user)
        self.assertIn("score 0.5\nFeedback: Short.\n```python\nx = 1\n```", user)

    def test_descriptions_are_shown_before_feedback(self) -> None:
        """A program's description, if it has one, comes right after its heading."""
        parent = Program(
            "x = 1\n", Result(Status.OK, score=0.5, feedback="Fine."), description="Rings."
        )
        user = PromptBuilder(PROBLEM).build(parent, []).user
        self.assertIn("score 0.5\nDescription: Rings.\nFeedback: Fine.\n```python", user)

    def test_the_reply_format_asks_for_a_description(self) -> None:
        """The system message asks for the two parts of the reply."""
        system = PromptBuilder(PROBLEM).system_message
        self.assertIn("<DESCRIPTION>\nHow this program solves the problem", system)
        self.assertIn("do not mention any other program.\n</DESCRIPTION>\n```python", system)

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
