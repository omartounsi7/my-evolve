"""Checks the LLM classes."""

import os
import unittest
from types import SimpleNamespace
from typing import Any

from fakes import FakeLLM

from my_evolve.llm import LLMError, MissingKeyError, OpenAICompatibleLLM
from my_evolve.problem import ModelSettings
from my_evolve.prompt import Prompt

PROMPT = Prompt(system="You write programs.", user="Write the improved program.")


def model(name: str, **settings: Any) -> ModelSettings:
    """Return a model's settings, on an address where no server listens (port 9)."""
    return ModelSettings(name=name, api_base="http://127.0.0.1:9/v1", **settings)


class OpenAICompatibleLLMTest(unittest.TestCase):
    def test_an_unreachable_server_raises_llm_error(self) -> None:
        """No server at the address: after its retries, LLMError names the model."""
        # Port 9 ("discard") has no server listening on an ordinary machine.
        llm = OpenAICompatibleLLM(model("some-model"))
        with self.assertRaisesRegex(LLMError, "some-model: APIConnectionError"):
            llm.complete(PROMPT)


class StubClient:
    """Stands for the openai client: create returns the response it was given, and keeps
    the arguments it received."""

    def __init__(self, response: Any) -> None:
        self.sent: dict[str, Any] = {}

        def create(**arguments: Any) -> Any:
            self.sent = arguments
            return response

        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))


def response(text: str | None, usage: Any) -> Any:
    """Return an object shaped like the openai package's chat completion."""
    message = SimpleNamespace(content=text)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


class ReplyTest(unittest.TestCase):
    def test_the_reply_carries_its_tokens_and_duration(self) -> None:
        """Token counts come from the server's usage; 0 when it gives none."""
        llm = OpenAICompatibleLLM(model("some-model"))
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
        llm = OpenAICompatibleLLM(model("some-model"))
        llm.client = StubClient(response("", None))  # type: ignore[assignment]
        with self.assertRaisesRegex(LLMError, "some-model: the reply is empty"):
            llm.complete(PROMPT)


class SettingsSentTest(unittest.TestCase):
    def sent(self, settings: ModelSettings) -> dict[str, Any]:
        """Return the arguments a request with these settings sends, besides the messages."""
        llm = OpenAICompatibleLLM(settings)
        client = StubClient(response("x = 1", None))
        llm.client = client  # type: ignore[assignment]
        llm.complete(PROMPT)
        return {name: value for name, value in client.sent.items() if name != "messages"}

    def test_an_ordinary_model(self) -> None:
        """max_tokens, and a temperature only if one is set."""
        self.assertEqual(self.sent(model("m")), {"model": "m", "max_tokens": 16_384})
        self.assertEqual(
            self.sent(model("m", temperature=0.5, max_tokens=100)),
            {"model": "m", "max_tokens": 100, "temperature": 0.5},
        )

    def test_a_reasoning_model(self) -> None:
        """max_completion_tokens, never a temperature; a reasoning effort only if set."""
        self.assertEqual(
            self.sent(model("o3", reasoning=True)),
            {"model": "o3", "max_completion_tokens": 16_384},
        )
        self.assertEqual(
            self.sent(model("o3", reasoning=True, reasoning_effort="high")),
            {"model": "o3", "max_completion_tokens": 16_384, "reasoning_effort": "high"},
        )

    def test_the_messages(self) -> None:
        llm = OpenAICompatibleLLM(model("m"))
        client = StubClient(response("x = 1", None))
        llm.client = client  # type: ignore[assignment]
        llm.complete(PROMPT)
        self.assertEqual(
            client.sent["messages"],
            [
                {"role": "system", "content": PROMPT.system},
                {"role": "user", "content": PROMPT.user},
            ],
        )


class KeyTest(unittest.TestCase):
    def test_the_key_is_read_from_its_variable(self) -> None:
        os.environ["MY_EVOLVE_TEST_KEY"] = "secret-value"
        self.addCleanup(os.environ.pop, "MY_EVOLVE_TEST_KEY")
        llm = OpenAICompatibleLLM(model("m", api_key_env="MY_EVOLVE_TEST_KEY"))
        self.assertEqual(llm.client.api_key, "secret-value")

    def test_a_missing_variable_is_named(self) -> None:
        os.environ.pop("MY_EVOLVE_NO_SUCH_KEY", None)
        with self.assertRaisesRegex(MissingKeyError, "MY_EVOLVE_NO_SUCH_KEY, which is not set"):
            OpenAICompatibleLLM(model("m", api_key_env="MY_EVOLVE_NO_SUCH_KEY"))

    def test_the_timeout_and_retries_reach_the_client(self) -> None:
        llm = OpenAICompatibleLLM(model("m", timeout=12.0, retries=0))
        self.assertEqual((llm.client.timeout, llm.client.max_retries), (12.0, 0))


class FakeLLMTest(unittest.TestCase):
    def test_replies_come_in_order_and_prompts_are_kept(self) -> None:
        """The fake LLM gives its replies in order, raises its exceptions, keeps the prompts."""
        llm = FakeLLM(["first", LLMError("fake-model", "down"), "third"])
        self.assertEqual(llm.complete(PROMPT).text, "first")
        with self.assertRaisesRegex(LLMError, "fake-model: down"):
            llm.complete(PROMPT)
        self.assertEqual(llm.complete(PROMPT).text, "third")
        self.assertEqual(llm.prompts, [PROMPT] * 3)


if __name__ == "__main__":
    unittest.main()
