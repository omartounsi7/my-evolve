"""The LLM classes: send a prompt to a language model and return its reply.

For now a run uses one model, reached through the OpenAI-compatible interface that
Ollama and most cloud providers offer. Step 2.9 of the implementation plan brings an
ensemble of several models.
"""

import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from my_evolve.problem import ModelSettings
from my_evolve.prompt import Prompt

# The openai package is imported inside OpenAICompatibleLLM, not here: it takes about a
# second to import, which the tests using a fake LLM need not pay.

# Sent when no API key is needed: local servers ignore it, but the openai package requires one
PLACEHOLDER_API_KEY = "no-key-needed"


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


class LLM(ABC):
    """What every LLM must be able to do: answer a prompt."""

    def __init__(self, name: str) -> None:
        # The model's name, as its server knows it
        self.name: str = name

    @abstractmethod
    def complete(self, prompt: Prompt) -> LLMReply:
        """Return the model's reply to the prompt. Raises LLMError if there is none."""


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
