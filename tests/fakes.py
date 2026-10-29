"""Stand-ins the tests use in place of the real building blocks."""

from my_evolve.llm import LLM
from my_evolve.prompt import Prompt


class FakeLLM(LLM):
    """An LLM that returns replies written in advance, in order, and remembers the prompts.

    A reply that is an exception is raised instead of returned, as a failing model would.
    """

    def __init__(self, replies: list[str | Exception], name: str = "fake-model") -> None:
        super().__init__(name)
        # The replies still to give, first one first
        self.replies: list[str | Exception] = list(replies)
        # Every prompt received, in order
        self.prompts: list[Prompt] = []

    def complete(self, prompt: Prompt) -> str:
        """Return the next reply written in advance (or raise it, if it is an exception)."""
        self.prompts.append(prompt)
        if not self.replies:
            raise AssertionError("FakeLLM: no reply left to give")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
