"""A tiny stand-in for an LLM server, for the tests (from my-alphaevolve's).

It runs inside the test process, listens on this machine only, and answers the one
request the openai package makes: a "chat completion". This lets the tests use the
real OpenAICompatibleLLM class, and the real run script, without any network or LLM.
"""

import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from my_evolve.llm import OpenAICompatibleLLM
from my_evolve.problem import ModelSettings

# A reply the fake server can be told to give: text for a normal answer, or a number
# for a failure with that HTTP status code (500 means "server error").
PreparedReply = str | int


def model_settings(url: str, name: str = "test-model", **changes: Any) -> ModelSettings:
    """Return the settings of a model on the fake server, with no retries by default."""
    settings: dict[str, Any] = {
        "name": name,
        "weight": 1.0,
        "api_base": url,
        "api_key_env": None,
        "temperature": None,
        "max_tokens": 16384,
        "reasoning_effort": None,
        "reasoning": False,
        "timeout": 30.0,
        "retries": 0,
        "price_input": None,
        "price_output": None,
    }
    settings.update(changes)
    return ModelSettings(**settings)


class FakeLLMServer:
    """A local web server that answers chat requests with replies prepared in advance."""

    def __init__(
        self, replies: list[PreparedReply], usage: bool = True, delay: float = 0.0
    ) -> None:
        """Start the server. Call stop() when done, or use it in a "with" block.

        usage: whether replies say how many tokens they used. delay: seconds to wait
        before answering each request.
        """
        # The prepared replies, given in order and then repeated from the first one
        self.replies: list[PreparedReply] = list(replies)
        # Every request received so far: the "authorization" header and the decoded "body"
        self.requests: list[dict[str, Any]] = []
        self.usage: bool = usage
        self.delay: float = delay
        self.lock = threading.Lock()
        fake_server = self

        class Handler(BaseHTTPRequestHandler):
            """Answers one request; the http.server module creates one per request."""

            def do_POST(self) -> None:  # noqa: N802 - the name is imposed by http.server
                """Record the request and send back the next prepared reply."""
                try:
                    self.answer()
                except (BrokenPipeError, ConnectionResetError):
                    # The client gave up waiting (a timeout test): nobody to answer.
                    pass

            def answer(self) -> None:
                """Send the next prepared reply to this request."""
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                with fake_server.lock:
                    call_number = len(fake_server.requests)
                    fake_server.requests.append(
                        {"authorization": self.headers.get("Authorization"), "body": body}
                    )
                reply = fake_server.replies[call_number % len(fake_server.replies)]
                time.sleep(fake_server.delay)

                if isinstance(reply, int):
                    # A failure: only the status code matters
                    self.send_response(reply)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"error": {"message": "prepared failure"}}')
                    return

                # A success, in the shape the OpenAI-compatible interface prescribes
                answer: dict[str, Any] = {
                    "id": "fake-completion",
                    "object": "chat.completion",
                    "created": 0,
                    "model": body.get("model", ""),
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": reply},
                            "finish_reason": "stop",
                        }
                    ],
                }
                if fake_server.usage:
                    answer["usage"] = {
                        "prompt_tokens": 120,
                        "completion_tokens": 45,
                        "total_tokens": 165,
                    }
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(answer).encode("utf-8"))

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                """Stay silent: by default every request would print a line during the tests."""

        # Port 0 asks the system for any free port; 127.0.0.1 is "this machine only"
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        # The address to give to a model's api_base
        self.url: str = f"http://127.0.0.1:{self._server.server_port}/v1"
        # The server waits for requests in the background while the test carries on
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def bodies(self) -> list[dict[str, Any]]:
        """The bodies of the requests received so far, in order."""
        return [request["body"] for request in self.requests]

    def llm(self, name: str = "test-model", **changes: Any) -> OpenAICompatibleLLM:
        """Return a real LLM that talks to this server."""
        return OpenAICompatibleLLM(model_settings(self.url, name, **changes))

    def stop(self) -> None:
        """Stop the server and free its port."""
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()


def serve(
    test_case: unittest.TestCase, replies: list[PreparedReply], **options: Any
) -> FakeLLMServer:
    """Start a stand-in server that is stopped automatically when the test ends."""
    server = FakeLLMServer(replies, **options)
    test_case.addCleanup(server.stop)
    return server
