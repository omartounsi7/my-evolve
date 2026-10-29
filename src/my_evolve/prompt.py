"""The prompt: the two messages sent to the LLM in each iteration.

The system message is the same for the whole run: the instruction, the problem, the
reply format. The user message changes every iteration: the example programs, then the
parent, the program to improve. Each program is shown with its score, its description,
the feedback the evaluation file wrote about it (cut to a size limit), and its code;
step 2.7 of the implementation plan gives the prompt its final text.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from my_evolve.problem import Problem, package_name
from my_evolve.program import Program

# The system message, with blanks for the problem's description and the allowed packages
SYSTEM_TEMPLATE = """\
You are an expert software engineer tasked with improving a program. You will see a \
program to improve, the parent, and other programs tried before, with their scores. \
Write a new version of the parent that solves the problem below better than it does.

# Problem
{description}

# Rules
- Change only the code between `# EVOLVE-BLOCK-START` and `# EVOLVE-BLOCK-END`. \
Leave everything else, the markers included, exactly as it is. Return the whole file.
- {packages_rule}
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

# The last words of the user message
REQUEST = "Write the improved program."


@dataclass(frozen=True)
class Prompt:
    """The two messages of one request to the LLM."""

    # What stays the same for the whole run
    system: str
    # What changes every iteration
    user: str


def packages_rule(packages: Sequence[str]) -> str:
    """Return the rule saying what the program may import: package names, without versions."""
    if not packages:
        return "You may import Python's standard library only. Nothing else is installed."
    names = ", ".join(package_name(package) for package in packages)
    return f"You may import Python's standard library and: {names}. Nothing else is installed."


def score_of(program: Program) -> float:
    """Return a program's score. Raises ValueError for a failed one: only working ones are shown."""
    if not program.result.is_ok or program.result.score is None:
        raise ValueError(f"program {program.id} has no score, so it cannot be shown in a prompt")
    return program.result.score


def truncated(text: str, limit: int) -> str:
    """Return the text if it fits in limit characters, otherwise its beginning and a mark."""
    return text if len(text) <= limit else text[:limit] + "… (truncated)"


def code_block(program: Program) -> str:
    """Return a program's code in a Python code block, without blank lines around it."""
    code = program.code.strip("\n")
    return f"```python\n{code}\n```"


class PromptBuilder:
    """Writes the prompt of each iteration for one problem."""

    def __init__(self, problem: Problem) -> None:
        """Write the system message, which stays the same for the whole run."""
        self.system_message: str = SYSTEM_TEMPLATE.format(
            description=problem.description.strip(), packages_rule=packages_rule(problem.packages)
        )
        # The longest feedback shown for one program, in characters
        self.max_feedback_chars: int = problem.prompt.max_feedback_chars

    def program_section(self, program: Program, heading: str) -> str:
        """Return one program's part of the user message: heading, description, feedback, code."""
        lines = [heading]
        if program.description:
            lines.append(f"Description: {program.description}")
        if program.result.feedback:
            feedback = truncated(program.result.feedback.strip(), self.max_feedback_chars)
            lines.append(f"Feedback: {feedback}")
        lines.append(code_block(program))
        return "\n".join(lines)

    def build(self, parent: Program, examples: Sequence[Program]) -> Prompt:
        """Return the prompt asking the LLM to improve parent, the example programs shown first.

        The code is added as it is, never through str.format, so braces in it are kept.
        Raises ValueError if a program shown has no score.
        """
        sections = []
        if examples:
            sections.append("# Previous attempts")
            for number, example in enumerate(examples, start=1):
                heading = f"## Attempt {number}: score {score_of(example)}"
                sections.append(self.program_section(example, heading))
        heading = f"# Program to improve (the parent): score {score_of(parent)}"
        sections.append(self.program_section(parent, heading))
        sections.append(REQUEST)
        return Prompt(system=self.system_message, user="\n\n".join(sections) + "\n")
