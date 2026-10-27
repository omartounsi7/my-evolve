"""Checks the evolve blocks, the fingerprints, the code feature and the checks before evaluation.

Children are made by editing the text of OpenEvolve's two initial programs.
"""

import ast
import unittest
from pathlib import Path

from my_evolve.checks import (
    MarkerError,
    check_child,
    count_block_nodes,
    defined_functions,
    fingerprint,
    same_outside_code,
    split_evolve_blocks,
)

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
CIRCLE_PACKING = (EXAMPLES / "circle_packing" / "initial_program.py").read_text(encoding="utf-8")
FUNCTION_MINIMIZATION = (EXAMPLES / "function_minimization" / "initial_program.py").read_text(
    encoding="utf-8"
)
INITIAL_PROGRAMS = {
    "circle_packing": CIRCLE_PACKING,
    "function_minimization": FUNCTION_MINIMIZATION,
}

START = "# EVOLVE-BLOCK-START"
END = "# EVOLVE-BLOCK-END"


def edited(code: str, old: str, new: str) -> str:
    """Return code with one exact piece of text replaced; fail if it is not there once."""
    if code.count(old) != 1:
        raise AssertionError(f"{old!r} appears {code.count(old)} times")
    return code.replace(old, new)


def tree_of(code: str) -> ast.Module:
    return ast.parse(code)


class TestSplitEvolveBlocks(unittest.TestCase):
    def test_initial_programs_have_one_block(self) -> None:
        blocks = split_evolve_blocks(CIRCLE_PACKING)
        self.assertEqual(len(blocks.blocks), 1)
        self.assertEqual(len(blocks.outside), 2)
        # Circle packing's markers are on lines 1 and 88.
        self.assertEqual(blocks.block_lines, (range(2, 88),))
        self.assertEqual(blocks.outside[0], (START,))
        self.assertEqual(blocks.outside[1][0], END)
        self.assertEqual(split_evolve_blocks(FUNCTION_MINIMIZATION).block_lines, (range(2, 35),))

    def test_two_blocks_give_three_outside_segments(self) -> None:
        code = f"a = 1\n{START}\nb = 2\n{END}\nc = 3\n{START}\nd = 4\n{END}\ne = 5\n"
        blocks = split_evolve_blocks(code)
        self.assertEqual(blocks.blocks, (("b = 2",), ("d = 4",)))
        self.assertEqual(len(blocks.outside), 3)
        self.assertEqual(blocks.outside[1], (END, "c = 3", START))

    def test_markers_may_have_spaces_around_them(self) -> None:
        code = f"   {START}  \nb = 2\n\t{END}\n"
        self.assertEqual(split_evolve_blocks(code).blocks, (("b = 2",),))

    def test_broken_markers_are_reported(self) -> None:
        cases = {
            f"{START}\n{START}\nx = 1\n{END}\n": r"a start inside a block \(line 2\)",
            f"x = 1\n{END}\n": r"an end without a start \(line 2\)",
            f"{START}\nx = 1\n": r"a start without an end \(line 1\)",
            "x = 1\n": "no evolve block",
        }
        for code, message in cases.items():
            with self.subTest(code=code), self.assertRaisesRegex(MarkerError, message):
                split_evolve_blocks(code)


class TestSameOutsideCode(unittest.TestCase):
    def assert_same(self, child: str, initial: str = CIRCLE_PACKING) -> None:
        self.assertIsNone(same_outside_code(child, initial))

    def assert_different(self, child: str, message: str, initial: str = CIRCLE_PACKING) -> None:
        difference = same_outside_code(child, initial)
        self.assertIsNotNone(difference)
        self.assertIn(message, str(difference))

    def test_initial_programs_are_the_same_as_themselves(self) -> None:
        for name, code in INITIAL_PROGRAMS.items():
            with self.subTest(name=name):
                self.assert_same(code, code)

    def test_changes_inside_the_block_are_allowed(self) -> None:
        self.assert_same(
            edited(CIRCLE_PACKING, "centers[0] = [0.5, 0.5]", "centers[0] = [0.4, 0.6]")
        )

    def test_blank_lines_and_spaces_at_line_ends_do_not_count(self) -> None:
        child = edited(CIRCLE_PACKING, "def run_packing():\n", "\n\ndef run_packing():   \n")
        self.assert_same(child.replace("\n\n\n", "\n"))

    def test_windows_line_endings_do_not_count(self) -> None:
        self.assert_same(CIRCLE_PACKING.replace("\n", "\r\n"))

    def test_indentation_outside_the_block_counts(self) -> None:
        child = edited(
            CIRCLE_PACKING,
            "    return centers, radii, sum_radii\n\n\ndef visualize",
            "        return centers, radii, sum_radii\n\n\ndef visualize",
        )
        self.assert_different(child, 'found "        return centers, radii, sum_radii"')

    def test_changed_line_outside_the_block_is_quoted(self) -> None:
        child = edited(CIRCLE_PACKING, "def run_packing():", "def run_packing(n=26):")
        self.assert_different(
            child,
            "code outside the evolve blocks was changed (after block 1): "
            'expected "def run_packing():", found "def run_packing(n=26):"',
        )

    def test_added_line_outside_the_block_is_reported(self) -> None:
        self.assert_different(
            CIRCLE_PACKING + "print('hello')\n",
            "expected the end of that part, found \"print('hello')\"",
        )

    def test_removed_line_outside_the_block_is_reported(self) -> None:
        child = edited(
            FUNCTION_MINIMIZATION,
            '    print(f"Found minimum at ({x}, {y}) with value {value}")\n',
            "",
        )
        self.assert_different(child, "found the end of that part", FUNCTION_MINIMIZATION)

    def test_code_before_the_block_counts(self) -> None:
        self.assert_different("import os\n" + CIRCLE_PACKING, "(before block 1)")

    def test_moved_marker_is_rejected(self) -> None:
        child = edited(CIRCLE_PACKING, f"\n\n{END}\n", "\n")
        child = edited(child, "def compute_max_radii", f"{END}\ndef compute_max_radii")
        self.assert_different(child, "code outside the evolve blocks was changed")

    def test_removed_marker_is_rejected(self) -> None:
        self.assert_different(
            edited(CIRCLE_PACKING, f"{END}\n", ""),
            "the evolve-block markers were changed: a start without an end",
        )

    def test_altered_marker_is_rejected(self) -> None:
        self.assert_different(
            edited(CIRCLE_PACKING, START, f"{START} here"),
            "the evolve-block markers were changed: an end without a start",
        )

    def test_added_marker_is_rejected(self) -> None:
        self.assert_different(
            edited(CIRCLE_PACKING, "def compute_max_radii", f"{START}\ndef compute_max_radii"),
            "a start inside a block",
        )

    def test_extra_block_is_rejected(self) -> None:
        self.assert_different(
            edited(
                CIRCLE_PACKING, "def compute_max_radii", f"{END}\n{START}\ndef compute_max_radii"
            ),
            "expected 1 evolve block, found 2",
        )

    def test_broken_initial_program_raises(self) -> None:
        with self.assertRaises(MarkerError):
            same_outside_code(CIRCLE_PACKING, "x = 1\n")


class TestTreeFunctions(unittest.TestCase):
    def test_defined_functions_of_the_initial_programs(self) -> None:
        self.assertEqual(
            defined_functions(tree_of(CIRCLE_PACKING)),
            {"construct_packing", "compute_max_radii", "run_packing", "visualize"},
        )
        self.assertEqual(
            defined_functions(tree_of(FUNCTION_MINIMIZATION)),
            {"search_algorithm", "evaluate_function", "run_search"},
        )

    def test_only_plain_top_level_defs_count(self) -> None:
        code = (
            "async def run_a():\n    return 1\n"
            "run_b = lambda: 1\n"
            "if True:\n    def run_c():\n        return 1\n"
            "def run_d():\n    def run_e():\n        return 1\n    return run_e\n"
        )
        self.assertEqual(defined_functions(tree_of(code)), {"run_d"})

    def test_comments_and_spacing_leave_the_fingerprint_unchanged(self) -> None:
        child = edited(
            CIRCLE_PACKING,
            "    centers[0] = [0.5, 0.5]\n",
            "    # The big one\n\n    centers[0] = [0.5,   0.5]  # in the middle\n",
        )
        self.assertEqual(fingerprint(tree_of(child)), fingerprint(tree_of(CIRCLE_PACKING)))

    def test_code_changes_change_the_fingerprint(self) -> None:
        reference = fingerprint(tree_of(CIRCLE_PACKING))
        for old, new in (
            ("centers[0] = [0.5, 0.5]", "centers[0] = [0.5, 0.49]"),
            ("n = 26", "count = 26"),
            ('"""Constructor-based circle packing for n=26 circles"""', '"""Another docstring"""'),
        ):
            with self.subTest(new=new):
                child = edited(CIRCLE_PACKING, old, new)
                self.assertNotEqual(fingerprint(tree_of(child)), reference)

    def test_fingerprint_is_a_sha256_hash(self) -> None:
        self.assertRegex(fingerprint(tree_of(CIRCLE_PACKING)), r"^[0-9a-f]{64}$")

    def test_nodes_are_counted_inside_the_block_only(self) -> None:
        reference = count_block_nodes(tree_of(CIRCLE_PACKING), CIRCLE_PACKING)
        inside = edited(CIRCLE_PACKING, "    n = 26\n", "    n = 26\n    extra = n + 1\n")
        outside = CIRCLE_PACKING + "extra = 26 + 1\n"
        self.assertGreater(count_block_nodes(tree_of(inside), inside), reference)
        self.assertEqual(count_block_nodes(tree_of(outside), outside), reference)

    def test_count_matches_the_block_parsed_on_its_own(self) -> None:
        for name, code in INITIAL_PROGRAMS.items():
            with self.subTest(name=name):
                block_code = "\n".join(split_evolve_blocks(code).blocks[0])
                expected = sum(
                    1 for node in ast.walk(ast.parse(block_code)) if hasattr(node, "end_lineno")
                )
                self.assertEqual(count_block_nodes(tree_of(code), code), expected)

    def test_count_needs_working_markers(self) -> None:
        with self.assertRaises(MarkerError):
            count_block_nodes(tree_of("x = 1\n"), "x = 1\n")


class TestCheckChild(unittest.TestCase):
    def check(
        self,
        code: str,
        known: dict[str, str] | None = None,
        entry_functions: tuple[str, ...] = ("run_packing",),
    ) -> tuple[str | None, str | None, int | None]:
        result = check_child(code, CIRCLE_PACKING, entry_functions, known or {})
        return result.reason, result.fingerprint, result.code_complexity

    def test_initial_programs_pass_against_themselves(self) -> None:
        for name, code, entry in (
            ("circle_packing", CIRCLE_PACKING, "run_packing"),
            ("function_minimization", FUNCTION_MINIMIZATION, "run_search"),
        ):
            with self.subTest(name=name):
                result = check_child(code, code, (entry,), {})
                self.assertIsNone(result.reason)
                self.assertIsNotNone(result.fingerprint)
                self.assertGreater(result.code_complexity or 0, 0)

    def test_accepted_child_gets_its_measures(self) -> None:
        child = edited(CIRCLE_PACKING, "centers[0] = [0.5, 0.5]", "centers[0] = [0.4, 0.6]")
        reason, child_fingerprint, complexity = self.check(child)
        self.assertIsNone(reason)
        self.assertEqual(child_fingerprint, fingerprint(tree_of(child)))
        self.assertEqual(complexity, count_block_nodes(tree_of(child), child))

    def test_empty_reply_is_rejected(self) -> None:
        self.assertEqual(self.check("  \n"), ("no code in the reply", None, None))

    def test_syntax_error_is_rejected_with_its_line(self) -> None:
        reason, child_fingerprint, complexity = self.check("def broken(:\n    pass\n")
        self.assertRegex(str(reason), r"^syntax error: .* \(line 1\)$")
        self.assertIsNone(child_fingerprint)
        self.assertIsNone(complexity)

    def test_null_byte_is_a_syntax_error(self) -> None:
        reason, _, _ = self.check("x = 1\0\n")
        self.assertTrue(str(reason).startswith("syntax error"))

    def test_change_outside_the_blocks_is_rejected(self) -> None:
        child = edited(CIRCLE_PACKING, "def run_packing():", "def run_packing(n=26):")
        reason, child_fingerprint, complexity = self.check(child)
        self.assertIn("code outside the evolve blocks was changed", str(reason))
        self.assertIsNotNone(child_fingerprint)
        self.assertIsNotNone(complexity)

    def test_broken_markers_keep_a_fingerprint_but_no_complexity(self) -> None:
        reason, child_fingerprint, complexity = self.check(edited(CIRCLE_PACKING, f"{END}\n", ""))
        self.assertIn("markers were changed", str(reason))
        self.assertIsNotNone(child_fingerprint)
        self.assertIsNone(complexity)

    def test_missing_entry_function_is_rejected(self) -> None:
        reason, _, _ = self.check(CIRCLE_PACKING, entry_functions=("run_packing", "run_search"))
        self.assertEqual(reason, "the entry function run_search is not defined at the top level")

    def test_duplicate_is_rejected_naming_the_earlier_program(self) -> None:
        known = {fingerprint(tree_of(CIRCLE_PACKING)): "1234-abcd"}
        # A comment inside the block (outside, it would change the outside code).
        copy_with_comment = edited(
            CIRCLE_PACKING, "    n = 26\n", "    n = 26  # a comment does not make it new\n"
        )
        reason, _, _ = self.check(copy_with_comment, known)
        self.assertEqual(reason, "same program as 1234-abcd")

    def test_entry_functions_are_checked_before_duplicates(self) -> None:
        known = {fingerprint(tree_of(CIRCLE_PACKING)): "1234-abcd"}
        reason, _, _ = self.check(CIRCLE_PACKING, known, ("run_packing", "run_search"))
        self.assertIn("entry function run_search", str(reason))


if __name__ == "__main__":
    unittest.main()
