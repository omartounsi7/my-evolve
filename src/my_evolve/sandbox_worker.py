"""The sandbox worker: runs one program and answers the host's calls to its functions.

Run as `python -m my_evolve.sandbox_worker`. The host sends the program in a load
message, then calls its functions one message at a time (see sandbox_protocol). The
evaluation file stays on the host: the worker only runs the program's own code, and
the host computes the score from the values the program returns.

The worker keeps standard input and output for the messages. The program gets an empty
standard input, and its standard output goes to standard error, so nothing it reads
or prints can disturb the messages.
"""

import linecache
import os
import sys
import traceback
from types import TracebackType
from typing import IO, Any

from my_evolve.sandbox_protocol import Message, NotPlainData, receive, send, to_plain

# The file name the program's code gets in tracebacks
PROGRAM_FILE_NAME = "<program>"


def describe_error(error: BaseException) -> str:
    """Return what went wrong in one line, such as "ZeroDivisionError: division by zero"."""
    return f"{type(error).__name__}: {error}"


def program_traceback(error: BaseException) -> str:
    """Return the traceback of an error, without the worker's own frame at its top."""
    trace: TracebackType | None = error.__traceback__
    # The first frame is the worker's line that ran the program's code.
    if trace is not None:
        trace = trace.tb_next
    return "".join(traceback.format_exception(type(error), error, trace))


def kind_of(value: Any) -> str:
    """Return "function", "data" or "other": how the host may use a name of the program."""
    if callable(value) and not isinstance(value, type):
        return "function"
    try:
        to_plain(value)
    except NotPlainData:
        return "other"
    return "data"


def load(code: str) -> dict[str, Any]:
    """Run the program's code in a fresh namespace named "program", and return the namespace.

    Its `if __name__ == "__main__":` part does not run.
    """
    # Tracebacks show the program's lines, as if it were a file.
    linecache.cache[PROGRAM_FILE_NAME] = (len(code), None, code.splitlines(True), "")
    namespace: dict[str, Any] = {"__name__": "program"}
    exec(compile(code, PROGRAM_FILE_NAME, "exec"), namespace)
    return namespace


def answer(namespace: dict[str, Any], message: Message) -> Message:
    """Carry out a call or get message, and return the answer to send."""
    try:
        name = message["name"]
        if name not in namespace or name.startswith("__"):
            raise NameError(f"the program defines no {name!r}")
        value = namespace[name]
        if message["type"] == "call":
            value = value(*message.get("args", []), **message.get("kwargs", {}))
        elif message["type"] != "get":
            raise ValueError(f"unknown message type {message['type']!r}")
        return {"type": "return", "id": message.get("id"), "value": to_plain(value)}
    # BaseException: a function calling exit() is an error of the program, not of the worker.
    except BaseException as error:
        return {
            "type": "raised",
            "id": message.get("id"),
            "error": describe_error(error),
            "traceback": program_traceback(error),
        }


def serve(requests: IO[str], answers: IO[str]) -> None:
    """Load the program sent first, then answer every message until the host closes the stream."""
    message = receive(requests)
    if message is None or message.get("type") != "load":
        raise SystemExit("the first message must be a load message")
    try:
        namespace = load(message["code"])
    except BaseException as error:
        send(
            answers,
            {
                "type": "load_failed",
                "error": describe_error(error),
                "traceback": program_traceback(error),
            },
        )
        return
    names = {name: kind_of(value) for name, value in namespace.items() if not name.startswith("__")}
    send(answers, {"type": "loaded", "names": names})
    while (message := receive(requests)) is not None:
        send(answers, answer(namespace, message))


def main() -> None:
    """Keep standard input and output for the messages, then serve."""
    # Private copies of the two streams, for the messages only.
    requests = os.fdopen(os.dup(0), "r", encoding="utf-8")
    answers = os.fdopen(os.dup(1), "w", encoding="utf-8")
    # The program reads an empty input, and what it prints goes to standard error.
    empty_input = os.open(os.devnull, os.O_RDONLY)
    os.dup2(empty_input, 0)
    os.close(empty_input)
    os.dup2(2, 1)
    serve(requests, answers)
    # Anything the program printed and Python kept in a buffer.
    sys.stdout.flush()


if __name__ == "__main__":
    main()
