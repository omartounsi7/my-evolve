"""The LLM classes: send a prompt to a language model and return its reply.

For now a run uses one model, reached through the OpenAI-compatible interface that
Ollama and most cloud providers offer. Step 2.9 of the implementation plan brings an
ensemble of several models.
"""

from abc import ABC, abstractmethod

from my_evolve.prompt import Prompt

# The openai package is imported inside OpenAICompatibleLLM, not here: it takes about a
# second to import, which the tests using a fake LLM need not pay.

# How long to wait for one reply, in seconds
TIMEOUT_SECONDS = 300.0
# How many times the openai package retries a request that failed for a passing reason
# (network, busy server). This is the only layer of retries.
RETRIES = 2
# Sent when no API key is needed: local servers ignore it, but the openai package requires one
PLACEHOLDER_API_KEY = "no-key-needed"


class LLMError(Exception):
    """Raised when a model gave no usable reply; the message names the model and says why."""


class LLM(ABC):
    """What every LLM must be able to do: answer a prompt."""

    def __init__(self, name: str) -> None:
        # The model's name, as its server knows it
        self.name: str = name

    @abstractmethod
    def complete(self, prompt: Prompt) -> str:
        """Return the model's reply to the prompt, as text. Raises LLMError if there is none."""


class OpenAICompatibleLLM(LLM):
    """A model reached through the OpenAI-compatible interface, such as a local Ollama server."""

    def __init__(self, name: str, api_base: str) -> None:
        """Prepare to talk to one model on one server. Nothing is sent yet."""
        super().__init__(name)
        # Imported here, not at the top of the file: see the note there.
        import openai

        # Sends the requests, with the timeout and the retries
        self.client: openai.OpenAI = openai.OpenAI(
            base_url=api_base,
            api_key=PLACEHOLDER_API_KEY,
            timeout=TIMEOUT_SECONDS,
            max_retries=RETRIES,
        )

    def complete(self, prompt: Prompt) -> str:
        """Send the system and user messages to the model and return its reply.

        Raises LLMError if the request fails after its retries, or if the reply is empty.
        """
        # Already imported in __init__, so this costs nothing.
        import openai

        try:
            response = self.client.chat.completions.create(
                model=self.name,
                messages=[
                    {"role": "system", "content": prompt.system},
                    {"role": "user", "content": prompt.user},
                ],
            )
        except openai.OpenAIError as error:
            raise LLMError(f"{self.name}: {type(error).__name__}: {error}") from error
        reply = response.choices[0].message.content if response.choices else None
        if not reply:
            raise LLMError(f"{self.name}: the reply is empty")
        return reply
