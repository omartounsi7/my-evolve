"""Checks the prompt's two messages against Appendix A of design-decisions.md."""

import unittest
from typing import Any

from my_evolve.problem import Problem
from my_evolve.program import LLMUsage, Program, Result, Status
from my_evolve.prompt import PromptBuilder, format_score

CODE = """\
# EVOLVE-BLOCK-START
def build():
    return {"radii": [0.1] * 26}
# EVOLVE-BLOCK-END


def run():
    return build()
"""

USAGE = LLMUsage(model="m", input_tokens=1, output_tokens=1, duration=1.0)


def make_problem(**changes: Any) -> Problem:
    data: dict[str, Any] = {
        "name": "test",
        "description": "Pack 26 circles.\nrun() returns {centers, radii}.\n",
        "entry_functions": ["run"],
        "packages": ["numpy==2.5.4", "scipy==1.18.1"],
        "llm": {"models": [{"name": "m", "api_base": "http://localhost:1/v1"}]},
    }
    data.update(changes)
    return Problem.from_dict(data)


def parent_with(result: Result, description: str | None = "Equal circles on a grid.") -> Program:
    """Return a child of the initial program, to be used as a parent."""
    initial = Program.initial(CODE, Result(Status.OK, score=0.1), None, None)
    return Program.new_child(
        initial,
        code=CODE,
        result=result,
        island=0,
        iteration=3,
        description=description,
        fingerprint=None,
        code_complexity=None,
        example_ids=(),
        llm=USAGE,
    )


EXPECTED_SYSTEM = """\
You are an expert software engineer tasked with improving a program. You will see
a program to improve, the parent, and other programs tried before, with their
results. Write a new version of the parent that solves the problem below better
than it does, using what the previous attempts show.

# Problem
Pack 26 circles.
run() returns {centers, radii}.

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
```"""

EXPECTED_USER = """\
# Program to improve (the parent): score 0.3642368945; best score so far in this run: 0.9487666034
Description: Equal circles on a grid.
Feedback: All circles are inside the square.
```python
# EVOLVE-BLOCK-START
def build():
    return {"radii": [0.1] * 26}
# EVOLVE-BLOCK-END


def run():
    return build()
```

Write the improved program.
"""


class TestPrompt(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = PromptBuilder(make_problem())
        self.result = Result(
            Status.OK, score=0.36423689449571406, feedback="All circles are inside the square."
        )

    def test_messages_are_those_of_appendix_a(self) -> None:
        prompt = self.builder.build(parent_with(self.result), best_score=0.9487666034155601)
        self.assertEqual(prompt.system, EXPECTED_SYSTEM)
        self.assertEqual(prompt.user, EXPECTED_USER)

    def test_system_message_is_the_same_for_every_iteration(self) -> None:
        first = self.builder.build(parent_with(self.result), 0.5)
        second = self.builder.build(parent_with(Result(Status.OK, score=0.2)), 0.7)
        self.assertEqual(first.system, second.system)
        self.assertNotEqual(first.user, second.user)

    def test_empty_fields_are_left_out_with_their_labels(self) -> None:
        prompt = self.builder.build(parent_with(Result(Status.OK, score=0.5), None), 0.5)
        self.assertNotIn("Description:", prompt.user)
        self.assertNotIn("Feedback:", prompt.user)
        self.assertNotIn("Error:", prompt.user)

    def test_error_of_a_later_stage_is_shown(self) -> None:
        result = Result(Status.OK, score=0.6, error="stage 2: IndexError: list index out of range")
        prompt = self.builder.build(parent_with(result), 0.6)
        self.assertIn("Error: stage 2: IndexError: list index out of range\n```python", prompt.user)

    def test_parent_comes_last_just_before_the_request(self) -> None:
        user = self.builder.build(parent_with(self.result), 0.5).user
        self.assertTrue(user.startswith("# Program to improve (the parent)"))
        self.assertTrue(user.endswith("```\n\nWrite the improved program.\n"))

    def test_long_feedback_and_errors_are_cut(self) -> None:
        builder = PromptBuilder(make_problem(prompt={"max_feedback_chars": 10}))
        result = Result(Status.OK, score=0.5, feedback="f" * 50, error="e" * 50)
        user = builder.build(parent_with(result), 0.5).user
        self.assertIn("Feedback: ffffffffff… (truncated)\n", user)
        self.assertIn("Error: eeeeeeeeee… (truncated)\n", user)

    def test_text_at_the_limit_is_kept_whole(self) -> None:
        builder = PromptBuilder(make_problem(prompt={"max_feedback_chars": 10}))
        self.assertEqual(builder.truncated("f" * 10), "f" * 10)

    def test_braces_in_code_and_descriptions_are_kept_as_written(self) -> None:
        parent = parent_with(self.result, description="Uses {placeholders} and {0}.")
        prompt = self.builder.build(parent, 0.5)
        self.assertIn('return {"radii": [0.1] * 26}', prompt.user)
        self.assertIn("Description: Uses {placeholders} and {0}.", prompt.user)
        self.assertIn("run() returns {centers, radii}.", prompt.system)

    def test_packages_are_named_without_their_versions(self) -> None:
        self.assertIn("and: numpy, scipy. Nothing else", self.builder.system_message)
        self.assertNotIn("2.5.4", self.builder.system_message)

    def test_problem_without_packages_allows_the_standard_library_only(self) -> None:
        system = PromptBuilder(make_problem(packages=[])).system_message
        self.assertIn("- You may import Python's standard library only.", system)

    def test_scores_show_ten_significant_digits(self) -> None:
        self.assertEqual(format_score(1.0003709277995376), "1.000370928")
        self.assertEqual(format_score(0.5), "0.5")
        self.assertEqual(format_score(None), "none")


if __name__ == "__main__":
    unittest.main()
