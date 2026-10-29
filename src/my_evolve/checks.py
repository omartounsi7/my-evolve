"""The checks a child passes before it is evaluated (D13).

They run on the host, without running the program. A child that fails one is stored
with the status rejected and the reason, and never evaluated, so the mistake costs no
evaluation and can be shown to the LLM later.

The checks, in this order (check_child):
1. the child compiles (a reply without code fails here);
2. it keeps the evolve blocks where the initial program has them (D12): the LLM may
   change only the code between `# EVOLVE-BLOCK-START` and `# EVOLVE-BLOCK-END`; the
   code outside them, and the markers, must stay as they are;
3. it defines, at the top level, every entry function the problem file names.
"""

import ast
from collections.abc import Sequence

# The lines that open and close an evolve block, without the spaces around them
START_MARKER = "# EVOLVE-BLOCK-START"
END_MARKER = "# EVOLVE-BLOCK-END"


class MarkerError(ValueError):
    """Raised when a program's evolve-block markers are broken; the message says how."""


def split_evolve_blocks(code: str) -> tuple[list[list[str]], list[list[str]]]:
    """Return the lines outside the evolve blocks and the lines inside them.

    The outside segments, marker lines included, are one more than the blocks: the code
    before the first block, between blocks, and after the last. Raises MarkerError if a
    start comes inside a block, an end without a start, a start without an end, or if
    there is no block at all.
    """
    outside: list[list[str]] = []
    blocks: list[list[str]] = []
    current: list[str] = []
    inside = False
    for line in code.splitlines():
        marker = line.strip()
        if marker == START_MARKER:
            if inside:
                raise MarkerError(f"a {START_MARKER} inside an evolve block")
            outside.append([*current, line])
            current = []
            inside = True
        elif marker == END_MARKER:
            if not inside:
                raise MarkerError(f"a {END_MARKER} without a {START_MARKER} before it")
            blocks.append(current)
            current = [line]
            inside = False
        else:
            current.append(line)
    if inside:
        raise MarkerError(f"a {START_MARKER} without a {END_MARKER} after it")
    if not blocks:
        raise MarkerError("no evolve block")
    outside.append(current)
    return outside, blocks


def significant_lines(lines: list[str]) -> list[str]:
    """Return the lines without blank lines and without spaces at their ends.

    Spaces at the start of a line still count: in Python, indentation has meaning.
    """
    return [line.rstrip() for line in lines if line.strip()]


def same_outside_code(child_code: str, initial_code: str) -> str | None:
    """Return None if the child keeps the evolve blocks where the initial program has them,
    otherwise what differs.

    Raises MarkerError if the initial program's own markers are broken.
    """
    initial_outside, initial_blocks = split_evolve_blocks(initial_code)
    try:
        child_outside, child_blocks = split_evolve_blocks(child_code)
    except MarkerError as error:
        return f"the evolve-block markers were changed: {error}"
    if len(child_blocks) != len(initial_blocks):
        return (
            f"the evolve-block markers were changed: expected {len(initial_blocks)} evolve "
            f"block(s), found {len(child_blocks)}"
        )
    for child_segment, initial_segment in zip(child_outside, initial_outside, strict=True):
        child_lines = significant_lines(child_segment)
        initial_lines = significant_lines(initial_segment)
        for child_line, initial_line in zip(child_lines, initial_lines, strict=False):
            if child_line != initial_line:
                return (
                    "the code outside the evolve blocks was changed: "
                    f"{child_line.strip()!r} where the original has {initial_line.strip()!r}"
                )
        if len(child_lines) > len(initial_lines):
            added = child_lines[len(initial_lines)].strip()
            return f"the code outside the evolve blocks was changed: {added!r} was added"
        if len(child_lines) < len(initial_lines):
            removed = initial_lines[len(child_lines)].strip()
            return f"the code outside the evolve blocks was changed: {removed!r} was removed"
    return None


def defined_functions(tree: ast.Module) -> set[str]:
    """Return the names of the functions defined at the top level of a program."""
    return {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def check_child(code: str, initial_code: str, entry_functions: Sequence[str]) -> str | None:
    """Run the checks of D13 on a child, in order; return the reason it is rejected, or None.

    Raises MarkerError if the initial program's own markers are broken.
    """
    if not code.strip():
        return "no code in the reply"
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError) as error:
        line = f" (line {error.lineno})" if isinstance(error, SyntaxError) and error.lineno else ""
        message = error.msg if isinstance(error, SyntaxError) else str(error)
        return f"the program does not compile: {message}{line}"
    difference = same_outside_code(code, initial_code)
    if difference is not None:
        return difference
    missing = [name for name in entry_functions if name not in defined_functions(tree)]
    if missing:
        return f"the program must define the function {missing[0]}() at its top level"
    return None
