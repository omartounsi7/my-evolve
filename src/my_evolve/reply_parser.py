"""Finding the program, and its description, in the LLM's reply.

The LLM returns the whole program, rewritten (D11): this is what the AlphaEvolve
diagram calls apply_diff. It also describes the program between <DESCRIPTION> and
</DESCRIPTION> (D15). Finding the code follows my-alphaevolve's rules (D68): the
reasoning of thinking models is dropped; among the code blocks, the valid Python ones
are kept, then those that do not merely repeat the parent, then the longest; a block cut
short and a reply without any block are handled too. Windows line endings become plain
ones, and a block indented as a whole (inside a list, say) loses that indentation.
"""

import ast
import re
import textwrap
from dataclasses import dataclass

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

# The program's description, between its tags, in any letter case.
DESCRIPTION_PATTERN = re.compile(r"<description>(.*?)</description>", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True)
class ParsedReply:
    """What is kept of an LLM's reply: the program, and its description."""

    # The program's code; empty if the reply holds none
    code: str
    # How the program solves the problem, in the LLM's words; None if it gave none
    description: str | None


def is_valid_python(code: str) -> bool:
    """Tell whether a piece of text is valid Python. The code is only parsed, not run."""
    try:
        ast.parse(code)
    except (SyntaxError, ValueError):
        return False
    return True


def is_same_program(first_code: str, second_code: str) -> bool:
    """Tell whether two pieces of code are the same program."""
    try:
        return ast.dump(ast.parse(first_code)) == ast.dump(ast.parse(second_code))
    except (SyntaxError, ValueError):
        return False


def unindented(block: str) -> str:
    """Return a code block without the indentation all its lines share, if they all have
    some (a block inside a list); any other block exactly as it is."""
    lines = [line for line in block.splitlines() if line.strip()]
    if lines and all(line[0] in " \t" for line in lines):
        return textwrap.dedent(block)
    return block


def choose_code_block(code_blocks: list[str], reply: str, parent_code: str | None) -> str:
    """Return the code block of a reply most likely to be the new program.

    A reply can hold several blocks (the original program quoted back, sample
    output, small snippets). Three rules apply in turn, each only if it leaves a block:

    1. keep the blocks that are valid Python;
    2. drop the blocks that merely repeat the parent program;
    3. keep the longest block.
    """
    candidates = [block for block in code_blocks if is_valid_python(block)]
    if not candidates:
        widest_block = WIDEST_CODE_BLOCK_PATTERN.search(reply)
        if widest_block and is_valid_python(widest_block.group(1)):
            return widest_block.group(1)
        candidates = code_blocks

    if parent_code is not None:
        new_blocks = [block for block in candidates if not is_same_program(block, parent_code)]
        if new_blocks:
            candidates = new_blocks

    return max(candidates, key=len)


def extract_code(reply: str, parent_code: str | None = None) -> str:
    """Return the program contained in an LLM's reply.

    The LLM may wrap the program in a code block, and write text around it. So:
    - if there are code blocks, the most likely one is the program (choose_code_block);
    - if a block is opened but never closed, everything after its opening is;
    - if there is no code block, the whole reply is.

    A block that merely repeats parent_code is not taken for the new program. The code
    is stripped of blank space around it and ends with one newline; a reply without
    any code gives an empty string.
    """
    reply = THINKING_PATTERN.sub("", reply)

    code_blocks: list[str] = CODE_BLOCK_PATTERN.findall(reply)
    if not code_blocks:
        code_blocks = ONE_LINE_CODE_BLOCK_PATTERN.findall(reply)
    code_blocks = [unindented(block) for block in code_blocks]

    if code_blocks:
        code = choose_code_block(code_blocks, reply, parent_code)
    else:
        unclosed_block = UNCLOSED_CODE_BLOCK_PATTERN.search(reply)
        code = unclosed_block.group(1) if unclosed_block else reply
    code = code.strip()
    return code + "\n" if code else ""


def extract_description(text: str) -> tuple[str | None, str]:
    """Return the first description in the text, and the text without it.

    Taking the description out first means code quoted inside it is never taken for
    the program. An empty description is None.
    """
    found = DESCRIPTION_PATTERN.search(text)
    if found is None:
        return None, text
    description = found.group(1).strip() or None
    return description, text[: found.start()] + text[found.end() :]


def parse_reply(reply: str, parent_code: str | None = None) -> ParsedReply:
    """Return the program and the description an LLM's reply holds.

    A reply without a description is still accepted if its code is usable.
    """
    without_thinking = THINKING_PATTERN.sub("", reply.replace("\r\n", "\n"))
    description, rest = extract_description(without_thinking)
    return ParsedReply(code=extract_code(rest, parent_code), description=description)
