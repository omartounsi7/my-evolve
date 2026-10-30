"""The prompt: the two messages sent to the LLM in each iteration (Appendix A).

The system message is the same for the whole run, so providers can cache it: the
instruction, the problem, the rules, the reply format. The user message changes every
iteration: the example programs, shown as previous attempts, then the parent, the
program to improve, then the request. Each program is shown with its score (or its
status if it failed), its description, the feedback the evaluation file wrote about it,
its error if it has one, and its code. Feedback and errors are cut to a size limit, and
the whole prompt to a character budget, by leaving out examples, last first (D30).
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from my_evolve.problem import Problem, package_name
from my_evolve.program import Program

logger = logging.getLogger(__name__)

# The system message, with blanks for the problem's description and the allowed packages
SYSTEM_TEMPLATE = """\
You are an expert software engineer tasked with improving a program. You will see
a program to improve, the parent, and other programs tried before, with their
results. Write a new version of the parent that solves the problem below better
than it does, using what the previous attempts show.

# Problem
{description}

# Rules
- Change only the code between `# EVOLVE-BLOCK-START` and `# EVOLVE-BLOCK-END`.
  Leave everything else, the markers included, exactly as it is. Return the whole file.
- {packages_rule}
- Higher scores are better.
- In the description, say what the program does, for a reader who has never seen any
  other version of it. Never compare it with another program: no "improved",
  "enhanced", "better than", "original", "previous" or "instead of".

# Reply format
Your reply must contain these two parts. You may write anything else around them.
<DESCRIPTION>
The program's approach and main ideas, in a few sentences.
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
    # The example programs the user message shows, after the budget left some out
    example_ids: tuple[str, ...] = ()


def packages_rule(packages: Sequence[str]) -> str:
    """Return the rule saying what the program may import: package names, without versions."""
    if not packages:
        return "You may import Python's standard library only. Nothing else is installed."
    names = ", ".join(package_name(package) for package in packages)
    return f"You may import Python's standard library and: {names}. Nothing else is installed."


def outcome_of(program: Program) -> str:
    """Return how a program's evaluation ended, for its heading: its score, or its status."""
    if program.result.score is not None:
        return f"score {program.result.score}"
    return program.result.status.value


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
        # The longest feedback or error shown for one program, in characters
        self.max_feedback_chars: int = problem.prompt.max_feedback_chars
        # The longest prompt, both messages together, in characters
        self.max_chars: int = problem.prompt.max_chars

    def program_section(self, program: Program, heading: str) -> str:
        """Return one program's part of the user message.

        Its heading, then its description, feedback and error, each left out with its
        label when empty, then its code.
        """
        lines = [heading]
        if program.description:
            lines.append(f"Description: {program.description}")
        if program.result.feedback:
            feedback = truncated(program.result.feedback.strip(), self.max_feedback_chars)
            lines.append(f"Feedback: {feedback}")
        if program.result.error:
            error = truncated(program.result.error.strip(), self.max_feedback_chars)
            lines.append(f"Error: {error}")
        lines.append(code_block(program))
        return "\n".join(lines)

    def user_message(
        self, parent: Program, examples: Sequence[Program], best_score: float | None
    ) -> str:
        """Return the user message: the examples as previous attempts, the parent, the request.

        The code is added as it is, never through str.format, so braces in it are kept.
        """
        sections = []
        if examples:
            sections.append("# Previous attempts")
            for number, example in enumerate(examples, start=1):
                heading = f"## Attempt {number}: {outcome_of(example)}"
                sections.append(self.program_section(example, heading))
        heading = f"# Program to improve (the parent): {outcome_of(parent)}"
        if best_score is not None:
            heading += f"; best score so far in this run: {best_score}"
        sections.append(self.program_section(parent, heading))
        sections.append(REQUEST)
        return "\n\n".join(sections) + "\n"

    def build(
        self, parent: Program, examples: Sequence[Program], best_score: float | None
    ) -> Prompt:
        """Return the prompt asking the LLM to improve parent, the example programs shown first.

        Over the character budget, examples are left out, last first, with a warning; a
        prompt still over it without any example is kept, with a warning.
        """
        shown = list(examples)
        user = self.user_message(parent, shown, best_score)
        while len(self.system_message) + len(user) > self.max_chars and shown:
            shown.pop()
            logger.warning(
                "The prompt is over its budget of %d characters: one example program left out",
                self.max_chars,
            )
            user = self.user_message(parent, shown, best_score)
        if len(self.system_message) + len(user) > self.max_chars:
            logger.warning(
                "The prompt is over its budget of %d characters, even without example programs",
                self.max_chars,
            )
        return Prompt(self.system_message, user, tuple(example.id for example in shown))
