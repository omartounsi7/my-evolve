"""Checks the LLM classes, and the extraction of the program from a reply."""

import unittest
from types import SimpleNamespace
from typing import Any

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


class StubClient:
    """Stands for the openai client: create returns the response it was given."""

    def __init__(self, response: Any) -> None:
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response))


def response(text: str | None, usage: Any) -> Any:
    """Return an object shaped like the openai package's chat completion."""
    message = SimpleNamespace(content=text)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


class ReplyTest(unittest.TestCase):
    def test_the_reply_carries_its_tokens_and_duration(self) -> None:
        """Token counts come from the server's usage; 0 when it gives none."""
        llm = OpenAICompatibleLLM("some-model", "http://127.0.0.1:9/v1")
        usage = SimpleNamespace(prompt_tokens=120, completion_tokens=45)
        llm.client = StubClient(response("x = 1", usage))  # type: ignore[assignment]
        reply = llm.complete(PROMPT)
        self.assertEqual((reply.text, reply.model), ("x = 1", "some-model"))
        self.assertEqual((reply.input_tokens, reply.output_tokens), (120, 45))
        self.assertGreaterEqual(reply.duration, 0.0)
        llm.client = StubClient(response("x = 1", None))  # type: ignore[assignment]
        self.assertEqual(llm.complete(PROMPT).input_tokens, 0)

    def test_an_empty_reply_is_an_error(self) -> None:
        """A reply without text is no reply."""
        llm = OpenAICompatibleLLM("some-model", "http://127.0.0.1:9/v1")
        llm.client = StubClient(response("", None))  # type: ignore[assignment]
        with self.assertRaisesRegex(LLMError, "some-model: the reply is empty"):
            llm.complete(PROMPT)


class FakeLLMTest(unittest.TestCase):
    def test_replies_come_in_order_and_prompts_are_kept(self) -> None:
        """The fake LLM gives its replies in order, raises its exceptions, keeps the prompts."""
        llm = FakeLLM(["first", LLMError("fake-model", "down"), "third"])
        self.assertEqual(llm.complete(PROMPT).text, "first")
        with self.assertRaisesRegex(LLMError, "fake-model: down"):
            llm.complete(PROMPT)
        self.assertEqual(llm.complete(PROMPT).text, "third")
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
