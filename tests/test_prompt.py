"""Checks the exact text of the prompt sent to the LLM (Appendix A)."""

import unittest

from my_evolve.problem import LLMSettings, ModelSettings, Problem, PromptSettings
from my_evolve.program import Program, Result, Status
from my_evolve.prompt import PromptBuilder

PROBLEM = Problem(
    name="toy",
    description="Write solve(), which returns a number up to 10.\n",
    llm=LLMSettings(
        models=(ModelSettings(name="some-model", api_base="http://localhost:11434/v1"),)
    ),
    packages=("numpy==2.5.4", "scipy==1.18.1"),
)

SYSTEM_MESSAGE = """\
You are an expert software engineer tasked with improving a program. You will see
a program to improve, the parent, and other programs tried before, with their
results. Write a new version of the parent that solves the problem below better
than it does, using what the previous attempts show.

# Problem
Write solve(), which returns a number up to 10.

# Rules
- Change only the code between `# EVOLVE-BLOCK-START` and `# EVOLVE-BLOCK-END`.
  Leave everything else, the markers included, exactly as it is. Return the whole file.
- You may import Python's standard library and: numpy, scipy. Nothing else is installed.
- Higher scores are better.

# Reply format
Your reply must contain these two parts. You may write anything else around them.
<DESCRIPTION>
How this program solves the problem: its approach and main ideas. Describe the
program on its own; do not mention any other program.
</DESCRIPTION>
```python
the complete program
```
"""


def working(code: str, score: float, description: str | None = None, feedback: str = "") -> Program:
    """Return a working program."""
    result = Result(Status.OK, score=score, feedback=feedback or None)
    return Program(code, result, description=description)


def failed(code: str, status: Status, error: str, feedback: str = "") -> Program:
    """Return a program that did not work."""
    return Program(code, Result.failure(status, error, feedback or None), description="Tries hard.")


class SystemMessageTest(unittest.TestCase):
    def test_the_exact_text(self) -> None:
        self.assertEqual(PromptBuilder(PROBLEM).system_message, SYSTEM_MESSAGE)

    def test_without_packages(self) -> None:
        problem = Problem(PROBLEM.name, PROBLEM.description, PROBLEM.llm)
        self.assertIn(
            "- You may import Python's standard library only. Nothing else is installed.\n",
            PromptBuilder(problem).system_message,
        )


class UserMessageTest(unittest.TestCase):
    def test_the_exact_text(self) -> None:
        """Previous attempts in the order given, working and failed, then the parent."""
        parent = working("x = 3\n", 3.0, "Returns three.", "solve() returned 3.")
        examples = [
            working("x = 1\n", 1.5, "Returns one.", "solve() returned 1.5."),
            failed("x = 11\n", Status.INVALID, "solve() returned 11, more than 10.0"),
        ]
        user = PromptBuilder(PROBLEM).build(parent, examples, best_score=4.0).user
        self.assertEqual(
            user,
            "# Previous attempts\n\n"
            "## Attempt 1: score 1.5\n"
            "Description: Returns one.\n"
            "Feedback: solve() returned 1.5.\n"
            "```python\nx = 1\n```\n\n"
            "## Attempt 2: invalid\n"
            "Description: Tries hard.\n"
            "Error: solve() returned 11, more than 10.0\n"
            "```python\nx = 11\n```\n\n"
            "# Program to improve (the parent): score 3.0; best score so far in this run: 4.0\n"
            "Description: Returns three.\n"
            "Feedback: solve() returned 3.\n"
            "```python\nx = 3\n```\n\n"
            "Write the improved program.\n",
        )

    def test_without_examples_or_fields(self) -> None:
        """No "Previous attempts" without examples; empty fields are left out with their label."""
        user = PromptBuilder(PROBLEM).build(working("x = 1\n", 0.5), [], best_score=0.5).user
        self.assertEqual(
            user,
            "# Program to improve (the parent): score 0.5; best score so far in this run: 0.5\n"
            "```python\nx = 1\n```\n\n"
            "Write the improved program.\n",
        )

    def test_a_parent_with_a_later_stage_error_shows_it(self) -> None:
        """An ok parent that failed a later cascade stage shows that error."""
        result = Result(Status.OK, score=0.7, error="stage 2: RuntimeError: boom")
        user = PromptBuilder(PROBLEM).build(Program("x = 1\n", result), [], 0.7).user
        self.assertIn("score 0.7; best score so far in this run: 0.7\nError: stage 2:", user)

    def test_feedback_and_errors_are_truncated(self) -> None:
        problem = Problem(
            PROBLEM.name,
            PROBLEM.description,
            PROBLEM.llm,
            prompt=PromptSettings(max_feedback_chars=10),
        )
        example = failed("x = 2\n", Status.FAILED, "E" * 11, feedback="  Short.  ")
        user = PromptBuilder(problem).build(working("x = 1\n", 0.5), [example], 0.5).user
        self.assertIn("Feedback: Short.\nError: EEEEEEEEEE… (truncated)\n```python", user)

    def test_braces_are_kept_as_written(self) -> None:
        """Code and descriptions containing braces reach the prompt unchanged."""
        problem = Problem(name="toy", description="Return {a: 1}.", llm=PROBLEM.llm)
        code = "def solve():\n    return len(f'{1}{{}}')\n"
        prompt = PromptBuilder(problem).build(working(code, 1.0, "Uses {braces}."), [], 1.0)
        self.assertIn("Return {a: 1}.", prompt.system)
        self.assertIn(code, prompt.user)
        self.assertIn("Description: Uses {braces}.", prompt.user)


class BudgetTest(unittest.TestCase):
    def builder(self, max_chars: int) -> PromptBuilder:
        problem = Problem(
            PROBLEM.name,
            PROBLEM.description,
            PROBLEM.llm,
            prompt=PromptSettings(max_chars=max_chars),
        )
        return PromptBuilder(problem)

    def test_examples_are_left_out_last_first(self) -> None:
        """Over the budget, the last example goes first, with a warning."""
        parent = working("x = 0\n", 0.5)
        examples = [working(f"x = {n}\n" + "#" * 500 + "\n", float(n)) for n in (1, 2, 3)]
        size = len(self.builder(10**6).build(parent, examples[:2], 3.0).user)
        builder = self.builder(len(SYSTEM_MESSAGE) + size)
        with self.assertLogs("my_evolve.prompt", "WARNING") as logs:
            user = builder.build(parent, examples, 3.0).user
        self.assertEqual(len(logs.output), 1)
        self.assertIn("## Attempt 2: score 2.0", user)
        self.assertNotIn("## Attempt 3", user)

    def test_a_prompt_over_budget_without_examples_is_kept(self) -> None:
        with self.assertLogs("my_evolve.prompt", "WARNING") as logs:
            user = self.builder(10).build(working("x = 0\n", 0.5), [], 0.5).user
        self.assertIn("even without example programs", logs.output[-1])
        self.assertIn("x = 0", user)


if __name__ == "__main__":
    unittest.main()
