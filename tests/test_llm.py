"""Checks the LLM classes, and the extraction of the program from a reply."""

import unittest

from fakes import FakeLLM

from my_evolve.llm import LLMError, OpenAICompatibleLLM
from my_evolve.prompt import Prompt
from my_evolve.reply_parser import extract_code

PROMPT = Prompt(system="You write programs.", user="Write the improved program.")


class OpenAICompatibleLLMTest(unittest.TestCase):
    def test_an_unreachable_server_raises_llm_error(self) -> None:
        """No server at the address: after its retries, LLMError names the model."""
        # Port 9 ("discard") has no server listening on an ordinary machine.
        llm = OpenAICompatibleLLM("some-model", "http://127.0.0.1:9/v1")
        with self.assertRaisesRegex(LLMError, "some-model: APIConnectionError"):
            llm.complete(PROMPT)


class FakeLLMTest(unittest.TestCase):
    def test_replies_come_in_order_and_prompts_are_kept(self) -> None:
        """The fake LLM gives its replies in order, raises its exceptions, keeps the prompts."""
        llm = FakeLLM(["first", LLMError("fake-model: down"), "third"])
        self.assertEqual(llm.complete(PROMPT), "first")
        with self.assertRaises(LLMError):
            llm.complete(PROMPT)
        self.assertEqual(llm.complete(PROMPT), "third")
        self.assertEqual(llm.prompts, [PROMPT] * 3)


class ExtractCodeTest(unittest.TestCase):
    def test_the_code_block(self) -> None:
        """The code of a fenced block, without the text around it."""
        reply = "Here it is:\n\n```python\ndef solve():\n    return 2\n```\n\nIt returns 2."
        self.assertEqual(extract_code(reply), "def solve():\n    return 2\n")

    def test_the_first_of_several_blocks(self) -> None:
        """With several blocks, the first one, whatever its language tag."""
        reply = "```\nx = 1\n```\nand\n```python\nx = 2\n```\n"
        self.assertEqual(extract_code(reply), "x = 1\n")

    def test_backticks_inside_the_code_do_not_end_the_block(self) -> None:
        """Only a fence at the start of a line closes the block."""
        reply = '```python\nNOTE = "use ``` for code"\n```'
        self.assertEqual(extract_code(reply), 'NOTE = "use ``` for code"\n')

    def test_no_block_gives_the_whole_reply(self) -> None:
        """A reply without fences is taken as the program itself."""
        self.assertEqual(extract_code("\nx = 1\n\n"), "x = 1\n")

    def test_no_code_gives_an_empty_string(self) -> None:
        """An empty block, or an empty reply, gives no code."""
        self.assertEqual(extract_code("```python\n```"), "")
        self.assertEqual(extract_code("   "), "")


if __name__ == "__main__":
    unittest.main()
