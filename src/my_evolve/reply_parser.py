"""Finding the program in the LLM's reply.

The LLM returns the whole program, rewritten (D11): this is what the AlphaEvolve
diagram calls apply_diff. For now the program is the reply's first fenced code block;
step 2.2 of the implementation plan brings my-alphaevolve's more careful rules.
"""

import re

# A fenced code block: an opening fence (``` and an optional language, such as python)
# and a closing fence, each at the start of a line. The group is what lies between.
CODE_BLOCK = re.compile(r"^```[^\n`]*\n(.*?)^```", re.DOTALL | re.MULTILINE)


def extract_code(reply: str) -> str:
    """Return the program in a reply: its first fenced code block, or the whole reply if none.

    The code is stripped of blank space around it and ends with one newline; a reply
    without any code gives an empty string.
    """
    block = CODE_BLOCK.search(reply)
    code = block.group(1) if block else reply
    code = code.strip()
    return code + "\n" if code else ""
