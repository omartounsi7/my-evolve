"""Stand-ins the tests use in place of the real building blocks."""

import threading
import time

from my_evolve.llm import LLM, LLMReply
from my_evolve.prompt import Prompt


class FakeLLM(LLM):
    """An LLM that returns replies written in advance, in order, and remembers the prompts.

    A reply that is an exception is raised instead of returned, as a failing model would.
    """

    def __init__(
        self, replies: list[str | Exception], name: str = "fake-model", delay: float = 0.0
    ) -> None:
        super().__init__(name)
        # The replies still to give, first one first
        self.replies: list[str | Exception] = list(replies)
        # Every prompt received, in order
        self.prompts: list[Prompt] = []
        # How long each reply takes, in seconds, as a real model's would
        self.delay: float = delay
        # How many calls are in progress, and the most there ever were at once
        self.in_progress: int = 0
        self.most_at_once: int = 0
        self.lock: threading.Lock = threading.Lock()

    def check(self) -> None:
        """Answer the start-up check without using up a reply written in advance."""

    def complete(self, prompt: Prompt) -> LLMReply:
        """Return the next reply written in advance (or raise it, if it is an exception).

        The tokens are counted as one per word of the prompt and of the reply.
        """
        with self.lock:
            self.prompts.append(prompt)
            if not self.replies:
                raise AssertionError("FakeLLM: no reply left to give")
            reply = self.replies.pop(0)
            self.in_progress += 1
            self.most_at_once = max(self.most_at_once, self.in_progress)
        time.sleep(self.delay)
        with self.lock:
            self.in_progress -= 1
        if isinstance(reply, Exception):
            raise reply
        input_tokens = len((prompt.system + prompt.user).split())
        return LLMReply(reply, self.name, input_tokens, len(reply.split()), 0.01)
