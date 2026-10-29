"""Finding the program in the LLM's reply.

The LLM returns the whole program, rewritten (D11): this is what the AlphaEvolve
diagram calls apply_diff. The rules are my-alphaevolve's (D68): the reasoning of
thinking models is dropped; among the code blocks, the valid Python ones are kept, then
those that do not merely repeat the parent, then the longest; a block cut short and a
reply without any block are handled too.
"""

import ast
import re

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

    if code_blocks:
        code = choose_code_block(code_blocks, reply, parent_code)
    else:
        unclosed_block = UNCLOSED_CODE_BLOCK_PATTERN.search(reply)
        code = unclosed_block.group(1) if unclosed_block else reply
    code = code.strip()
    return code + "\n" if code else ""
