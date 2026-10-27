"""The LLM classes: send a prompt to a language model and return its reply (D31-D35, D66).

Every model is reached through an OpenAI-compatible endpoint, with the synchronous
openai client: a local Ollama server, Anthropic's compatible endpoint, OpenAI, or
any other (D32). The loop always goes through an Ensemble, with one model or several:
each iteration draws one model in proportion to its weight (D31), and a model that
keeps failing is dropped for the rest of the run (D34).

Models are drawn, and their failures counted, in the main thread only, so the run's
random generator and the counters are never shared between threads.
"""

import logging
import os
import random
import time
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

# problem.py and prompt.py import this module, so these are imported for type
# checking only. The openai package is imported inside OpenAICompatibleLLM: it takes
# about a second to import, which processes that never call an LLM need not pay.
if TYPE_CHECKING:
    from my_evolve.problem import LLMSettings, ModelSettings
    from my_evolve.prompt import Prompt

logger = logging.getLogger(__name__)

# The name prefixes of OpenAI's reasoning models, as openevolve recognises them (D32).
REASONING_MODEL_PREFIXES = ("o1", "o3", "o4", "gpt-5", "gpt-oss")

# Sent when a model needs no key: local servers ignore it, but the openai client requires one.
PLACEHOLDER_API_KEY = "no-key-needed"

# The start-up check's request (D34).
CHECK_SYSTEM_MESSAGE = "You are being tested before a run starts."
CHECK_USER_MESSAGE = "Reply with the word OK."


def is_reasoning_model(name: str) -> bool:
    """Guess from its name whether a model is one of OpenAI's reasoning models.

    These models refuse max_tokens and temperature, and need max_completion_tokens
    instead. Any provider prefix is ignored: "openai/o3" is a reasoning model.
    """
    model_name = name.rsplit("/", 1)[-1].lower()
    return model_name.startswith(REASONING_MODEL_PREFIXES)


@dataclass(frozen=True)
class LLMReply:
    """One reply of a model."""

    # The reply's text, as the model wrote it.
    text: str
    # The model that wrote it.
    model: str
    # Tokens sent and received; 0 when the server does not say.
    input_tokens: int
    output_tokens: int
    # How long the call took, in seconds, retries included.
    duration: float


class LLMError(Exception):
    """No reply could be obtained from a model; the message says why."""

    def __init__(self, model: str, message: str) -> None:
        super().__init__(f"{model}: {message}")
        # The model that failed, whose failures the ensemble counts (D34).
        self.model: str = model


class NoModelLeft(Exception):
    """Every model of the ensemble has been dropped (D34)."""


class ModelSetupError(ValueError):
    """A model that cannot be used at all, such as one whose key variable is not set."""


class LLM(ABC):
    """What every model must be able to do: turn a prompt into a reply."""

    def __init__(self, name: str) -> None:
        # The model's name, as its server knows it; unique in the ensemble.
        self.name: str = name

    @abstractmethod
    def complete(self, prompt: "Prompt") -> LLMReply:
        """Return the model's reply to the prompt; raise LLMError if there is none."""

    def check(self) -> LLMReply:
        """Send a one-line test request with the model's own settings (D34).

        Raises LLMError if the model does not answer.
        """
        from my_evolve.prompt import Prompt

        return self.complete(Prompt(system=CHECK_SYSTEM_MESSAGE, user=CHECK_USER_MESSAGE))


class OpenAICompatibleLLM(LLM):
    """A model reached through the OpenAI-compatible interface."""

    def __init__(
        self, settings: "ModelSettings", environment: Mapping[str, str] | None = None
    ) -> None:
        """Prepare the client of one model; nothing is sent yet.

        environment is where the API key's variable is read (by default, this
        process's environment variables). Raises ModelSetupError if the model names a
        key variable that is not set.
        """
        super().__init__(settings.name)
        self.settings: ModelSettings = settings
        environment = os.environ if environment is None else environment
        api_key = PLACEHOLDER_API_KEY
        if settings.api_key_env is not None:
            api_key = environment.get(settings.api_key_env, "")
            if not api_key:
                raise ModelSetupError(
                    f"the model {settings.name} reads its API key from the environment "
                    f"variable {settings.api_key_env}, which is not set"
                )
        import openai

        # Sends the requests, with its own retries (the only layer of retries, D34),
        # and is the only holder of the API key.
        self.client: openai.OpenAI = openai.OpenAI(
            base_url=settings.api_base,
            api_key=api_key,
            timeout=settings.timeout,
            max_retries=settings.retries,
        )

    def request_parameters(self, prompt: "Prompt") -> dict[str, Any]:
        """Return what is sent for a prompt: settings left unset are not sent (D32, D33)."""
        parameters: dict[str, Any] = {
            "model": self.settings.name,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ],
        }
        if self.settings.reasoning:
            # Reasoning models refuse max_tokens and temperature.
            parameters["max_completion_tokens"] = self.settings.max_tokens
            if self.settings.reasoning_effort is not None:
                parameters["reasoning_effort"] = self.settings.reasoning_effort
        else:
            parameters["max_tokens"] = self.settings.max_tokens
            if self.settings.temperature is not None:
                parameters["temperature"] = self.settings.temperature
        return parameters

    def complete(self, prompt: "Prompt") -> LLMReply:
        """Send the prompt and return the reply.

        Raises LLMError if the request fails after its retries, or if the reply is empty.
        """
        import openai

        started = time.monotonic()
        try:
            response = self.client.chat.completions.create(**self.request_parameters(prompt))
        except openai.OpenAIError as error:
            raise LLMError(self.name, f"{type(error).__name__}: {error}") from error
        duration = time.monotonic() - started

        text = response.choices[0].message.content if response.choices else None
        if not text:
            raise LLMError(self.name, "empty reply")
        usage = response.usage
        return LLMReply(
            text=text,
            model=self.name,
            input_tokens=(usage.prompt_tokens or 0) if usage is not None else 0,
            output_tokens=(usage.completion_tokens or 0) if usage is not None else 0,
            duration=duration,
        )


class Ensemble:
    """The models of a run, drawn by weight, with failing models dropped (D31, D34).

    Used from the main thread only.
    """

    def __init__(
        self,
        models: Sequence[LLM],
        weights: Sequence[float],
        max_failures: int,
        rng: random.Random,
    ) -> None:
        if not models or len(models) != len(weights):
            raise ValueError("an ensemble needs at least one model, and one weight per model")
        # The models by name, in the order of the problem file.
        self.models: dict[str, LLM] = {model.name: model for model in models}
        self.weights: dict[str, float] = {
            model.name: weight for model, weight in zip(models, weights, strict=True)
        }
        # The names of the models still in use, in the order of the problem file.
        self.active: list[str] = [model.name for model in models]
        self.failures_in_a_row: dict[str, int] = {model.name: 0 for model in models}
        # A model failing this many times in a row is dropped.
        self.max_failures: int = max_failures
        # The run's random generator (D39).
        self.rng: random.Random = rng

    @classmethod
    def from_settings(cls, settings: "LLMSettings", rng: random.Random) -> "Ensemble":
        """Return the ensemble of a problem file's llm section, one client per model.

        Raises ModelSetupError if a model cannot be used.
        """
        return cls(
            [OpenAICompatibleLLM(model) for model in settings.models],
            [model.weight for model in settings.models],
            settings.max_failures_in_a_row,
            rng,
        )

    def draw(self) -> LLM:
        """Draw one active model in proportion to the weights of the active models.

        Dropping a model thus rescales the others' weights (D34). Raises NoModelLeft
        when every model has been dropped.
        """
        if not self.active:
            raise NoModelLeft("every model of the ensemble has been dropped")
        weights = [self.weights[name] for name in self.active]
        return self.models[self.rng.choices(self.active, weights=weights)[0]]

    def record_success(self, name: str) -> None:
        """A model answered: its failures in a row start again from 0."""
        self.failures_in_a_row[name] = 0

    def record_failure(self, name: str) -> None:
        """A model gave no reply; after max_failures in a row, it is dropped."""
        self.failures_in_a_row[name] += 1
        if self.failures_in_a_row[name] >= self.max_failures and name in self.active:
            self.active.remove(name)
            left = ", ".join(self.active) or "none"
            logger.warning(
                "The model %s failed %d times in a row: it is dropped for the rest of the run "
                "(models left: %s).",
                name,
                self.failures_in_a_row[name],
                left,
            )

    def check_all(self) -> None:
        """Send every model its test request; the first failure stops the run (D34).

        Raises LLMError naming the model that failed.
        """
        for model in self.models.values():
            reply = model.check()
            logger.info("The model %s answered in %.1f s.", model.name, reply.duration)
