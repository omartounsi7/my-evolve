"""Checks the LLM classes."""

import os
import random
import unittest
from collections import Counter
from types import SimpleNamespace
from typing import Any

from fakes import FakeLLM

from my_evolve.llm import Ensemble, LLMError, MissingKeyError, NoModelLeft, OpenAICompatibleLLM
from my_evolve.problem import LLMSettings, ModelSettings
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


class EnsembleTest(unittest.TestCase):
    def ensemble(self, max_failures: int = 3) -> Ensemble:
        """Return an ensemble of three fake models, weighted 0.6, 0.3 and 0.1."""
        models = [FakeLLM([], name) for name in ("a", "b", "c")]
        return Ensemble(models, [0.6, 0.3, 0.1], max_failures)

    def test_draws_follow_the_weights(self) -> None:
        """With a seeded generator, each model is drawn about as often as its weight says."""
        ensemble = self.ensemble()
        rng = random.Random(0)
        counts = Counter(ensemble.draw(rng).name for _ in range(10_000))
        for name, weight in [("a", 0.6), ("b", 0.3), ("c", 0.1)]:
            self.assertAlmostEqual(counts[name] / 10_000, weight, delta=0.02)
        again = [ensemble.draw(random.Random(5)).name for _ in range(3)]
        self.assertEqual(again, [ensemble.draw(random.Random(5)).name for _ in range(3)])

    def test_a_model_failing_in_a_row_is_dropped_and_the_weights_rescaled(self) -> None:
        """3 failures in a row drop a model; a success in between starts the count again."""
        ensemble = self.ensemble()
        ensemble.record_failure("a")
        ensemble.record_failure("a")
        ensemble.record_success("a")
        ensemble.record_failure("a")
        ensemble.record_failure("a")
        self.assertIn("a", ensemble.active)
        with self.assertLogs("my_evolve.llm", "WARNING") as logs:
            ensemble.record_failure("a")
        self.assertIn("a failed 3 times in a row", logs.output[0])
        rng = random.Random(0)
        counts = Counter(ensemble.draw(rng).name for _ in range(4_000))
        self.assertEqual(counts["a"], 0)
        self.assertAlmostEqual(counts["b"] / 4_000, 0.75, delta=0.03)

    def test_no_model_left(self) -> None:
        ensemble = self.ensemble(max_failures=1)
        with self.assertLogs("my_evolve.llm", "WARNING"):
            for name in ("a", "b", "c"):
                ensemble.record_failure(name)
        with self.assertRaises(NoModelLeft):
            ensemble.draw(random.Random(0))

    def test_check_all_stops_at_the_first_model_that_fails(self) -> None:
        good = OpenAICompatibleLLM(model("good"))
        good.client = StubClient(response("OK", None))  # type: ignore[assignment]
        bad = OpenAICompatibleLLM(model("bad"))
        bad.client = StubClient(response("", None))  # type: ignore[assignment]
        Ensemble([good], [1.0], 3).check_all()
        with self.assertRaisesRegex(LLMError, "bad: the reply is empty"):
            Ensemble([good, bad], [1.0, 1.0], 3).check_all()

    def test_an_ensemble_from_the_problem_file(self) -> None:
        settings = LLMSettings(models=(model("a", weight=2.0), model("b")), max_failures_in_a_row=4)
        ensemble = Ensemble.from_settings(settings)
        self.assertEqual([llm.name for llm in ensemble.models], ["a", "b"])
        self.assertEqual((ensemble.weights, ensemble.max_failures), ({"a": 2.0, "b": 1.0}, 4))


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
