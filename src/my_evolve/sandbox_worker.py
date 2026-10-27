"""Runs inside the sandbox: loads one program and answers calls of its functions (D77).

Usage: python -m my_evolve.sandbox_worker

The host sends a load message with the program's code, then call and get
messages, one JSON line each on standard input; the worker answers each on
standard output (sandbox_protocol). Whatever the program prints goes to standard
error, which the host keeps as the program's error output (D10).

The program chooses what its functions return, and nothing else: the score is
computed on the host, from those values (D8). This file imports nothing but the
standard library and sandbox_protocol, since the container has none of the host's
packages.
"""

import builtins
import inspect
import io
import linecache
import os
import sys
import traceback
from types import TracebackType
from typing import Any, TextIO

from my_evolve.sandbox_protocol import (
    DATA,
    FUNCTION,
    OTHER,
    NotPlainData,
    decode,
    encode,
    receive,
    send,
)

# The file name the program's code is given, as it appears in its tracebacks.
PROGRAM_FILE_NAME = "program.py"
# The program's __name__: not "__main__", so its "if __name__ == '__main__':" part never runs.
PROGRAM_MODULE_NAME = "program"


def private_streams() -> tuple[TextIO, TextIO]:
    """Keep the protocol's streams to this worker, out of the program's reach.

    Standard output becomes a copy of standard error, so that anything the program
    prints, from Python or from compiled code, lands in the error output; standard
    input reads nothing, so that a program calling input() cannot swallow a message.
    Returns the private input and output of the protocol.
    """
    protocol_in = io.TextIOWrapper(os.fdopen(os.dup(0), "rb"), encoding="utf-8")
    protocol_out = io.TextIOWrapper(os.fdopen(os.dup(1), "wb"), encoding="utf-8")
    sys.stdout.flush()
    os.dup2(2, 1)
    # print() writes to sys.stdout, which is block-buffered when it is not a terminal:
    # the last prints before a crash would be lost. Standard error is line-buffered.
    sys.stdout = sys.stderr
    empty_input = os.open(os.devnull, os.O_RDONLY)
    os.dup2(empty_input, 0)
    os.close(empty_input)
    sys.stdin = open(os.devnull, encoding="utf-8")  # kept open for the program
    return protocol_in, protocol_out


def describe_error(error: BaseException) -> str:
    """Return a short text saying what went wrong, such as "ZeroDivisionError: division by zero"."""
    message = str(error)
    return f"{type(error).__name__}: {message}" if message else type(error).__name__


def program_traceback(error: BaseException) -> str:
    """Return the traceback of an error raised by the program, without this file's frames."""
    frames: TracebackType | None = error.__traceback__
    while frames is not None and frames.tb_frame.f_code.co_filename == __file__:
        frames = frames.tb_next
    return "".join(traceback.format_exception(type(error), error, frames))


def kind_of(value: Any) -> str:
    """Tell what one of the program's names holds: a function, plain data, or other."""
    if inspect.isroutine(value):
        return FUNCTION
    try:
        encode(value)
    except (NotPlainData, RecursionError):
        return OTHER
    return DATA


def load_program(code: str) -> dict[str, Any]:
    """Run the program's code in a fresh namespace and return that namespace."""
    # Registering the code lets tracebacks show the program's own lines.
    lines = code.splitlines(keepends=True)
    linecache.cache[PROGRAM_FILE_NAME] = (len(code), None, lines, PROGRAM_FILE_NAME)
    namespace: dict[str, Any] = {"__name__": PROGRAM_MODULE_NAME, "__builtins__": builtins}
    exec(compile(code, PROGRAM_FILE_NAME, "exec"), namespace)
    return namespace


def answer(message: dict[str, Any], namespace: dict[str, Any]) -> dict[str, Any]:
    """Return the answer to one call or get message.

    Anything the program raises, exit requests included, becomes a raised message,
    and so does a value that is not plain data.
    """
    message_id = message.get("id")
    name = message.get("name")
    try:
        if not isinstance(name, str) or name not in namespace:
            raise NameError(f"the program defines no name {name!r}")
        value = namespace[name]
        if message["type"] == "call":
            if not callable(value):
                raise TypeError(f"{name} is not a function")
            args = decode(message.get("args", []))
            kwargs = decode(message.get("kwargs", {"__dict__": {}}))
            value = value(*args, **kwargs)
        elif message["type"] != "get":
            raise ValueError(f"unknown message type {message['type']!r}")
        return {"type": "return", "id": message_id, "value": encode(value)}
    except BaseException as error:  # the program may raise anything
        return {
            "type": "raised",
            "id": message_id,
            "error": describe_error(error),
            "traceback": program_traceback(error),
        }


def reply(protocol_out: TextIO, message: dict[str, Any]) -> None:
    """Send a message, after flushing what the program printed so far.

    The host may read the error output as soon as it has the answer.
    """
    try:
        sys.stderr.flush()
    except (OSError, ValueError):
        # The program closed or broke its error output; the answer still goes out.
        pass
    send(protocol_out, message)


def main() -> None:
    """Load the program sent by the host, then answer its messages until the input ends."""
    protocol_in, protocol_out = private_streams()

    message = receive(protocol_in)
    if message is None or message.get("type") != "load":
        return
    try:
        namespace = load_program(message["code"])
    except BaseException as error:  # the program may raise anything
        reply(
            protocol_out,
            {
                "type": "load_failed",
                "error": describe_error(error),
                "traceback": program_traceback(error),
            },
        )
        return
    names = {name: kind_of(value) for name, value in namespace.items() if not name.startswith("__")}
    reply(protocol_out, {"type": "loaded", "names": names})

    while (message := receive(protocol_in)) is not None:
        reply(protocol_out, answer(message, namespace))


if __name__ == "__main__":
    main()
