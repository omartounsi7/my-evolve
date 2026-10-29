"""The prompt: what the LLM is asked in each iteration (D25 to D30, Appendix A).

Two messages. The system message holds what stays the same for a whole run (the
instruction, the problem, the rules and the reply format), so providers can cache
it. The user message holds what changes: the parent, last, just before the request,
since models attend most to the end of a prompt.

The templates are plain Python strings filled with str.format (D29); their text is
Appendix A of design-decisions.md. Values filled in are never read as templates, so
braces in code or descriptions are kept as written.
"""

from dataclasses import dataclass

from my_evolve.problem import Problem, PromptSettings
from my_evolve.program import Program

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

# Reply format
Your reply must contain these two parts. You may write anything else around them.
<DESCRIPTION>
How this program solves the problem: its approach and main ideas. Write it for a
reader who has never seen any other version: do not compare it with the parent or
any earlier program, and do not use words such as "improved", "enhanced", "now",
"instead", "previous" or "original".
</DESCRIPTION>
```python
the complete program
```"""

# The rule naming the packages programs may import (D71).
PACKAGES_RULE = (
    "You may import Python's standard library and: {packages}. Nothing else is installed."
)
NO_PACKAGES_RULE = "You may import Python's standard library only. Nothing else is installed."

PARENT_HEADING = (
    "# Program to improve (the parent): score {score}; best score so far in this run: {best}"
)
REQUEST = "Write the improved program."

# Added to a feedback or an error cut to the size limit (D30).
TRUNCATION_MARK = "… (truncated)"


@dataclass(frozen=True)
class Prompt:
    """The two messages of one LLM call."""

    system: str
    user: str


def format_score(score: float | None) -> str:
    """Write a score with up to 10 significant digits, enough to see small improvements."""
    return "none" if score is None else f"{score:.10g}"


class PromptBuilder:
    """Builds the prompt of each iteration of a run (D67)."""

    def __init__(self, problem: Problem) -> None:
        """Write the system message, the same for the whole run."""
        if problem.package_names:
            packages_rule = PACKAGES_RULE.format(packages=", ".join(problem.package_names))
        else:
            packages_rule = NO_PACKAGES_RULE
        self.system_message: str = SYSTEM_TEMPLATE.format(
            description=problem.description.strip(), packages_rule=packages_rule
        )
        self.settings: PromptSettings = problem.prompt

    def build(self, parent: Program, best_score: float) -> Prompt:
        """Return the prompt of one iteration: the parent with its score and the run's best."""
        heading = PARENT_HEADING.format(
            score=format_score(parent.result.score), best=format_score(best_score)
        )
        sections = [self.program_section(parent, heading), REQUEST]
        return Prompt(system=self.system_message, user="\n\n".join(sections) + "\n")

    def program_section(self, program: Program, heading: str) -> str:
        """Return one program's part of the user message.

        The heading, then its description, feedback and error when it has them (an
        empty field is left out with its label), then its code.
        """
        lines = [heading]
        if program.description:
            lines.append(f"Description: {program.description.strip()}")
        if program.result.feedback:
            lines.append(f"Feedback: {self.truncated(program.result.feedback.strip())}")
        if program.result.error:
            lines.append(f"Error: {self.truncated(program.result.error.strip())}")
        lines.append(f"```python\n{program.code.rstrip()}\n```")
        return "\n".join(lines)

    def truncated(self, text: str) -> str:
        """Return the text, cut to max_feedback_chars with a mark if it is longer (D10)."""
        limit = self.settings.max_feedback_chars
        if len(text) <= limit:
            return text
        return text[:limit] + TRUNCATION_MARK
