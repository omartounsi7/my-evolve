"""The LLM classes: send a prompt to a language model and return its reply.

Every model is reached through the OpenAI-compatible interface that Ollama and most
cloud providers offer (D32). A run uses an ensemble of models, as openevolve does (D31):
each iteration draws one, in proportion to its weight. A model that fails too often in
a row is dropped for the rest of the run, and the others' weights rescaled (D34).
"""

import logging
import os
import random
import time
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from my_evolve.problem import LLMSettings, ModelSettings
from my_evolve.prompt import Prompt

logger = logging.getLogger(__name__)

# The openai package is imported inside OpenAICompatibleLLM, not here: it takes about a
# second to import, which the tests using a fake LLM need not pay.

# Sent when no API key is needed: local servers ignore it, but the openai package requires one
PLACEHOLDER_API_KEY = "no-key-needed"
# The request every model gets before the run starts, to check that it answers (D34)
CHECK_PROMPT = Prompt(system="You are a helpful assistant.", user="Reply with the word OK.")


class MissingKeyError(ValueError):
    """Raised when the environment variable a model's key should be in is not set."""


@dataclass(frozen=True)
class LLMReply:
    """A model's reply to a prompt, and what it cost."""

    # The reply's text
    text: str
    # The model that wrote it
    model: str
    # The tokens of the prompt and of the reply, as the server counted them (0 if it did not)
    input_tokens: int
    output_tokens: int
    # How long the call took, in seconds
    duration: float


class LLMError(Exception):
    """Raised when a model gave no usable reply; the message names the model and says why."""

    def __init__(self, model: str, reason: str) -> None:
        super().__init__(f"{model}: {reason}")
        # The model that gave no reply
        self.model: str = model


class NoModelLeft(Exception):
    """Raised when every model of the ensemble has been dropped (D34)."""


class LLM(ABC):
    """What every LLM must be able to do: answer a prompt."""

    def __init__(self, name: str) -> None:
        # The model's name, as its server knows it
        self.name: str = name

    @abstractmethod
    def complete(self, prompt: Prompt) -> LLMReply:
        """Return the model's reply to the prompt. Raises LLMError if there is none."""

    def check(self) -> None:
        """Send a one-line request, with the model's own settings. Raises LLMError if it fails."""
        self.complete(CHECK_PROMPT)


class OpenAICompatibleLLM(LLM):
    """A model reached through the OpenAI-compatible interface, such as a local Ollama server.

    OpenAI's reasoning models get their token limit as max_completion_tokens, and a
    reasoning effort if one is set; the others get max_tokens, and a temperature if one
    is set (D32, D33). Settings left unset are not sent.
    """

    def __init__(self, settings: ModelSettings) -> None:
        """Prepare to talk to one model. Nothing is sent yet.

        Raises MissingKeyError if the variable holding the model's key is not set.
        """
        super().__init__(settings.name)
        # Imported here, not at the top of the file: see the note there.
        import openai

        # How to ask this model
        self.settings: ModelSettings = settings
        key = PLACEHOLDER_API_KEY
        if settings.api_key_env is not None:
            key = os.environ.get(settings.api_key_env, "")
            if not key:
                raise MissingKeyError(
                    f"the API key of {settings.name} should be in the environment variable "
                    f"{settings.api_key_env}, which is not set"
                )
        # Sends the requests, with the timeout and the retries; the only holder of the key
        self.client: openai.OpenAI = openai.OpenAI(
            base_url=settings.api_base,
            api_key=key,
            timeout=settings.timeout,
            max_retries=settings.retries,
        )

    def generation_settings(self) -> dict[str, Any]:
        """Return the settings sent with every request, leaving out those not set."""
        settings = self.settings
        if settings.reasoning:
            sent: dict[str, Any] = {"max_completion_tokens": settings.max_tokens}
            if settings.reasoning_effort is not None:
                sent["reasoning_effort"] = settings.reasoning_effort
        else:
            sent = {"max_tokens": settings.max_tokens}
            if settings.temperature is not None:
                sent["temperature"] = settings.temperature
        return sent

    def complete(self, prompt: Prompt) -> LLMReply:
        """Send the system and user messages to the model and return its reply.

        Raises LLMError if the request fails after its retries, or if the reply is empty.
        """
        # Already imported in __init__, so this costs nothing.
        import openai

        started = time.monotonic()
        try:
            response = self.client.chat.completions.create(
                model=self.name,
                messages=[
                    {"role": "system", "content": prompt.system},
                    {"role": "user", "content": prompt.user},
                ],
                **self.generation_settings(),
            )
        except openai.OpenAIError as error:
            raise LLMError(self.name, f"{type(error).__name__}: {error}") from error
        text = response.choices[0].message.content if response.choices else None
        if not text:
            raise LLMError(self.name, "the reply is empty")
        usage = response.usage
        return LLMReply(
            text=text,
            model=self.name,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            duration=time.monotonic() - started,
        )


class Ensemble:
    """The models of a run, each drawn in proportion to its weight (D31).

    Only the main thread uses it, so its counts need no locking (D36). The run's random
    generator is passed to draw, so that every draw of the run comes from it (D39).
    """

    def __init__(self, models: Sequence[LLM], weights: Sequence[float], max_failures: int) -> None:
        """Gather the models; a model failing max_failures times in a row will be dropped."""
        if len(models) != len(weights) or not models:
            raise ValueError("an ensemble needs one weight per model, and one model or more")
        # The models, in the problem file's order
        self.models: list[LLM] = list(models)
        # Each model's weight, by name
        self.weights: dict[str, float] = {
            model.name: weight for model, weight in zip(models, weights, strict=True)
        }
        # The names of the models still in use
        self.active: list[str] = [model.name for model in models]
        # Each model's failures since its last success
        self.failures_in_a_row: dict[str, int] = {model.name: 0 for model in models}
        # How many failures in a row drop a model
        self.max_failures: int = max_failures

    @classmethod
    def from_settings(cls, settings: LLMSettings) -> "Ensemble":
        """Return the ensemble of the problem file's llm section.

        Raises MissingKeyError if a model's key is not in its variable.
        """
        models = [OpenAICompatibleLLM(model) for model in settings.models]
        weights = [model.weight for model in settings.models]
        return cls(models, weights, settings.max_failures_in_a_row)

    def draw(self, rng: random.Random) -> LLM:
        """Draw one active model, in proportion to the weights of the active models.

        Dropping a model thus rescales the others' weights. Raises NoModelLeft if every
        model has been dropped.
        """
        if not self.active:
            raise NoModelLeft("every model has been dropped after failing repeatedly")
        name = rng.choices(self.active, weights=[self.weights[name] for name in self.active])[0]
        return next(model for model in self.models if model.name == name)

    def record_success(self, name: str) -> None:
        """Note that a model replied: its count of failures in a row starts again."""
        self.failures_in_a_row[name] = 0

    def record_failure(self, name: str) -> None:
        """Note that a model gave no reply; drop it once it has failed too often in a row."""
        self.failures_in_a_row[name] += 1
        if self.failures_in_a_row[name] >= self.max_failures and name in self.active:
            self.active.remove(name)
            logger.warning(
                "%s failed %d times in a row: dropped for the rest of the run",
                name,
                self.max_failures,
            )

    def check_all(self) -> None:
        """Send every model a one-line request; the first that fails raises LLMError (D34)."""
        for model in self.models:
            model.check()
