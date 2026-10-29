"""The prompt: the two messages sent to the LLM in each iteration.

The system message is the same for the whole run: the instruction, the problem, the
reply format. The user message changes every iteration: the example programs, then the
parent, the program to improve. For now each program is shown with its score and its
code only; step 2.7 of the implementation plan gives the prompt its final text.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from my_evolve.problem import Problem
from my_evolve.program import Program

# The system message, with a blank for the problem's description
SYSTEM_TEMPLATE = """\
You are an expert software engineer tasked with improving a program. You will see a \
program to improve, the parent, and other programs tried before, with their scores. \
Write a new version of the parent that solves the problem below better than it does. \
Higher scores are better.

# Problem
{description}

# Reply format
Reply with the complete new program in a single ```python code block.
"""

# The last words of the user message
REQUEST = "Write the improved program."


@dataclass(frozen=True)
class Prompt:
    """The two messages of one request to the LLM."""

    # What stays the same for the whole run
    system: str
    # What changes every iteration
    user: str


def score_of(program: Program) -> float:
    """Return a program's score. Raises ValueError for a failed one: only working ones are shown."""
    if program.result.score is None:
        raise ValueError(f"program {program.id} has no score, so it cannot be shown in a prompt")
    return program.result.score


def code_block(program: Program) -> str:
    """Return a program's code in a Python code block, without blank lines around it."""
    code = program.code.strip("\n")
    return f"```python\n{code}\n```"


class PromptBuilder:
    """Writes the prompt of each iteration for one problem."""

    def __init__(self, problem: Problem) -> None:
        """Write the system message, which stays the same for the whole run."""
        self.system_message: str = SYSTEM_TEMPLATE.format(description=problem.description.strip())

    def build(self, parent: Program, examples: Sequence[Program]) -> Prompt:
        """Return the prompt asking the LLM to improve parent, the example programs shown first.

        The code is added as it is, never through str.format, so braces in it are kept.
        Raises ValueError if a program shown has no score.
        """
        sections = []
        if examples:
            sections.append("# Previous attempts")
            for number, example in enumerate(examples, start=1):
                sections.append(
                    f"## Attempt {number}: score {score_of(example)}\n{code_block(example)}"
                )
        sections.append(
            f"# Program to improve (the parent): score {score_of(parent)}\n{code_block(parent)}"
        )
        sections.append(REQUEST)
        return Prompt(system=self.system_message, user="\n\n".join(sections) + "\n")
