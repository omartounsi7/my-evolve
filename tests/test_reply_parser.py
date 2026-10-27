"""Checks that an LLM's reply is turned into the right description and program."""

import unittest

from my_evolve.reply_parser import extract_code, extract_description, parse_reply, remove_thinking

# The marker that opens and closes a code block, named so the tests stay readable
FENCE = "```"


class TestExtractCode(unittest.TestCase):
    """Checks on extract_code, one shape of reply per test (v1's tests)."""

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
        self.assertIsNone(extract_code(""))
        self.assertIsNone(extract_code("   \n\n"))
        self.assertIsNone(extract_code(f"{FENCE}python\n\n{FENCE}"))


class TestThinking(unittest.TestCase):
    """Checks on remove_thinking, through parse_reply where the code matters."""

    def test_reasoning_of_a_thinking_model_is_dropped(self) -> None:
        # Some models write their reasoning first, between <think> and </think>
        reply = "<think>\nMaybe x = 5? No, too big.\n</think>\n\nx = 1\ny = 2\n"
        self.assertEqual(parse_reply(reply, None).code, "x = 1\ny = 2\n")

    def test_code_block_inside_the_reasoning_is_not_taken_for_the_program(self) -> None:
        # The discarded attempt is longer than the answer, and must still lose
        reply = (
            f"<think>\nFirst idea:\n{FENCE}python\nx = 100\ny = 200\nz = 300\n{FENCE}\n</think>\n"
            f"{FENCE}python\nx = 1\n{FENCE}\n"
        )
        self.assertEqual(parse_reply(reply, None).code, "x = 1\n")

    def test_tags_in_any_letter_case_are_recognised(self) -> None:
        self.assertEqual(remove_thinking("<THINK>hmm</Think>answer"), "answer")

    def test_lone_end_tag_drops_everything_before_it(self) -> None:
        # The opening tag was part of the prompt (Qwen3's chat template does this)
        reply = (
            f"Let me try:\n{FENCE}python\nx = 100\ny = 200\n{FENCE}\nNo.\n</think>\n"
            f"{FENCE}python\nx = 1\n{FENCE}\n"
        )
        self.assertEqual(parse_reply(reply, None).code, "x = 1\n")

    def test_unclosed_thinking_drops_everything_after_it(self) -> None:
        # The reply was cut off while the model was still thinking
        reply = f"<think>\nFirst idea:\n{FENCE}python\nx = 100\n{FENCE}\nBut then"
        self.assertIsNone(parse_reply(reply, None).code)

    def test_several_thinking_sections_are_all_dropped(self) -> None:
        reply = "<think>one</think>x = 1\n<think>two</think>"
        self.assertEqual(remove_thinking(reply).strip(), "x = 1")


class TestDescription(unittest.TestCase):
    """Checks on the description and how it is kept apart from the code."""

    def test_reply_in_the_asked_format_gives_both_parts(self) -> None:
        reply = (
            "<DESCRIPTION>\nPlaces circles on a hexagonal grid.\n</DESCRIPTION>\n"
            f"{FENCE}python\nx = 1\n{FENCE}\n"
        )
        parsed = parse_reply(reply, None)
        self.assertEqual(parsed.description, "Places circles on a hexagonal grid.")
        self.assertEqual(parsed.code, "x = 1\n")

    def test_tags_in_any_letter_case_are_recognised(self) -> None:
        description, _ = extract_description("<description>A grid.</Description>")
        self.assertEqual(description, "A grid.")

    def test_lines_of_the_description_are_kept(self) -> None:
        description, _ = extract_description("<DESCRIPTION>\nFirst.\n\nSecond.\n</DESCRIPTION>")
        self.assertEqual(description, "First.\n\nSecond.")

    def test_code_quoted_in_the_description_is_not_taken_for_the_program(self) -> None:
        # The snippet in the description is longer than the program, and must still lose
        reply = (
            "<DESCRIPTION>\nThe core step is:\n"
            f"{FENCE}python\nfor i in range(26):\n    place(i)\n    adjust(i)\n{FENCE}\n"
            "</DESCRIPTION>\n"
            f"{FENCE}python\nx = 1\n{FENCE}\n"
        )
        self.assertEqual(parse_reply(reply, None).code, "x = 1\n")

    def test_reply_without_a_description_still_gives_its_code(self) -> None:
        parsed = parse_reply(f"{FENCE}python\nx = 1\n{FENCE}", None)
        self.assertIsNone(parsed.description)
        self.assertEqual(parsed.code, "x = 1\n")

    def test_empty_description_is_none(self) -> None:
        description, _ = extract_description("<DESCRIPTION>  \n </DESCRIPTION>")
        self.assertIsNone(description)

    def test_unclosed_description_gives_none_and_leaves_the_text(self) -> None:
        text = "<DESCRIPTION>\nPlaces circles"
        self.assertEqual(extract_description(text), (None, text))

    def test_only_the_first_description_is_kept(self) -> None:
        reply = "<DESCRIPTION>First.</DESCRIPTION>\nx = 1\n<DESCRIPTION>Second.</DESCRIPTION>"
        self.assertEqual(parse_reply(reply, None).description, "First.")

    def test_description_inside_the_reasoning_is_dropped_with_it(self) -> None:
        reply = f"<think><DESCRIPTION>A draft.</DESCRIPTION></think>\n{FENCE}python\nx = 1\n{FENCE}"
        self.assertIsNone(parse_reply(reply, None).description)

    def test_reply_with_only_a_description_gives_no_code(self) -> None:
        self.assertIsNone(parse_reply("<DESCRIPTION>A grid.</DESCRIPTION>", None).code)


class TestParseReply(unittest.TestCase):
    """A realistic reply, from start to end."""

    def test_reasoning_description_note_and_program(self) -> None:
        parent_code = (
            "# EVOLVE-BLOCK-START\ndef build():\n    return [0.1] * 26\n# EVOLVE-BLOCK-END\n"
        )
        program = (
            "# EVOLVE-BLOCK-START\n"
            "def build():\n"
            "    radii = [0.1] * 26\n"
            "    radii[0] = 0.13\n"
            "    return radii\n"
            "# EVOLVE-BLOCK-END\n"
        )
        reply = (
            "<think>\nThe parent uses equal radii. A bigger centre circle may help:\n"
            f"{FENCE}python\nradii[0] = 0.2\n{FENCE}\nToo big; 0.13 fits.\n</think>\n\n"
            "<DESCRIPTION>\nEqual radii of 0.1, except a larger first circle of 0.13.\n"
            "</DESCRIPTION>\n\n"
            "Here is the original, for reference:\n"
            f"{FENCE}python\n{parent_code}{FENCE}\n\n"
            "And the complete program:\n"
            f"{FENCE}python\n{program}{FENCE}\n"
            "This should score a little higher."
        )
        parsed = parse_reply(reply, parent_code)
        self.assertEqual(parsed.code, program)
        self.assertEqual(
            parsed.description, "Equal radii of 0.1, except a larger first circle of 0.13."
        )


if __name__ == "__main__":
    unittest.main()
