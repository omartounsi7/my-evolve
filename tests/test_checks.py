"""Checks the checks before evaluation: evolve blocks kept where the initial program has them."""

import ast
import unittest
from pathlib import Path

from my_evolve.checks import (
    MarkerError,
    check_child,
    fingerprint,
    same_outside_code,
    split_evolve_blocks,
)

REPOSITORY_FOLDER = Path(__file__).parent.parent
INITIAL_PROGRAMS = {
    name: (REPOSITORY_FOLDER / "examples" / name / "initial_program.py").read_text()
    for name in ("circle_packing", "function_minimization")
}
START = "# EVOLVE-BLOCK-START"
END = "# EVOLVE-BLOCK-END"

# A small program with two blocks, and code before, between and after them
TWO_BLOCKS = f"""import math

{START}
def a():
    return 1
{END}

def middle():
    return 2

    {START}
def b():
    return 3
    {END}

if __name__ == "__main__":
    print(a())
"""


class SplitTest(unittest.TestCase):
    def test_the_segments_and_blocks(self) -> None:
        """One outside segment more than blocks; marker lines belong to the outside."""
        outside, blocks = split_evolve_blocks(TWO_BLOCKS)
        self.assertEqual(len(outside), 3)
        self.assertEqual(blocks[0], ["def a():", "    return 1"])
        self.assertEqual(outside[0][-1], START)
        self.assertEqual(outside[1][0], END)
        self.assertEqual(outside[1][-1], f"    {START}")

    def test_the_initial_programs_split(self) -> None:
        """Both of OpenEvolve's initial programs have one block."""
        for name, code in INITIAL_PROGRAMS.items():
            with self.subTest(name=name):
                self.assertEqual(len(split_evolve_blocks(code)[1]), 1)

    def test_broken_markers(self) -> None:
        """Each way of breaking the markers is reported."""
        for code, error in [
            (f"{START}\n{START}\n{END}\n", "inside an evolve block"),
            (f"{END}\n", "without a # EVOLVE-BLOCK-START before it"),
            (f"{START}\nx = 1\n", "without a # EVOLVE-BLOCK-END after it"),
            ("x = 1\n", "no evolve block"),
        ]:
            with self.subTest(error=error), self.assertRaisesRegex(MarkerError, error):
                split_evolve_blocks(code)


class SameOutsideCodeTest(unittest.TestCase):
    def test_changes_inside_the_blocks_are_allowed(self) -> None:
        """Rewriting a block entirely, even to nothing, keeps the outside code."""
        child = TWO_BLOCKS.replace("    return 1", "    import os\n    return len(os.sep) * 9")
        self.assertIsNone(same_outside_code(child, TWO_BLOCKS))
        self.assertIsNone(same_outside_code(TWO_BLOCKS.replace("    return 3\n", ""), TWO_BLOCKS))

    def test_blank_lines_and_spaces_at_line_ends_do_not_count(self) -> None:
        child = TWO_BLOCKS.replace("import math\n", "import math   \n\n\n")
        self.assertIsNone(same_outside_code(child, TWO_BLOCKS))

    def test_spaces_at_line_starts_count(self) -> None:
        child = TWO_BLOCKS.replace("    return 2", "        return 2")
        self.assertIn("'return 2' where the original", same_outside_code(child, TWO_BLOCKS) or "")

    def test_changes_outside_the_blocks_are_refused(self) -> None:
        """A changed, added or removed line outside the blocks."""
        for child, reason in [
            (TWO_BLOCKS.replace("return 2", "return 20"), "'return 20' where the original has"),
            (TWO_BLOCKS + "x = 1\n", "'x = 1' was added"),
            (TWO_BLOCKS.replace("    print(a())\n", ""), "'print(a())' was removed"),
        ]:
            with self.subTest(reason=reason):
                self.assertIn(reason, same_outside_code(child, TWO_BLOCKS) or "")

    def test_moved_removed_added_and_altered_markers_are_refused(self) -> None:
        """Every change to the markers is a rejection."""
        moved = TWO_BLOCKS.replace(f"{END}\n\ndef middle():", f"\ndef middle():\n{END}")
        for child in [
            TWO_BLOCKS.replace(f"{START}\ndef a():", "def a():"),
            TWO_BLOCKS.replace(f"{START}\ndef a():", f"{START}\n{START}\ndef a():"),
            TWO_BLOCKS + f"{START}\nx = 1\n{END}\n",
            TWO_BLOCKS.replace(START, "# EVOLVE-BLOCK START"),
            moved,
            "def a():\n    return 1\n",
        ]:
            with self.subTest(child=child[:40]):
                self.assertIsNotNone(same_outside_code(child, TWO_BLOCKS))

    def test_an_unchanged_initial_program_passes(self) -> None:
        for name, code in INITIAL_PROGRAMS.items():
            with self.subTest(name=name):
                self.assertIsNone(same_outside_code(code, code))


class CheckChildTest(unittest.TestCase):
    def test_a_good_child_passes(self) -> None:
        child = TWO_BLOCKS.replace("    return 1", "    return 10")
        self.assertIsNone(check_child(child, TWO_BLOCKS, ["a", "middle"], {}).reason)

    def test_each_rejection_with_its_reason(self) -> None:
        for child, reason in [
            ("", "no code in the reply"),
            ("  \n", "no code in the reply"),
            (TWO_BLOCKS.replace("def a():", "def a(:"), "does not compile: invalid syntax"),
            (TWO_BLOCKS.replace("import math", "import mat h"), "does not compile"),
            (
                TWO_BLOCKS.replace("def a():\n    return 1", "a = lambda: 1"),
                "define the function a()",
            ),
            (TWO_BLOCKS + "\nx = 1\n", "'x = 1' was added"),
        ]:
            with self.subTest(reason=reason):
                self.assertIn(reason, check_child(child, TWO_BLOCKS, ["a"], {}).reason or "")

    def test_the_checks_come_in_order(self) -> None:
        """A program that fails several checks gets the reason of the first."""
        no_markers_and_no_function = "def b():\n    return 1\n"
        reason = check_child(no_markers_and_no_function, TWO_BLOCKS, ["a"], {}).reason or ""
        self.assertIn("evolve-block markers", reason)

    def test_entry_functions_must_be_at_the_top_level(self) -> None:
        """A function of that name inside a class does not count."""
        in_a_class = "class K:\n    def a(self):\n        return 1"
        child = TWO_BLOCKS.replace("def a():\n    return 1", in_a_class)
        self.assertIn(
            "define the function a()", check_child(child, TWO_BLOCKS, ["a"], {}).reason or ""
        )

    def test_the_initial_programs_pass_against_themselves(self) -> None:
        entry = {"circle_packing": ["run_packing"], "function_minimization": ["run_search"]}
        for name, code in INITIAL_PROGRAMS.items():
            with self.subTest(name=name):
                self.assertIsNone(check_child(code, code, entry[name], {}).reason)


class FingerprintTest(unittest.TestCase):
    def test_comments_and_spacing_do_not_change_the_fingerprint(self) -> None:
        code = "def f(x):\n    return x + 1\n"
        reformatted = "# A comment\ndef f( x ):\n\n    return x+1  # another\n"
        self.assertEqual(fingerprint(ast.parse(code)), fingerprint(ast.parse(reformatted)))
        changed = "def f(x):\n    return x + 2\n"
        self.assertNotEqual(fingerprint(ast.parse(code)), fingerprint(ast.parse(changed)))

    def test_a_known_program_is_rejected_with_the_id_of_the_first(self) -> None:
        child = TWO_BLOCKS.replace("    return 1", "    return 10  # better")
        checks = check_child(child, TWO_BLOCKS, ["a"], {})
        self.assertIsNone(checks.reason)
        assert checks.fingerprint is not None
        repeat = check_child(child + "\n\n", TWO_BLOCKS, ["a"], {checks.fingerprint: "abc"})
        self.assertEqual(repeat.reason, "same program as abc")

    def test_a_program_that_does_not_compile_has_no_fingerprint(self) -> None:
        self.assertIsNone(check_child("def (", TWO_BLOCKS, ["a"], {}).fingerprint)


if __name__ == "__main__":
    unittest.main()
