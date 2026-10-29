"""Checks that the program is found in an LLM's reply (my-alphaevolve's tests, ported)."""

import unittest

from my_evolve.reply_parser import extract_code

# The marker that opens and closes a code block, named so the tests stay readable
FENCE = "```"


class TestExtractCode(unittest.TestCase):
    """Checks on extract_code, one shape of reply per test."""

    def test_code_block_with_a_language_name(self) -> None:
        reply = f"{FENCE}python\nx = 1\n{FENCE}"
        self.assertEqual(extract_code(reply), "x = 1\n")

    def test_code_block_without_a_language_name(self) -> None:
        reply = f"{FENCE}\nx = 1\n{FENCE}"
        self.assertEqual(extract_code(reply), "x = 1\n")

    def test_sentences_around_the_code_block_are_dropped(self) -> None:
        reply = f"Here is a better version.\n\n{FENCE}python\nx = 1\n{FENCE}\n\nIt is faster."
        self.assertEqual(extract_code(reply), "x = 1\n")

    def test_longest_of_several_code_blocks_is_kept(self) -> None:
        reply = (
            f"First change this line:\n{FENCE}python\nx = 1\n{FENCE}\n"
            f"The full program is:\n{FENCE}python\nx = 1\ny = 2\n{FENCE}\n"
        )
        self.assertEqual(extract_code(reply), "x = 1\ny = 2\n")

    def test_code_block_that_is_never_closed(self) -> None:
        reply = f"Here it is.\n{FENCE}python\nx = 1\ny = 2"
        self.assertEqual(extract_code(reply), "x = 1\ny = 2\n")

    def test_reply_without_a_code_block_is_taken_whole(self) -> None:
        self.assertEqual(extract_code("x = 1\ny = 2\n"), "x = 1\ny = 2\n")

    def test_indentation_and_blank_lines_inside_the_code_are_kept(self) -> None:
        code = "def f():\n    a = 1\n\n    return a\n"
        self.assertEqual(extract_code(f"{FENCE}python\n{code}{FENCE}"), code)

    def test_reasoning_of_a_thinking_model_is_dropped(self) -> None:
        # Some models write their reasoning first, between <think> and </think>
        reply = "<think>\nMaybe x = 5? No, too big.\n</think>\n\nx = 1\ny = 2\n"
        self.assertEqual(extract_code(reply), "x = 1\ny = 2\n")

    def test_code_block_inside_the_reasoning_is_not_taken_for_the_program(self) -> None:
        # The discarded attempt is longer than the answer, and must still lose
        reply = (
            f"<think>\nFirst idea:\n{FENCE}python\nx = 100\ny = 200\nz = 300\n{FENCE}\n</think>\n"
            f"{FENCE}python\nx = 1\n{FENCE}\n"
        )
        self.assertEqual(extract_code(reply), "x = 1\n")

    def test_original_program_quoted_before_a_shorter_improved_one_is_not_kept(self) -> None:
        # The model repeats the parent, then gives a new program that is shorter
        parent_code = "def f():\n    '''A long explanation of what f does.'''\n    return 1\n"
        improved_code = "def f():\n    return 2\n"
        reply = (
            f"Original:\n{FENCE}python\n{parent_code}{FENCE}\n"
            f"Improved:\n{FENCE}python\n{improved_code}{FENCE}\n"
        )
        self.assertEqual(extract_code(reply, parent_code), improved_code)

    def test_copy_of_the_parent_is_recognised_despite_comments_and_spacing(self) -> None:
        parent_code = "def f():\n    return 1\n"
        # The same program, with a comment and blank lines added: a longer text
        quoted_parent = "# the original\n\ndef f():\n\n    return 1\n"
        improved_code = "def f():\n    return 2\n"
        reply = (
            f"{FENCE}python\n{quoted_parent}{FENCE}\n"
            f"Better:\n{FENCE}python\n{improved_code}{FENCE}\n"
        )
        self.assertEqual(extract_code(reply, parent_code), improved_code)

    def test_reply_that_only_repeats_the_parent_still_gives_that_program(self) -> None:
        parent_code = "x = 1\n"
        self.assertEqual(
            extract_code(f"{FENCE}python\n{parent_code}{FENCE}", parent_code), parent_code
        )

    def test_block_that_is_not_python_loses_to_a_shorter_block_that_is(self) -> None:
        # The sample of output is longer than the program, but it is not code
        sample_output = "Score: 1.5\nBest point found: [0.1, 0.2]\nDone in 3 steps.\n"
        reply = f"{FENCE}python\nx = 1\n{FENCE}\nIt prints:\n{FENCE}\n{sample_output}{FENCE}\n"
        self.assertEqual(extract_code(reply), "x = 1\n")

    def test_code_block_written_on_one_line(self) -> None:
        self.assertEqual(extract_code(f"Use {FENCE}x = 1{FENCE} instead."), "x = 1\n")

    def test_three_backticks_inside_the_code_do_not_end_the_block(self) -> None:
        # The program holds text that itself contains a code block
        code = f'TEXT = """{FENCE}python\nprint(1)\n{FENCE}"""\nx = 1\n'
        self.assertEqual(extract_code(f"{FENCE}python\n{code}{FENCE}\n"), code)

    def test_lines_of_three_backticks_inside_the_code_do_not_cut_it_in_pieces(self) -> None:
        # Here the inner backticks even stand alone on their lines
        code = f'TEXT = """\n{FENCE}python\nprint(1)\n{FENCE}\n"""\nx = 1\n'
        self.assertEqual(extract_code(f"{FENCE}python\n{code}{FENCE}\n"), code)

    def test_empty_reply_gives_no_code(self) -> None:
        self.assertEqual(extract_code(""), "")
        self.assertEqual(extract_code(f"{FENCE}python\n{FENCE}"), "")


if __name__ == "__main__":
    unittest.main()
