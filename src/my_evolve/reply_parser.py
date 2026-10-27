"""Turns the LLM's reply, which is plain text, into a description and a program (D68).

The prompt asks for a description between <DESCRIPTION> and </DESCRIPTION>, and
the complete program in a code block (Appendix A). Models do not always comply:
they think aloud, quote the parent, add snippets or sample output, or are cut
off. These functions take the description and the most likely program from
whatever comes back; anything else in the reply is ignored.
"""

import ast
import re
from dataclasses import dataclass

from my_evolve.checks import fingerprint

# A code block: a line starting with three backticks (and an optional language name),
# the code, and a line holding only three backticks. Backticks inside the code that
# do not stand alone on their line do not end the block.
#   ^[ \t]*```      opening backticks at the start of a line
#   [^\n`]*\n       optional language name, such as "python"
#   (.*?)           the code (the part kept), as short as possible
#   ^[ \t]*```[ \t]*$   closing backticks, alone on their line
# DOTALL lets the code span several lines; MULTILINE makes ^ and $ match at every line.
CODE_BLOCK_PATTERN = re.compile(
    r"^[ \t]*```[^\n`]*\n(.*?)^[ \t]*```[ \t]*$", re.DOTALL | re.MULTILINE
)

# A code block on a single line: ```code```.
ONE_LINE_CODE_BLOCK_PATTERN = re.compile(r"```(.+?)```")

# A code block that is opened but never closed (a reply that was cut short).
UNCLOSED_CODE_BLOCK_PATTERN = re.compile(r"^[ \t]*```[^\n`]*\n(.*)", re.DOTALL | re.MULTILINE)

# Everything from the first opening line of backticks to the last closing one.
# Unlike CODE_BLOCK_PATTERN, (.*) is greedy: it takes as much as it can.
WIDEST_CODE_BLOCK_PATTERN = re.compile(
    r"^[ \t]*```[^\n`]*\n(.*)^[ \t]*```[ \t]*$", re.DOTALL | re.MULTILINE
)

# The reasoning some models write before the answer, which is not part of the program.
THINKING_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
# What is left of a thinking section whose opening tag was in the prompt, not the
# reply (Qwen3 and DeepSeek-R1 templates do this): everything up to a lone closing tag.
LONE_THINKING_END_PATTERN = re.compile(r".*</think>", re.DOTALL | re.IGNORECASE)
# A thinking section that was never closed (a reply cut off while thinking).
UNCLOSED_THINKING_PATTERN = re.compile(r"<think>.*", re.DOTALL | re.IGNORECASE)

# The program's description, as Appendix A asks for it. The first one is kept.
DESCRIPTION_PATTERN = re.compile(r"<DESCRIPTION>(.*?)</DESCRIPTION>", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True)
class ParsedReply:
    """What a reply holds: the program and its description, either possibly missing."""

    # The program, ending with one newline; None if the reply holds no code.
    code: str | None
    # How the program solves the problem (D15); None if the reply gives none.
    description: str | None


def parse_reply(reply: str, parent_code: str | None) -> ParsedReply:
    """Return the description and the program of an LLM's reply.

    A code block that merely repeats parent_code is not taken for the program.
    """
    text = remove_thinking(reply)
    description, rest = extract_description(text)
    return ParsedReply(code=extract_code(rest, parent_code), description=description)


def remove_thinking(text: str) -> str:
    """Remove the reasoning a thinking model writes before its answer.

    Three shapes are handled: <think>...</think>; a lone </think>, whose opening tag
    was part of the prompt (everything before it goes); and a <think> that was never
    closed because the reply was cut off (everything after it goes).
    """
    text = THINKING_PATTERN.sub("", text)
    text = LONE_THINKING_END_PATTERN.sub("", text, count=1)
    return UNCLOSED_THINKING_PATTERN.sub("", text, count=1)


def extract_description(text: str) -> tuple[str | None, str]:
    """Return the first description of a text, and the text without it.

    Taking the description out means that code quoted inside it is never taken
    for the program. With no complete <DESCRIPTION> section, there is no
    description and the text is returned unchanged.
    """
    match = DESCRIPTION_PATTERN.search(text)
    if match is None:
        return None, text
    description = match.group(1).strip() or None
    return description, text[: match.start()] + text[match.end() :]


def is_valid_python(code: str) -> bool:
    """Tell whether a piece of text is valid Python. The code is only parsed, not run."""
    try:
        ast.parse(code)
    except (SyntaxError, ValueError):
        return False
    return True


def fingerprint_of(code: str) -> str | None:
    """Return the fingerprint of a piece of code, or None if it is not valid Python."""
    try:
        return fingerprint(ast.parse(code))
    except (SyntaxError, ValueError):
        return None


def choose_code_block(code_blocks: list[str], text: str, parent_code: str | None) -> str:
    """Return the code block of a reply most likely to be the new program.

    A reply can hold several blocks (the original program quoted back, sample
    output, small snippets). Three rules apply in turn, each only if it leaves a block:

    1. keep the blocks that are valid Python;
    2. drop the blocks that are the same program as the parent (same syntax tree);
    3. keep the longest block.
    """
    candidates = [block for block in code_blocks if is_valid_python(block)]
    if not candidates:
        widest_block = WIDEST_CODE_BLOCK_PATTERN.search(text)
        if widest_block and is_valid_python(widest_block.group(1)):
            return widest_block.group(1)
        candidates = code_blocks

    parent_fingerprint = fingerprint_of(parent_code) if parent_code is not None else None
    if parent_fingerprint is not None:
        new_blocks = [block for block in candidates if fingerprint_of(block) != parent_fingerprint]
        if new_blocks:
            candidates = new_blocks

    return max(candidates, key=len)


def extract_code(text: str, parent_code: str | None = None) -> str | None:
    """Return the program contained in a reply, or None if there is no code at all.

    - If there are code blocks, the most likely one is the program (choose_code_block).
    - If a block is opened but never closed, everything after its opening is.
    - If there is no code block, the whole text is; if it is not Python, the checks
      before evaluation reject it (D13).
    """
    code_blocks: list[str] = CODE_BLOCK_PATTERN.findall(text)
    if not code_blocks:
        code_blocks = ONE_LINE_CODE_BLOCK_PATTERN.findall(text)

    if code_blocks:
        code = choose_code_block(code_blocks, text, parent_code)
    else:
        unclosed_block = UNCLOSED_CODE_BLOCK_PATTERN.search(text)
        code = unclosed_block.group(1) if unclosed_block else text
    code = code.strip()
    return code + "\n" if code else None
