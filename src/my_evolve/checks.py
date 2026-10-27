"""The checks a child passes before it is evaluated, and what they measure (D13, D74).

The LLM may change only the code between "# EVOLVE-BLOCK-START" and
"# EVOLVE-BLOCK-END" (D12). A child is checked here, on the host, without running
it: it must compile, keep the code outside the blocks, define the entry functions,
and not repeat an earlier program. The same functions give each program its
fingerprint (the hash of its syntax tree) and its code complexity (the number of
syntax-tree nodes inside its blocks, D17).
"""

import ast
import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

START_MARKER = "# EVOLVE-BLOCK-START"
END_MARKER = "# EVOLVE-BLOCK-END"

# The longest line quoted in a reason, in characters.
MAX_QUOTED_LINE = 100


class MarkerError(ValueError):
    """The evolve-block markers of a program are broken; the message says how and where."""


@dataclass(frozen=True)
class EvolveBlocks:
    """A program cut into the code outside its evolve blocks and the blocks' contents."""

    # The code outside the blocks, marker lines included: one segment more than blocks.
    outside: tuple[tuple[str, ...], ...]
    # The lines inside each block, markers excluded.
    blocks: tuple[tuple[str, ...], ...]
    # The line numbers (from 1) inside each block, markers excluded.
    block_lines: tuple[range, ...]


@dataclass(frozen=True)
class CheckResult:
    """What check_child found."""

    # Why the child is rejected; None if it passed every check.
    reason: str | None
    # The hash of its syntax tree; None if it does not compile.
    fingerprint: str | None
    # Its node count inside the evolve blocks; None if it does not compile or its
    # markers are broken.
    code_complexity: int | None


def is_marker(line: str, marker: str) -> bool:
    """Tell whether a line is the given marker, with nothing else on it but spaces."""
    return line.strip() == marker


def split_evolve_blocks(code: str) -> EvolveBlocks:
    """Cut a program into the code outside its evolve blocks and the blocks' contents.

    Raises MarkerError if the markers are broken: a start inside a block, an end
    without a start, a start without an end, or no block at all.
    """
    outside: list[tuple[str, ...]] = []
    blocks: list[tuple[str, ...]] = []
    block_lines: list[range] = []
    current: list[str] = []
    inside = False
    block_start_line = 0

    for line_number, line in enumerate(code.splitlines(), start=1):
        if is_marker(line, START_MARKER):
            if inside:
                raise MarkerError(f"a start inside a block (line {line_number})")
            # The start marker ends the segment outside, and a block begins.
            current.append(line)
            outside.append(tuple(current))
            current = []
            inside = True
            block_start_line = line_number
        elif is_marker(line, END_MARKER):
            if not inside:
                raise MarkerError(f"an end without a start (line {line_number})")
            # The end marker ends the block, and begins the next segment outside.
            blocks.append(tuple(current))
            block_lines.append(range(block_start_line + 1, line_number))
            current = [line]
            inside = False
        else:
            current.append(line)

    if inside:
        raise MarkerError(f"a start without an end (line {block_start_line})")
    if not blocks:
        raise MarkerError("no evolve block")
    outside.append(tuple(current))
    return EvolveBlocks(tuple(outside), tuple(blocks), tuple(block_lines))


def comparable_lines(segment: Iterable[str]) -> list[str]:
    """Return a segment's lines as they are compared: no blank lines, no spaces at line ends.

    Spaces at the start of lines are kept: indentation has meaning in Python.
    """
    return [line.rstrip() for line in segment if line.strip()]


def quoted(line: str) -> str:
    """Return a line in quotes for a reason, cut if it is very long."""
    if len(line) > MAX_QUOTED_LINE:
        line = line[: MAX_QUOTED_LINE - 3] + "..."
    return f'"{line}"'


def segment_name(index: int) -> str:
    """Name a segment outside the blocks: "before block 1", "after block 1", ..."""
    return "before block 1" if index == 0 else f"after block {index}"


def plural_blocks(count: int) -> str:
    """Return "1 evolve block" or "2 evolve blocks"."""
    return f"{count} evolve block" + ("" if count == 1 else "s")


def same_outside_code(child_code: str, initial_code: str) -> str | None:
    """Return None if the child kept the evolve blocks where the initial program has them.

    Otherwise return what differs, worded for the LLM: the markers changed, a
    different number of blocks, or the first line that differs outside them.
    Raises MarkerError if the initial program's own markers are broken.
    """
    expected = split_evolve_blocks(initial_code)
    try:
        found = split_evolve_blocks(child_code)
    except MarkerError as error:
        return f"the evolve-block markers were changed: {error}"
    if len(found.blocks) != len(expected.blocks):
        return f"expected {plural_blocks(len(expected.blocks))}, found {len(found.blocks)}"

    for index, (expected_segment, found_segment) in enumerate(
        zip(expected.outside, found.outside, strict=True)
    ):
        expected_lines = comparable_lines(expected_segment)
        found_lines = comparable_lines(found_segment)
        if expected_lines == found_lines:
            continue
        place = f"code outside the evolve blocks was changed ({segment_name(index)})"
        for expected_line, found_line in zip(expected_lines, found_lines, strict=False):
            if expected_line != found_line:
                return f"{place}: expected {quoted(expected_line)}, found {quoted(found_line)}"
        # Every line both have is the same: one of them has lines the other lacks.
        if len(expected_lines) > len(found_lines):
            missing = expected_lines[len(found_lines)]
            return f"{place}: expected {quoted(missing)}, found the end of that part"
        extra = found_lines[len(expected_lines)]
        return f"{place}: expected the end of that part, found {quoted(extra)}"
    return None


def defined_functions(tree: ast.Module) -> set[str]:
    """Return the names of the functions a program defines with "def" at its top level."""
    return {statement.name for statement in tree.body if isinstance(statement, ast.FunctionDef)}


def fingerprint(tree: ast.Module) -> str:
    """Return the SHA-256 hash of a syntax tree.

    ast.dump leaves out line and column numbers, and comments and spacing are not
    part of the tree, so they do not change the fingerprint; any change to the code
    itself, docstrings included, does.
    """
    return hashlib.sha256(ast.dump(tree).encode("utf-8")).hexdigest()


def count_block_nodes(tree: ast.Module, code: str) -> int:
    """Return the number of syntax-tree nodes inside the evolve blocks (D17).

    A node counts if its first and last lines are both inside one block. Nodes
    without a position (the module itself, contexts, operators) are not counted.
    Raises MarkerError if the markers are broken.
    """
    block_lines = split_evolve_blocks(code).block_lines
    count = 0
    for node in ast.walk(tree):
        first_line = getattr(node, "lineno", None)
        last_line = getattr(node, "end_lineno", None)
        if first_line is None or last_line is None:
            continue
        if any(first_line in lines and last_line in lines for lines in block_lines):
            count += 1
    return count


def check_child(
    code: str,
    initial_code: str,
    entry_functions: Iterable[str],
    known_fingerprints: Mapping[str, str],
) -> CheckResult:
    """Run the four checks of D13 on a child, in order, without running it.

    known_fingerprints maps each fingerprint of the database to the id of the first
    program that had it. Returns the reason for a rejection (None if the child is
    accepted), its fingerprint and its code complexity.
    """
    if not code.strip():
        return CheckResult("no code in the reply", None, None)
    try:
        tree = ast.parse(code)
    except SyntaxError as error:
        return CheckResult(f"syntax error: {error.msg} (line {error.lineno})", None, None)
    except ValueError as error:
        return CheckResult(f"syntax error: {error}", None, None)

    child_fingerprint = fingerprint(tree)
    try:
        code_complexity: int | None = count_block_nodes(tree, code)
    except MarkerError:
        code_complexity = None

    def rejected(reason: str) -> CheckResult:
        return CheckResult(reason, child_fingerprint, code_complexity)

    difference = same_outside_code(code, initial_code)
    if difference is not None:
        return rejected(difference)
    defined = defined_functions(tree)
    for name in entry_functions:
        if name not in defined:
            return rejected(f"the entry function {name} is not defined at the top level")
    earlier_id = known_fingerprints.get(child_fingerprint)
    if earlier_id is not None:
        return rejected(f"same program as {earlier_id}")
    return CheckResult(None, child_fingerprint, code_complexity)
