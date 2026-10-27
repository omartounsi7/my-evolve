"""Checks the LLM client against a fake OpenAI-compatible server, and the ensemble."""

import random
import socket
import unittest
from collections import Counter

from fake_llm_server import model_settings, serve

from my_evolve.llm import (
    LLM,
    Ensemble,
    LLMError,
    LLMReply,
    ModelSetupError,
    NoModelLeft,
    OpenAICompatibleLLM,
)
from my_evolve.problem import Problem
from my_evolve.prompt import Prompt

PROMPT = Prompt(system="You improve programs.", user="Improve this one.")


class TestOpenAICompatibleLLM(unittest.TestCase):
    def test_reply_comes_back_with_its_model_tokens_and_duration(self) -> None:
        reply = serve(self, ["x = 1"]).llm().complete(PROMPT)
        self.assertEqual(reply.text, "x = 1")
        self.assertEqual(reply.model, "test-model")
        self.assertEqual((reply.input_tokens, reply.output_tokens), (120, 45))
        self.assertGreaterEqual(reply.duration, 0)

    def test_request_holds_the_model_both_messages_and_the_token_limit(self) -> None:
        server = serve(self, ["x = 1"])
        server.llm(max_tokens=4096).complete(PROMPT)
        body = server.bodies[0]
        self.assertEqual(body["model"], "test-model")
        self.assertEqual(
            body["messages"],
            [
                {"role": "system", "content": "You improve programs."},
                {"role": "user", "content": "Improve this one."},
            ],
        )
        self.assertEqual(body["max_tokens"], 4096)
        self.assertNotIn("max_completion_tokens", body)

    def test_settings_left_unset_are_not_sent(self) -> None:
        server = serve(self, ["x = 1"])
        server.llm().complete(PROMPT)
        self.assertNotIn("temperature", server.bodies[0])
        self.assertNotIn("reasoning_effort", server.bodies[0])

    def test_temperature_is_sent_when_set(self) -> None:
        server = serve(self, ["x = 1"])
        server.llm(temperature=0.7).complete(PROMPT)
        self.assertEqual(server.bodies[0]["temperature"], 0.7)

    def test_reasoning_model_gets_completion_tokens_and_effort_never_temperature(self) -> None:
        server = serve(self, ["x = 1"])
        server.llm("o3", reasoning=True, reasoning_effort="high", max_tokens=8000).complete(PROMPT)
        body = server.bodies[0]
        self.assertEqual(body["max_completion_tokens"], 8000)
        self.assertEqual(body["reasoning_effort"], "high")
        self.assertNotIn("max_tokens", body)
        self.assertNotIn("temperature", body)

    def test_key_is_read_from_the_variable_the_problem_file_names(self) -> None:
        server = serve(self, ["x = 1"])
        settings = model_settings(server.url, api_key_env="MY_EVOLVE_TEST_KEY")
        OpenAICompatibleLLM(settings, {"MY_EVOLVE_TEST_KEY": "sk-secret"}).complete(PROMPT)
        self.assertEqual(server.requests[0]["authorization"], "Bearer sk-secret")

    def test_missing_key_variable_is_an_error_naming_it(self) -> None:
        settings = model_settings("http://127.0.0.1:1/v1", api_key_env="MY_EVOLVE_TEST_KEY")
        for environment in ({}, {"MY_EVOLVE_TEST_KEY": ""}):
            with self.subTest(environment=environment):
                with self.assertRaisesRegex(ModelSetupError, "MY_EVOLVE_TEST_KEY"):
                    OpenAICompatibleLLM(settings, environment)

    def test_model_without_a_key_sends_a_placeholder(self) -> None:
        server = serve(self, ["x = 1"])
        server.llm().complete(PROMPT)
        self.assertEqual(server.requests[0]["authorization"], "Bearer no-key-needed")

    def test_token_counts_are_zero_when_the_server_gives_none(self) -> None:
        reply = serve(self, ["x = 1"], usage=False).llm().complete(PROMPT)
        self.assertEqual((reply.input_tokens, reply.output_tokens), (0, 0))

    def test_server_failure_becomes_an_llm_error_naming_the_model(self) -> None:
        with self.assertRaises(LLMError) as caught:
            serve(self, [500]).llm("qwen3:8b").complete(PROMPT)
        self.assertEqual(caught.exception.model, "qwen3:8b")
        self.assertIn("InternalServerError", str(caught.exception))

    def test_refused_key_becomes_an_llm_error(self) -> None:
        with self.assertRaisesRegex(LLMError, "AuthenticationError"):
            serve(self, [401]).llm().complete(PROMPT)

    def test_failed_request_is_retried_by_the_openai_package(self) -> None:
        server = serve(self, [500, "x = 1"])
        self.assertEqual(server.llm(retries=1).complete(PROMPT).text, "x = 1")
        self.assertEqual(len(server.requests), 2)

    def test_retries_are_not_multiplied(self) -> None:
        # One layer of retries only (D34): with 2 retries, 3 requests in all.
        server = serve(self, [500])
        with self.assertRaises(LLMError):
            server.llm(retries=2).complete(PROMPT)
        self.assertEqual(len(server.requests), 3)

    def test_slow_server_runs_into_the_timeout(self) -> None:
        with self.assertRaisesRegex(LLMError, "Timeout"):
            serve(self, ["x = 1"], delay=2.0).llm(timeout=0.5).complete(PROMPT)

    def test_unreachable_server_becomes_an_llm_error(self) -> None:
        with socket.socket() as unused:
            unused.bind(("127.0.0.1", 0))
            port = unused.getsockname()[1]
        llm = OpenAICompatibleLLM(model_settings(f"http://127.0.0.1:{port}/v1"))
        with self.assertRaisesRegex(LLMError, "APIConnectionError"):
            llm.complete(PROMPT)

    def test_empty_reply_becomes_an_llm_error(self) -> None:
        with self.assertRaisesRegex(LLMError, "empty reply"):
            serve(self, [""]).llm().complete(PROMPT)

    def test_check_sends_a_one_line_request(self) -> None:
        server = serve(self, ["OK"])
        self.assertEqual(server.llm().check().text, "OK")
        self.assertEqual(server.bodies[0]["messages"][1]["content"], "Reply with the word OK.")


class StubLLM(LLM):
    """A model answering from a list, without any server: True for a reply, False for a failure."""

    def __init__(self, name: str, answers: list[bool] | None = None) -> None:
        super().__init__(name)
        self.answers: list[bool] = list(answers or [True])
        self.calls: int = 0

    def complete(self, prompt: Prompt) -> LLMReply:
        answer = self.answers[self.calls % len(self.answers)]
        self.calls += 1
        if not answer:
            raise LLMError(self.name, "prepared failure")
        return LLMReply("OK", self.name, 1, 1, 0.0)


def ensemble(seed: int = 7, max_failures: int = 3) -> Ensemble:
    return Ensemble(
        [StubLLM("main"), StubLLM("second")], [0.8, 0.2], max_failures, random.Random(seed)
    )


class TestEnsemble(unittest.TestCase):
    def test_draws_follow_the_weights(self) -> None:
        models = ensemble()
        counts = Counter(models.draw().name for _ in range(10_000))
        self.assertAlmostEqual(counts["main"] / 10_000, 0.8, delta=0.02)

    def test_same_seed_gives_the_same_draws(self) -> None:
        first, second = ensemble(seed=3), ensemble(seed=3)
        self.assertEqual(
            [first.draw().name for _ in range(50)], [second.draw().name for _ in range(50)]
        )

    def test_model_failing_too_often_in_a_row_is_dropped(self) -> None:
        models = ensemble()
        with self.assertLogs("my_evolve.llm", "WARNING") as logs:
            for _ in range(3):
                models.record_failure("main")
        self.assertEqual(models.active, ["second"])
        self.assertIn("main failed 3 times in a row", logs.output[0])
        # The others' weights are rescaled: only the remaining model is drawn.
        self.assertEqual({models.draw().name for _ in range(100)}, {"second"})

    def test_success_starts_the_count_again(self) -> None:
        models = ensemble()
        for _ in range(2):
            models.record_failure("main")
        models.record_success("main")
        for _ in range(2):
            models.record_failure("main")
        self.assertEqual(models.active, ["main", "second"])

    def test_no_model_left_once_every_model_is_dropped(self) -> None:
        models = ensemble(max_failures=1)
        models.record_failure("main")
        models.record_failure("second")
        with self.assertRaises(NoModelLeft):
            models.draw()

    def test_check_all_stops_at_the_first_failing_model(self) -> None:
        failing, never_checked = StubLLM("main", [False]), StubLLM("second")
        models = Ensemble([failing, never_checked], [0.8, 0.2], 3, random.Random(0))
        with self.assertRaisesRegex(LLMError, "main"):
            models.check_all()
        self.assertEqual(never_checked.calls, 0)

    def test_check_all_checks_every_model(self) -> None:
        models = ensemble()
        models.check_all()
        self.assertTrue(
            all(isinstance(model, StubLLM) and model.calls == 1 for model in models.models.values())
        )

    def test_ensemble_of_a_problem_file(self) -> None:
        server = serve(self, ["OK"])
        problem = Problem.from_dict(
            {
                "name": "test",
                "description": "Test.",
                "entry_functions": ["run"],
                "llm": {
                    "api_base": server.url,
                    "max_failures_in_a_row": 5,
                    "models": [{"name": "a", "weight": 3}, {"name": "b", "weight": 1}],
                },
            }
        )
        models = Ensemble.from_settings(problem.llm, random.Random(0))
        self.assertEqual(list(models.models), ["a", "b"])
        self.assertEqual(models.weights, {"a": 3.0, "b": 1.0})
        self.assertEqual(models.max_failures, 5)
        models.check_all()
        self.assertEqual([body["model"] for body in server.bodies], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
