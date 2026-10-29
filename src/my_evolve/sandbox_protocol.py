"""The messages between the host and the sandbox worker: one JSON object per line.

The host sends:
    {"type": "load", "code": "..."}                                  run the program
    {"type": "call", "id": 1, "name": "f", "args": [...], "kwargs": {...}}
    {"type": "get", "id": 2, "name": "N"}                            a plain-data global

The worker answers:
    {"type": "loaded", "names": {"f": "function", "N": "data", "np": "other"}}
    {"type": "load_failed", "error": "...", "traceback": "..."}
    {"type": "return", "id": 1, "value": ...}
    {"type": "raised", "id": 1, "error": "...", "traceback": "..."}

Values travel as plain JSON data. For now, numpy arrays and numbers become lists and
Python numbers, and tuples become lists; step 1.6 of the plan makes this exact.

This module, like the worker, imports nothing outside Python's standard library, so
that the evaluation container needs nothing else.
"""

import json
from typing import IO, Any

# One message: a JSON object, read as a dictionary
Message = dict[str, Any]


class NotPlainData(TypeError):
    """Raised for a value that cannot travel between the host and the worker."""


def to_plain(value: Any) -> Any:
    """Return value as plain JSON data: None, booleans, numbers, text, lists, text-keyed dicts.

    numpy arrays and numbers (anything with a tolist method) become lists and Python
    numbers; tuples become lists. Raises NotPlainData for anything else.
    """
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list | tuple):
        return [to_plain(item) for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise NotPlainData("a dictionary's keys must be text")
        return {key: to_plain(item) for key, item in value.items()}
    # numpy arrays and numbers, recognized without importing numpy
    if hasattr(value, "tolist") and type(value).__module__ == "numpy":
        return to_plain(value.tolist())
    raise NotPlainData(f"a value of type {type(value).__name__} is not plain data")


def send(stream: IO[str], message: Message) -> None:
    """Write one message as one line, and make sure it leaves at once."""
    stream.write(json.dumps(message) + "\n")
    stream.flush()


def receive(stream: IO[str]) -> Message | None:
    """Read one message; None when the stream has ended. Raises ValueError for a bad line."""
    line = stream.readline()
    if not line:
        return None
    message = json.loads(line)
    if not isinstance(message, dict):
        raise ValueError(f"a message must be a JSON object, got {line!r}")
    return message
